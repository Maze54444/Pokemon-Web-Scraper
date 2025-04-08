import os
import requests
import json
import hashlib
import time
import re
from bs4 import BeautifulSoup
from datetime import datetime
import unicodedata


# 🔁 Auto-Reset der seen.txt beim Start (optional)
if os.path.exists("seen.txt"):
    os.remove("seen.txt")
    print("🗑️ seen.txt gelöscht (beim Start)", flush=True)

def load_list(filename):
    with open(filename, "r", encoding="utf-8") as f:
        return [line.strip().lower() for line in f if line.strip()]

def load_seen():
    try:
        with open("seen.txt", "r", encoding="utf-8") as f:
            return set(line.strip() for line in f)
    except FileNotFoundError:
        return set()

def save_seen(seen):
    with open("seen.txt", "w", encoding="utf-8") as f:
        for item in seen:
            f.write(item + "\n")

def load_telegram_config():
    with open("telegram_config.json", "r") as f:
        return json.load(f)

def send_telegram_message(text):
    try:
        config = load_telegram_config()
        url = f"https://api.telegram.org/bot{config['bot_token']}/sendMessage"
        data = {"chat_id": config["chat_id"], "text": text}
        response = requests.post(url, data=data)
        if response.status_code == 200:
            print("📨 Telegram-Nachricht gesendet", flush=True)
        else:
            print(f"⚠️ Telegram-Fehler: {response.status_code}", flush=True)
    except Exception as e:
        print(f"❌ Telegram-Fehler: {e}", flush=True)

def clean_text(text):
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("utf-8")  # Entfernt Akzente korrekt
    text = re.sub(r"[^a-zA-Z0-9 ]", " ", text)
    return text.lower()

def is_flexible_match(keywords, raw_text, threshold=0.75):
    text = clean_text(raw_text)
    text_words = set(text.split())
    keywords_clean = [clean_text(word) for word in keywords]
    matches = [word for word in keywords_clean if word in text_words]
    score = len(matches) / len(keywords_clean)
    print(f"🟡 LOG: Keywords = {keywords_clean}")
    print(f"🟡 LOG: Gefundene Wörter = {matches} → Trefferquote = {score:.2f}")
    return score >= threshold

# 🔍 JSON-Methode für tcgviert.com
def scrape_tcgviert(products, seen):
    print("🌐 JSON-API von tcgviert.com wird verwendet", flush=True)
    try:
        response = requests.get("https://tcgviert.com/products.json", timeout=10)
        response.raise_for_status()
        data = response.json()

        for item in data["products"]:
            title = item["title"].lower()
            handle = item["handle"]
            link = f"https://tcgviert.com/products/{handle}"
            price = item["variants"][0]["price"]
            identifier = hashlib.md5((title + link).encode()).hexdigest()

            for entry in products:
                keywords = entry.lower().split()
                if is_flexible_match(keywords, title) and identifier not in seen:
                    seen.add(identifier)
                    message = f"🔥 Neuer Fund: {item['title']}\n💶 Preis: {price} €\n🔗 Link: {link}"
                    print(f"✅ TREFFER: {item['title']} – {price} € – {link}", flush=True)
                    send_telegram_message(message)

    except Exception as e:
        print(f"❌ Fehler bei tcgviert.com: {e}", flush=True)

# 🌐 HTML-Methode (klassisch)
def scrape_generic(url, products, seen):
    try:
        response = requests.get(url, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")
        text = soup.get_text().lower()

        for entry in products:
            keywords = entry.lower().split()
            identifier = hashlib.md5((entry + url).encode()).hexdigest()
            if is_flexible_match(keywords, text) and identifier not in seen:
                seen.add(identifier)
                message = f"🔥 Neuer Fund auf generischer Seite:\n📝 Produkt: {entry}\n🔗 Link: {url}"
                print(f"✅ GENERISCH TREFFER: {entry} → {url}", flush=True)
                send_telegram_message(message)

    except Exception as e:
        print(f"❌ Fehler bei {url}: {e}", flush=True)

# 🔁 Dauerhafter Zyklus
if __name__ == "__main__":
    print("🟢 Master-Scraper gestartet", flush=True)
    seen = load_seen()

    while True:
        urls = load_list("urls.txt")
        products = load_list("products.txt")

        for url in urls:
            if "tcgviert.com" in url:
                scrape_tcgviert(products, seen)
            else:
                scrape_generic(url, products, seen)

        save_seen(seen)
        print(f"⏳ Warten bis {datetime.now().strftime('%H:%M:%S')} + 300s\n", flush=True)
        time.sleep(300)
