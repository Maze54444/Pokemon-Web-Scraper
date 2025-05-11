import argparse
import time
import logging
import traceback
from datetime import datetime
import concurrent.futures
import random
from contextlib import contextmanager

# Neue Importe für verbesserte Konfigurationsverwaltung und Request-Handling
from utils.config_manager import (
    load_products, load_urls, load_seen, save_seen,
    load_out_of_stock, save_out_of_stock, get_current_interval
)
from utils.telegram import send_telegram_message
from utils.matcher import prepare_keywords
from utils.requests_handler import get_page_content, fetch_url

# Scraper-Module
from scrapers.tcgviert import scrape_tcgviert
from scrapers.generic import scrape_generic
from scrapers.sapphire_cards import scrape_sapphire_cards
from scrapers.mighty_cards import scrape_mighty_cards
from scrapers.games_island import scrape_games_island  # Neuer Import für games-island.eu

# Logger-Konfiguration
logger = logging.getLogger("main")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),  # Konsolenausgabe
        logging.FileHandler("scraper.log")  # Dateiausgabe
    ]
)

# Initialisiere Logger für Selenium
selenium_logger = logging.getLogger("selenium")
selenium_logger.setLevel(logging.WARNING)  # Reduziere Log-Spam von Selenium

# Globale Flag für Selenium-Verfügbarkeit
SELENIUM_AVAILABLE = False

def check_selenium_availability():
    """
    Prüft, ob Selenium und Chrome korrekt eingerichtet sind
    
    :return: True wenn verfügbar, False sonst
    """
    global SELENIUM_AVAILABLE
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        
        # Minimale Chrome-Optionen für Test
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        
        # Versuche, Chrome zu starten
        driver = webdriver.Chrome(options=options)
        driver.quit()
        
        logger.info("✅ Selenium und Chrome erfolgreich initialisiert")
        SELENIUM_AVAILABLE = True
        return True
    except Exception as e:
        logger.warning(f"⚠️ Selenium/Chrome nicht verfügbar: {str(e)}")
        logger.debug(traceback.format_exc())
        SELENIUM_AVAILABLE = False
        return False

@contextmanager
def selenium_handler():
    """
    Context Manager für sicheres Starten und Beenden von Selenium-Ressourcen
    
    :yield: True wenn Selenium verfügbar ist, False sonst
    """
    global SELENIUM_AVAILABLE
    
    selenium_status = check_selenium_availability()
    try:
        yield selenium_status
    except Exception as e:
        logger.error(f"❌ Fehler bei Selenium-Operation: {str(e)}")
        logger.debug(traceback.format_exc())
    finally:
        # Bereinige Browser-Ressourcen, wenn Selenium verfügbar ist
        if SELENIUM_AVAILABLE:
            try:
                from scrapers.mighty_cards import cleanup_browsers
                cleanup_browsers()
                logger.info("🧹 Selenium-Browser-Ressourcen bereinigt")
            except Exception as e:
                logger.warning(f"⚠️ Fehler beim Bereinigen von Selenium-Ressourcen: {str(e)}")

