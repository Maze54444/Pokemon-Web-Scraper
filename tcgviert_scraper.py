import requests
import json
import hashlib
import time
from datetime import datetime
import os

# 🔁 Optional: seen.txt löschen (Testzwecke)
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

def is_flexible_match(keywords, raw_text, threshold=0.75):
    text = clean_text(raw_text)
    text_words = text.split()

    keywords_clean = [clean_text(word) for word in keywords]
    matches = []

    for word in keywords_clean:
        for text_word in text_words:
            if word in text_word:  # Teilwortsuche!
                matches.append(word)
                break

    score = len(matches) / len(keywords_clean)
    print(f"🟡 LOG: Keywords = {keywords_clean}")
    print(f"🟡 LOG: Gefundene Wörter = {matches} → Trefferquote = {score:.2f}")
    return score >= threshold


def check_products():
    products = load_list("products.txt")
    seen = load_seen()

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
        print(f"❌ Fehler bei API-Abfrage: {e}", flush=True)

    save_seen(seen)

# 🔁 Dauerlauf alle 5 Minuten
if __name__ == "__main__":
    print("🟢 Shopify JSON-Scraper gestartet", flush=True)
    while True:
        check_products()
        print(f"⏳ Warten bis {datetime.now().strftime('%H:%M:%S')} + 300s", flush=True)
        time.sleep(300)
