import requests
import time
from utils.telegram import send_telegram_message
from utils.matcher import clean_text, is_keyword_in_text, prepare_keywords
from utils.filetools import load_list_from_file, load_seen, save_seen

def scrape_tcgviert():
    print("🌐 Starte JSON-Scraper für tcgviert", flush=True)
    seen = load_seen("data/seen.txt")
    products = load_list_from_file("data/products.txt")
    keywords_map = prepare_keywords(products)

    try:
        response = requests.get("https://tcgviert.com/products.json", timeout=10)
        items = response.json()["products"]
    except Exception as e:
        print(f"❌ Fehler beim Abruf der API: {e}", flush=True)
        return

    hits = []
    for item in items:
        title = item["title"]
        handle = item["handle"]
        clean = clean_text(title)

        for product, keys in keywords_map.items():
            score = 0
            if is_keyword_in_text(keys, clean):
                score = 1.0  # da alle enthalten sein müssen
                if title not in seen:
                    url = f"https://tcgviert.com/products/{handle}"
                    price = item["variants"][0]["price"]
                    msg = f"🎯 *{title}*\n💶 {price}€\n🔗 [Zum Produkt]({url})"
                    hits.append(msg)
                    seen.append(title)
            print(f"🟡 Prüfe gegen Produkt: '{clean}' mit Keywords {keys} → Treffer: {score}", flush=True)

    for msg in hits:
        send_telegram_message(msg)

    save_seen("data/seen.txt", seen)