def run_once(only_available=False, reset_seen=False):
    """
    Führt einen einzelnen Scan-Durchlauf aus
    
    :param only_available: Ob nur verfügbare Produkte gemeldet werden sollen
    :param reset_seen: Ob die Liste der gesehenen Produkte zurückgesetzt werden soll
    :return: Intervall für den nächsten Durchlauf
    """
    logger.info("[START] Einzelscan gestartet")
    logger.info(f"[MODE] {'Nur verfügbare Produkte' if only_available else 'Alle Produkte'}")
    
    # Prüfe Selenium-Verfügbarkeit beim Start
    with selenium_handler() as selenium_status:
        logger.info(f"[INFO] Selenium-Status: {'Verfügbar' if selenium_status else 'Nicht verfügbar'}")
    
    # Seen-Liste zurücksetzen, wenn angefordert
    if reset_seen:
        logger.info("[RESET] Setze Liste der gesehenen Produkte zurück")
        save_seen(set())
    
    # Lade Konfiguration und Zustände mit den neuen Funktionen
    seen = load_seen()
    out_of_stock = load_out_of_stock()
    products = load_products()
    urls = load_urls()
    keywords_map = prepare_keywords(products)
    
    logger.info(f"[INFO] Durchlauf: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"[INFO] Suchbegriffe: {list(keywords_map.keys())}")
    logger.info(f"[INFO] {len(out_of_stock)} ausverkaufte Produkte werden überwacht")
    
    all_matches = []
    all_urls = urls.copy()  # Kopie erstellen, damit die Originalliste intakt bleibt
    
    # Sapphire-Cards spezifischer Scraper (wichtig: keine URLs mehr entfernen)
    sapphire_urls = [url for url in all_urls if "sapphire-cards.de" in url]
    if sapphire_urls:
        try:
            logger.info("[SCRAPER] Starte Sapphire-Cards Scraper")
            sapphire_matches = scrape_sapphire_cards(keywords_map, seen, out_of_stock, only_available)
            if sapphire_matches:
                logger.info(f"[SUCCESS] {len(sapphire_matches)} neue Treffer bei Sapphire-Cards gefunden")
                all_matches.extend(sapphire_matches)
            else:
                logger.info("[INFO] Keine neuen Treffer bei Sapphire-Cards")
        except Exception as e:
            logger.error(f"[ERROR] Fehler beim Sapphire-Cards Scraping: {str(e)}")
            logger.debug(traceback.format_exc())
    
    # TCGViert-spezifischer Scraper (wichtig: keine URLs mehr entfernen)
    tcgviert_urls = [url for url in all_urls if "tcgviert.com" in url]
    if tcgviert_urls:
        try:
            logger.info("[SCRAPER] Starte TCGViert Scraper")
            tcgviert_matches = scrape_tcgviert(keywords_map, seen, out_of_stock, only_available)
            if tcgviert_matches:
                logger.info(f"[SUCCESS] {len(tcgviert_matches)} neue Treffer bei TCGViert gefunden")
                all_matches.extend(tcgviert_matches)
            else:
                logger.info("[INFO] Keine neuen Treffer bei TCGViert")
        except Exception as e:
            logger.error(f"[ERROR] Fehler beim TCGViert Scraping: {str(e)}")
            logger.debug(traceback.format_exc())
    
    # Mighty-cards spezifischer Scraper mit Selenium-Unterstützung
    mighty_cards_urls = [url for url in all_urls if "mighty-cards.de" in url]
    if mighty_cards_urls:
        try:
            logger.info("[SCRAPER] Starte Mighty-Cards Scraper mit Selenium")
            # Führe Scraper in einem Selenium-Handler aus, um Ressourcen zu bereinigen
            with selenium_handler() as selenium_status:
                mighty_cards_matches = scrape_mighty_cards(keywords_map, seen, out_of_stock, only_available)
                if mighty_cards_matches:
                    logger.info(f"[SUCCESS] {len(mighty_cards_matches)} neue Treffer bei Mighty-Cards gefunden")
                    all_matches.extend(mighty_cards_matches)
                else:
                    logger.info("[INFO] Keine neuen Treffer bei Mighty-Cards")
        except Exception as e:
            logger.error(f"[ERROR] Fehler beim Mighty-Cards Scraping: {str(e)}")
            logger.debug(traceback.format_exc())
            
    # Games-Island spezifischer Scraper (NEU)
    games_island_urls = [url for url in all_urls if "games-island.eu" in url]
    if games_island_urls:
        try:
            logger.info("[SCRAPER] Starte Games-Island Scraper")
            games_island_matches = scrape_games_island(keywords_map, seen, out_of_stock, only_available)
            if games_island_matches:
                logger.info(f"[SUCCESS] {len(games_island_matches)} neue Treffer bei Games-Island gefunden")
                all_matches.extend(games_island_matches)
            else:
                logger.info("[INFO] Keine neuen Treffer bei Games-Island")
        except Exception as e:
            logger.error(f"[ERROR] Fehler beim Games-Island Scraping: {str(e)}")
            logger.debug(traceback.format_exc())
    
    # Generische URLs - immer alle scannen, aber jetzt auch Games-Island ausschließen
    generic_urls = [url for url in all_urls if not ("sapphire-cards.de" in url or 
                                                  "tcgviert.com" in url or 
                                                  "mighty-cards.de" in url or
                                                  "games-island.eu" in url)]
    if generic_urls:
        logger.info(f"[INFO] Starte generische Scraper für {len(generic_urls)} URLs")
        
        # Parallele Verarbeitung mit ThreadPoolExecutor
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(generic_urls)) as executor:
            # Dictionary zum Speichern der Future-Objekte mit ihren URLs
            future_to_url = {
                executor.submit(
                    scrape_generic, url, keywords_map, seen, out_of_stock, 
                    check_availability=True, only_available=only_available
                ): url for url in generic_urls
            }
            
            # Ergebnisse sammeln
            for future in concurrent.futures.as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    new_url_matches = future.result()
                    if new_url_matches:
                        logger.info(f"[SUCCESS] {len(new_url_matches)} neue Treffer bei {url} gefunden")
                        all_matches.extend(new_url_matches)
                    else:
                        logger.info(f"[INFO] Keine neuen Treffer bei {url}")
                except Exception as e:
                    logger.error(f"[ERROR] Fehler beim Scraping von {url}: {str(e)}")
                    logger.debug(traceback.format_exc())

    # Speichere aktualisierte Zustände
    save_seen(seen)
    save_out_of_stock(out_of_stock)
    
    # Erfolgsmeldung senden, wenn mindestens ein Treffer gefunden wurde
    if all_matches:
        success_message = f"✅ Scraper-Durchlauf erfolgreich! {len(all_matches)} neue Treffer gefunden."
        logger.info(f"[SUCCESS] {success_message}")
    else:
        logger.info("[INFO] Keine neuen Treffer in diesem Durchlauf")
    
    interval = get_current_interval()
    logger.info(f"[DONE] Fertig. Nächster Durchlauf in {interval} Sekunden")
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
            logger.error(f"[ERROR] Fehler im Hauptloop: {str(e)}")
            logger.error(traceback.format_exc())
            
            # Exponentielles Backoff bei wiederholten Fehlern
            retry_time = min(60 * (2 ** (consecutive_errors - 1)), 3600)  # Max 1 Stunde
            
            # Bei zu vielen aufeinanderfolgenden Fehlern, Benachrichtigung senden
            if consecutive_errors >= max_consecutive_errors:
                error_msg = f"⚠️ *WARNUNG*: Der Scraper hat {consecutive_errors} Fehler in Folge. Letzte Fehlermeldung: {str(e)}"
                send_telegram_message(error_msg)
                consecutive_errors = 0  # Zähler zurücksetzen nach Benachrichtigung
            
            logger.warning(f"[RETRY] Neustart in {retry_time} Sekunden...")
            time.sleep(retry_time)

