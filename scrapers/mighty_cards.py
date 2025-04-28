import requests
import logging
import re
import time
import json
import hashlib
import random
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote_plus, urlparse
from utils.matcher import is_keyword_in_text, extract_product_type_from_text
from utils.stock import get_status_text, update_product_status
from utils.availability import detect_availability

# Logger konfigurieren
logger = logging.getLogger(__name__)

# Konstanten
ECWID_STORE_ID = "100312571"
ECWID_BASE_URL = "https://app.ecwid.com"
MAX_RETRIES = 3
TIMEOUT = 15  # Erhöht von 10 auf 15 Sekunden
REQUEST_DELAY = 0.5  # Delay zwischen Anfragen

# Cache für 404-URLs, um sie später erneut zu überprüfen
_404_cache = {}
# Maximale Lebenszeit eines 404-Eintrags im Cache (in Sekunden)
_404_CACHE_TTL = 24 * 3600  # 24 Stunden

def scrape_mighty_cards(keywords_map, seen, out_of_stock, only_available=False, min_price=None, max_price=None):
    """
    Generalisierter Scraper für mighty-cards.de, der flexibel mit allen Produkten aus der products.txt umgehen kann
    
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param seen: Set mit bereits gesehenen Produkttiteln
    :param out_of_stock: Set mit ausverkauften Produkten
    :param only_available: Ob nur verfügbare Produkte gemeldet werden sollen
    :param min_price: Minimaler Preis für Produktbenachrichtigungen
    :param max_price: Maximaler Preis für Produktbenachrichtigungen
    :return: Liste der neuen Treffer
    """
    logger.info("🌐 Starte generalisierten Scraper für mighty-cards.de")
    new_matches = []
    all_products = []
    found_product_ids = set()
    
    # User-Agent-Rotation für bessere Stabilität
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15"
    ]
    
    headers = {
        "User-Agent": random.choice(user_agents),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "de,en-US;q=0.7,en;q=0.3",
        "DNT": "1",
        "Connection": "keep-alive",
        "Referer": "https://www.mighty-cards.de/",
        "Upgrade-Insecure-Requests": "1"
    }
    
    # Extrahiere Suchbegriffe für spätere Verwendung
    search_terms = list(keywords_map.keys())
    logger.info(f"🔍 Suche nach folgenden Suchbegriffen: {search_terms}")
    
    # 1. Überprüfe, ob es Einträge im 404-Cache gibt, die neu überprüft werden sollten
    logger.info("🔍 Überprüfe vorherige 404-URLs auf neue Produkte")
    current_time = time.time()
    recheck_urls = []
    
    # Bereinige abgelaufene Einträge aus dem 404-Cache
    for url, timestamp in list(_404_cache.items()):
        if current_time - timestamp > _404_CACHE_TTL:
            del _404_cache[url]
        else:
            recheck_urls.append(url)
    
    # Versuche, vorherige 404-URLs erneut zu überprüfen
    for url in recheck_urls:
        product_data = process_mighty_cards_product(url, keywords_map, seen, out_of_stock, only_available, headers, min_price, max_price)
        if product_data and isinstance(product_data, dict):
            product_id = create_product_id(product_data["title"])
            if product_id not in found_product_ids:
                # Produkt ist nun verfügbar!
                all_products.append(product_data)
                new_matches.append(product_id)
                found_product_ids.add(product_id)
                logger.info(f"✅ Vormals 404-URL ist jetzt verfügbar: {product_data['title']} - {product_data['status_text']}")
                # Entferne URL aus 404-Cache
                if url in _404_cache:
                    del _404_cache[url]
        time.sleep(REQUEST_DELAY)
    
    # 2. Durchsuche Vorbestellungs-Kategorie
    logger.info("🔍 Durchsuche Vorbestellungen-Kategorie")
    preorder_urls = [
        "https://www.mighty-cards.de/shop/Vorbestellung-c166467816/",
        "https://www.mighty-cards.de/vorbestellungen/",
        "https://www.mighty-cards.de/shop/Neuheiten-c165819789/",
        "https://www.mighty-cards.de/neu/"
    ]
    
    for preorder_url in preorder_urls:
        try:
            response = requests.get(preorder_url, headers=headers, timeout=TIMEOUT)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")
                
                # Alle Links in der Kategorie finden
                links = soup.find_all("a", href=True)
                for link in links:
                    href = link["href"]
                    if "/shop/" in href and "p" in href.split('/')[-1]:
                        product_url = urljoin("https://www.mighty-cards.de", href)
                        
                        # Prüfe, ob die URL für unsere Suchbegriffe relevant sein könnte
                        link_text = link.get_text().lower().strip()
                        if "pokemon" in link_text or any(term.lower() in link_text for term in search_terms):
                            if product_url not in found_product_ids:
                                product_data = process_mighty_cards_product(
                                    product_url, keywords_map, seen, out_of_stock, only_available, headers, min_price, max_price
                                )
                                
                                if product_data and isinstance(product_data, dict):
                                    product_id = create_product_id(product_data["title"])
                                    if product_id not in found_product_ids:
                                        all_products.append(product_data)
                                        new_matches.append(product_id)
                                        found_product_ids.add(product_id)
                                        logger.info(f"✅ Gefunden in Vorbestellungen: {product_data['title']} - {product_data['status_text']}")
                            
                            # Kleine Pause zwischen Anfragen
                            time.sleep(REQUEST_DELAY)
        except Exception as e:
            logger.warning(f"⚠️ Fehler beim Abrufen von {preorder_url}: {e}")
    
    # 3. Suche mit den genauen Suchbegriffen aus products.txt
    logger.info("🔍 Verwende Suchfunktion mit Suchbegriffen aus products.txt")
    
    # Verwende alle Suchbegriffe, nicht nur hardcodierte
    for search_term in search_terms:
        # Generiere potenzielle URLs basierend auf dem Suchbegriff
        potential_urls = generate_potential_urls(search_term)
        
        # Versuche zuerst, direkt spezifische Produkt-URLs aufzurufen
        for potential_url in potential_urls:
            if potential_url not in found_product_ids:
                product_data = process_mighty_cards_product(
                    potential_url, keywords_map, seen, out_of_stock, only_available, headers, min_price, max_price
                )
                
                if product_data and isinstance(product_data, dict):
                    product_id = create_product_id(product_data["title"])
                    if product_id not in found_product_ids:
                        all_products.append(product_data)
                        new_matches.append(product_id)
                        found_product_ids.add(product_id)
                        logger.info(f"✅ Gefunden durch generierte URL: {product_data['title']} - {product_data['status_text']}")
                
                time.sleep(REQUEST_DELAY)
        
        # Verwende die Suchfunktion des Shops
        search_url = f"https://www.mighty-cards.de/shop/search?keyword={quote_plus(search_term)}"
        
        try:
            response = requests.get(search_url, headers=headers, timeout=TIMEOUT)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")
                
                # Produktkarten suchen
                product_elems = soup.select('.grid-product, .product-card, .product-item')
                if not product_elems:
                    # Fallback auf alle Links
                    links = soup.find_all("a", href=True)
                    
                    for link in links:
                        href = link["href"]
                        if "/shop/" in href and "p" in href.split('/')[-1]:
                            product_url = urljoin("https://www.mighty-cards.de", href)
                            
                            if product_url not in found_product_ids:
                                product_data = process_mighty_cards_product(
                                    product_url, keywords_map, seen, out_of_stock, only_available, headers, min_price, max_price
                                )
                                
                                if product_data and isinstance(product_data, dict):
                                    product_id = create_product_id(product_data["title"])
                                    if product_id not in found_product_ids:
                                        all_products.append(product_data)
                                        new_matches.append(product_id)
                                        found_product_ids.add(product_id)
                                        logger.info(f"✅ Gefunden durch Suche: {product_data['title']} - {product_data['status_text']}")
                            
                            # Kleine Pause
                            time.sleep(REQUEST_DELAY)
                else:
                    # Verarbeite gefundene Produktkarten
                    for product in product_elems:
                        link = product.find("a", href=True)
                        if link and link.has_attr("href"):
                            product_url = urljoin("https://www.mighty-cards.de", link["href"])
                            
                            if product_url not in found_product_ids:
                                product_data = process_mighty_cards_product(
                                    product_url, keywords_map, seen, out_of_stock, only_available, headers, min_price, max_price
                                )
                                
                                if product_data and isinstance(product_data, dict):
                                    product_id = create_product_id(product_data["title"])
                                    if product_id not in found_product_ids:
                                        all_products.append(product_data)
                                        new_matches.append(product_id)
                                        found_product_ids.add(product_id)
                                        logger.info(f"✅ Gefunden durch Suche: {product_data['title']} - {product_data['status_text']}")
                            
                            # Kleine Pause
                            time.sleep(REQUEST_DELAY)
        except Exception as e:
            logger.warning(f"⚠️ Fehler bei der Suche nach '{search_term}': {e}")
    
    # 4. Durchsuche allgemeine Pokémon Kategorien
    if len(all_products) < 2:  # Wenn bisher weniger als 2 Produkte gefunden wurden
        logger.info("🔍 Durchsuche Pokémon-Kategorien")
        category_urls = [
            "https://www.mighty-cards.de/shop/Pokemon-c165637849/",
            "https://www.mighty-cards.de/shop/Displays-c165638577/",
            "https://www.mighty-cards.de/pokemon/"
        ]
        
        for category_url in category_urls:
            try:
                response = requests.get(category_url, headers=headers, timeout=TIMEOUT)
                
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, "html.parser")
                    
                    # Alle Links in der Kategorie finden
                    links = soup.find_all("a", href=True)
                    for link in links:
                        href = link["href"]
                        if "/shop/" in href and ("p" in href.split('/')[-1] or "c" in href.split('/')[-1]):
                            product_url = urljoin("https://www.mighty-cards.de", href)
                            link_text = link.get_text().lower().strip()
                            
                            # Prüfe, ob der Link zu unseren Suchbegriffen passt
                            for search_term in search_terms:
                                search_tokens = search_term.lower().split()
                                # Wenn mindestens zwei Tokens übereinstimmen oder "pokemon" + ein Token
                                if (sum(1 for token in search_tokens if token in link_text) >= 2 or 
                                    ("pokemon" in link_text and any(token in link_text for token in search_tokens))):
                                    
                                    if product_url not in found_product_ids:
                                        product_data = process_mighty_cards_product(
                                            product_url, keywords_map, seen, out_of_stock, only_available, headers, min_price, max_price
                                        )
                                        
                                        if product_data and isinstance(product_data, dict):
                                            product_id = create_product_id(product_data["title"])
                                            if product_id not in found_product_ids:
                                                all_products.append(product_data)
                                                new_matches.append(product_id)
                                                found_product_ids.add(product_id)
                                                logger.info(f"✅ Gefunden in Kategorie: {product_data['title']} - {product_data['status_text']}")
                                    
                                    # Kleine Pause zwischen Anfragen
                                    time.sleep(REQUEST_DELAY)
                                    break  # Wenn ein Suchbegriff übereinstimmt, prüfe nicht weitere
            except Exception as e:
                logger.warning(f"⚠️ Fehler beim Abrufen von {category_url}: {e}")
    
    # Sende Benachrichtigungen
    if all_products:
        from utils.telegram import send_batch_notification
        send_batch_notification(all_products)
    
    return new_matches

