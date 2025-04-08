# utils/scheduler.py
import json
import datetime

def get_current_interval(path="config/schedule.json"):
    try:
        today = datetime.date.today()
        with open(path, "r", encoding="utf-8") as f:
            schedule = json.load(f)
        for entry in schedule:
            start = datetime.datetime.strptime(entry["start"], "%d.%m.%Y").date()
            end = datetime.datetime.strptime(entry["end"], "%d.%m.%Y").date()
            if start <= today <= end:
                return entry["interval"]
    except Exception as e:
        print(f"⚠️ Fehler beim Laden des Zeitplans: {e}")
    return 300  # default fallback
