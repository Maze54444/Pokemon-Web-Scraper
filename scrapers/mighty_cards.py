import requests
import logging
import re
import time
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote_plus
from utils.matcher import is_keyword_in_text, extract_product_type_from_text
from utils.stock import get_status_text, update_product_status
from utils.availability import detect_availability

# Logger konfigurieren
logger = logging.getLogger(__name__)

def scrape_mighty_cards(keywords_map, seen, out_of_stock, only_available=False):
    """
    Spezieller Scraper für mighty-cards.de
    
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param seen: Set mit bereits gesehenen Produkttiteln
    :param out_of_stock: Set mit ausverkauften Produkten
    :param only_available: Ob nur verfügbare Produkte gemeldet werden sollen
    :return: Liste der neuen Treffer
    """
    logger.info("🌐 Starte speziellen Scraper für mighty-cards.de")
    new_matches = []
    all_products = []  # Liste für alle gefundenen Produkte
    
    # Set für Deduplizierung von gefundenen Produkten
    found_product_ids = set()
    
    # Hardcoded Beispiel-URLs für bekannte Produkte
    # Diese sollten nur als Backup dienen, wenn die Suche nicht funktioniert
    hardcoded_urls = [
        "https://www.mighty-cards.de/shop/SV09-Journey-Togehter-36er-Booster-Display-Pokemon-p743684893",
        "https://www.mighty-cards.de/shop/KP09-Reisegefahrten-36er-Booster-Display-Pokemon-p739749306",
        "https://www.mighty-cards.de/shop/KP09-Reisegefahrten-18er-Booster-Display-Pokemon-p739750556"
    ]
    
    # Kategorie-URL für Pokémon-Produkte
    category_urls = [
        "https://www.mighty-cards.de/pokemon/"
    ]
    
    # Dynamische Erstellung von Suchanfragen basierend auf den Keywords
    search_urls = []
    for search_term in keywords_map.keys():
        # URL-Encoding für die Suche
        encoded_term = quote_plus(search_term)
        search_url = f"https://www.mighty-cards.de/shop/search?keyword={encoded_term}&limit=20"
        search_urls.append(search_url)
        
        # Zusätzliche Suchanfragen für Varianten
        if "display" in search_term.lower():
            # Variante ohne "display" für bessere Trefferquote
            base_term = search_term.lower().replace("display", "").strip()
            if base_term:
                encoded_base = quote_plus(base_term)
                search_urls.append(f"https://www.mighty-cards.de/shop/search?keyword={encoded_base}&limit=20")
    
    # User-Agent für Anfragen
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "de,en-US;q=0.7,en;q=0.3",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control": "max-age=0"
    }
    
    # 1. Zuerst Suchanfragen durchführen (basierend auf den tatsächlichen Suchbegriffen aus products.txt)
    logger.info(f"🔍 Durchführe {len(search_urls)} Suchanfragen basierend auf Suchbegriffen")
    for url in search_urls:
        try:
            logger.info(f"🔍 Durchsuche Suchergebnisse: {url}")
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code != 200:
                logger.warning(f"⚠️ Fehler beim Abrufen von {url}: Status {response.status_code}")
                continue
                
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Produkt-Links in den Suchergebnissen finden
            product_links = []
            
            # Finde alle Produktkarten/Links
            product_elements = soup.select('.category-grid .category-product, .product-grid-item, .product')
            if not product_elements:
                # Alternativer Selektor, falls obiger nicht funktioniert
                product_elements = soup.select('a[href*="/shop/"]')
            
            for product_elem in product_elements:
                # Finde den Link (entweder ist das Element selbst ein Link oder enthält einen)
                link = product_elem if product_elem.name == 'a' else product_elem.find('a')
                if not link or not link.has_attr('href'):
                    continue
                    
                href = link.get('href', '')
                if '/shop/' not in href:
                    continue
                    
                # Vollständige URL erstellen
                product_url = urljoin("https://www.mighty-cards.de", href)
                product_links.append(product_url)
            
            logger.info(f"🔍 {len(product_links)} Produkt-Links in Suchergebnissen gefunden")
            
            # Produkt-Links verarbeiten
            for product_url in product_links:
                product_data = process_mighty_cards_product(product_url, keywords_map, seen, out_of_stock, only_available, headers)
                if product_data and isinstance(product_data, dict):
                    product_id = create_product_id(product_data["title"])
                    if product_id not in found_product_ids:
                        all_products.append(product_data)
                        new_matches.append(product_id)
                        found_product_ids.add(product_id)
                        logger.info(f"✅ Neuer Treffer gefunden (Suche): {product_data['title']} - {product_data['status_text']}")
                
        except Exception as e:
            logger.error(f"❌ Fehler beim Durchsuchen der Suchergebnisse {url}: {e}")
    
    # 2. Dann Kategorie-Seiten durchsuchen, falls bei der Suche nichts gefunden wurde
    if not all_products:
        logger.info(f"🔍 Durchsuche {len(category_urls)} Kategorie-Seiten")
        for url in category_urls:
            try:
                logger.info(f"🔍 Durchsuche Kategorie-Seite: {url}")
                response = requests.get(url, headers=headers, timeout=15)
                if response.status_code != 200:
                    logger.warning(f"⚠️ Fehler beim Abrufen von {url}: Status {response.status_code}")
                    continue
                    
                soup = BeautifulSoup(response.text, "html.parser")
                
                # Suche nach Unterkategorien, die die Suchbegriffe enthalten könnten
                subcategory_links = []
                for link in soup.select('a[href*="/pokemon/"]'):
                    href = link.get('href', '')
                    text = link.get_text().strip().lower()
                    
                    # Prüfe, ob Unterkategorie für eines der gesuchten Produkte relevant sein könnte
                    for search_term in keywords_map.keys():
                        clean_search = search_term.lower().replace("display", "").strip()
                        if clean_search in text or clean_search in href.lower():
                            subcategory_url = urljoin("https://www.mighty-cards.de", href)
                            subcategory_links.append(subcategory_url)
                            break
                
                logger.info(f"🔍 {len(subcategory_links)} relevante Unterkategorien gefunden")
                
                # Verarbeite Unterkategorien
                for subcat_url in subcategory_links:
                    try:
                        subcat_response = requests.get(subcat_url, headers=headers, timeout=15)
                        if subcat_response.status_code != 200:
                            continue
                            
                        subcat_soup = BeautifulSoup(subcat_response.text, "html.parser")
                        
                        # Finde Produkt-Links
                        product_elements = subcat_soup.select('.category-grid .category-product, .product-grid-item, .product')
                        if not product_elements:
                            product_elements = subcat_soup.select('a[href*="/shop/"]')
                        
                        for product_elem in product_elements:
                            link = product_elem if product_elem.name == 'a' else product_elem.find('a')
                            if not link or not link.has_attr('href'):
                                continue
                                
                            href = link.get('href', '')
                            if '/shop/' not in href:
                                continue
                                
                            product_url = urljoin("https://www.mighty-cards.de", href)
                            
                            # Verarbeite Produkt
                            product_data = process_mighty_cards_product(product_url, keywords_map, seen, out_of_stock, only_available, headers)
                            if product_data and isinstance(product_data, dict):
                                product_id = create_product_id(product_data["title"])
                                if product_id not in found_product_ids:
                                    all_products.append(product_data)
                                    new_matches.append(product_id)
                                    found_product_ids.add(product_id)
                                    logger.info(f"✅ Neuer Treffer gefunden (Kategorie): {product_data['title']} - {product_data['status_text']}")
                    
                    except Exception as e:
                        logger.warning(f"⚠️ Fehler beim Verarbeiten der Unterkategorie {subcat_url}: {e}")
                
            except Exception as e:
                logger.error(f"❌ Fehler beim Durchsuchen der Kategorie-Seite {url}: {e}")
    
    # 3. Zuletzt direkte Produkt-URLs als Fallback-Lösung prüfen
    if not all_products:
        logger.info(f"🔍 Prüfe {len(hardcoded_urls)} bekannte Produkt-URLs als Fallback")
        for url in hardcoded_urls:
            product_data = process_mighty_cards_product(url, keywords_map, seen, out_of_stock, only_available, headers)
            if product_data and isinstance(product_data, dict):
                product_id = create_product_id(product_data["title"])
                if product_id not in found_product_ids:
                    all_products.append(product_data)
                    new_matches.append(product_id)
                    found_product_ids.add(product_id)
                    logger.info(f"✅ Neuer Treffer gefunden (direkte URL): {product_data['title']} - {product_data['status_text']}")
    
    # Sende Benachrichtigungen
    if all_products:
        from utils.telegram import send_batch_notification
        send_batch_notification(all_products)
    
    return new_matches

