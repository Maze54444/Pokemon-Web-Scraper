
import requests, json

def load_telegram_config(path="config/telegram_config.json"):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def send_telegram_message(text):
    cfg = load_telegram_config()
    url = f"https://api.telegram.org/bot{cfg['bot_token']}/sendMessage"
    data = {"chat_id": cfg["chat_id"], "text": text}
    try:
        res = requests.post(url, data=data)
        if res.status_code == 200:
            print("📨 Telegram gesendet")
        else:
            print(f"⚠️ Fehlercode {res.status_code}")
    except Exception as e:
        print(f"❌ Telegram Error: {e}")
