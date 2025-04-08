import requests
import hashlib
from bs4 import BeautifulSoup
from utils.matcher import clean_text, is_flexible_match
from utils.telegram import send_telegram_message

def scrape_tcgviert(keywords_map, seen):
    print("🌐 Starte JSON-Scraper für tcgviert", flush=True)
    found = scrape_tcgviert_json(keywords_map, seen)

    if not found:
        print("⚠️ Keine Treffer über JSON – fallback zu HTML-Scraper", flush=True)
        scrape_tcgviert_html(keywords_map, seen)

def scrape_tcgviert_json(keywords_map, seen):
    try:
        res = requests.get("https://tcgviert.com/products.json", timeout=10)
        found_any = False
        for product in res.json().get("products", []):
            title = product.get("title", "")
            clean = clean_text(title)
            url = f"https://tcgviert.com/products/{product.get('handle')}"
            price = product["variants"][0]["price"] if product["variants"] else "?"
            for entry, keys in keywords_map.items():
                id = hashlib.md5((title + url).encode()).hexdigest()
                if id not in seen and is_flexible_match(keys, clean):
                    send_telegram_message(f"🔥 Neuer Fund (API): {title}\n💶 Preis: {price} €\n🔗 Link: {url}")
                    seen.add(id)
                    print(f"✅ JSON TREFFER: {title} – {price} € – {url}", flush=True)
                    found_any = True
        return found_any
    except Exception as e:
        print(f"❌ Fehler im JSON-Scraper: {e}", flush=True)
        return False

def scrape_tcgviert_html(keywords_map, seen):
    try:
        res = requests.get("https://tcgviert.com/collections/vorbestellungen", timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        found_any = False
        for product_tag in soup.select("a.product-item__title"):
            title = product_tag.get_text(strip=True)
            clean = clean_text(title)
            url = "https://tcgviert.com" + product_tag["href"]
            for entry, keys in keywords_map.items():
                id = hashlib.md5((title + url).encode()).hexdigest()
                if id not in seen and is_flexible_match(keys, clean):
                    send_telegram_message(f"🔥 Neuer Fund (HTML): {title}\n🔗 Link: {url}")
                    seen.add(id)
                    print(f"✅ HTML TREFFER: {title} – {url}", flush=True)
                    found_any = True
        return found_any
    except Exception as e:
        print(f"❌ Fehler im HTML-Scraper: {e}", flush=True)
        return False