def test_telegram():
    """Testet die Telegram-Benachrichtigungsfunktion"""
    logger.info("[TEST] Starte Telegram-Test")
    result = send_telegram_message("[TEST] Test-Nachricht vom TCG-Scraper")
    if result:
        logger.info("[SUCCESS] Telegram-Test erfolgreich")
    else:
        logger.error("[ERROR] Telegram-Test fehlgeschlagen")

def test_matching():
    """Testet das Matching für bekannte Produktnamen"""
    logger.info("[TEST] Teste Matching-Funktion")
    
    test_titles = [
        "Pokémon TCG: Journey Together (SV09) - 36er Display (EN) - max. 1 per person",
        "Pokémon TCG: Journey Together (SV09) - Checklane Blister (EN) - max. 6 per person",
        "Pokémon TCG: Journey Together (SV09) - Premium Checklane Blister (EN) - max. 6 per person",
        "Pokémon TCG: Journey Together (SV09) - Elite Trainer Box (EN) - max. 1 per person",
        "Pokémon TCG: Journey Together (SV09) - Sleeved Booster (EN) - max. 12 per person",
        "Pokémon TCG: Reisegefährten (KP09) - 36er Display (DE) - max. 1 pro Person",
        "Pokémon TCG: Reisegefährten (KP09) - Top Trainer Box (DE) - max. 1 pro Person",
        "Pokemon Journey Together | Reisegefährten Booster Box (Display)"  # Sapphire-Cards Format
    ]
    
    test_keywords = [
        ["journey", "together", "display"],
        ["reisegefährten", "display"]
    ]
    
    from utils.matcher import is_keyword_in_text, clean_text
    
    for title in test_titles:
        logger.info(f"\nTest für Titel: {title}")
        clean_title_lower = clean_text(title)
        logger.info(f"  Bereinigter Titel: '{clean_title_lower}'")
        for keywords in test_keywords:
            result = is_keyword_in_text(keywords, title)
            logger.info(f"  Mit Keywords {keywords}: {result}")

