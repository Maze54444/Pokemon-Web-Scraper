
import requests, hashlib
from bs4 import BeautifulSoup
from utils.matcher import clean_text, is_flexible_match
from utils.telegram import send_telegram_message

def scrape_generic(url, keywords_map, seen):
    try:
        res = requests.get(url, timeout=10)
        text = clean_text(BeautifulSoup(res.text, "html.parser").get_text())
        for entry, keys in keywords_map.items():
            id = hashlib.md5((entry + url).encode()).hexdigest()
            if id not in seen and is_flexible_match(keys, text):
                send_telegram_message(f"🔥 Fund auf generischer Seite: {entry}\n🔗 {url}")
                seen.add(id)
    except Exception as e:
        print(f"❌ Fehler bei {url}: {e}")
