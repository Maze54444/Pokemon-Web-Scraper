# utils/telegram.py
import requests
import json

def load_telegram_config(path="config/telegram_config.json"):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def send_telegram_message(text):
    try:
        config = load_telegram_config()
        url = f"https://api.telegram.org/bot{config['8002829946:AAG6IXKbTW-LTZs2aX_xgsmzRA2jmjQ7RTU']}/sendMessage"
        data = {"7159376682": config["7159376682"], "text": text}
        response = requests.post(url, data=data)
        if response.status_code == 200:
            print("📨 Telegram-Nachricht gesendet")
        else:
            print(f"⚠️ Telegram-Fehler: {response.status_code}")
    except Exception as e:
        print(f"❌ Telegram-Fehler: {e}")
