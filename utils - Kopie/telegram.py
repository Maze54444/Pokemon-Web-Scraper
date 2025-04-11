import requests
import json
import re

def load_telegram_config(path="config/telegram_config.json"):
    """Lädt die Telegram-Konfiguration"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"❌ Fehler beim Laden der Telegram-Konfiguration: {e}", flush=True)
        return {"bot_token": "", "chat_id": ""}

def escape_markdown(text):
    """
    Escapes Markdown special characters in a string.
    Characters to escape: _*[]()~`>#+-=|{}.!
    """
    if text is None:
        return ""
        
    # Ersetzt Markdown-Sonderzeichen mit einem Escape-Backslash
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return ''.join(f'\\{c}' if c in escape_chars else c for c in text)

def send_telegram_message(text, retry_without_markdown=True):
    """
    Sendet eine Nachricht über Telegram mit verbesserter Fehlerbehandlung
    
    :param text: Der zu sendende Text (mit Markdown-Formatierung)
    :param retry_without_markdown: Ob bei Formatierungsfehlern ohne Markdown erneut versucht werden soll
    :return: True bei Erfolg, False bei Fehler
    """
    cfg = load_telegram_config()
    
    if not cfg["bot_token"] or not cfg["chat_id"]:
        print("⚠️ Telegram-Konfiguration unvollständig. Nachricht wird nicht gesendet.", flush=True)
        return False
    
    url = f"https://api.telegram.org/bot{cfg['bot_token']}/sendMessage"
    
    # Versuche zuerst mit Markdown
    try:
        data = {
            "chat_id": cfg["chat_id"],
            "text": text,
            "parse_mode": "MarkdownV2",  # Verwende MarkdownV2 für bessere Kompatibilität
            "disable_web_page_preview": False  # Link-Vorschau aktivieren
        }
        
        response = requests.post(url, data=data, timeout=10)
        if response.status_code == 200:
            print("📨 Telegram-Nachricht erfolgreich gesendet", flush=True)
            return True
        elif response.status_code == 400 and retry_without_markdown:
            # Bei Formatierungsfehlern probieren wir es ohne Markdown
            print(f"⚠️ Formatierungsfehler in Telegram-Nachricht, versuche ohne Markdown...", flush=True)
            
            # Entferne alle Markdown-Symbole für Links, aber behalte die URLs
            clean_text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\1: \2', text)
            
            # Entferne andere Markdown-Symbole
            clean_text = re.sub(r'[*_`]', '', clean_text)
            
            data = {
                "chat_id": cfg["chat_id"],
                "text": clean_text,
                "parse_mode": "",  # Kein Markdown
                "disable_web_page_preview": False
            }
            
            retry_response = requests.post(url, data=data, timeout=10)
            if retry_response.status_code == 200:
                print("📨 Telegram-Nachricht (ohne Markdown) erfolgreich gesendet", flush=True)
                return True
            else:
                print(f"⚠️ Telegram-Fehlercode {retry_response.status_code}: {retry_response.text}", flush=True)
                return False
        else:
            print(f"⚠️ Telegram-Fehlercode {response.status_code}: {response.text}", flush=True)
            return False
    except Exception as e:
        print(f"❌ Telegram-Fehler: {e}", flush=True)
        return False