def process_mighty_cards_product(product_url, keywords_map, seen, out_of_stock, only_available, headers):
    """
    Verarbeitet eine einzelne Produktseite von Mighty Cards
    
    :param product_url: URL der Produktseite
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param seen: Set mit bereits gesehenen Produkttiteln
    :param out_of_stock: Set mit ausverkauften Produkten
    :param only_available: Ob nur verfügbare Produkte gemeldet werden sollen
    :param headers: HTTP-Headers
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
        
        # Extrahiere den Titel
        title_elem = soup.select_one('h1, .product-title, .h1')
        if not title_elem:
            logger.warning(f"⚠️ Kein Titel gefunden auf {product_url}")
            return False
            
        title = title_elem.text.strip()
        
        # Normalisiere den Titel (korrigiere häufige Tippfehler)
        # Falls "Togehter" statt "Together" im Titel steht
        if "Togehter" in title:
            title = title.replace("Togehter", "Together")
        
        # Extrahiere Produkttyp aus dem Titel
        title_product_type = extract_product_type_from_text(title)
        
        # Prüfe den Titel gegen alle Suchbegriffe
        matched_term = None
        for search_term, tokens in keywords_map.items():
            # Extrahiere Produkttyp aus dem Suchbegriff
            search_term_type = extract_product_type_from_text(search_term)
            
            # Wenn nach Display gesucht wird und das Produkt kein Display ist, überspringen
            if search_term_type == "display" and title_product_type != "display":
                continue
                
            # Prüfe, ob der Titel den Suchbegriff enthält
            if is_keyword_in_text(tokens, title, log_level='None'):
                matched_term = search_term
                break
        
        # Wenn kein passender Suchbegriff gefunden wurde
        if not matched_term:
            logger.debug(f"❌ Kein passender Suchbegriff für {title}")
            return False
        
        # Überprüfe die Verfügbarkeit
        is_available, price, status_text = detect_mighty_cards_availability(soup, product_url)
        
        # Falls detect_availability keine hilfreichen Infos liefert, manuelle Prüfung
        if status_text == "[?] Status unbekannt":
            # Prüfe auf "AUSVERKAUFT"-Text
            sold_out_elems = soup.select(".sold-out, .out-of-stock, .text-danger, .unavailable")
            ausverkauft_text = soup.find(string=re.compile('ausverkauft', re.IGNORECASE))
            
            if sold_out_elems or ausverkauft_text or "ausverkauft" in soup.text.lower():
                is_available = False
                status_text = "❌ Ausverkauft"
            else:
                # Prüfe auf "In den Warenkorb"-Button
                cart_button = soup.select_one(".btn-cart, .btn-primary, .add-to-cart:not([disabled])")
                if cart_button:
                    is_available = True
                    status_text = "✅ Verfügbar"
        
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
        
        # Extraktion des Produkttyps für die Benachrichtigung
        product_type = extract_product_type_from_text(title)
        
        # Produkt-Informationen für die Benachrichtigung
        product_data = {
            "title": title,
            "url": product_url,
            "price": price,
            "status_text": status_text,
            "is_available": is_available,
            "matched_term": matched_term,
            "product_type": product_type,
            "shop": "mighty-cards.de"
        }
        
        return product_data
        
    except Exception as e:
        logger.error(f"❌ Fehler beim Verarbeiten des Produkts {product_url}: {e}")
        return False

def detect_mighty_cards_availability(soup, url):
    """
    Spezifische Verfügbarkeitserkennung für mighty-cards.de
    
    :param soup: BeautifulSoup-Objekt der Produktseite
    :param url: URL der Produktseite
    :return: Tuple (is_available, price, status_text)
    """
    # Erste Prüfung: Verwende das generische Availability-Modul
    from utils.availability import detect_availability
    is_available, price, status_text = detect_availability(soup, url)
    
    # Wenn die generische Erkennung unsicher ist, verwenden wir spezifische Methoden
    if status_text == "[?] Status unbekannt":
        # 1. Prüfe auf "AUSVERKAUFT"-Text oder Label
        ausverkauft_elems = soup.select('.sold-out, .unavailable, .out-of-stock')
        ausverkauft_text = soup.find(string=re.compile('ausverkauft', re.IGNORECASE))
        
        if ausverkauft_elems or ausverkauft_text:
            is_available = False
            status_text = "❌ Ausverkauft"
        else:
            # 2. Prüfe auf aktiven "In den Warenkorb"-Button
            cart_btn = soup.select_one('.btn-cart:not([disabled]), .add-to-cart:not([disabled]), .btn-primary:not([disabled])')
            if cart_btn:
                is_available = True
                status_text = "✅ Verfügbar"
        
        # 3. Zusätzliche Prüfung: Text auf der Seite
        page_text = soup.get_text().lower()
        if "nicht verfügbar" in page_text or "nicht mehr verfügbar" in page_text:
            is_available = False
            status_text = "❌ Ausverkauft (nicht verfügbar)"
    
    # Preis extrahieren, falls noch nicht gefunden
    if price == "Preis nicht verfügbar":
        price_elem = soup.select_one('.current-price, .price, .product-price, .product__price')
        if price_elem:
            price = price_elem.text.strip()
    
    return is_available, price, status_text

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