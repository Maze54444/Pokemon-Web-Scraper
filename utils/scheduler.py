
import json, datetime

def get_current_interval(path="config/schedule.json"):
    today = datetime.date.today()
    for e in json.load(open(path, "r", encoding="utf-8")):
        s = datetime.datetime.strptime(e["start"], "%d.%m.%Y").date()
        e_ = datetime.datetime.strptime(e["end"], "%d.%m.%Y").date()
        if s <= today <= e_:
            return e["interval"]
    return 300
