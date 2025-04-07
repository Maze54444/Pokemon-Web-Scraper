import requests
import datetime
import json
import time

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

def get_current_interval(schedule):
    today = datetime.date.today()
    for entry in schedule:
        start = datetime.datetime.strptime(entry["start"], "%d.%m.%Y").date()
        end = datetime.datetime.strptime(entry["end"], "%d.%m.%Y").date()
        if start <= today <= end:
            return entry["interval"]
    return 3600

def run_once():
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
                    print(f"✅ TREFFER: {product} auf {url}", flush=True)
        except Exception as e:
            print(f"❌ Fehler bei {url}: {e}", flush=True)

    print(f"⏳ Nächster Durchlauf in {interval} Sekunden...\n", flush=True)
    return interval

if __name__ == "__main__":
    print("📦 Hauptblock wurde erreicht", flush=True)
    while True:
        interval = run_once()
        time.sleep(interval)
