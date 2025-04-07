import requests
import datetime
import json
import time
import hashlib

print("🟢 START scraper.py", flush=True)

def load_list(filename):
    print(f"📂 Lade Datei: {filename}", flush=True)
    with open(filename, 'r', encoding='utf-8') as f:
        data = [line.strip().lower() for line in f if line.strip()]
        print(f"✅ {filename} geladen mit {len(data)} Einträgen", flush=True)
        return data

def load_schedule():
    print("📂 Lade schedule.json", flush=True)
    with open("schedule.json", 'r') as f:
        data = json.load(f)
        print(f"✅ schedule.json geladen mit {len(data)} Zeiträumen", flush=True)
        return data

def load_telegram_config():
    print("📂 Lade telegram_config.json", flush=True)
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

def get_current_interval(schedule):
    today = datetime.date.today()
    for entry in schedule:
        start = datetime.datetime.strptime(entry["start"], "%d.%m.%Y").date()
        end = datetime.datetime.strptime(entry["end"], "%d.%m.%Y").date()
        if start <= today <= end:
            return entry["interval"]
    return 3600

def send_telegram_message(text):
    try:
        config = load_telegram_config()
        url = f"https://api.telegram.org/bot{config['bot_token']}/sendMessage"
        data = {
            "chat_id": config['chat_id'],
            "text": text
        }
        response = requests.post(url, data=data)
        if response.status_code == 200:
            print("📨 Telegram-Nachricht gesendet", flush=True)
        else:
            print(f"⚠️ Telegram-Fehler: {response.status_code}", flush=True)
    except Exception as e:
        print(f"❌ Telegram-Fehler: {e}", flush=True)

def run_once(seen):
    print("🔍 Starte Einzelscan", flush=True)

    products = load_list("products.txt")
    urls = load_list("urls.txt")
    schedule = load_schedule()
    interval = get_current_interval(schedule)
    print(f"⏱ Intervall ist: {interval} Sekunden", flush=True)

    for url in urls:
        print(f"🌐 Prüfe URL: {url}", flush=True)
        try:
            response = requests.get(url, timeout=10)
            content = response.text.lower()

            for product in products:
                if product in content:
                    identifier = hashlib.md5(f"{product}_{url}".encode()).hexdigest()
                    if identifier not in seen:
                        seen.add(identifier)
                        send_telegram_message(f"🔥 Neuer Fund: {product}\n🛒 {url}")
                        print(f"✅ TREFFER: {product} auf {url}", flush=True)
        except Exception as e:
            print(f"❌ Fehler bei {url}: {e}", flush=True)

    save_seen(seen)
    print(f"⏳ Nächster Durchlauf in {interval} Sekunden...\n", flush=True)
    return interval

if __name__ == "__main__":
    print("📦 Hauptblock wurde erreicht", flush=True)
    seen = set()
    while True:
        interval = run_once(seen)
        time.sleep(interval)