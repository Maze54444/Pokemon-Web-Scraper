import requests
import logging
import re
import time
import json
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote_plus
from utils.matcher import is_keyword_in_text, extract_product_type_from_text
from utils.stock import get_status_text, update_product_status
from utils.availability import detect_availability

# Logger konfigurieren
logger = logging.getLogger(__name__)

def scrape_mighty_cards(keywords_map, seen, out_of_stock, only_available=False, min_price=None, max_price=None):
    """
    Spezieller Scraper für mighty-cards.de
    
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param seen: Set mit bereits gesehenen Produkttiteln
    :param out_of_stock: Set mit ausverkauften Produkten
    :param only_available: Ob nur verfügbare Produkte gemeldet werden sollen
    :param min_price: Minimaler Preis für Produktbenachrichtigungen
    :param max_price: Maximaler Preis für Produktbenachrichtigungen
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
                product_data = process_mighty_cards_product(product_url, keywords_map, seen, out_of_stock, only_available, headers, min_price, max_price)
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
                            product_data = process_mighty_cards_product(product_url, keywords_map, seen, out_of_stock, only_available, headers, min_price, max_price)
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
            product_data = process_fallback_product(url, keywords_map, seen, out_of_stock, only_available, headers, min_price, max_price)
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
        
        # Versuche JavaScript-Daten zu extrahieren
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
            # Extrahiere den Titel
            title_elem = soup.select_one('h1, .product-title, .h1')
            if not title_elem:
                # Versuche alternative Selektoren
                title_elem = soup.select_one('.page-title, .product-name, .title')
                
            # Wenn immer noch kein Titel gefunden wurde, verwende URL als Fallback
            if not title_elem:
                title = extract_title_from_url(product_url)
                logger.info(f"⚠️ Kein Titel gefunden, generiert aus URL: {title}")
            else:
                title = title_elem.text.strip()
            
            # Normalisiere den Titel (korrigiere häufige Tippfehler)
            # Falls "Togehter" statt "Together" im Titel steht
            if "Togehter" in title:
                title = title.replace("Togehter", "Together")
            
            # Prüfe auf eindeutigen Produkttyp in der URL
            if "36er-Booster-Display" in product_url or "36er-Display" in product_url:
                if not "display" in title.lower():
                    title += " Display"
            
            # Überprüfe die Verfügbarkeit
            is_available, price, status_text = detect_mighty_cards_availability(soup, product_url)
            
            # Preis-Filter anwenden
            price_value = extract_price_value(price)
            if price_value is not None:
                if (min_price is not None and price_value < min_price) or (max_price is not None and price_value > max_price):
                    logger.info(f"⚠️ Produkt '{title}' mit Preis {price} liegt außerhalb des Preisbereichs ({min_price or 0}€ - {max_price or '∞'}€)")
                    return False
        
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
        
        # Wenn kein Match gefunden, versuche Fallback basierend auf URL
        if not matched_term:
            if "SV09" in product_url or "Journey" in product_url:
                matched_term = "Journey Together display"
            elif "KP09" in product_url or "Reisegef" in product_url:
                matched_term = "Reisegefährten display"
        
        # Wenn kein passender Suchbegriff gefunden wurde
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

def process_fallback_product(product_url, keywords_map, seen, out_of_stock, only_available, headers, min_price=None, max_price=None):
    """
    Verarbeitet eine direkte Produkt-URL mit erweiterter Logik für mighty-cards.de
    
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
    try:
        logger.info(f"🔍 Prüfe Fallback-Produkt: {product_url}")
        
        # Abrufen der Produktseite
        try:
            response = requests.get(product_url, headers=headers, timeout=15)
            if response.status_code != 200:
                logger.warning(f"⚠️ Fehler beim Abrufen von {product_url}: Status {response.status_code}")
                return False
        except requests.exceptions.RequestException as e:
            logger.warning(f"⚠️ Fehler beim Abrufen von {product_url}: {e}")
            return False
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        # JavaScript-Daten extrahieren, die möglicherweise zusätzliche Produktinformationen enthalten
        js_data = extract_js_product_data(soup, product_url)
        if js_data:
            logger.info(f"✅ JavaScript-Produktdaten extrahiert für {product_url}")
            
            # Titel extrahieren oder generieren aus URL falls nicht vorhanden
            title = js_data.get("title", "")
            if not title:
                # Fallback: Extrahiere Titel aus URL
                title = extract_title_from_url(product_url)
                
            # Prüfe auf eindeutigen Produkttyp in der URL
            if "36er-Booster-Display" in product_url or "36er-Display" in product_url:
                if not "display" in title.lower():
                    title += " Display"
                    
            # Korrigiere bekannte Tippfehler
            if "Togehter" in title:
                title = title.replace("Togehter", "Together")
                
            # Verfügbarkeit bestimmen
            is_available = js_data.get("available", False)
            
            # Preis extrahieren
            price = js_data.get("price", "Preis nicht verfügbar")
            if isinstance(price, (int, float)):
                price = f"{price:.2f}€"
            
            # Preis-Filter anwenden
            price_value = extract_price_value(price)
            if price_value is not None:
                if (min_price is not None and price_value < min_price) or (max_price is not None and price_value > max_price):
                    logger.info(f"⚠️ Produkt '{title}' mit Preis {price} liegt außerhalb des Preisbereichs ({min_price or 0}€ - {max_price or '∞'}€)")
                    return False
                    
            # Status-Text generieren
            status_text = "✅ Verfügbar" if is_available else "❌ Ausverkauft"
                
            # Prüfe, ob der Titel zu einem der Suchbegriffe passt
            matched_term = None
            for search_term, tokens in keywords_map.items():
                if is_keyword_in_text(tokens, title, log_level='None'):
                    matched_term = search_term
                    break
                    
            if not matched_term:
                # Versuche noch einen Fallback basierend auf der URL
                if "SV09" in product_url or "Journey" in product_url:
                    matched_term = "Journey Together display"
                elif "KP09" in product_url or "Reisegef" in product_url:
                    matched_term = "Reisegefährten display"
                    
            if not matched_term:
                logger.warning(f"❌ Kein passender Suchbegriff für {title}")
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
            
        # Wenn keine JS-Daten gefunden wurden, nutze Standard-HTML-Parsing
        title_elem = soup.select_one('h1, .product-title, .h1')
        if not title_elem:
            # Versuche alternative Selektoren
            title_elem = soup.select_one('.page-title, .product-name, .title')
            
        # Wenn immer noch kein Titel gefunden wurde, generiere aus URL
        if not title_elem:
            # Extrahiere Titel aus URL-Pfad
            title = extract_title_from_url(product_url)
            logger.info(f"📝 Generierter Titel aus URL: '{title}'")
        else:
            title = title_elem.text.strip()
        
        # Normalisiere den Titel (korrigiere häufige Tippfehler)
        # Falls "Togehter" statt "Together" im Titel steht
        if "Togehter" in title:
            title = title.replace("Togehter", "Together")
        
        # Prüfe auf eindeutigen Produkttyp in der URL
        if "36er-Booster-Display" in product_url or "36er-Display" in product_url:
            if not "display" in title.lower():
                title += " Display"
        
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
        
        # Wenn kein Match gefunden, versuche Fallback basierend auf URL
        if not matched_term:
            if "SV09" in product_url or "Journey" in product_url:
                matched_term = "Journey Together display"
            elif "KP09" in product_url or "Reisegef" in product_url:
                matched_term = "Reisegefährten display"
        
        # Wenn immer noch kein passender Suchbegriff gefunden wurde
        if not matched_term:
            logger.warning(f"❌ Kein passender Suchbegriff für {title}")
            return False
        
        # Überprüfe die Verfügbarkeit - nutze direkte HTML-Indikatoren
        is_available = check_mighty_cards_availability_enhanced(soup, product_url)
        
        # Preis extrahieren mit erweiterter Logik
        price = extract_price_from_page(soup)
        
        # Preis-Filter anwenden
        price_value = extract_price_value(price)
        if price_value is not None:
            if (min_price is not None and price_value < min_price) or (max_price is not None and price_value > max_price):
                logger.info(f"⚠️ Produkt '{title}' mit Preis {price} liegt außerhalb des Preisbereichs ({min_price or 0}€ - {max_price or '∞'}€)")
                return False
        
        # Status-Text generieren
        status_text = "✅ Verfügbar" if is_available else "❌ Ausverkauft"
        
        # Erstelle eine einzigartige ID für das Produkt
        product_id = create_product_id(title)
        
        # Überprüfe den Status und ob eine Benachrichtigung gesendet werden soll
        should_notify, is_back_in_stock = update_product_status(
            product_id, is_available, seen, out_of_stock
        )
        
        # Bei "nur verfügbare" Option überspringen, wenn nicht verfügbar
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
        logger.error(f"❌ Fehler beim Verarbeiten des Fallback-Produkts {product_url}: {e}")
        return False

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
    
    # Suche nach window.__PRELOADED_STATE__
    for script in soup.find_all('script'):
        script_content = script.string
        if script_content and 'window.__PRELOADED_STATE__' in script_content:
            try:
                # Extrahiere den JSON-Teil
                json_str = re.search(r'window\.__PRELOADED_STATE__\s*=\s*({.*?});', script_content, re.DOTALL)
                if json_str:
                    data = json.loads(json_str.group(1))
                    # Suche nach Produktdaten im State
                    product = find_product_in_state(data, url)
                    if product:
                        return product
            except (json.JSONDecodeError, AttributeError) as e:
                logger.debug(f"Fehler beim Parsen von PRELOADED_STATE: {e}")
    
    # Suche nach productOptions oder productJson
    for script in soup.find_all('script'):
        script_content = script.string
        if not script_content:
            continue
            
        # Suche nach verschiedenen Mustern
        patterns = [
            r'var\s+product\s*=\s*({.*?});',
            r'window\.product\s*=\s*({.*?});',
            r'var\s+productData\s*=\s*({.*?});',
            r'var\s+productJson\s*=\s*({.*?});',
            r'window\.productOptions\s*=\s*({.*?});'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, script_content, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                    # Standardisierte Struktur erstellen
                    product_data = {
                        'title': data.get('title', ''),
                        'price': data.get('price', data.get('current_price', 'Preis nicht verfügbar')),
                        'available': data.get('available', False)
                    }
                    
                    # Wenn kein Titel gefunden wurde, versuche andere Felder
                    if not product_data['title'] and data.get('product'):
                        product_data['title'] = data['product'].get('title', '')
                        
                    # Wenn immer noch kein Titel, schaue tiefer in verschachtelten Strukturen
                    if not product_data['title'] and isinstance(data.get('product'), dict):
                        product_data['title'] = data['product'].get('title', '')
                        
                    # Prüfe auf Verfügbarkeit in verschiedenen Formaten
                    if 'available' not in data and 'variants' in data:
                        # Prüfe, ob mindestens eine Variante verfügbar ist
                        for variant in data['variants']:
                            if variant.get('available', False):
                                product_data['available'] = True
                                break
                    
                    # Wenn genug Daten vorhanden sind, nutze sie
                    if product_data['title'] or product_data.get('available') is not None:
                        return product_data
                except (json.JSONDecodeError, AttributeError) as e:
                    logger.debug(f"Fehler beim Parsen von JavaScript-Objekt: {e}")
    
    # Suche nach Web-Komponenten Produktdaten (für neuere Mighty-Cards Implementierung)
    for script in soup.find_all('script'):
        script_content = script.string
        if not script_content:
            continue
            
        # Suche nach Produktdaten in Web-Komponenten
        variants_match = re.search(r'dataProducts\s*=\s*(\[.*?\]);', script_content, re.DOTALL)
        if variants_match:
            try:
                variants_data = json.loads(variants_match.group(1))
                if variants_data and isinstance(variants_data, list) and len(variants_data) > 0:
                    variant = variants_data[0]  # Erste Variante nehmen
                    product_data = {
                        'title': variant.get('title', ''),
                        'price': variant.get('price', variant.get('variant_price', 'Preis nicht verfügbar')),
                        'available': variant.get('available', False)
                    }
                    return product_data
            except (json.JSONDecodeError, AttributeError) as e:
                logger.debug(f"Fehler beim Parsen von dataProducts: {e}")
    
    # Suche nach PRODUCT-Tag in HTML - neuere Mighty-Cards Implementierung
    product_elem = soup.select_one('[data-product-id], [data-product-handle]')
    if product_elem:
        product_id = product_elem.get('data-product-id', '')
        product_handle = product_elem.get('data-product-handle', '')
        
        # Titel aus strukturierten Daten
        title_elem = product_elem.select_one('.product-title, .product-name, .title')
        title = title_elem.text.strip() if title_elem else ''
        
        # Verfügbarkeit aus Struktur
        available_elem = product_elem.select_one('.available, .in-stock, .status-available')
        unavailable_elem = product_elem.select_one('.unavailable, .out-of-stock, .status-unavailable')
        is_available = True if available_elem else False
        if unavailable_elem:
            is_available = False
            
        # Preis aus Struktur
        price_elem = product_elem.select_one('.price, .product-price, .current-price')
        price = price_elem.text.strip() if price_elem else 'Preis nicht verfügbar'
        
        if title or is_available is not None:
            return {
                'title': title,
                'price': price,
                'available': is_available
            }
    
    return None

def find_product_in_state(state_data, url):
    """
    Sucht in einem komplexen JS-State-Objekt nach Produktdaten
    
    :param state_data: JSON-Objekt des State
    :param url: URL zur Identifikation des richtigen Produkts
    :return: Produktdaten oder None
    """
    # Extrahiere Produkt-ID aus URL wenn möglich
    product_id_match = re.search(r'p(\d+)$', url)
    product_id = product_id_match.group(1) if product_id_match else None
    
    # Rekursive Hilfsfunktion zum Durchsuchen des State
    def search_product(obj, product_id):
        if isinstance(obj, dict):
            # Prüfe, ob das aktuelle Objekt ein Produkt sein könnte
            if 'id' in obj and 'title' in obj and ('available' in obj or 'variants' in obj):
                # Prüfe auf Übereinstimmung mit der Produkt-ID wenn vorhanden
                if product_id and str(obj.get('id')) == product_id:
                    return {
                        'title': obj.get('title', ''),
                        'price': obj.get('price', 'Preis nicht verfügbar'),
                        'available': obj.get('available', False)
                    }
                # Wenn keine ID-Übereinstimmung nötig ist, nehme das erste gute Produkt
                if not product_id:
                    return {
                        'title': obj.get('title', ''),
                        'price': obj.get('price', 'Preis nicht verfügbar'),
                        'available': obj.get('available', False)
                    }
            
            # Rekursiv durch alle Attribute suchen
            for key, value in obj.items():
                result = search_product(value, product_id)
                if result:
                    return result
        
        elif isinstance(obj, list):
            # Rekursiv durch alle Elemente suchen
            for item in obj:
                result = search_product(item, product_id)
                if result:
                    return result
        
        return None
    
    return search_product(state_data, product_id)

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
    
    # Erster Buchstabe groß
    title = title.strip().capitalize()
    
    return title

def check_mighty_cards_availability_enhanced(soup, url):
    """
    Verbesserte Verfügbarkeitsprüfung speziell für Mighty-Cards
    
    :param soup: BeautifulSoup-Objekt der Produktseite
    :param url: URL der Produktseite
    :return: Verfügbarkeitsstatus (True/False)
    """
    # 1. Prüfe auf "Nicht verfügbar"-Meldung im Text
    if re.search(r'nicht\s+verf(ü|ue)gbar|ausverkauft', soup.get_text().lower()):
        return False
    
    # 2. Prüfe auf deaktivierte Add-to-Cart-Buttons
    add_to_cart = soup.select_one('button.add-to-cart, .btn-cart, [name="add"]')
    if add_to_cart and ('disabled' in add_to_cart.get('class', []) or add_to_cart.has_attr('disabled')):
        return False
    
    # 3. Prüfe auf "In den Warenkorb"-Text ohne Disabled-Status
    cart_button = soup.find('button', string=re.compile('in den warenkorb|add to cart', re.IGNORECASE))
    if cart_button and 'disabled' not in cart_button.get('class', []) and not cart_button.has_attr('disabled'):
        return True
    
    # 4. Prüfe auf Verfügbarkeits-Badges
    availability_badge = soup.select_one('.in-stock, .product-available, .available')
    if availability_badge:
        return True
    
    # 5. Prüfe auf Ausverkauft-Badges
    sold_out_badge = soup.select_one('.sold-out, .out-of-stock, .unavailable')
    if sold_out_badge:
        return False
    
    # 6. Fallback: Prüfe ob ein aktiver Kaufbutton vorhanden ist
    buy_button = soup.select_one('button:not([disabled]), .btn:not(.disabled)')
    if buy_button and ('cart' in buy_button.get_text().lower() or 'warenkorb' in buy_button.get_text().lower()):
        return True
    
    # 7. Wenn nichts Eindeutiges gefunden wurde, prüfe auf spezifische Meldungen
    page_text = soup.get_text().lower()
    if any(term in page_text for term in ['auf lager', 'lieferbar', 'in stock']):
        return True
    if any(term in page_text for term in ['ausverkauft', 'nicht verfügbar', 'out of stock']):
        return False
    
    # Standard-Fallback (konservativ): als nicht verfügbar behandeln bei Unsicherheit
    return False

def extract_price_from_page(soup):
    """
    Extrahiert den Preis mit verschiedenen Selektoren speziell für mighty-cards.de
    
    :param soup: BeautifulSoup-Objekt der Produktseite
    :return: Preis als String
    """
    # Versuche verschiedene Selektoren für den Preis
    price_selectors = [
        '.price', '.product-price', '.current-price', 
        '[itemprop="price"]', '[data-product-price]',
        '.price-item--regular', '.price-regular'
    ]
    
    for selector in price_selectors:
        price_elem = soup.select_one(selector)
        if price_elem:
            price_text = price_elem.text.strip()
            # Bereinige den Preis (entferne mehrfache Leerzeichen, etc.)
            price_text = re.sub(r'\s+', ' ', price_text)
            return price_text
    
    # Wenn keine strukturierten Preisdaten gefunden wurden, versuche Regex
    text = soup.get_text()
    price_patterns = [
        r'(\d+[,.]\d+)\s*€',  # 19,99 €
        r'(\d+[,.]\d+)\s*EUR',  # 19,99 EUR
        r'EUR\s*(\d+[,.]\d+)',  # EUR 19,99
        r'€\s*(\d+[,.]\d+)',  # € 19,99
    ]
    
    for pattern in price_patterns:
        match = re.search(pattern, text)
        if match:
            price = match.group(1)
            return f"{price}€"
    
    return "Preis nicht verfügbar"

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

def detect_mighty_cards_availability(soup, url):
    """
    Spezifische Verfügbarkeitserkennung für mighty-cards.de
    
    :param soup: BeautifulSoup-Objekt der Produktseite
    :param url: URL der Produktseite
    :return: Tuple (is_available, price, status_text)
    """
    # Preis extrahieren
    price = extract_price_from_page(soup)
    
    # Verfügbarkeitsprüfung mit erweiterter Logik
    is_available = check_mighty_cards_availability_enhanced(soup, url)
    
    # Status-Text generieren
    if is_available:
        status_text = "✅ Verfügbar"
    else:
        status_text = "❌ Ausverkauft"
        
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