def test_availability():
    """Testet die Verfügbarkeitsprüfung für bekannte URLs"""
    logger.info("[TEST] Teste Verfügbarkeitsprüfung")
    
    from scrapers.generic import check_product_availability
    from utils.availability import detect_availability
    from utils.requests_handler import get_default_headers, get_page_content
    
    test_urls = [
        "https://tcgviert.com/products/pokemon-tcg-journey-together-sv09-36er-display-en-max-1-per-person",
        "https://www.card-corner.de/pokemon-schwert-und-schild-scarlet-und-violet-151-display-deutsch",
        "https://sapphire-cards.de/produkt/pokemon-journey-together-reisegefaehrten-booster-box-display/",
    ]
    
    # Verwende verbesserten Request-Handler
    headers = get_default_headers()
    
    for url in test_urls:
        logger.info(f"\nTest für URL: {url}")
        try:
            # Verwende robuste HTTP-Anfragen
            success, soup, status_code, error = get_page_content(
                url,
                headers=headers,
                verify_ssl=True if "gameware.at" not in url and "games-island.eu" not in url else False,
                timeout=30 if "games-island.eu" in url else 15
            )
            
            if success:
                is_available, price, status_text = detect_availability(soup, url)
                logger.info(f"  Verfügbar: {is_available}")
                logger.info(f"  Preis: {price}")
                logger.info(f"  Status: {status_text}")
            else:
                logger.error(f"  Fehler: {error}")
        except Exception as e:
            logger.error(f"  Fehler: {e}")

def test_request_handler():
    """Testet den verbesserten Request-Handler mit problematischen URLs"""
    logger.info("[TEST] Teste verbesserten Request-Handler")
    
    from utils.requests_handler import fetch_url, get_page_content, get_default_headers
    
    # URLs mit bekannten Problemen
    test_urls = [
        "https://www.gameware.at/info/spaces/gameware/gamewareSearch?query=reisegef%E4hrten&actionTag=search",
        "https://games-island.eu/",
        "https://tcgviert.com/",  # Referenz-URL ohne bekannte Probleme
    ]
    
    headers = get_default_headers()
    
    for url in test_urls:
        logger.info(f"\nTest für URL: {url}")
        try:
            # Verwende verbesserte fetch_url Funktion
            verify_ssl = True if "gameware.at" not in url and "games-island.eu" not in url else False
            timeout = 30 if "games-island.eu" in url else 15
            
            response, error = fetch_url(
                url,
                headers=headers,
                verify_ssl=verify_ssl,
                timeout=timeout
            )
            
            if response:
                logger.info(f"  ✅ Erfolgreich abgerufen: Status {response.status_code}")
            else:
                logger.error(f"  ❌ Fehler: {error}")
                
            # Teste auch die get_page_content Funktion
            success, soup, status_code, error = get_page_content(
                url,
                headers=headers,
                verify_ssl=verify_ssl,
                timeout=timeout
            )
            
            if success:
                logger.info(f"  ✅ Seite erfolgreich geladen und geparst")
                title = soup.title.text if soup.title else "Kein Titel gefunden"
                logger.info(f"  Titel: {title[:50]}...")
            else:
                logger.error(f"  ❌ Fehler beim Parsen: {error}")
                
        except Exception as e:
            logger.error(f"  Fehler bei manuellem Test: {e}")

def test_sapphire():
    """Testet den Sapphire-Cards Scraper isoliert"""
    logger.info("[TEST] Teste Sapphire-Cards Scraper isoliert")
    
    products = load_products()
    keywords_map = prepare_keywords(products)
    
    seen = set()
    out_of_stock = set()
    
    from scrapers.sapphire_cards import scrape_sapphire_cards
    matches = scrape_sapphire_cards(keywords_map, seen, out_of_stock)
    
    if matches:
        logger.info(f"[SUCCESS] Test erfolgreich, {len(matches)} Treffer gefunden")
    else:
        logger.warning("[WARNING] Test möglicherweise fehlgeschlagen, keine Treffer gefunden")

