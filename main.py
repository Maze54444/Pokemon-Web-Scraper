import argparse
import time
import logging
import traceback
from datetime import datetime
import concurrent.futures
import random

# Neue Importe für verbesserte Konfigurationsverwaltung
from utils.config_manager import (
    load_products, load_urls, load_seen, save_seen,
    load_out_of_stock, save_out_of_stock, get_current_interval
)
from utils.telegram import send_telegram_message
from utils.matcher import prepare_keywords

# Scraper-Module
from scrapers.tcgviert import scrape_tcgviert
from scrapers.generic import scrape_generic
from scrapers.sapphire_cards import scrape_sapphire_cards
from scrapers.mighty_cards import scrape_mighty_cards

# Logger-Konfiguration
logger = logging.getLogger("main")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),  # Konsolenausgabe
        logging.FileHandler("scraper.log", encoding='utf-8')  # Dateiausgabe
    ]
)

def run_once(only_available=False, reset_seen=False):
    """
    Führt einen einzelnen Scan-Durchlauf aus
    
    :param only_available: Ob nur verfügbare Produkte gemeldet werden sollen
    :param reset_seen: Ob die Liste der gesehenen Produkte zurückgesetzt werden soll
    :return: Intervall für den nächsten Durchlauf
    """
    logger.info("[START] Einzelscan gestartet")
    logger.info(f"[MODE] {'Nur verfügbare Produkte' if only_available else 'Alle Produkte'}")
    
    # Seen-Liste zurücksetzen, wenn angefordert
    if reset_seen:
        logger.info("[RESET] Setze Liste der gesehenen Produkte zurück")
        save_seen(set())
    
    # Lade Konfiguration und Zustände
    seen = load_seen()
    out_of_stock = load_out_of_stock()
    products = load_products()
    urls = load_urls()
    
    # Bereite Keywords vor - WICHTIG: Nutzt die neue Matcher-Logik
    keywords_map = prepare_keywords(products)
    
    logger.info(f"[INFO] Durchlauf: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"[INFO] Aktive Suchbegriffe: {list(keywords_map.keys())}")
    logger.info(f"[INFO] {len(out_of_stock)} ausverkaufte Produkte werden überwacht")
    logger.info(f"[INFO] {len(urls)} URLs werden geprüft")
    
    all_matches = []
    all_urls = urls.copy()
    
    # Gruppiere URLs nach Domain für bessere Fehlerbehandlung
    domain_groups = {}
    for url in all_urls:
        domain = url.split('/')[2]
        if domain not in domain_groups:
            domain_groups[domain] = []
        domain_groups[domain].append(url)
    
    # Verarbeite jede Domain einzeln
    for domain, domain_urls in domain_groups.items():
        logger.info(f"[DOMAIN] Verarbeite {domain} mit {len(domain_urls)} URLs")
        
        try:
            # Spezielle Scraper aufrufen
            if "sapphire-cards.de" in domain:
                matches = scrape_sapphire_cards(keywords_map, seen, out_of_stock, only_available)
                if matches:
                    logger.info(f"[SUCCESS] {len(matches)} neue Treffer bei Sapphire-Cards")
                    all_matches.extend(matches)
            
            elif "tcgviert.com" in domain:
                matches = scrape_tcgviert(keywords_map, seen, out_of_stock, only_available)
                if matches:
                    logger.info(f"[SUCCESS] {len(matches)} neue Treffer bei TCGViert")
                    all_matches.extend(matches)
            
            elif "mighty-cards.de" in domain:
                matches = scrape_mighty_cards(keywords_map, seen, out_of_stock, only_available)
                if matches:
                    logger.info(f"[SUCCESS] {len(matches)} neue Treffer bei Mighty-Cards")
                    all_matches.extend(matches)
            
            else:
                # Generischer Scraper für alle anderen Seiten
                for url in domain_urls:
                    try:
                        matches = scrape_generic(url, keywords_map, seen, out_of_stock, 
                                               check_availability=True, only_available=only_available)
                        if matches:
                            logger.info(f"[SUCCESS] {len(matches)} neue Treffer bei {url}")
                            all_matches.extend(matches)
                    except Exception as e:
                        logger.error(f"[ERROR] Fehler beim Scraping von {url}: {str(e)}")
                        if logger.level == logging.DEBUG:
                            logger.debug(traceback.format_exc())
        
        except Exception as e:
            logger.error(f"[ERROR] Fehler bei Domain {domain}: {str(e)}")
            if logger.level == logging.DEBUG:
                logger.debug(traceback.format_exc())
    
    # Speichere aktualisierte Zustände
    save_seen(seen)
    save_out_of_stock(out_of_stock)
    
    # Zusammenfassung
    logger.info(f"[SUMMARY] Scan abgeschlossen. {len(all_matches)} neue Treffer gefunden.")
    
    interval = get_current_interval()
    logger.info(f"[DONE] Nächster Durchlauf in {interval} Sekunden")
    return interval

def run_loop(only_available=False):
    """
    Startet den Scraper im Dauerbetrieb mit verbesserter Fehlerbehandlung
    
    :param only_available: Ob nur verfügbare Produkte gemeldet werden sollen
    """
    logger.info("[START] Dauerbetrieb gestartet")
    consecutive_errors = 0
    max_consecutive_errors = 5
    
    while True:
        try:
            interval = run_once(only_available=only_available)
            consecutive_errors = 0  # Fehler zurücksetzen bei erfolgreichem Durchlauf
            time.sleep(interval)
            
        except Exception as e:
            consecutive_errors += 1
            logger.error(f"[ERROR] Fehler im Hauptloop ({consecutive_errors}/{max_consecutive_errors}): {str(e)}")
            logger.error(traceback.format_exc())
            
            # Exponentielles Backoff bei wiederholten Fehlern
            retry_time = min(60 * (2 ** (consecutive_errors - 1)), 3600)  # Max 1 Stunde
            
            # Bei zu vielen aufeinanderfolgenden Fehlern, Benachrichtigung senden
            if consecutive_errors >= max_consecutive_errors:
                error_msg = (
                    f"⚠️ WARNUNG: Der Scraper hatte {consecutive_errors} Fehler in Folge.\n"
                    f"Letzter Fehler: {str(e)}\n"
                    f"Neustart in {retry_time} Sekunden..."
                )
                send_telegram_message(error_msg)
                consecutive_errors = 0  # Zähler zurücksetzen nach Benachrichtigung
            
            logger.warning(f"[RETRY] Neustart in {retry_time} Sekunden...")
            time.sleep(retry_time)

def test_telegram():
    """Testet die Telegram-Benachrichtigungsfunktion"""
    logger.info("[TEST] Starte Telegram-Test")
    test_message = (
        "🧪 TEST-NACHRICHT\n"
        f"Zeit: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        "Status: Telegram-Integration funktioniert!"
    )
    result = send_telegram_message(test_message)
    if result:
        logger.info("[SUCCESS] Telegram-Test erfolgreich")
    else:
        logger.error("[ERROR] Telegram-Test fehlgeschlagen")

def test_matching():
    """Testet das Matching für bekannte Produktnamen"""
    logger.info("[TEST] Teste Matching-Funktion")
    
    # Lade aktuelle Produkte aus products.txt
    products = load_products()
    keywords_map = prepare_keywords(products)
    
    # Test-Titel von verschiedenen Shops
    test_titles = [
        "Pokémon TCG: Journey Together (SV09) - 36er Display (EN)",
        "Pokemon Journey Together | Reisegefährten Booster Box (Display)",
        "Pokémon Karmesin & Purpur 09: Reisegefährten Display (36 Booster)",
        "Journey Together Elite Trainer Box EN",
        "Reisegefährten Top Trainer Box DE",
        "Pokemon Reisegefährten 3er Blister Pack"
    ]
    
    logger.info(f"Aktive Suchbegriffe: {list(keywords_map.keys())}")
    
    from utils.matcher import is_keyword_in_text, extract_product_type_from_text
    
    for title in test_titles:
        logger.info(f"\nTest für: '{title}'")
        product_type = extract_product_type_from_text(title)
        logger.info(f"  Erkannter Produkttyp: {product_type}")
        
        matches = []
        for search_term, keywords in keywords_map.items():
            if is_keyword_in_text(keywords, title, log_level='None'):
                matches.append(search_term)
        
        if matches:
            logger.info(f"  ✅ Treffer für: {matches}")
        else:
            logger.info(f"  ❌ Keine Treffer")

def monitor_keywords():
    """Zeigt die aktuell aktiven Suchbegriffe und ihre Token"""
    products = load_products()
    keywords_map = prepare_keywords(products)
    
    logger.info("[KEYWORDS] Aktive Suchbegriffe:")
    for search_term, tokens in keywords_map.items():
        product_type = extract_product_type_from_text(search_term)
        logger.info(f"  - '{search_term}' → Tokens: {tokens}, Typ: {product_type}")

def test_shops():
    """Testet die Verbindung zu allen konfigurierten Shops"""
    import requests
    from urllib.parse import urlparse
    
    urls = load_urls()
    logger.info(f"[TEST] Teste {len(urls)} Shop-URLs")
    
    for url in urls:
        try:
            domain = urlparse(url).netloc
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                logger.info(f"  ✅ {domain} - OK")
            else:
                logger.warning(f"  ⚠️ {domain} - Status {response.status_code}")
        except Exception as e:
            logger.error(f"  ❌ {domain} - Fehler: {str(e)}")

def clean_database():
    """Bereinigt die Datenbanken von alten Einträgen"""
    logger.info("[CLEAN] Bereinige Datenbanken")
    
    seen = load_seen()
    out_of_stock = load_out_of_stock()
    
    initial_seen = len(seen)
    initial_oos = len(out_of_stock)
    
    # Entferne ungültige Einträge
    valid_seen = set()
    for entry in seen:
        if "_status_" in entry and (entry.endswith("_available") or entry.endswith("_unavailable")):
            valid_seen.add(entry)
    
    # Entferne veraltete out_of_stock Einträge
    valid_domains = [
        "tcgviert", "card-corner", "comicplanet", "gameware", 
        "kofuku", "mighty-cards", "games-island", "sapphirecards", 
        "mightycards", "fantasiacards"
    ]
    
    valid_out_of_stock = set()
    for entry in out_of_stock:
        parts = entry.split('_')
        if len(parts) >= 2 and any(domain in parts[0] for domain in valid_domains):
            valid_out_of_stock.add(entry)
    
    # Speichere bereinigte Daten
    save_seen(valid_seen)
    save_out_of_stock(valid_out_of_stock)
    
    removed_seen = initial_seen - len(valid_seen)
    removed_oos = initial_oos - len(valid_out_of_stock)
    
    logger.info(f"[CLEAN] Entfernt: {removed_seen} seen-Einträge, {removed_oos} out_of_stock-Einträge")
    logger.info(f"[CLEAN] Verbleibend: {len(valid_seen)} seen, {len(valid_out_of_stock)} out_of_stock")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pokémon TCG Scraper mit dynamischen Suchbegriffen")
    parser.add_argument("--mode", choices=["once", "loop", "test", "match_test", 
                                          "shops_test", "keywords", "clean"], 
                        default="loop", help="Ausführungsmodus")
    parser.add_argument("--only-available", action="store_true", 
                        help="Nur verfügbare Produkte melden")
    parser.add_argument("--reset", action="store_true",
                        help="Liste der gesehenen Produkte zurücksetzen")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        default="INFO", help="Log-Level einstellen")
    args = parser.parse_args()

    # Log-Level setzen
    log_level = getattr(logging, args.log_level)
    logging.getLogger().setLevel(log_level)
    logger.setLevel(log_level)
    
    # Logging-Handler aktualisieren
    for handler in logger.handlers:
        handler.setLevel(log_level)
    
    logger.info(f"[START] Modus: {args.mode}, Log-Level: {args.log_level}")
    
    try:
        if args.mode == "once":
            run_once(only_available=args.only_available, reset_seen=args.reset)
        elif args.mode == "loop":
            run_loop(only_available=args.only_available)
        elif args.mode == "test":
            test_telegram()
        elif args.mode == "match_test":
            test_matching()
        elif args.mode == "shops_test":
            test_shops()
        elif args.mode == "keywords":
            monitor_keywords()
        elif args.mode == "clean":
            clean_database()
    except KeyboardInterrupt:
        logger.info("[STOP] Programm durch Benutzer beendet")
    except Exception as e:
        logger.error(f"[CRITICAL] Kritischer Fehler: {str(e)}")
        logger.error(traceback.format_exc())
        sys.exit(1)