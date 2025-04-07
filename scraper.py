import requests
import datetime
import json
import time

print("🟢 START scraper.py")

def load_list(filename):
    print(f"📂 Lade Datei: {filename}")
    with open(filename, 'r', encoding='utf-8') as f:
        data = [line.strip().lower() for line in f if line.strip()]
        print(f"✅ {filename} geladen mit {len(data)} Einträgen")
        return data

def load_schedule():
    print("📂 Lade schedule.json")
    with open("schedule.json", 'r') as f:
        data = json.load(f)
        print(f"✅ schedule.json geladen mit {len(data)} Zeiträumen")
        return data

def get_current_interval(schedule):
    today = datetime.date.today()
    for entry in schedule:
        start = datetime.datetime.strptime(entry["start"], "%d.%m.%Y").date()
        end = datetime.datetime.strptime(entry["end"], "%d.%m.%Y").date()
        if start <= today <= end:
            return entry["interval"]
    return 3600

def run_once():
    print("🔍 Starte Einzelscan")

    products = load_list("products.txt")
    urls = load_list("urls.txt")
    schedule = load_schedule()
    interval = get_current_interval(schedule)
    print(f"⏱ Intervall ist: {interval} Sekunden")

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

    print(f"⏳ Nächster Durchlauf in {interval} Sekunden...\n")
    return interval

if __name__ == "__main__":
    print("📦 Hauptblock wurde erreicht")
    while True:
        interval = run_once()
        time.sleep(interval)
