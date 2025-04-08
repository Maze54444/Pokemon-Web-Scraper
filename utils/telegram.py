import requests
import json

def load_telegram_config(path="config/telegram_config.json"):
    """Lädt die Telegram-Konfiguration"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"❌ Fehler beim Laden der Telegram-Konfiguration: {e}", flush=True)
        return {"bot_token": "", "chat_id": ""}

def send_telegram_message(text):
    """Sendet eine Nachricht über Telegram"""
    cfg = load_telegram_config()
    
    if not cfg["bot_token"] or not cfg["chat_id"]:
        print("⚠️ Telegram-Konfiguration unvollständig. Nachricht wird nicht gesendet.", flush=True)
        return False
    
    url = f"https://api.telegram.org/bot{cfg['bot_token']}/sendMessage"
    data = {
        "chat_id": cfg["chat_id"],
        "text": text,
        "parse_mode": "Markdown",  # Für Markdown-Formatierung
        "disable_web_page_preview": False  # Link-Vorschau aktivieren
    }
    
    try:
        response = requests.post(url, data=data, timeout=10)
        if response.status_code == 200:
            print("📨 Telegram-Nachricht erfolgreich gesendet", flush=True)
            return True
        else:
            print(f"⚠️ Telegram-Fehlercode {response.status_code}: {response.text}", flush=True)
            return False
    except Exception as e:
        print(f"❌ Telegram-Fehler: {e}", flush=True)
        return False
