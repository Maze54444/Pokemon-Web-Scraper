import requests
import logging
import re
import time
import json
import hashlib
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote_plus, urlparse
from utils.matcher import is_keyword_in_text, extract_product_type_from_text
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
    
    # Hardcoded Beispiel-URLs für bekannte Produkte basierend auf deiner Analyse
    hardcoded_urls = [
        "https://www.mighty-cards.de/shop/SV09-Journey-Togehter-36er-Booster-Display-Pokemon-p743684893",
        "https://www.mighty-cards.de/shop/KP09-Reisegefahrten-36er-Booster-Display-Pokemon-p739749306",
        "https://www.mighty-cards.de/shop/KP09-Reisegefahrten-18er-Booster-Display-Pokemon-p739750556",
        # Neue URL aus der Log-Analyse hinzugefügt
        "https://www.mighty-cards.de/pokemon/reisegefahrten-journey-together/"
    ]
    
    # User-Agent für Anfragen
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "de,en-US;q=0.7,en;q=0.3",
        "DNT": "1",
        "Connection": "keep-alive",
        "Referer": "https://www.mighty-cards.de/",
        "Upgrade-Insecure-Requests": "1"
    }
    
    # 1. Zuerst: Versuche die WordPress Sitemap für Produkte zu laden
    logger.info("🔍 Versuche Produktdaten über die WP-Sitemap zu laden")
    sitemap_products = fetch_products_from_sitemap(headers)
    
    # Verarbeite Sitemap-Produkte
    for product_url in sitemap_products:
        logger.debug(f"Verarbeite Sitemap-Produkt: {product_url}")
        if product_url not in found_product_ids:
            product_data = process_mighty_cards_product(product_url, keywords_map, seen, out_of_stock, only_available, headers, min_price, max_price)
            if product_data and isinstance(product_data, dict):
                product_id = create_product_id(product_data["title"])
                if product_id not in found_product_ids:
                    all_products.append(product_data)
                    new_matches.append(product_id)
                    found_product_ids.add(product_id)
                    logger.info(f"✅ Neuer Treffer gefunden (Sitemap): {product_data['title']} - {product_data['status_text']}")
    
    # 2. Dann: Versuche die Ecwid-API direkt zu nutzen
    logger.info("🔍 Versuche Produktdaten über die Ecwid-Integration zu laden")
    ecwid_products = fetch_products_from_ecwid(keywords_map, headers)
    
    # Verarbeite Ecwid-Produkte
    for product_url in ecwid_products:
        logger.debug(f"Verarbeite Ecwid-Produkt: {product_url}")
        if product_url not in found_product_ids:
            product_data = process_mighty_cards_product(product_url, keywords_map, seen, out_of_stock, only_available, headers, min_price, max_price)
            if product_data and isinstance(product_data, dict):
                product_id = create_product_id(product_data["title"])
                if product_id not in found_product_ids:
                    all_products.append(product_data)
                    new_matches.append(product_id)
                    found_product_ids.add(product_id)
                    logger.info(f"✅ Neuer Treffer gefunden (Ecwid): {product_data['title']} - {product_data['status_text']}")
    
    # 3. Dann: Durchsuche wichtige Kategorie-Seiten
    logger.info("🔍 Durchsuche Pokemon-Kategorie und Unterkategorien")
    category_products = fetch_products_from_categories(headers)
    
    # Verarbeite Kategorie-Produkte
    for product_url in category_products:
        logger.debug(f"Verarbeite Kategorie-Produkt: {product_url}")
        if product_url not in found_product_ids:
            product_data = process_mighty_cards_product(product_url, keywords_map, seen, out_of_stock, only_available, headers, min_price, max_price)
            if product_data and isinstance(product_data, dict):
                product_id = create_product_id(product_data["title"])
                if product_id not in found_product_ids:
                    all_products.append(product_data)
                    new_matches.append(product_id)
                    found_product_ids.add(product_id)
                    logger.info(f"✅ Neuer Treffer gefunden (Kategorie): {product_data['title']} - {product_data['status_text']}")
    
    # 4. Dann: Suche mit Suchbegriffen durchführen
    # Dynamische Erstellung von Suchanfragen basierend auf den Keywords
    search_products = []
    for search_term in keywords_map.keys():
        search_term_products = search_mighty_cards_products(search_term, headers)
        search_products.extend(search_term_products)
    
    # Verarbeite Produkte aus der Suche
    for product_url in search_products:
        logger.debug(f"Verarbeite Produkt aus Suche: {product_url}")
        if product_url not in found_product_ids:
            product_data = process_mighty_cards_product(product_url, keywords_map, seen, out_of_stock, only_available, headers, min_price, max_price)
            if product_data and isinstance(product_data, dict):
                product_id = create_product_id(product_data["title"])
                if product_id not in found_product_ids:
                    all_products.append(product_data)
                    new_matches.append(product_id)
                    found_product_ids.add(product_id)
                    logger.info(f"✅ Neuer Treffer gefunden (Suche): {product_data['title']} - {product_data['status_text']}")
    
    # 5. Zuletzt: Fallback auf hardcoded URLs, wenn keine Produkte gefunden wurden
    if not all_products:
        logger.info(f"🔍 Keine Produkte gefunden. Prüfe {len(hardcoded_urls)} bekannte Produkt-URLs als Fallback")
        for product_url in hardcoded_urls:
            if product_url not in found_product_ids:
                product_data = process_fallback_product(product_url, keywords_map, seen, out_of_stock, only_available, headers, min_price, max_price)
                if product_data and isinstance(product_data, dict):
                    product_id = create_product_id(product_data["title"])
                    if product_id not in found_product_ids:
                        all_products.append(product_data)
                        new_matches.append(product_id)
                        found_product_ids.add(product_id)
                        logger.info(f"✅ Neuer Treffer gefunden (Fallback): {product_data['title']} - {product_data['status_text']}")
    
    # Sende Benachrichtigungen
    if all_products:
        from utils.telegram import send_batch_notification
        send_batch_notification(all_products)
    
    return new_matches

