import requests
import logging
import re
import time
import json
import hashlib
import random
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote_plus, urlparse
from utils.matcher import is_keyword_in_text, extract_product_type_from_text, load_exclusion_sets, is_strict_match
from utils.stock import get_status_text, update_product_status
from utils.availability import detect_availability

# Logger konfigurieren
logger = logging.getLogger(__name__)

# Konstanten für Ecwid-API
ECWID_STORE_ID = "100312571"  # Identifiziert aus der Webanalyse
ECWID_BASE_URL = "https://app.ecwid.com"

def scrape_mighty_cards(keywords_map, seen, out_of_stock, only_available=False, min_price=None, max_price=None):
    """
    Spezieller Scraper für mighty-cards.de mit Ecwid-Integration
    
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param seen: Set mit bereits gesehenen Produkttiteln
    :param out_of_stock: Set mit ausverkauften Produkten
    :param only_available: Ob nur verfügbare Produkte gemeldet werden sollen
    :param min_price: Minimaler Preis für Produktbenachrichtigungen
    :param max_price: Maximaler Preis für Produktbenachrichtigungen
    :return: Liste der neuen Treffer
    """
    logger.info("🌐 Starte speziellen Scraper für mighty-cards.de mit Ecwid-Integration")
    new_matches = []
    all_products = []  # Liste für alle gefundenen Produkte
    
    # Set für Deduplizierung von gefundenen Produkten
    found_product_ids = set()
    
    # Extrahiere den Produkttyp aus dem ersten Suchbegriff (meistens "display")
    search_product_type = None
    if keywords_map:
        sample_search_term = list(keywords_map.keys())[0]
        search_product_type = extract_product_type_from_text(sample_search_term)
        logger.debug(f"🔍 Suche nach Produkttyp: '{search_product_type}'")
    
    # User-Agent-Rotation zur Vermeidung von Bot-Erkennung
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.4 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0"
    ]
    
    headers = {
        "User-Agent": random.choice(user_agents),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.mighty-cards.de/",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1"
    }
    
    # Direkte Suche für jeden Suchbegriff
    logger.info("🔍 Starte direkte Suche für jeden Suchbegriff")
    
    for search_term in keywords_map.keys():
        # Mehrere Such-URLs ausprobieren
        search_urls = [
            f"https://www.mighty-cards.de/shop/search?keyword={quote_plus(search_term)}",
            f"https://www.mighty-cards.de/shop/search?keyword={quote_plus(search_term)}&category_id=0", 
            f"https://www.mighty-cards.de/shop/?search={quote_plus(search_term)}",
            f"https://www.mighty-cards.de/shop/Pokemon?search={quote_plus(search_term)}"
        ]
        
        for search_url in search_urls:
            try:
                logger.info(f"🔍 Suche mit URL: {search_url}")
                response = requests.get(search_url, headers=headers, timeout=15)
                
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, "html.parser")
                    
                    # Suche nach Produkt-Links
                    product_links = []
                    
                    # Verschiedene Selektoren für Produktlinks
                    selectors = [
                        'a[href*="/shop/"][href*="-p"]',
                        'a.grid-product__link',
                        'a.product-title',
                        'div.grid-product a[href^="/shop/"]',
                        'div.product-card a',
                        '.product a'
                    ]
                    
                    for selector in selectors:
                        links = soup.select(selector)
                        for link in links:
                            href = link.get('href', '')
                            if href and '/shop/' in href:
                                if not href.startswith('http'):
                                    href = urljoin('https://www.mighty-cards.de', href)
                                if href not in product_links:
                                    product_links.append(href)
                    
                    logger.info(f"🔍 {len(product_links)} Produktlinks gefunden")
                    
                    # Verarbeite jeden Produktlink
                    for product_url in product_links:
                        product_data = process_mighty_cards_product(
                            product_url, keywords_map, seen, out_of_stock, 
                            only_available, headers, min_price, max_price
                        )
                        
                        if product_data and isinstance(product_data, dict):
                            product_id = create_product_id(product_data["title"])
                            if product_id not in found_product_ids:
                                all_products.append(product_data)
                                new_matches.append(product_id)
                                found_product_ids.add(product_id)
                                logger.info(f"✅ Produkt gefunden: {product_data['title']}")
                    
                    # Wenn Produkte gefunden wurden, keine weitere Suche nötig
                    if all_products:
                        break
                        
            except Exception as e:
                logger.error(f"❌ Fehler bei der Suche mit {search_url}: {e}")
                continue
        
        # Wenn Produkte gefunden wurden, zur nächsten Suche
        if all_products:
            break
    
    # Fallback: Durchsuche Kategorieseiten
    if not all_products:
        logger.info("🔍 Durchsuche Pokemon-Kategorieseiten als Fallback")
        category_urls = [
            "https://www.mighty-cards.de/shop/Pokemon/",
            "https://www.mighty-cards.de/shop/Pokemon-c165637849",
            "https://www.mighty-cards.de/shop/Displays-c165638577",
            "https://www.mighty-cards.de/shop/Vorbestellung-c166467816"
        ]
        
        for category_url in category_urls:
            try:
                logger.info(f"🔍 Prüfe Kategorie: {category_url}")
                response = requests.get(category_url, headers=headers, timeout=15)
                
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, "html.parser")
                    
                    # Sammle Produktlinks
                    product_links = []
                    for link in soup.find_all("a", href=True):
                        href = link.get("href", "")
                        if "/shop/" in href and "-p" in href:
                            if not href.startswith('http'):
                                href = urljoin('https://www.mighty-cards.de', href)
                            if href not in product_links:
                                product_links.append(href)
                    
                    logger.info(f"🔍 {len(product_links)} Produktlinks in Kategorie gefunden")
                    
                    # Verarbeite Produktlinks
                    for product_url in product_links:
                        product_data = process_mighty_cards_product(
                            product_url, keywords_map, seen, out_of_stock, 
                            only_available, headers, min_price, max_price
                        )
                        
                        if product_data and isinstance(product_data, dict):
                            product_id = create_product_id(product_data["title"]) 
                            if product_id not in found_product_ids:
                                all_products.append(product_data)
                                new_matches.append(product_id)
                                found_product_ids.add(product_id)
                                logger.info(f"✅ Produkt gefunden: {product_data['title']}")
            
            except Exception as e:
                logger.error(f"❌ Fehler beim Durchsuchen der Kategorie {category_url}: {e}")
    
    # Sende Benachrichtigungen
    if all_products:
        from utils.telegram import send_batch_notification
        send_batch_notification(all_products)
    
    logger.info(f"🏁 Mighty-Cards Scraping abgeschlossen. {len(all_products)} neue Produkte gefunden.")
    return new_matches

