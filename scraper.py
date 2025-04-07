import requests
import time
import datetime
import json
import hashlib

print("🟢 START scraper.py")

def load_list(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        return [line.strip().lower() for line in f if line.strip()]

def load_schedule():
    with open("schedule.json", 'r') as f:
        return json.load(f)

def get_current_interval(schedule):
    today = datetime.date.today()
    for entry in schedule:
        start = datetime.datetime.strptime(entry["start"], "%d.%m.%Y").date()
        end = datetime.datetime.strptime(entry["end"], "%d.%m.%Y").date()
        if start <= today <= end:
            return entry["interval"]
    return 3600

def run_scraper():
    print("📡 run_scraper() gestartet")

    products = load_list("products.txt")
    urls = load_list("urls.txt")
    schedule = load_schedule()

    while True:
        print(f"\n--- [{datetime.datetime.now()}] Starte Scan ---")
        interval = get_current_interval(schedule)

        for url in urls:
            print(f"🌐 Prüfe URL: {url}")
            try:
                response = requests.get(url, timeout=10)
                content = response.text.lower()

                for product in products:
                    if product in content:
                        print(f"✅ TREFFER: {product} auf {url}")
            except Exception as e:
                print(f"❌ Fehler bei {url}: {e}")

        print(f"⏳ Warte {interval} Sekunden...\n")
        time.sleep(interval)

if __name__ == "__main__":
    print("📦 Main wurde erreicht")
    run_scraper()