def test_mighty_cards():
    """Testet den Mighty-Cards Scraper isoliert mit Selenium-Unterstützung"""
    logger.info("[TEST] Teste Mighty-Cards Scraper isoliert mit Selenium")
    
    products = load_products()
    keywords_map = prepare_keywords(products)
    
    seen = set()
    out_of_stock = set()
    
    # Führe Mighty-Cards Test in einem Selenium-Handler aus
    with selenium_handler() as selenium_status:
        if not selenium_status:
            logger.warning("[WARNING] Selenium nicht verfügbar, verwende nur BeautifulSoup")
        
        from scrapers.mighty_cards import scrape_mighty_cards
        matches = scrape_mighty_cards(keywords_map, seen, out_of_stock)
        
        if matches:
            logger.info(f"[SUCCESS] Test erfolgreich, {len(matches)} Treffer gefunden")
        else:
            logger.warning("[WARNING] Test möglicherweise fehlgeschlagen, keine Treffer gefunden")

def test_games_island():
    """Testet den Games-Island Scraper isoliert"""
    logger.info("[TEST] Teste Games-Island Scraper isoliert")
    
    products = load_products()
    keywords_map = prepare_keywords(products)
    
    seen = set()
    out_of_stock = set()
    
    from scrapers.games_island import scrape_games_island
    matches = scrape_games_island(keywords_map, seen, out_of_stock)
    
    if matches:
        logger.info(f"[SUCCESS] Test erfolgreich, {len(matches)} Treffer gefunden")
    else:
        logger.warning("[WARNING] Test möglicherweise fehlgeschlagen, keine Treffer gefunden")

def test_selenium():
    """Testet die Selenium-Verfügbarkeit und Browser-Funktionalität"""
    logger.info("[TEST] Teste Selenium und Browser-Funktionalität")
    
    with selenium_handler() as selenium_status:
        if selenium_status:
            try:
                # Definiere Test-URL
                test_url = "https://www.mighty-cards.de/"
                
                # Importiere notwendige Selenium-Funktionen
                from selenium import webdriver
                from selenium.webdriver.chrome.options import Options
                from selenium.webdriver.common.by import By
                
                # Konfiguriere Browser
                options = Options()
                options.add_argument("--headless")
                options.add_argument("--no-sandbox")
                options.add_argument("--disable-dev-shm-usage")
                
                # Browser starten
                driver = webdriver.Chrome(options=options)
                
                # Test-URL laden
                driver.get(test_url)
                
                # Prüfe, ob die Seite geladen wurde
                page_title = driver.title
                
                # Extrahiere einige Elemente, um die Funktionalität zu testen
                logo = driver.find_elements(By.CSS_SELECTOR, "img.shop-logo")
                navigation = driver.find_elements(By.CSS_SELECTOR, ".header-navigation")
                
                # Browser schließen
                driver.quit()
                
                # Ergebnis ausgeben
                logger.info(f"[SUCCESS] Selenium-Test erfolgreich, Titel: {page_title}")
                logger.info(f"[INFO] Logo gefunden: {bool(logo)}")
                logger.info(f"[INFO] Navigation gefunden: {bool(navigation)}")
                
            except Exception as e:
                logger.error(f"[ERROR] Selenium-Test fehlgeschlagen: {str(e)}")
                logger.debug(traceback.format_exc())
        else:
            logger.warning("[WARNING] Selenium nicht verfügbar, Test übersprungen")

def monitor_out_of_stock():
    """Zeigt die aktuell ausverkauften Produkte an, die überwacht werden"""
    out_of_stock = load_out_of_stock()
    
    if not out_of_stock:
        logger.info("Keine ausverkauften Produkte werden aktuell überwacht.")
        return
    
    logger.info(f"[INFO] Aktuell werden {len(out_of_stock)} ausverkaufte Produkte überwacht:")
    for product_id in sorted(out_of_stock):
        parts = product_id.split('_')
        site = parts[0]
        series = parts[1] if len(parts) > 1 else "unknown"
        type_ = parts[2] if len(parts) > 2 else "unknown"
        lang = parts[3] if len(parts) > 3 else "unknown"
        
        logger.info(f"  - {site}: {series} {type_} ({lang})")