def process_mighty_cards_product(product_url, keywords_map, seen, out_of_stock, only_available, headers, min_price=None, max_price=None):
    """
    Verarbeitet eine einzelne Produktseite von Mighty Cards
    
    :param product_url: URL der Produktseite
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param seen: Set mit bereits gesehenen Produkttiteln
    :param out_of_stock: Set mit ausverkauften Produkten
    :param only_available: Ob nur verfügbare Produkte gemeldet werden sollen
    :param headers: HTTP-Headers
    :param min_price: Minimaler Preis für Produktbenachrichtigungen
    :param max_price: Maximaler Preis für Produktbenachrichtigungen
    :return: Produkt-Daten oder False bei Fehler/Nicht-Übereinstimmung
    """
    try:
        logger.debug(f"🔍 Prüfe Produkt: {product_url}")
        
        # Abrufen der Produktseite
        response = requests.get(product_url, headers=headers, timeout=10)
        if response.status_code != 200:
            logger.warning(f"⚠️ Fehler beim Abrufen von {product_url}: Status {response.status_code}")
            return False
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Titel extrahieren mit verschiedenen Methoden
        title = None
        
        # Methode 1: Standard h1-Element
        title_elem = soup.find('h1', class_='product-details__product-title')
        if not title_elem:
            title_elem = soup.find('h1', class_='product__title')
        if not title_elem:
            title_elem = soup.find('h1')
        
        if title_elem:
            title = title_elem.text.strip()
        
        # Methode 2: Aus Meta-Tags
        if not title:
            meta_title = soup.find('meta', property='og:title')
            if meta_title and meta_title.get('content'):
                title = meta_title.get('content')
        
        # Methode 3: Aus der URL extrahieren
        if not title:
            title = extract_title_from_url(product_url)
        
        if not title:
            logger.warning(f"⚠️ Kein Titel gefunden für {product_url}")
            return False
        
        logger.debug(f"📝 Gefundener Titel: '{title}'")
        
        # Prüfe Titel gegen Suchbegriffe mit verbessertem Matching
        matched_term = None
        for search_term, tokens in keywords_map.items():
            # Verwende is_strict_match für genauere Prüfung
            if is_strict_match(tokens, title, threshold=0.7):  # 70% der Keywords müssen passen
                matched_term = search_term
                logger.debug(f"✅ Match gefunden für '{search_term}'")
                break
            
            # Fallback: Prüfe auf exakte Wortübereinstimmung
            if not matched_term:
                clean_title = title.lower()
                clean_search = search_term.lower()
                # Entferne Produkttypen für besseren Vergleich
                title_words = re.sub(r'\b(display|box|booster|etb|ttb)\b', '', clean_title).split()
                search_words = re.sub(r'\b(display|box|booster|etb|ttb)\b', '', clean_search).split()
                
                # Prüfe ob alle wichtigen Suchwörter im Titel sind
                if all(any(sw in tw for tw in title_words) for sw in search_words if sw):
                    matched_term = search_term
                    logger.debug(f"✅ Match gefunden via Wortvergleich für '{search_term}'")
                    break
        
        if not matched_term:
            logger.debug(f"❌ Kein passender Suchbegriff für '{title}'")
            return False
        
        # Preis extrahieren
        price = "Preis nicht verfügbar"
        price_elem = soup.find('span', class_='details-product-price__value')
        if not price_elem:
            price_elem = soup.find('div', class_='product-details__product-price')
        if not price_elem:
            price_elem = soup.find('span', class_='product-price')
        
        if price_elem:
            price = price_elem.text.strip()
        
        # Verfügbarkeit prüfen
        is_available, price, status_text = detect_availability(soup, product_url)
        
        # Preis-Filter anwenden
        if min_price is not None or max_price is not None:
            price_value = extract_price_value(price)
            if price_value is not None:
                if (min_price is not None and price_value < min_price) or \
                   (max_price is not None and price_value > max_price):
                    logger.info(f"⚠️ Produkt '{title}' mit Preis {price} liegt außerhalb des Preisbereichs")
                    return False
        
        # Produkt-ID erstellen
        product_id = create_product_id(title)
        
        # Status aktualisieren
        should_notify, is_back_in_stock = update_product_status(
            product_id, is_available, seen, out_of_stock
        )
        
        # Bei "nur verfügbare" Option
        if only_available and not is_available:
            return False
        
        if should_notify:
            if is_back_in_stock:
                status_text = "🎉 Wieder verfügbar!"
            
            product_data = {
                "title": title,
                "url": product_url,
                "price": price,
                "status_text": status_text,
                "is_available": is_available,
                "matched_term": matched_term,
                "product_type": extract_product_type_from_text(title),
                "shop": "mighty-cards.de"
            }
            
            return product_data
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Fehler beim Verarbeiten des Produkts {product_url}: {e}")
        return False

