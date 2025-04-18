import requests
import json
import re
import logging

# Logger konfigurieren
logger = logging.getLogger(__name__)

def load_telegram_config(path="config/telegram_config.json"):
    """Lädt die Telegram-Konfiguration"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"❌ Fehler beim Laden der Telegram-Konfiguration: {e}")
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
        logger.warning("⚠️ Telegram-Konfiguration unvollständig. Nachricht wird nicht gesendet.")
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
            logger.info("📨 Telegram-Nachricht erfolgreich gesendet")
            return True
        elif response.status_code == 400 and retry_without_markdown:
            # Bei Formatierungsfehlern probieren wir es ohne Markdown
            logger.warning(f"⚠️ Formatierungsfehler in Telegram-Nachricht, versuche ohne Markdown...")
            
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
                logger.info("📨 Telegram-Nachricht (ohne Markdown) erfolgreich gesendet")
                return True
            else:
                logger.warning(f"⚠️ Telegram-Fehlercode {retry_response.status_code}: {retry_response.text}")
                return False
        else:
            logger.warning(f"⚠️ Telegram-Fehlercode {response.status_code}: {response.text}")
            return False
    except Exception as e:
        logger.error(f"❌ Telegram-Fehler: {e}")
        return False

def sort_products_by_availability(products):
    """
    Sortiert Produkte nach Verfügbarkeit (verfügbar, dann nicht verfügbar)
    
    :param products: Liste von Produktdicts {"title": str, "url": str, "price": str, 
                                           "status_text": str, "is_available": bool,
                                           "matched_term": str, "shop": str}
    :return: Sortierte Liste von Produkten
    """
    # Sortiere zuerst nach Verfügbarkeit, dann nach Shop und Titel
    return sorted(products, key=lambda p: (not p.get("is_available", False), p.get("shop", ""), p.get("title", "")))

def send_product_notification(product):
    """
    Sendet eine Benachrichtigung über ein einzelnes Produkt
    
    :param product: Produktdaten als Dict
    :return: True bei Erfolg, False bei Fehler
    """
    title = product.get("title", "Unbekanntes Produkt")
    url = product.get("url", "")
    price = product.get("price", "Preis unbekannt")
    status_text = product.get("status_text", "Status unbekannt")
    matched_term = product.get("matched_term", "")
    product_type = product.get("product_type", "")
    
    # Füge Produkttyp-Information hinzu
    product_type_info = f" [{product_type.upper()}]" if product_type and product_type != "unknown" else ""
    
    # Escape Markdown-Sonderzeichen
    safe_title = escape_markdown(title)
    safe_price = escape_markdown(price)
    safe_status_text = escape_markdown(status_text)
    safe_matched_term = escape_markdown(matched_term)
    
    # Nachricht zusammenstellen
    msg = (
        f"🎯 *{safe_title}*{product_type_info}\n"
        f"💶 {safe_price}\n"
        f"📊 {safe_status_text}\n"
        f"🔎 Treffer für: '{safe_matched_term}'\n"
        f"🔗 [Zum Produkt]({url})"
    )
    
    return send_telegram_message(msg)

def send_batch_notification(products):
    """
    Sendet eine Batch-Benachrichtigung für mehrere Produkte, sortiert nach Verfügbarkeit
    
    :param products: Liste von Produktdicts
    :return: True bei Erfolg, False bei Fehler
    """
    if not products:
        return True
        
    # Sortiere Produkte: Zuerst verfügbare, dann nicht verfügbare
    sorted_products = sort_products_by_availability(products)
    
    # Erstelle Nachrichtentext
    message_parts = []
    
    # Überschrift
    message_parts.append(f"*Neue Produkte gefunden \\({len(sorted_products)}\\)*\n")
    
    # Verfügbare Produkte
    available_products = [p for p in sorted_products if p.get("is_available", False)]
    if available_products:
        message_parts.append(f"\n*✅ Verfügbare Produkte \\({len(available_products)}\\):*\n")
        for idx, product in enumerate(available_products, 1):
            title = product.get("title", "Unbekanntes Produkt")
            url = product.get("url", "")
            price = product.get("price", "Preis unbekannt")
            shop = product.get("shop", "Unbekannter Shop")
            
            # Escape Markdown-Sonderzeichen
            safe_title = escape_markdown(title)
            safe_price = escape_markdown(price)
            safe_shop = escape_markdown(shop)
            
            message_parts.append(f"{idx}\\. [{safe_title}]({url}) \\- {safe_price} \\({safe_shop}\\)")
    
    # Nicht verfügbare Produkte
    unavailable_products = [p for p in sorted_products if not p.get("is_available", False)]
    if unavailable_products:
        message_parts.append(f"\n*❌ Nicht verfügbare Produkte \\({len(unavailable_products)}\\):*\n")
        for idx, product in enumerate(unavailable_products, 1):
            title = product.get("title", "Unbekanntes Produkt")
            url = product.get("url", "")
            shop = product.get("shop", "Unbekannter Shop")
            
            # Escape Markdown-Sonderzeichen
            safe_title = escape_markdown(title)
            safe_shop = escape_markdown(shop)
            
            message_parts.append(f"{idx}\\. [{safe_title}]({url}) \\({safe_shop}\\)")
    
    # Nachricht senden
    message = "\n".join(message_parts)
    return send_telegram_message(message)