def clean_database():
    """Bereinigt die Datenbanken von alten oder fehlerhaften Einträgen"""
    logger.info("[CLEAN] Bereinige Datenbanken")
    
    # Lade aktuelle Daten
    seen = load_seen()
    out_of_stock = load_out_of_stock()
    
    # Vor der Bereinigung
    logger.info(f"[INFO] Vor der Bereinigung: {len(seen)} gesehene Produkte, {len(out_of_stock)} ausverkaufte Produkte")
    
    # Entferne Einträge, die kein korrektes Format haben
    valid_seen = set()
    for entry in seen:
        # Gültiges Format: product_id_status_available oder product_id_status_unavailable
        if "_status_" in entry and (entry.endswith("_available") or entry.endswith("_unavailable")):
            valid_seen.add(entry)
    
    # Entferne veraltete Einträge aus out_of_stock
    # Wir behalten nur Einträge, die einer der bekannten Domains entsprechen
    valid_domains = ["tcgviert", "card-corner", "comicplanet", "gameware", 
                     "kofuku", "mighty-cards", "games-island", "sapphirecards", "mightycards",
                     "gamesisland"]  # Neuer Eintrag für Games-Island
    
    valid_out_of_stock = set()
    for product_id in out_of_stock:
        parts = product_id.split('_')
        if len(parts) >= 2 and parts[0] in valid_domains:
            valid_out_of_stock.add(product_id)
    
    # Speichere bereinigte Daten
    save_seen(valid_seen)
    save_out_of_stock(valid_out_of_stock)
    
    # Nach der Bereinigung
    logger.info(f"[INFO] Nach der Bereinigung: {len(valid_seen)} gesehene Produkte, {len(valid_out_of_stock)} ausverkaufte Produkte")
    logger.info(f"[INFO] Entfernt: {len(seen) - len(valid_seen)} gesehene Produkte, {len(out_of_stock) - len(valid_out_of_stock)} ausverkaufte Produkte")
    
    return len(seen) - len(valid_seen), len(out_of_stock) - len(valid_out_of_stock)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pokémon TCG Scraper mit verbesserten Filtern")
    parser.add_argument("--mode", choices=["once", "loop", "test", "match_test", "availability_test", 
                                          "sapphire_test", "mighty_cards_test", "games_island_test",
                                          "selenium_test", # Neuer Test für Selenium
                                          "request_test", "show_out_of_stock", "clean"], 
                        default="loop", help="Ausführungsmodus")
    parser.add_argument("--only-available", action="store_true", 
                        help="Nur verfügbare Produkte melden (nicht ausverkaufte)")
    parser.add_argument("--reset", action="store_true",
                        help="Liste der gesehenen Produkte zurücksetzen")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
                        default="INFO", help="Log-Level einstellen")
    args = parser.parse_args()

    # Log-Level entsprechend setzen
    log_level = getattr(logging, args.log_level)
    logging.getLogger().setLevel(log_level)
    
    logger.info(f"[START] Modus gewählt: {args.mode} - Log-Level: {args.log_level}")
    
    if args.mode == "once":
        run_once(only_available=args.only_available, reset_seen=args.reset)
    elif args.mode == "loop":
        run_loop(only_available=args.only_available)
    elif args.mode == "test":
        test_telegram()
    elif args.mode == "match_test":
        test_matching()
    elif args.mode == "availability_test":
        test_availability()
    elif args.mode == "sapphire_test":
        test_sapphire()
    elif args.mode == "mighty_cards_test":
        test_mighty_cards()
    elif args.mode == "games_island_test":
        test_games_island()
    elif args.mode == "selenium_test":
        test_selenium()
    elif args.mode == "request_test":
        test_request_handler()
    elif args.mode == "show_out_of_stock":
        monitor_out_of_stock()
    elif args.mode == "clean":
        clean_database()