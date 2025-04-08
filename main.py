import argparse
import time
from datetime import datetime
from utils.filetools import load_list, load_seen, save_seen
from utils.scheduler import get_current_interval
from utils.telegram import send_telegram_message
from utils.matcher import prepare_keywords
from scrapers.tcgviert import scrape_tcgviert
from scrapers.generic import scrape_generic

def run_once():
    """Führt einen einzelnen Scan-Durchlauf aus"""
    print("🟢 Einzelscan gestartet", flush=True)
    seen = load_seen()
    products = load_list("data/products.txt")
    urls = load_list("data/urls.txt")
    keywords_map = prepare_keywords(products)

    print(f"🔄 Durchlauf: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    
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

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["once", "loop"], default="loop",
                        help="Ausführungsmodus: once = Einzelabruf, loop = Dauerschleife")
    args = parser.parse_args()

    print(f"📦 Modus gewählt: {args.mode}", flush=True)
    if args.mode == "once":
        run_once()
    else:
        run_loop()