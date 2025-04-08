# scrapers/tcgviert.py
import requests
import hashlib
from utils.matcher import is_flexible_match, clean_text
from utils.telegram import send_telegram_message

def scrape_tcgviert(keywords_map, seen):
    print("🌐 Verwende tcgviert.com JSON-API")
    try:
        response = requests.get("https://tcgviert.com/products.json", timeout=10)
        response.raise_for_status()
        data = response.json()

        for product in data.get("products", []):
            title = product.get("title", "")
            clean_title = clean_text(title)
            handle = product.get("handle", "")
            url = f"https://tcgviert.com/products/{handle}"
            price = product["variants"][0]["price"] if product["variants"] else "?"

            for entry, keywords in keywords_map.items():
                identifier = hashlib.md5((title + url).encode()).hexdigest()
                if identifier not in seen and is_flexible_match(keywords, clean_title):
                    message = f"🔥 Neuer Fund: {title}\n💶 Preis: {price} €\n🔗 Link: {url}"
                    send_telegram_message(message)
                    seen.add(identifier)
                    print(f"✅ TREFFER: {title} – {price} € – {url}")

    except Exception as e:
        print(f"❌ Fehler bei tcgviert.com: {e}")
