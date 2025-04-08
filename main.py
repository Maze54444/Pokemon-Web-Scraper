import argparse
import time
from datetime import datetime
from utils.files import load_list, load_seen, save_seen
from utils.scheduler import get_current_interval
from utils.telegram import send_telegram_message
from utils.matcher import prepare_keywords
from scrapers.tcgviert import scrape_tcgviert
from scrapers.generic import scrape_generic

def run_once():
    print("🟢 Einzelscan gestartet", flush=True)
    seen = load_seen()
    products = load_list("data/products.txt")
    urls = load_list("data/urls.txt")
    keywords_map = prepare_keywords(products)

    print(f"🔄 Durchlauf: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    for url in urls:
        if "tcgviert.com" in url:
            scrape_tcgviert(keywords_map, seen)
        else:
            scrape_generic(url, keywords_map, seen)

    save_seen(seen)
    interval = get_current_interval("config/schedule.json")
    print(f"⏳ Fertig. Nächster Durchlauf wäre in {interval} Sekunden", flush=True)
    return interval

def run_loop():
    print("🌀 Dauerbetrieb gestartet", flush=True)
    while True:
        interval = run_once()
        time.sleep(interval)

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