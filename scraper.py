import datetime

print("✅ TEST: scraper.py wurde gestartet!")

with open("startcheck.txt", "w", encoding="utf-8") as f:
    f.write(f"✅ TEST-Start: {datetime.datetime.now()}\n")

print("📦 Datei geschrieben – Ende")