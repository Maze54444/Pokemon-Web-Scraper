import argparse
import time
from datetime import datetime
from utils.filetools import load_list, load_seen, save_seen
from utils.scheduler import get_current_interval
from utils.telegram import send_telegram_message
from utils.matcher import prepare_keywords, is_keyword_in_text, clean_text
from scrapers.tcgviert import scrape_tcgviert
from scrapers.generic import scrape_generic

def run_once():
    """Führt einen einzelnen Scan-Durchlauf aus"""
    print("🟢 Einzelscan gestartet", flush=True)
    
    # Seen-Liste zurücksetzen
    with open("data/seen.txt", "w", encoding="utf-8") as f:
        f.write("")
    
    seen = load_seen()
    products = load_list("data/products.txt")
    urls = load_list("data/urls.txt")
    keywords_map = prepare_keywords(products)
    
    print(f"🔄 Durchlauf: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    print(f"🔍 Suchbegriffe: {keywords_map}", flush=True)
    
    # TCGViert-spezifischer Scraper
    new_matches = scrape_tcgviert(keywords_map, seen)
    if new_matches:
        print(f"✅ {len(new_matches)} neue Treffer bei TCGViert gefunden", flush=True)
    
    # Generische URL-Scraper
    for url in urls:
        if "tcgviert.com" not in url:  # TCGViert wird bereits separat abgefragt
            new_url_matches = scrape_generic(url, keywords_map, seen)
            if new_url_matches:
                print(f"✅ {len(new_url_matches)} neue Treffer bei {url} gefunden", flush=True)

    save_seen(seen)
    interval = get_current_interval("config/schedule.json")
    print(f"⏳ Fertig. Nächster Durchlauf in {interval} Sekunden", flush=True)
    return interval

def run_loop():
    """Startet den Scraper im Dauerbetrieb"""
    print("🌀 Dauerbetrieb gestartet", flush=True)
    while True:
        try:
            interval = run_once()
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
        ["journey", "together"],
        ["reisegefährten"]
    ]
    
    for title in test_titles:
        print(f"\nTest für Titel: {title}")
        clean_title = clean_text(title)
        print(f"  Bereinigter Titel: '{clean_title}'")
        for keywords in test_keywords:
            result = is_keyword_in_text(keywords, title)
            print(f"  Mit Keywords {keywords}: {result}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["once", "loop", "test", "match_test"], default="loop",
                        help="Ausführungsmodus: once = Einzelabruf, loop = Dauerschleife, test = Telegram-Test, match_test = Matching-Test")
    args = parser.parse_args()

    print(f"📦 Modus gewählt: {args.mode}", flush=True)
    if args.mode == "once":
        run_once()
    elif args.mode == "test":
        test_telegram()
    elif args.mode == "match_test":
        test_matching()
    else:
        run_loop()