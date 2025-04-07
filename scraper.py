import requests
import time
import datetime
import json
import hashlib

# --- Dateien laden ---
def load_list(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        return [line.strip().lower() for line in f if line.strip()]

def load_schedule():
    with open("schedule.json", 'r') as f:
        return json.load(f)

def load_telegram_config():
    with open("telegram_config.json", 'r') as f:
        return json.load(f)

def load_seen():
    try:
        with open("seen.txt", "r", encoding='utf-8') as f:
            return set(line.strip() for line in f)
    except FileNotFoundError:
        return set()

def save_seen(seen_set):
    with open("seen.txt", "w", encoding='utf-8') as f:
        for entry in seen_set:
            f.write(entry + "\n")

# --- Zeit-Intervall bestimmen ---
def get_current_interval(schedule):
    today = datetime.date.today()
    for entry in schedule:
        start = datetime.datetime.strptime(entry["start"], "%d.%m.%Y").date()
        end = datetime.datetime.strptime(entry["end"], "%d.%m.%Y").date()
        if start <= today <= end:
            return entry["interval"]
    return 3600  # Fallback: 1h

# --- Telegram senden ---
def send_telegram_message(text):
    try:
        config = load_telegram_config()
        url = f"https://api.telegram.org/bot{config['bot_token']}/sendMessage"
        data = {
            "chat_id": config['chat_id'],
            "text": text
        }
        requests.post(url, data=data)
    except Exception as e:
        print(f"Telegram Fehler: {e}")

# --- Hauptfunktion ---
def run_scraper():
    products = load_list("products.txt")
    urls = load_list("urls.txt")
    schedule = load_schedule()
    seen = load_seen()

    while True:
        print(f"--- [{datetime.datetime.now()}] Starte Scan ---")
        interval = get_current_interval(schedule)

        for url in urls:
            try:
                response = requests.get(url, timeout=10)
                content = response.text.lower()

                for product in products:
                    if product in content:
                        identifier = hashlib.md5(f"{product}_{url}".encode()).hexdigest()
                        if identifier not in seen:
                            seen.add(identifier)
                            with open("treffer_links.txt", "a", encoding='utf-8') as f:
                                f.write(f"{product} gefunden auf {url}\n")
                            send_telegram_message(f"🔥 NEUER TREFFER: {product}\n🛒 {url}")
                            print(f"Treffer: {product} auf {url}")
            except Exception as e:
                print(f"Fehler beim Abrufen von {url}: {e}")

        save_seen(seen)
        print(f"--- [{datetime.datetime.now()}] Warte {interval} Sekunden bis zum nächsten Scan ---\n")
        time.sleep(interval)

# --- Start ---
if __name__ == "__main__":
    run_scraper()
