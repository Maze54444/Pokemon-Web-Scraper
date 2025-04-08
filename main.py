# main.py

from utils.files import load_list, load_seen, save_seen
from utils.scheduler import get_current_interval
from utils.telegram import send_telegram_message
from utils.matcher import prepare_keywords
from scrapers.tcgviert import scrape_tcgviert
from scrapers.generic import scrape_generic
import time
from datetime import datetime

def run():
    print("🟢 Scraper gestartet")
    seen = load_seen()
    products = load_list("data/products.txt")
    urls = load_list("data/urls.txt")
    keywords_map = prepare_keywords(products)

    while True:
        print(f"🔄 Durchlauf: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        for url in urls:
            if "tcgviert.com" in url:
                scrape_tcgviert(keywords_map, seen)
            else:
                scrape_generic(url, keywords_map, seen)

        save_seen(seen)
        interval = get_current_interval("config/schedule.json")
        print(f"⏳ Warte {interval} Sekunden bis zum nächsten Scan")
        time.sleep(interval)

# 🧠 Der entscheidende Block:
if __name__ == "__main__":
    run()