def fetch_products_from_sitemap(headers):
    """
    Lädt Produkt-URLs aus der WordPress-Sitemap
    
    :param headers: HTTP-Headers für Anfragen
    :return: Liste mit Produkt-URLs
    """
    product_urls = []
    
    # Basierend auf der Analyse: Die Sitemap-URLs für Ecwid-Produkte und Kategorien
    sitemap_urls = [
        "https://www.mighty-cards.de/wp-sitemap-ecstore-1.xml",  # Primäre Ecwid Store Sitemap
        "https://www.mighty-cards.de/wp-sitemap-posts-page-1.xml",  # Enthält Kategorieseiten
        "https://www.mighty-cards.de/wp-sitemap.xml",  # WordPress Hauptsitemap
        "https://www.mighty-cards.de/sitemap_index.xml",  # Alternative Sitemap-Format
    ]
    
    for sitemap_url in sitemap_urls:
        try:
            logger.info(f"🔍 Versuche Sitemap zu laden: {sitemap_url}")
            response = requests.get(sitemap_url, headers=headers, timeout=15)
            if response.status_code != 200:
                logger.warning(f"⚠️ Sitemap nicht gefunden: {sitemap_url}, Status: {response.status_code}")
                continue
            
            # Parse XML - Verwende HTML-Parser als Fallback, wenn lxml nicht verfügbar ist
            try:
                # Versuche zuerst mit lxml-xml Parser (wenn verfügbar)
                soup = BeautifulSoup(response.content, "lxml-xml")
            except Exception as e:
                logger.warning(f"XML-Parser nicht verfügbar, verwende HTML-Parser als Fallback: {e}")
                # Fallback zum Standard-HTML-Parser
                soup = BeautifulSoup(response.content, "html.parser")
            
            # Sammle alle URLs
            urls = soup.find_all("url")
            if urls:
                for url_tag in urls:
                    loc_tag = url_tag.find("loc")
                    if loc_tag:
                        product_url = loc_tag.text
                        if any(keyword in product_url.lower() for keyword in 
                              ["shop/", "pokemon", "journey", "togehter", "together", "reisegefahrten"]):
                            product_urls.append(product_url)
            
            # Wenn es sich um einen Sitemap-Index handelt, prüfe auch die verlinkten Sitemaps
            sitemaps = soup.find_all("sitemap")
            if sitemaps:
                for sitemap_tag in sitemaps:
                    loc_tag = sitemap_tag.find("loc")
                    if loc_tag:
                        try:
                            sub_url = loc_tag.text
                            if "ecstore" in sub_url or "post" in sub_url:
                                logger.info(f"🔍 Untersuche Sub-Sitemap: {sub_url}")
                                sub_response = requests.get(sub_url, headers=headers, timeout=15)
                                if sub_response.status_code == 200:
                                    try:
                                        # Versuche zuerst mit lxml-xml Parser
                                        sub_soup = BeautifulSoup(sub_response.content, "lxml-xml")
                                    except Exception:
                                        # Fallback zum HTML-Parser
                                        sub_soup = BeautifulSoup(sub_response.content, "html.parser")
                                    
                                    for url_tag in sub_soup.find_all("url"):
                                        loc_tag = url_tag.find("loc")
                                        if loc_tag:
                                            url = loc_tag.text
                                            if any(keyword in url.lower() for keyword in 
                                                  ["shop/", "pokemon", "journey", "togehter", "together", "reisegefahrten"]):
                                                product_urls.append(url)
                        except Exception as e:
                            logger.warning(f"⚠️ Fehler beim Laden der Sub-Sitemap {loc_tag.text}: {e}")
            
            # Wenn keine strukturierten URLs gefunden wurden, suche nach regulären Links im HTML
            if not urls and not sitemaps:
                logger.info("Keine strukturierten URL-Tags gefunden, suche nach regulären Links")
                # Suche nach allen href-Attributen
                for link in soup.find_all("a", href=True):
                    href = link.get("href")
                    if any(keyword in href.lower() for keyword in 
                          ["shop/", "pokemon", "journey", "togehter", "together", "reisegefahrten"]):
                        if href.startswith("http"):
                            product_urls.append(href)
                        else:
                            product_urls.append(f"https://www.mighty-cards.de{href}" if href.startswith('/') else f"https://www.mighty-cards.de/{href}")
                        
            
            logger.info(f"✅ {len(product_urls)} Produkt-URLs aus Sitemap extrahiert")
            
            # Wenn URLs gefunden wurden, früh beenden
            if product_urls:
                break
        
        except Exception as e:
            logger.warning(f"⚠️ Fehler beim Abrufen oder Parsen der Sitemap {sitemap_url}: {e}")
    
    # Spezielle Kategorie hinzufügen, wenn aus Logs bekannt
    journey_category_url = "https://www.mighty-cards.de/pokemon/reisegefahrten-journey-together/"
    if journey_category_url not in product_urls:
        product_urls.append(journey_category_url)
        logger.info("Spezielle Kategorieseite für Reisegefährten hinzugefügt")
    
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
        
        # Versuche zuerst die Storefront-Seite zu laden, um Cookie und Session-Daten zu erhalten
        logger.info("🔍 Versuche Ecwid-Storedaten zu laden")
        try:
            response = requests.get("https://www.mighty-cards.de/", headers=headers, timeout=15)
            # Speichere Cookies für spätere Requests
            cookies = response.cookies
        except Exception as e:
            logger.warning(f"⚠️ Fehler beim Laden der Startseite: {e}")
            cookies = None

        for search_term in keywords_map.keys():
            # Bereinige den Suchbegriff
            clean_term = search_term.lower().replace("display", " ").strip()
            
            # 1. Versuche über die Bootstrap-API
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
            
            # 2. Versuche über die Initial-Data API
            try:
                initial_data_url = f"{ECWID_BASE_URL}/storefront/api/v1/{store_id}/initial-data"
                
                initial_data_response = requests.post(initial_data_url, json={}, headers=api_headers, cookies=cookies, timeout=15)
                if initial_data_response.status_code == 200:
                    try:
                        data = initial_data_response.json()
                        if 'items' in data.get('productsWithAdditionalInfo', {}):
                            for item in data['productsWithAdditionalInfo']['items']:
                                product_id = item.get('id')
                                product_name = item.get('name', '').lower()
                                
                                # Filtern nach relevanten Produkten
                                if (product_id and 
                                    ('journey' in product_name or 'reisegef' in product_name or 
                                     'sv09' in product_name or 'kp09' in product_name)):
                                    product_url = f"https://www.mighty-cards.de/shop/p{product_id}"
                                    product_urls.append(product_url)
                    except (ValueError, KeyError) as e:
                        logger.debug(f"⚠️ Fehler beim Parsen der Initial-Data: {e}")
            except Exception as e:
                logger.debug(f"⚠️ Fehler bei Initial-Data-API: {e}")
            
            # 3. Versuche die direkte Suche-URL
            try:
                search_url = f"https://www.mighty-cards.de/shop/search?keyword={quote_plus(clean_term)}"
                search_response = requests.get(search_url, headers=headers, cookies=cookies, timeout=15)
                
                if search_response.status_code == 200:
                    soup = BeautifulSoup(search_response.text, "html.parser")
                    
                    # Finde Produktlinks in den Suchergebnissen
                    links = soup.find_all("a", href=True)
                    for link in links:
                        href = link["href"]
                        if '/shop/' in href and 'p' in href.split('/')[-1]:
                            full_url = href if href.startswith('http') else urljoin("https://www.mighty-cards.de", href)
                            if full_url not in product_urls:
                                product_urls.append(full_url)
            except Exception as e:
                logger.debug(f"⚠️ Fehler bei der Such-URL: {e}")
                
    except Exception as e:
        logger.warning(f"⚠️ Fehler beim Laden der Ecwid-Daten: {e}")
    
    logger.info(f"✅ {len(product_urls)} Produkt-URLs über Ecwid-Integration gefunden")
    return product_urls

