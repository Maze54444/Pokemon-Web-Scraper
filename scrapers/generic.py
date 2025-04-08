
import requests
import hashlib
from bs4 import BeautifulSoup
from utils.matcher import clean_text, is_keyword_in_text
from utils.telegram import send_telegram_message

def scrape_generic(url, keywords_map, seen):
    """
    Generischer Scraper für beliebige Websites
    
    :param url: URL der zu scrapenden Website
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param seen: Set mit bereits gesehenen Produkttiteln
    :return: Liste der neuen Treffer
    """
    print(f"🌐 Starte generischen Scraper für {url}", flush=True)
    new_matches = []
    
    try:
        # User-Agent setzen, um Blockierung zu vermeiden
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            print(f"⚠️ Fehler beim Abrufen von {url}: Status {response.status_code}", flush=True)
            return new_matches
        
        # HTML parsen
        soup = BeautifulSoup(response.text, "html.parser")
        page_text = clean_text(soup.get_text())
        
        # Titel der Seite extrahieren
        page_title = soup.title.text.strip() if soup.title else url
        
        # Prüfe jeden Suchbegriff gegen den Seiteninhalt
        for search_term, tokens in keywords_map.items():
            if is_keyword_in_text(tokens, page_text):
                # Eindeutige ID für diesen Fund generieren
                search_id = hashlib.md5(f"{search_term}_{url}".encode()).hexdigest()
                
                if search_id not in seen:
                    # Nachricht zusammenstellen
                    msg = (
                        f"🔎 Treffer für: *{search_term}*\n"
                        f"📄 Auf Seite: {page_title}\n"
                        f"🔗 [Zur Seite]({url})"
                    )
                    
                    # Telegram-Nachricht senden
                    if send_telegram_message(msg):
                        seen.add(search_id)
                        new_matches.append(search_id)
                        print(f"✅ Neuer generischer Treffer: {search_term} auf {url}", flush=True)
    
    except Exception as e:
        print(f"❌ Fehler beim generischen Scraping von {url}: {e}", flush=True)
    
    return new_matches