def extract_title_from_url(url):
    """
    Extrahiert einen sinnvollen Titel aus der URL-Struktur
    
    :param url: URL der Produktseite
    :return: Extrahierter Titel
    """
    try:
        # Entferne Query-Parameter und Fragment
        path = urlparse(url).path
        
        # Entferne führenden und abschließenden Slash
        path = path.strip('/')
        
        # Extrahiere den letzten Teil des Pfades
        parts = path.split('/')
        if not parts:
            return "Pokemon Produkt"
        
        product_part = parts[-1]
        
        # Entferne Produkt-ID (z.B. -p123456789)
        product_part = re.sub(r'-p\d+$', '', product_part)
        
        # Ersetze Bindestriche durch Leerzeichen
        title = product_part.replace('-', ' ')
        
        # Korrigiere bekannte Abkürzungen
        replacements = {
            'sv09': 'SV09',
            'kp09': 'KP09',
            'etb': 'Elite Trainer Box',
            'ttb': 'Top Trainer Box'
        }
        
        for old, new in replacements.items():
            title = re.sub(rf'\b{old}\b', new, title, flags=re.IGNORECASE)
        
        # Kapitalisiere Wörter
        title = ' '.join(word.capitalize() for word in title.split())
        
        # Stelle sicher, dass Pokemon im Titel ist
        if 'pokemon' not in title.lower():
            title += ' Pokemon'
        
        return title
    
    except Exception as e:
        logger.error(f"Fehler beim Extrahieren des Titels aus URL {url}: {e}")
        return "Pokemon Produkt"

def extract_price_value(price_str):
    """
    Extrahiert den numerischen Wert aus einem Preis-String
    
    :param price_str: Preis als String (z.B. "19,99€" oder "EUR 29.99")
    :return: Preis als Float oder None wenn nicht extrahierbar
    """
    if not price_str or price_str == "Preis nicht verfügbar":
        return None
    
    # Suche nach Zahlen mit Komma oder Punkt
    match = re.search(r'(\d+[.,]\d+|\d+)', price_str)
    if match:
        # Extrahiere den Wert und normalisiere das Format (Komma zu Punkt)
        value_str = match.group(1).replace(',', '.')
        try:
            return float(value_str)
        except ValueError:
            pass
    
    return None