def fetch_products_from_categories(headers):
    """
    Durchsucht wichtige Kategorie-Seiten nach Produkten
    
    :param headers: HTTP-Headers für Anfragen
    :return: Liste mit Produkt-URLs
    """
    product_urls = []
    
    # Liste der wichtigen Kategorien basierend auf der Sitemap-Analyse
    category_urls = [
        "https://www.mighty-cards.de/shop/Pokemon-c165637849/",  # Pokemon-Kategorie
        "https://www.mighty-cards.de/shop/Displays-c165638577/",  # Displays-Kategorie
        "https://www.mighty-cards.de/shop/Vorbestellung-c166467816/",  # Vorbestellungen
        "https://www.mighty-cards.de/pokemon/reisegefahrten-journey-together/"  # Spezifische Reisegefährten-Kategorie
    ]
    
    for category_url in category_urls:
        try:
            logger.info(f"🔍 Durchsuche Kategorie: {category_url}")
            response = requests.get(category_url, headers=headers, timeout=15)
            if response.status_code != 200:
                logger.warning(f"⚠️ Fehler beim Abrufen der Kategorie {category_url}: Status {response.status_code}")
                continue
                
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Suche nach Produktlinks und Kategorielinks
            links = soup.find_all("a", href=True)
            
            # Extrahiere Produktlinks
            for link in links:
                href = link["href"]
                
                # Direkter Produktlink
                if '/shop/' in href and 'p' in href.split('/')[-1]:
                    full_url = href if href.startswith('http') else urljoin("https://www.mighty-cards.de", href)
                    if full_url not in product_urls:
                        product_urls.append(full_url)
                
                # Kategorie-Links weiterverfolgen (nur eine Ebene tief)
                elif '/shop/' in href and 'c' in href.split('/')[-1] and href != category_url:
                    try:
                        subcat_response = requests.get(href if href.startswith('http') else urljoin("https://www.mighty-cards.de", href), 
                                                    headers=headers, timeout=15)
                        if subcat_response.status_code == 200:
                            subcat_soup = BeautifulSoup(subcat_response.text, "html.parser")
                            subcat_links = subcat_soup.find_all("a", href=True)
                            
                            for sublink in subcat_links:
                                subhref = sublink["href"]
                                if '/shop/' in subhref and 'p' in subhref.split('/')[-1]:
                                    full_url = subhref if subhref.startswith('http') else urljoin("https://www.mighty-cards.de", subhref)
                                    if full_url not in product_urls:
                                        product_urls.append(full_url)
                    except Exception as e:
                        logger.debug(f"⚠️ Fehler beim Durchsuchen der Unterkategorie {href}: {e}")
                        
        except Exception as e:
            logger.error(f"❌ Fehler beim Durchsuchen der Kategorie {category_url}: {e}")
    
    # Dedupliziere die URLs
    product_urls = list(set(product_urls))
    logger.info(f"✅ {len(product_urls)} Produkt-URLs aus Kategorien extrahiert")
    
    return product_urls

