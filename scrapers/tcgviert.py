
import requests, hashlib
from utils.matcher import clean_text, is_flexible_match
from utils.telegram import send_telegram_message

def scrape_tcgviert(keywords_map, seen):
    try:
        res = requests.get("https://tcgviert.com/products.json", timeout=10)
        for product in res.json().get("products", []):
            title = product.get("title", "")
            clean = clean_text(title)
            url = f"https://tcgviert.com/products/{product.get('handle')}"
            price = product["variants"][0]["price"] if product["variants"] else "?"
            for entry, keys in keywords_map.items():
                id = hashlib.md5((title + url).encode()).hexdigest()
                if id not in seen and is_flexible_match(keys, clean):
                    send_telegram_message(f"🔥 Neuer Fund: {title}\n💶 Preis: {price} €\n🔗 Link: {url}")
                    seen.add(id)
                    print(f"✅ {title} – {price} € – {url}")
    except Exception as e:
        print(f"❌ Fehler bei tcgviert: {e}")