def generate_potential_urls(search_term):
    """
    Generiert potenzielle Produkt-URLs basierend auf einem Suchbegriff
    
    :param search_term: Suchbegriff aus products.txt
    :return: Liste mit möglichen URLs
    """
    base_url = "https://www.mighty-cards.de"
    urls = []
    
    # Bereinige den Suchbegriff für URL-Pfade
    clean_term = search_term.lower()
    clean_term = re.sub(r'[^a-z0-9äöüß\s]', '', clean_term)
    clean_term = re.sub(r'\s+', '-', clean_term)
    
    # Variationen für den Suchbegriff in URL-Form
    term_variations = [
        clean_term,
        clean_term.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss"),
        # Andere mögliche Namenskonventionen
        "-".join([word for word in clean_term.split('-') if len(word) > 2])
    ]
    
    # Generiere verschiedene URL-Muster
    for term in term_variations:
        # Direkte Produkt-URL-Muster
        urls.append(f"{base_url}/shop/{term.title()}-p")  # Nur Anfang der URL, wird später validiert
        
        # Kategorie-/Sammlungs-URL-Muster
        urls.append(f"{base_url}/shop/{term.title()}-c")
        urls.append(f"{base_url}/{term}/")
        
        # Andere mögliche URL-Muster von mighty-cards.de
        urls.append(f"{base_url}/shop/{term.title()}")
        urls.append(f"{base_url}/pokemon/{term}/")
    
    # Extrahiere wichtige Schlüsselwörter (z.B. Produktnamen ohne "display", "booster", etc.)
    words = clean_term.split('-')
    key_words = [w for w in words if len(w) > 3 and w not in ["display", "booster", "pack", "box"]]
    
    if key_words:
        # URLs mit den wichtigsten Wörtern
        main_term = "-".join(key_words)
        urls.append(f"{base_url}/shop/{main_term.title()}-p")
        urls.append(f"{base_url}/pokemon/{main_term}/")
    
    # Entferne Duplikate und gib eindeutige URLs zurück
    return list(set(urls))