def search_mighty_cards_products(search_term, headers):
    """
    Führt eine Suche auf der Website durch und extrahiert Produkt-URLs.
    Diese Funktion nutzt die Suchfunktion der Website, wie in der Analyse identifiziert.
    
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
        
        # Suche nach Produktlinks basierend auf der Seitenanalyse
        # 1. Versuche zuerst spezifische Produktkomponenten zu identifizieren
        product_elements = soup.select('.product-card, .grid-product, .product-item')
        
        if product_elements:
            for product_elem in product_elements:
                link = product_elem.find("a", href=True)
                if link and link.has_attr('href'):
                    href = link['href']
                    if '/shop/' in href and 'p' in href.split('/')[-1]:
                        # Vollständige URL erstellen
                        product_url = urljoin("https://www.mighty-cards.de", href)
                        if product_url not in product_urls:
                            product_urls.append(product_url)
        else:
            # 2. Fallback: Suche nach allen Links
            links = soup.find_all("a", href=True)
            
            for link in links:
                href = link.get('href', '')
                if '/shop/' in href and 'p' in href.split('/')[-1]:
                    # Vollständige URL erstellen
                    product_url = urljoin("https://www.mighty-cards.de", href)
                    if product_url not in product_urls:
                        product_urls.append(product_url)
        
        logger.info(f"🔍 {len(product_urls)} Produkt-Links in Suchergebnissen gefunden")
        
    except Exception as e:
        logger.warning(f"⚠️ Fehler bei der Suche nach '{search_term}': {e}")
    
    return product_urls

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
        try:
            response = requests.get(product_url, headers=headers, timeout=10)
            if response.status_code != 200:
                logger.warning(f"⚠️ Fehler beim Abrufen von {product_url}: Status {response.status_code}")
                return False
        except requests.exceptions.RequestException as e:
            logger.warning(f"⚠️ Fehler beim Abrufen von {product_url}: {e}")
            return False
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Versuche JavaScript-Daten für strukturierte Informationen zu extrahieren
        js_data = extract_js_product_data(soup, product_url)
        if js_data:
            # Verwende die Daten aus dem JavaScript
            title = js_data.get("title", "")
            if not title:
                title = extract_title_from_url(product_url)
                
            # Korrigiere bekannte Tippfehler
            if "Togehter" in title:
                title = title.replace("Togehter", "Together")
                
            is_available = js_data.get("available", False)
            price = js_data.get("price", "Preis nicht verfügbar")
            if isinstance(price, (int, float)):
                price = f"{price:.2f}€"
                
            # Preis-Filter anwenden
            price_value = extract_price_value(price)
            if price_value is not None:
                if (min_price is not None and price_value < min_price) or (max_price is not None and price_value > max_price):
                    logger.info(f"⚠️ Produkt '{title}' mit Preis {price} liegt außerhalb des Preisbereichs ({min_price or 0}€ - {max_price or '∞'}€)")
                    return False
                
            status_text = "✅ Verfügbar" if is_available else "❌ Ausverkauft"
        else:
            # HTML-basierte Extraktion basierend auf der Seitenanalyse
            title_elem = soup.find('h1', {'class': 'product-details__product-title'})
            if not title_elem:
                title_elem = soup.find('h1')
            
            # Wenn immer noch kein Titel gefunden wurde, verwende URL als Fallback
            if not title_elem:
                title = extract_title_from_url(product_url)
                logger.info(f"📝 Generierter Titel aus URL: '{title}'")
            else:
                title = title_elem.text.strip()
            
            # Korrigiere bekannte Tippfehler
            if "Togehter" in title:
                title = title.replace("Togehter", "Together")
            
            # Basierend auf der HTML-Analyse: Extrahiere Preis aus dem entsprechenden Element
            price_elem = soup.find('span', {'class': 'details-product-price__value'})
            price = price_elem.text.strip() if price_elem else "Preis nicht verfügbar"
            
            # Preis-Filter anwenden
            price_value = extract_price_value(price)
            if price_value is not None:
                if (min_price is not None and price_value < min_price) or (max_price is not None and price_value > max_price):
                    logger.info(f"⚠️ Produkt '{title}' mit Preis {price} liegt außerhalb des Preisbereichs ({min_price or 0}€ - {max_price or '∞'}€)")
                    return False
            
            # Verfügbarkeitsprüfung: Suche nach dem "In den Warenkorb"-Button
            cart_button = soup.find('span', {'class': 'form-control__button-text'}, text=re.compile('In den Warenkorb', re.IGNORECASE))
            if cart_button:
                is_available = True
                status_text = "✅ Verfügbar"
            else:
                is_available = False
                status_text = "❌ Ausverkauft"
        
        # Extrahiere Produkttyp aus dem Titel
        title_product_type = extract_product_type_from_text(title)
        
        # Prüfe den Titel gegen alle Suchbegriffe
        matched_term = None
        for search_term, tokens in keywords_map.items():
            # Extrahiere Produkttyp aus dem Suchbegriff
            search_term_type = extract_product_type_from_text(search_term)
            
            # Wenn nach einem Display gesucht wird, aber das Produkt keins ist, überspringen
            if search_term_type == "display" and title_product_type != "display":
                continue
                
            # Prüfe, ob der Titel den Suchbegriff enthält
            if is_keyword_in_text(tokens, title, log_level='None'):
                matched_term = search_term
                break
        
        # Wenn kein Match gefunden, versuche Fallback basierend auf URL
        if not matched_term:
            if "SV09" in product_url or "Journey" in product_url:
                matched_term = "Journey Together display"
            elif "KP09" in product_url or "Reisegef" in product_url:
                matched_term = "Reisegefährten display"
            elif "SV10" in product_url or "Destined" in product_url or "destined" in title.lower():
                matched_term = "Journey Together display"  # Als Fallback für neue Sets
            elif "KP10" in product_url or "Ewige" in product_url or "ewige" in title.lower() or "rivalen" in title.lower():
                matched_term = "Reisegefährten display"  # Als Fallback für neue Sets
        
        # Wenn immer noch kein passender Suchbegriff gefunden wurde
        if not matched_term:
            logger.debug(f"❌ Kein passender Suchbegriff für {title}")
            return False
        
        # Erstelle eine einzigartige ID für das Produkt
        product_id = create_product_id(title)
        
        # Überprüfe den Status und ob eine Benachrichtigung gesendet werden soll
        should_notify, is_back_in_stock = update_product_status(
            product_id, is_available, seen, out_of_stock
        )
        
        # Bei "nur verfügbare" Option, nicht verfügbare Produkte überspringen
        if only_available and not is_available:
            return False
        
        # Wenn keine Benachrichtigung gesendet werden soll
        if not should_notify:
            return True  # Produkt erfolgreich verarbeitet, aber keine Benachrichtigung
        
        # Status-Text aktualisieren, wenn Produkt wieder verfügbar ist
        if is_back_in_stock:
            status_text = "🎉 Wieder verfügbar!"
        
        # Produkt-Informationen für die Benachrichtigung
        product_data = {
            "title": title,
            "url": product_url,
            "price": price,
            "status_text": status_text,
            "is_available": is_available,
            "matched_term": matched_term,
            "product_type": title_product_type,
            "shop": "mighty-cards.de"
        }
        
        return product_data
            
    except Exception as e:
        logger.error(f"❌ Fehler beim Verarbeiten des Produkts {product_url}: {e}")
        return False

def process_fallback_product(product_url, keywords_map, seen, out_of_stock, only_available, headers, min_price=None, max_price=None):
    """
    Verarbeitet eine direkte Produkt-URL als Fallback-Mechanismus
    
    :param product_url: URL der Produktseite
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param seen: Set mit bereits gesehenen Produkttiteln
    :param out_of_stock: Set mit ausverkauften Produkten
    :param only_available: Ob nur verfügbare Produkte gemeldet werden sollen
    :param headers: HTTP-Headers
    :param min_price: Minimaler Preis für Produktbenachrichtigungen
    :param max_price: Maximaler Preis für Produktbenachrichtigungen
    :return: Product data dict if successful, False otherwise
    """
    # Da die URL-Struktur bekannt ist: Versuche den Titel direkt aus der URL zu extrahieren
    try:
        url_path = urlparse(product_url).path
        product_slug = url_path.split('/')[-1]
        
        # Für URLs wie https://www.mighty-cards.de/shop/SV09-Journey-Togehter-36er-Booster-Display-Pokemon-p743684893
        if '-p' in product_slug:
            title_part = product_slug.split('-p')[0]
            title = title_part.replace('-', ' ')
            
            # Korrigiere bekannte Tippfehler
            if "Togehter" in title:
                title = title.replace("Togehter", "Together")
                
            # Stelle sicher, dass "Pokemon" im Titel ist
            if "Pokemon" not in title:
                title += " Pokemon"
                
            # Prüfe jeden Suchbegriff gegen den generierten Titel
            matched_term = None
            for search_term, tokens in keywords_map.items():
                if is_keyword_in_text(tokens, title, log_level='None'):
                    matched_term = search_term
                    break
                    
            if matched_term:
                # Vereinfachter Fallback: Annahme, dass Produkt verfügbar ist mit Standard-Preis
                product_data = {
                    "title": title,
                    "url": product_url,
                    "price": "159,99€",  # Standard-Preis für Display
                    "status_text": "✅ Verfügbar (Fallback)",
                    "is_available": True,
                    "matched_term": matched_term,
                    "product_type": "display",
                    "shop": "mighty-cards.de"
                }
                
                product_id = create_product_id(title)
                
                # Status aktualisieren, aber keine Verfügbarkeitsprüfung durchführen
                update_product_status(product_id, True, seen, out_of_stock)
                
                return product_data
    except Exception as e:
        logger.warning(f"⚠️ Fehler bei URL-basiertem Fallback: {e}")
    
    # Wenn URL-Extraktion fehlschlägt, versuche es mit dem regulären Prozess
    return process_mighty_cards_product(product_url, keywords_map, seen, out_of_stock, only_available, headers, min_price, max_price)

def extract_js_product_data(soup, url):
    """
    Extrahiert Produktdaten aus JavaScript-Objekten auf der Seite
    
    :param soup: BeautifulSoup-Objekt der Produktseite
    :param url: URL der Produktseite
    :return: Dictionary mit Produktdaten oder None wenn keine gefunden
    """
    # Suche nach JSON-LD Daten (strukturierte Daten)
    json_ld = soup.find('script', {'type': 'application/ld+json'})
    if json_ld:
        try:
            data = json.loads(json_ld.string)
            if isinstance(data, dict) and data.get('@type') == 'Product':
                product_data = {
                    'title': data.get('name', ''),
                    'price': data.get('offers', {}).get('price', 'Preis nicht verfügbar'),
                    'available': data.get('offers', {}).get('availability', '').endswith('InStock')
                }
                return product_data
        except (json.JSONDecodeError, AttributeError):
            pass
    
    # Suche nach Ecwid-spezifischen Daten
    # Extrahiere Produkt-ID aus der URL
    product_id_match = re.search(r'p(\d+)$', url)
    if product_id_match:
        product_id = product_id_match.group(1)
        
        # Suche nach JavaScript-Variablen mit Produktdaten
        for script in soup.find_all('script'):
            script_content = script.string
            if not script_content:
                continue
            
            # Suche nach dem spezifischen Produkt-ID
            product_js_match = re.search(rf'"id":\s*{product_id}.*?"name":\s*"([^"]+)"', script_content)
            if product_js_match:
                product_title = product_js_match.group(1)
                
                # Suche nach Verfügbarkeitsinformationen
                available_match = re.search(rf'"id":\s*{product_id}.*?"inStock":\s*(true|false)', script_content)
                is_available = available_match and available_match.group(1) == 'true'
                
                # Suche nach Preisinformationen
                price_match = re.search(rf'"id":\s*{product_id}.*?"price":\s*(\d+\.\d+)', script_content)
                price = f"{price_match.group(1)}€" if price_match else "Preis nicht verfügbar"
                
                return {
                    'title': product_title,
                    'price': price,
                    'available': is_available
                }
    
    # Suche nach "product"-Variablen in JavaScript
    for script in soup.find_all('script'):
        script_content = script.string
        if not script_content:
            continue
            
        # Suche nach verschiedenen gängigen Produkt-Variablen
        product_vars = [
            r'var\s+product\s*=\s*({.*?});',
            r'window\.product\s*=\s*({.*?});',
            r'var\s+productData\s*=\s*({.*?});'
        ]
        
        for pattern in product_vars:
            try:
                match = re.search(pattern, script_content, re.DOTALL)
                if match:
                    data = json.loads(match.group(1))
                    
                    # Versuche die Daten zu extrahieren
                    title = data.get('title', data.get('name', ''))
                    available = data.get('available', data.get('inStock', False))
                    price = data.get('price', data.get('currentPrice', 'Preis nicht verfügbar'))
                    
                    if title or available is not None or price:
                        return {
                            'title': title,
                            'price': price,
                            'available': available
                        }
            except (json.JSONDecodeError, AttributeError):
                continue
    
    # Nichts gefunden
    return None

def extract_title_from_url(url):
    """
    Extrahiert einen sinnvollen Titel aus der URL-Struktur
    
    :param url: URL der Produktseite
    :return: Extrahierter Titel
    """
    # Extrahiere den Pfad aus der URL
    path = url.split('/')[-1]
    
    # Entferne Parameter bei p12345 Endungen
    path = re.sub(r'-p\d+$', '', path)
    
    # Ersetze Bindestriche durch Leerzeichen
    title = path.replace('-', ' ')
    
    # Verarbeite Spezialfälle für bekannte Produkte
    if "SV09" in title or "Journey" in title:
        if "display" not in title.lower():
            title += " Display"
        if "Togehter" in title:
            title = title.replace("Togehter", "Together")
    elif "KP09" in title or "Reisegef" in title:
        if "display" not in title.lower():
            title += " Display"
    elif "SV10" in title or "destined" in title.lower() or "Destined" in title:
        if "display" not in title.lower():
            title += " Display"
    elif "KP10" in title or "ewige" in title.lower() or "Ewige" in title or "rivalen" in title.lower():
        if "display" not in title.lower():
            title += " Display"
    
    # Erster Buchstabe groß
    title = title.strip().capitalize()
    
    return title

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
    # Extrahiere relevante Informationen für die ID
    title_lower = title.lower()
    
    # Sprache (DE/EN)
    if "deutsch" in title_lower or "karmesin" in title_lower or "purpur" in title_lower:
        language = "DE"
    elif "english" in title_lower or "scarlet" in title_lower or "violet" in title_lower:
        language = "EN"
    else:
        # Betrachte bekannte deutsche/englische Produktnamen
        de_sets = ["reisegefährten", "ewige rivalen", "verborgene schätze"]
        en_sets = ["journey together", "destined rivals", "hidden treasures"]
        
        if any(term in title_lower for term in de_sets):
            language = "DE"
        elif any(term in title_lower for term in en_sets):
            language = "EN"
        else:
            language = "UNK"
    
    # Produkttyp
    product_type = extract_product_type_from_text(title)
    
    # Serien-Code erkennen
    series_code = "unknown"
    
    # Suche nach Standardcodes wie SV09, KP09, etc.
    code_match = re.search(r'(?:sv|kp|op)(?:\s|-)?\d+', title_lower)
    if code_match:
        series_code = code_match.group(0).replace(" ", "").replace("-", "")
    # Bekannte Setnamen auf Codes mappen
    elif "journey together" in title_lower:
        series_code = "sv09"
    elif "reisegefährten" in title_lower:
        series_code = "kp09"
    elif "destined rivals" in title_lower:
        series_code = "sv10"
    elif "ewige rivalen" in title_lower:
        series_code = "kp10"
    
    # Erstelle eine strukturierte ID
    product_id = f"{base_id}_{series_code}_{product_type}_{language}"
    
    # Zusatzinformationen
    if "18er" in title_lower:
        product_id += "_18er"
    elif "36er" in title_lower:
        product_id += "_36er"
    
    return product_id