def create_product_id(title, base_id="mightycards"):
    """
    Erstellt eine eindeutige Produkt-ID basierend auf dem Titel
    
    :param title: Produkttitel
    :param base_id: Basis-ID (Website-Name)
    :return: Eindeutige Produkt-ID
    """
    # Normalisiere den Titel
    title_lower = title.lower()
    
    # Extrahiere wichtige Informationen
    series_match = re.search(r'(sv|kp|op)\d+', title_lower)
    series_code = series_match.group(0) if series_match else "unknown"
    
    product_type = extract_product_type_from_text(title)
    
    # Erkenne Sprache
    if "deutsch" in title_lower or "de" in title_lower or "deu" in title_lower:
        language = "de"
    elif "english" in title_lower or "en" in title_lower or "eng" in title_lower:
        language = "en"
    else:
        language = "unknown"
    
    # Erstelle strukturierte ID
    product_id = f"{base_id}_{series_code}_{product_type}_{language}"
    
    # Füge Hash für Eindeutigkeit hinzu
    title_hash = hashlib.md5(title.encode()).hexdigest()[:8]
    product_id += f"_{title_hash}"
    
    return product_id

def search_mighty_cards_products(search_term, headers):
    """
    Führt eine Suche auf der Website durch und extrahiert Produkt-URLs
    
    :param search_term: Suchbegriff
    :param headers: HTTP-Headers für Anfragen
    :return: Liste mit Produkt-URLs
    """
    product_urls = []
    
    try:
        logger.info(f"🔍 Suche nach Produkten mit Begriff: {search_term}")
        
        # URL-Encoding für die Suche
        encoded_term = quote_plus(search_term)
        search_url = f"https://www.mighty-cards.de/shop/search?keyword={encoded_term}"
        
        response = requests.get(search_url, headers=headers, timeout=15)
        if response.status_code != 200:
            logger.warning(f"⚠️ Fehler bei der Suche: Status {response.status_code}")
            return product_urls
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Suche nach Produktlinks
        links = soup.find_all("a", href=True)
        
        for link in links:
            href = link.get('href', '')
            if '/shop/' in href and '-p' in href:
                # Vollständige URL erstellen
                product_url = urljoin("https://www.mighty-cards.de", href)
                if product_url not in product_urls:
                    product_urls.append(product_url)
        
        logger.info(f"🔍 {len(product_urls)} Produkt-Links in Suchergebnissen gefunden")
        
    except Exception as e:
        logger.warning(f"⚠️ Fehler bei der Suche nach '{search_term}': {e}")
    
    return product_urls

def fetch_products_from_ecwid(keywords_map, headers):
    """
    Versucht, Produkte direkt über die Ecwid-Integration zu laden
    
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param headers: HTTP-Headers für Anfragen
    :return: Liste mit Produkt-URLs
    """
    product_urls = []
    
    try:
        # Verwenden der Ecwid-Store-ID aus den Analyseinfos
        store_id = ECWID_STORE_ID
        
        logger.info("🔍 Versuche Ecwid-Storedaten zu laden")
        
        # Versuche die Storefront-Seite zu laden, um Cookie und Session-Daten zu erhalten
        try:
            response = requests.get("https://www.mighty-cards.de/", headers=headers, timeout=15)
            cookies = response.cookies
        except Exception as e:
            logger.warning(f"⚠️ Fehler beim Laden der Startseite: {e}")
            cookies = None
        
        # Versuche über die Bootstrap-API
        for search_term in keywords_map.keys():
            try:
                bootstrap_url = f"{ECWID_BASE_URL}/storefront/api/v1/{store_id}/bootstrap"
                api_headers = {
                    **headers,
                    "Referer": "https://www.mighty-cards.de/",
                    "X-Requested-With": "XMLHttpRequest",
                    "content-type": "application/json"
                }
                
                bootstrap_response = requests.post(bootstrap_url, json={}, headers=api_headers, cookies=cookies, timeout=15)
                if bootstrap_response.status_code == 200:
                    logger.debug("Bootstrap-API erfolgreich aufgerufen")
            except Exception as e:
                logger.debug(f"⚠️ Fehler bei Bootstrap-API: {e}")
        
        # ... weitere Ecwid-API Versuche ...
        
    except Exception as e:
        logger.warning(f"⚠️ Fehler beim Laden der Ecwid-Daten: {e}")
    
    return product_urls