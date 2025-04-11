import argparse
import time
from datetime import datetime
from utils.filetools import load_list, load_seen, save_seen
from utils.stock import load_out_of_stock, save_out_of_stock
from utils.scheduler import get_current_interval
from utils.telegram import send_telegram_message
from utils.matcher import prepare_keywords, is_keyword_in_text, clean_text
from scrapers.tcgviert import scrape_tcgviert
from scrapers.generic import scrape_generic
from scrapers.sapphire_cards import scrape_sapphire_cards  # Neuer Import

def run_once(only_available=False, reset_seen=False):
    """
    Führt einen einzelnen Scan-Durchlauf aus
    
    :param only_available: Ob nur verfügbare Produkte gemeldet werden sollen
    :param reset_seen: Ob die Liste der gesehenen Produkte zurückgesetzt werden soll
    :return: Intervall für den nächsten Durchlauf
    """
    print("🟢 Einzelscan gestartet", flush=True)
    print(f"👁️ Modus: {'Nur verfügbare Produkte' if only_available else 'Alle Produkte'}", flush=True)
    
    # Seen-Liste zurücksetzen, wenn angefordert
    if reset_seen:
        print("🧹 Setze Liste der gesehenen Produkte zurück", flush=True)
        with open("data/seen.txt", "w", encoding="utf-8") as f:
            f.write("")
    
    # Lade Konfiguration und Zustände
    seen = load_seen()
    out_of_stock = load_out_of_stock()
    products = load_list("data/products.txt")
    urls = load_list("data/urls.txt")
    keywords_map = prepare_keywords(products)
    
    print(f"🔄 Durchlauf: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    print(f"🔍 Suchbegriffe: {list(keywords_map.keys())}", flush=True)
    print(f"📋 {len(out_of_stock)} ausverkaufte Produkte werden überwacht", flush=True)
    
    # TCGViert-spezifischer Scraper
    new_matches = scrape_tcgviert(keywords_map, seen, out_of_stock, only_available)
    if new_matches:
        print(f"✅ {len(new_matches)} neue Treffer bei TCGViert gefunden", flush=True)
    
    # Sapphire-Cards spezifischer Scraper
    if any("sapphire-cards.de" in url for url in urls):
        sapphire_matches = scrape_sapphire_cards(keywords_map, seen, out_of_stock, only_available)
        if sapphire_matches:
            print(f"✅ {len(sapphire_matches)} neue Treffer bei Sapphire-Cards gefunden", flush=True)
            new_matches.extend(sapphire_matches)
        # Entferne sapphire-cards.de aus der URL-Liste für den generischen Scraper
        urls = [url for url in urls if "sapphire-cards.de" not in url]
    
    # Generische URL-Scraper
    for url in urls:
        if "tcgviert.com" not in url:  # TCGViert wird bereits separat abgefragt
            new_url_matches = scrape_generic(url, keywords_map, seen, out_of_stock, check_availability=True, only_available=only_available)
            if new_url_matches:
                print(f"✅ {len(new_url_matches)} neue Treffer bei {url} gefunden", flush=True)
                new_matches.extend(new_url_matches)

    # Speichere aktualisierte Zustände
    save_seen(seen)
    save_out_of_stock(out_of_stock)
    
    interval = get_current_interval("config/schedule.json")
    print(f"⏳ Fertig. Nächster Durchlauf in {interval} Sekunden", flush=True)
    return interval

def run_loop(only_available=False):
    """
    Startet den Scraper im Dauerbetrieb
    
    :param only_available: Ob nur verfügbare Produkte gemeldet werden sollen
    """
    print("🌀 Dauerbetrieb gestartet", flush=True)
    while True:
        try:
            interval = run_once(only_available=only_available)
            time.sleep(interval)
        except Exception as e:
            print(f"❌ Fehler im Hauptloop: {e}", flush=True)
            print("🔄 Neustart in 60 Sekunden...", flush=True)
            time.sleep(60)

def test_telegram():
    """Testet die Telegram-Benachrichtigungsfunktion"""
    print("🧪 Starte Telegram-Test", flush=True)
    result = send_telegram_message("🧪 Test-Nachricht vom TCG-Scraper")
    if result:
        print("✅ Telegram-Test erfolgreich", flush=True)
    else:
        print("❌ Telegram-Test fehlgeschlagen", flush=True)

def test_matching():
    """Testet das Matching für bekannte Produktnamen"""
    print("🧪 Teste Matching-Funktion", flush=True)
    
    test_titles = [
        "Pokémon TCG: Journey Together (SV09) - 36er Display (EN) - max. 1 per person",
        "Pokémon TCG: Journey Together (SV09) - Checklane Blister (EN) - max. 6 per person",
        "Pokémon TCG: Journey Together (SV09) - Premium Checklane Blister (EN) - max. 6 per person",
        "Pokémon TCG: Journey Together (SV09) - Elite Trainer Box (EN) - max. 1 per person",
        "Pokémon TCG: Journey Together (SV09) - Sleeved Booster (EN) - max. 12 per person",
        "Pokémon TCG: Reisegefährten (KP09) - 36er Display (DE) - max. 1 pro Person",
        "Pokémon TCG: Reisegefährten (KP09) - Top Trainer Box (DE) - max. 1 pro Person"
    ]
    
    test_keywords = [
        ["journey", "together", "display"],
        ["reisegefährten", "display"]
    ]
    
    for title in test_titles:
        print(f"\nTest für Titel: {title}")
        clean_title = clean_text(title)
        print(f"  Bereinigter Titel: '{clean_title}'")
        for keywords in test_keywords:
            result = is_keyword_in_text(keywords, title)
            print(f"  Mit Keywords {keywords}: {result}")

def test_availability():
    """Testet die Verfügbarkeitsprüfung für bekannte URLs"""
    print("🧪 Teste Verfügbarkeitsprüfung", flush=True)
    
    from scrapers.generic import check_product_availability
    from utils.availability import detect_availability
    import requests
    from bs4 import BeautifulSoup
    
    test_urls = [
        "https://tcgviert.com/products/pokemon-tcg-journey-together-sv09-36er-display-en-max-1-per-person",
        "https://www.card-corner.de/pokemon-schwert-und-schild-scarlet-und-violet-151-display-deutsch",
    ]
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    for url in test_urls:
        print(f"\nTest für URL: {url}")
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")
                is_available, price, status_text = detect_availability(soup, url)
                print(f"  Verfügbar: {is_available}")
                print(f"  Preis: {price}")
                print(f"  Status: {status_text}")
            else:
                print(f"  Fehler: HTTP Status {response.status_code}")
        except Exception as e:
            print(f"  Fehler: {e}")

def monitor_out_of_stock():
    """Zeigt die aktuell ausverkauften Produkte an, die überwacht werden"""
    out_of_stock = load_out_of_stock()
    
    if not out_of_stock:
        print("Keine ausverkauften Produkte werden aktuell überwacht.", flush=True)
        return
    
    print(f"Aktuell werden {len(out_of_stock)} ausverkaufte Produkte überwacht:", flush=True)
    for product_id in sorted(out_of_stock):
        parts = product_id.split('_')
        site = parts[0]
        series = parts[1] if len(parts) > 1 else "unknown"
        type_ = parts[2] if len(parts) > 2 else "unknown"
        lang = parts[3] if len(parts) > 3 else "unknown"
        
        print(f"  - {site}: {series} {type_} ({lang})", flush=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["once", "loop", "test", "match_test", "availability_test", "show_out_of_stock"], 
                        default="loop", help="Ausführungsmodus")
    parser.add_argument("--only-available", action="store_true", 
                        help="Nur verfügbare Produkte melden (nicht ausverkaufte)")
    parser.add_argument("--reset", action="store_true",
                        help="Liste der gesehenen Produkte zurücksetzen")
    args = parser.parse_args()

    print(f"📦 Modus gewählt: {args.mode}", flush=True)
    
    if args.mode == "once":
        run_once(only_available=args.only_available, reset_seen=args.reset)
    elif args.mode == "test":
        test_telegram()
    elif args.mode == "match_test":
        test_matching()
    elif args.mode == "availability_test":
        test_availability()
    elif args.mode == "show_out_of_stock":
        monitor_out_of_stock()
    else:
        run_loop(only_available=args.only_available)