def process_mighty_cards_product(product_url, keywords_map, seen, out_of_stock, only_available, headers, min_price=None, max_price=None):
    """
    Verarbeitet eine einzelne Produktseite mit verbesserter Fehlerbehandlung
    
    :param product_url: URL der Produktseite
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param seen: Set mit bereits gesehenen Produkttiteln
    :param out_of_stock: Set mit ausverkauften Produkten
    :param only_available: Ob nur verfügbare Produkte gemeldet werden sollen
    :param headers: HTTP-Headers für Anfragen
    :param min_price: Minimaler Preis für Produktbenachrichtigungen
    :param max_price: Maximaler Preis für Produktbenachrichtigungen
    :return: Produkt-Daten oder False bei Fehler/Nicht-Übereinstimmung
    """
    global _404_cache
    retry_count = 0
    max_retries = MAX_RETRIES
    
    while retry_count <= max_retries:
        try:
            logger.debug(f"🔍 Prüfe Produkt: {product_url}")
            
            response = requests.get(product_url, headers=headers, timeout=TIMEOUT)
            
            # Behandle 404-Status (Seite nicht gefunden) - könnte ein zukünftiges Produkt sein
            if response.status_code == 404:
                # Speichere URL im 404-Cache für spätere Überprüfung
                _404_cache[product_url] = time.time()
                logger.info(f"ℹ️ Produkt-URL existiert noch nicht (404): {product_url}")
                return False
                
            if response.status_code != 200:
                logger.warning(f"⚠️ Fehler beim Abrufen von {product_url}: Status {response.status_code}")
                return False
                
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Versuche JavaScript-Daten für strukturierte Informationen
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
                # HTML-basierte Extraktion
                title_elem = soup.find('h1', {'class': 'product-details__product-title'})
                if not title_elem:
                    title_elem = soup.find('h1')
                
                if not title_elem:
                    title = extract_title_from_url(product_url)
                    logger.info(f"📝 Generierter Titel aus URL: '{title}'")
                else:
                    title = title_elem.text.strip()
                
                # Korrigiere bekannte Tippfehler
                if "Togehter" in title:
                    title = title.replace("Togehter", "Together")
                
                # Extrahiere Preis
                price_elem = soup.find('span', {'class': 'details-product-price__value'})
                price = price_elem.text.strip() if price_elem else "Preis nicht verfügbar"
                
                # Preis-Filter anwenden
                price_value = extract_price_value(price)
                if price_value is not None:
                    if (min_price is not None and price_value < min_price) or (max_price is not None and price_value > max_price):
                        logger.info(f"⚠️ Produkt '{title}' mit Preis {price} liegt außerhalb des Preisbereichs ({min_price or 0}€ - {max_price or '∞'}€)")
                        return False
                
                # Verfügbarkeitsprüfung
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
                # Produkttyp aus dem Suchbegriff
                search_term_type = extract_product_type_from_text(search_term)
                
                # Bei Displays strikte Prüfung
                if search_term_type == "display" and title_product_type != "display":
                    continue
                    
                # Prüfe Übereinstimmung
                if is_keyword_in_text(tokens, title, log_level='None'):
                    matched_term = search_term
                    break
            
            # Wenn kein Match gefunden, mache eine weniger strenge Prüfung
            if not matched_term:
                for search_term, tokens in keywords_map.items():
                    # Weniger strenge Variante: Mindestens 50% der Tokens müssen übereinstimmen
                    title_tokens = re.sub(r'[^\w\s]', '', title.lower()).split()
                    common_words = set(title_tokens).intersection(set([t.lower() for t in tokens]))
                    
                    if len(common_words) / len(tokens) >= 0.5:  # 50% der Tokens stimmen überein
                        matched_term = search_term
                        logger.debug(f"🔍 Flexibles Matching für {title} mit {search_term} (Score: {len(common_words)}/{len(tokens)})")
                        break
            
            # Wenn immer noch kein Match, versuche URL-basiertes Matching als letzten Fallback
            if not matched_term:
                for search_term in keywords_map.keys():
                    # Normalisiere Begriffe für Vergleich
                    search_norm = search_term.lower().replace(" ", "").replace("-", "")
                    url_norm = product_url.lower().replace("-", "").replace("_", "")
                    
                    # Wenn der Suchbegriff ein wesentlicher Teil der URL ist
                    if search_norm in url_norm:
                        matched_term = search_term
                        logger.debug(f"🔍 URL-basiertes Matching für {product_url} mit {search_term}")
                        break
            
            # Wenn kein Match gefunden wurde, dieses Produkt überspringen
            if not matched_term:
                return False
            
            # Produkt-ID erstellen
            product_id = create_product_id(title)
            
            # Status überprüfen
            should_notify, is_back_in_stock = update_product_status(
                product_id, is_available, seen, out_of_stock
            )
            
            # Nur verfügbare Produkte bei entsprechender Option
            if only_available and not is_available:
                return False
            
            # Wenn keine Benachrichtigung gesendet werden soll
            if not should_notify:
                return True
            
            # Bei wieder verfügbaren Produkten
            if is_back_in_stock:
                status_text = "🎉 Wieder verfügbar!"
            
            # Prüfe, ob es ein Vorbestellprodukt ist
            is_preorder = False
            page_text = soup.get_text().lower()
            preorder_terms = ["vorbestellung", "pre-order", "preorder", "pre order", "erscheint am", "release", "kommt bald"]
            
            if any(term in page_text for term in preorder_terms):
                is_preorder = True
                # Hinweis zum Status hinzufügen, wenn es eine Vorbestellung ist
                if "✅" in status_text or "🎉" in status_text:
                    status_text = "🔮 Vorbestellbar"
            
            # Produkt-Informationen
            product_data = {
                "title": title,
                "url": product_url,
                "price": price,
                "status_text": status_text,
                "is_available": is_available,
                "is_preorder": is_preorder,
                "matched_term": matched_term,
                "product_type": title_product_type,
                "shop": "mighty-cards.de"
            }
            
            return product_data
                
        except requests.exceptions.Timeout:
            retry_count += 1
            logger.warning(f"⚠️ Timeout beim Abrufen von {product_url}. Versuch {retry_count}/{max_retries+1}")
            if retry_count <= max_retries:
                time.sleep(1 * retry_count)  # Progressives Backoff
            else:
                logger.error(f"❌ Maximale Anzahl an Versuchen erreicht für {product_url}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Fehler beim Verarbeiten des Produkts {product_url}: {e}")
            return False

def extract_js_product_data(soup, url):
    """
    Extrahiert Produktdaten aus JavaScript-Objekten auf der Seite
    
    :param soup: BeautifulSoup-Objekt der Produktseite
    :param url: URL der Produktseite
    :return: Dictionary mit Produktdaten oder None wenn keine gefunden
    """
    # JSON-LD Daten (strukturierte Daten)
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
    
    # Ecwid-spezifische Daten
    product_id_match = re.search(r'p(\d+)$', url)
    if product_id_match:
        product_id = product_id_match.group(1)
        
        for script in soup.find_all('script'):
            script_content = script.string
            if not script_content:
                continue
            
            # Suche nach dem spezifischen Produkt-ID
            product_js_match = re.search(rf'"id":\s*{product_id}.*?"name":\s*"([^"]+)"', script_content)
            if product_js_match:
                product_title = product_js_match.group(1)
                
                # Verfügbarkeitsinformationen
                available_match = re.search(rf'"id":\s*{product_id}.*?"inStock":\s*(true|false)', script_content)
                is_available = available_match and available_match.group(1) == 'true'
                
                # Preisinformationen
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
    Extrahiert einen sinnvollen Titel aus der URL-Struktur mit verbesserten Fallbacks
    
    :param url: URL der Produktseite
    :return: Extrahierter Titel
    """
    try:
        # Protokoll und Domain entfernen, um nur den Pfad zu erhalten
        path_parts = urlparse(url).path.strip('/').split('/')
        
        # Nur den letzten Teil betrachten (das letzte Segment des Pfads)
        if not path_parts:
            logger.warning(f"Keine Pfadteile in der URL gefunden: {url}")
            return "Unbekanntes Mighty-Cards Produkt"
            
        path = path_parts[-1]  # Letzter Teil des Pfads
        
        # Für URLs ohne -p Format (Kategorien), versuche vorherige Teile
        if not (path.endswith('.html') or '-p' in path or path.startswith('p')):
            for part in reversed(path_parts):
                if "pokemon" in part.lower() or len(part) > 5:
                    path = part
                    break
        
        # Entferne Parameter bei p12345 Endungen
        path = re.sub(r'-p\d+$', '', path)
        
        # Ersetze Bindestriche durch Leerzeichen
        title = path.replace('-', ' ')
        
        # Überprüfen ob der Titel leer ist
        if not title.strip():
            # Versuche erneut mit dem Kategorieteil
            if len(path_parts) > 1:
                title = path_parts[-2].replace('-', ' ')
                
        # Wenn immer noch leer, setze Standard-Titel
        if not title.strip():
            if "pokemon" in url.lower():
                title = "Pokemon TCG Produkt"
            else:
                title = "Mighty Cards Produkt"
        
        # Korrigiere bekannte Tippfehler
        if "Togehter" in title:
            title = title.replace("Togehter", "Together")
        
        # Erster Buchstabe groß
        title = title.strip().capitalize()
        
        return title
    except Exception as e:
        logger.warning(f"Fehler bei Titel-Extraktion aus URL {url}: {e}")
        # Standard-Fallback-Titel
        if "pokemon" in url.lower():
            return "Pokemon TCG Produkt"
        else:
            return "Mighty Cards Produkt"

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
    
    # Produkttyp ermitteln
    product_type = extract_product_type_from_text(title)
    
    # Serien-Code versuchen zu extrahieren
    series_code = "unknown"
    
    # Standardcodes wie SV09, KP09, etc.
    code_match = re.search(r'(?:sv|kp|op)(?:\s|-)?\d+', title_lower)
    if code_match:
        series_code = code_match.group(0).replace(" ", "").replace("-", "")
    else:
        # Bekannte Setnamen
        set_mapping = {
            "journey together": "sv09",
            "reisegefährten": "kp09",
            "destined rivals": "sv10",
            "ewige rivalen": "kp10",
            "hidden treasures": "sv11",
            "verborgene schätze": "kp11"
        }
        
        for set_name, code in set_mapping.items():
            if set_name in title_lower:
                series_code = code
                break
    
    # Hash aus Titel erstellen für eindeutige ID bei unbekannten Produkten
    if series_code == "unknown":
        clean_title = re.sub(r'[^\w]', '', title_lower)
        hash_part = hashlib.md5(clean_title.encode()).hexdigest()[:6]
        series_code = f"hash{hash_part}"
    
    # Erstelle eine strukturierte ID
    product_id = f"{base_id}_{series_code}_{product_type}_{language}"
    
    # Zusatzinformationen
    if "18er" in title_lower:
        product_id += "_18er"
    elif "36er" in title_lower:
        product_id += "_36er"
    
    return product_id

def clean_404_cache():
    """
    Bereinigt den 404-Cache von veralteten Einträgen
    
    :return: Anzahl der entfernten Einträge
    """
    global _404_cache
    if not _404_cache:
        return 0
        
    current_time = time.time()
    original_count = len(_404_cache)
    
    # Entferne Einträge, die älter als TTL sind
    _404_cache = {url: timestamp for url, timestamp in _404_cache.items() 
                 if current_time - timestamp < _404_CACHE_TTL}
    
    removed_count = original_count - len(_404_cache)
    if removed_count > 0:
        logger.info(f"🧹 404-Cache bereinigt: {removed_count} veraltete Einträge entfernt")
    
    return removed_count

def get_404_cache_stats():
    """
    Gibt Statistiken zum 404-Cache zurück
    
    :return: Dictionary mit Statistiken
    """
    current_time = time.time()
    
    stats = {
        "total_urls": len(_404_cache),
        "newest_entry": min([current_time - ts for ts in _404_cache.values()]) if _404_cache else None,
        "oldest_entry": max([current_time - ts for ts in _404_cache.values()]) if _404_cache else None,
        "avg_age": sum([current_time - ts for ts in _404_cache.values()]) / len(_404_cache) if _404_cache else None
    }
    
    return stats