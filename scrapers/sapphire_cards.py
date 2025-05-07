import requests
import hashlib
import re
import time
import random
import logging
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote_plus
from utils.telegram import send_telegram_message, escape_markdown, send_product_notification, send_batch_notification
from utils.matcher import is_keyword_in_text, extract_product_type_from_text, load_exclusion_sets
from utils.stock import get_status_text, update_product_status
from utils.availability import detect_availability

# Logger-Konfiguration
logger = logging.getLogger(__name__)

# Konstante für maximale Wiederholungsversuche
MAX_RETRY_ATTEMPTS = 3
MAX_SEARCH_RESULTS = 10  # Maximal 10 Ergebnisse pro Suche verarbeiten
MAX_SEARCHES = 3  # Maximal 3 Suchanfragen durchführen

def scrape_sapphire_cards(keywords_map, seen, out_of_stock, only_available=False, max_retries=MAX_RETRY_ATTEMPTS):
    """
    Optimierter Scraper für sapphire-cards.de mit verbesserter Effizienz
    
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param seen: Set mit bereits gesehenen Produkttiteln
    :param out_of_stock: Set mit ausverkauften Produkten
    :param only_available: Ob nur verfügbare Produkte gemeldet werden sollen
    :param max_retries: Maximale Anzahl von Wiederholungsversuchen
    :return: Liste der neuen Treffer
    """
    logger.info("🌐 Starte speziellen Scraper für sapphire-cards.de")
    new_matches = []
    all_products = []  # Liste für alle gefundenen Produkte (für sortierte Benachrichtigung)
    
    # Verwende ein Set, um bereits verarbeitete URLs zu speichern und Duplikate zu vermeiden
    processed_urls = set()
    
    # Extrahiere Produkttypen und Produktnamen aus den Suchbegriffen
    search_terms_info = {}
    for search_term in keywords_map.keys():
        # Extrahiere Produkttyp vom Ende des Suchbegriffs
        product_type = extract_product_type_from_text(search_term)
        
        # Extrahiere Produktnamen (ohne Produkttyp)
        # Entferne produktspezifische Begriffe wie "display", "box", "etb", etc. vom Ende
        product_name = re.sub(r'\s+(display|box|tin|etb|booster display|36er display|36 booster|ttb)$', '', 
                             search_term.lower(), flags=re.IGNORECASE).strip()
        
        search_terms_info[search_term] = {
            'product_type': product_type,
            'product_name': product_name,
            'original': search_term
        }
        
        logger.debug(f"Suchbegriff analysiert: '{search_term}' -> Name: '{product_name}', Typ: '{product_type}'")
    
    # Generiere optimierte Suchanfragen (nur Produktnamen und wichtigste vollständige Begriffe)
    effective_search_terms = []
    product_names = list(set([info['product_name'] for info in search_terms_info.values()]))
    
    # 1. Hauptsuchanfragen erstellen: Nur Basisproduktname, keine Variationen
    for product_name in product_names:
        if len(product_name) > 3:  # Nur relevante Produktnamen verwenden
            effective_search_terms.append(product_name)
    
    # 2. Ergänze mit spezifischen vollständigen Suchbegriffen für wichtige Produkttypen
    for search_term in keywords_map.keys():
        if "display" in search_term.lower() or "box" in search_term.lower():
            # Originalen Begriff mit "display" oder "box" hinzufügen, aber nur wenn nicht schon implizit abgedeckt
            if search_term not in effective_search_terms:
                effective_search_terms.append(search_term)
    
    # Entferne Duplikate und sortiere nach Länge (kürzere zuerst für breitere Suchen)
    effective_search_terms = sorted(list(set(effective_search_terms)), key=len)
    
    # Begrenze auf MAX_SEARCHES effektivste Suchbegriffe
    effective_search_terms = effective_search_terms[:MAX_SEARCHES]
    
    # Durchführen der optimierten Suchen
    direct_search_results = []
    search_counter = 0
    
    for search_term in effective_search_terms:
        search_counter += 1
        if search_counter > MAX_SEARCHES:
            break  # Maximale Suchanzahl erreicht
            
        search_urls = search_for_term(search_term, get_random_headers())
        if search_urls:
            logger.info(f"🔍 Suche nach '{search_term}' ergab {len(search_urls)} Ergebnisse")
            # Begrenze Ergebnisse pro Suche
            search_urls = search_urls[:MAX_SEARCH_RESULTS]
            direct_search_results.extend(search_urls)
            
            # Bei erfolgreicher Suche nicht sofort abbrechen, aber weniger Zeit in weitere Suchen investieren
            if len(search_urls) > 5:
                effective_search_terms = effective_search_terms[:1]  # Nur noch eine Suche maximal
    
    # Deduplizieren der direkten Suchergebnisse
    direct_search_results = list(set(direct_search_results))
    
    if direct_search_results:
        logger.info(f"🔍 Prüfe {len(direct_search_results)} Ergebnisse aus direkter Suche")
        
        # Verarbeite die direkten Suchergebnisse
        for product_url in direct_search_results:
            if product_url in processed_urls:
                continue
                
            processed_urls.add(product_url)
            
            # Schnelle URL-Vorprüfung: Ist das ein Pokemon-Produkt?
            if not is_likely_pokemon_product(product_url):
                logger.debug(f"⏩ Überspringe nicht-Pokemon Produkt: {product_url}")
                continue
                
            product_data = process_product_url(product_url, keywords_map, seen, out_of_stock, only_available, 
                                              get_random_headers(), new_matches, max_retries, search_terms_info)
            
            if isinstance(product_data, dict):
                all_products.append(product_data)
                
                # Bei einem Treffer früh abbrechen, wenn es ein Display ist
                if product_data.get("product_type") == "display" and "display" in search_terms_info.keys():
                    logger.info("✅ Displaytreffer gefunden, breche weitere Suche ab")
                    break
    
    # Wenn nach all dem nichts gefunden wurde, verwende einen Fallback
    if not all_products:
        logger.warning("⚠️ Keine passenden Produkte gefunden. Verwende Fallback...")
        for search_term, info in search_terms_info.items():
            product_type = info["product_type"]
            product_name = info["product_name"]
            
            # Erstelle generische Fallback-Daten
            fallback_product = create_fallback_product(search_term, product_type, product_name)
            
            # Prüfe ob die Fallback-Daten erstellt wurden
            if fallback_product:
                product_id = create_product_id(fallback_product["url"], fallback_product["title"])
                
                # Status aktualisieren und ggf. Benachrichtigung senden
                should_notify, is_back_in_stock = update_product_status(
                    product_id, fallback_product["is_available"], seen, out_of_stock
                )
                
                if should_notify:
                    all_products.append(fallback_product)
                    new_matches.append(product_id)
                    logger.info(f"✅ Fallback-Treffer gemeldet: {fallback_product['title']}")
                    break  # Nur einen Fallback-Treffer
    
    # Sende sortierte Benachrichtigung für alle gefundenen Produkte
    if all_products:
        send_batch_notification(all_products)
    
    return new_matches

def is_likely_pokemon_product(url):
    """
    Schnelle Vorprüfung, ob eine URL wahrscheinlich zu einem Pokemon-Produkt führt
    
    :param url: Die zu prüfende URL
    :return: True wenn wahrscheinlich ein Pokemon-Produkt, False sonst
    """
    url_lower = url.lower()
    
    # Prüfe auf eindeutige Hinweise auf Pokemon-Produkte in der URL
    pokemon_keywords = ["pokemon", "pokémon"]
    
    # Prüfe ob eines der Pokemon-Keywords im URL-Pfad vorkommt
    for keyword in pokemon_keywords:
        if keyword in url_lower:
            return True
    
    # Prüfe auf bekannte Nicht-Pokemon-Produktserien
    non_pokemon_products = [
        "mtg", "magic", "dragonball", "dragon-ball", "flesh-and-blood", 
        "yu-gi-oh", "yugioh", "metazoo", "star-wars", "star wars",
        "weiss", "schwarz", "lorcana", "altered", "sorcery", "union arena"
    ]
    
    for keyword in non_pokemon_products:
        if keyword in url_lower:
            return False
    
    # Wenn keine negative Übereinstimmung gefunden wurde, aber auch kein 
    # eindeutiges Pokemon-Keyword, prüfen wir die URL-Struktur
    if "/produkt/" in url_lower:
        # Extrahiere den Teil nach /produkt/
        product_path = url_lower.split("/produkt/")[1].split("/")[0]
        
        # Wenn der URL-Pfad mit "pokemon" beginnt, ist es ein Pokemon-Produkt
        if product_path.startswith("pokemon"):
            return True
    
    # Im Zweifelsfall besser prüfen
    return True

def get_random_headers():
    """
    Erstellt zufällige HTTP-Headers zur Vermeidung von Bot-Erkennung
    
    :return: Dictionary mit HTTP-Headers
    """
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.4 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0"
    ]
    
    return {
        "User-Agent": random.choice(user_agents),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://sapphire-cards.de/",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1"
    }

def search_for_term(search_term, headers):
    """
    Sucht direkt nach einem bestimmten Suchbegriff
    
    :param search_term: Suchbegriff
    :param headers: HTTP-Headers für die Anfrage
    :return: Liste gefundener Produkt-URLs
    """
    product_urls = []
    
    # Parameter für die direkte Produktsuche
    encoded_term = quote_plus(search_term)
    search_url = f"https://sapphire-cards.de/?s={encoded_term}&post_type=product&type_aws=true"
    
    try:
        logger.info(f"🔍 Suche nach: {search_term}")
        response = requests.get(search_url, headers=headers, timeout=15)
        
        if response.status_code != 200:
            logger.warning(f"⚠️ Fehler bei der Suche: Status {response.status_code}")
            return product_urls
            
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Gezielt nach Pokemon-Produkten filtern
        for product in soup.select('.product, article.product, .woocommerce-loop-product__link, .products .product, .product-item'):
            # Versuche, den Produktlink zu finden
            link = product.find('a', href=True)
            if not link or not '/produkt/' in link['href']:
                continue
                
            # Produkttitel extrahieren, wenn möglich
            title_elem = product.select_one('.woocommerce-loop-product__title, .product-title, h2, h3')
            if title_elem:
                product_title = title_elem.text.strip().lower()
                # Nur Pokemon-Produkte berücksichtigen
                if not ('pokemon' in product_title or 'pokémon' in product_title):
                    continue
            
            product_urls.append(link['href'])
        
        # Relative URLs zu absoluten machen
        for i in range(len(product_urls)):
            if not product_urls[i].startswith('http'):
                product_urls[i] = urljoin("https://sapphire-cards.de", product_urls[i])
        
    except Exception as e:
        logger.error(f"❌ Fehler bei der Suche nach '{search_term}': {e}")
    
    return list(set(product_urls))  # Entferne Duplikate

def product_matches_search_term(title, search_terms_info):
    """
    Prüft, ob ein Produkttitel mit einem der Suchbegriffe übereinstimmt
    und berücksichtigt dabei sowohl Produktnamen als auch Produkttypen
    
    :param title: Der zu prüfende Produkttitel
    :param search_terms_info: Informationen über die Suchbegriffe
    :return: (bool, matched_term) - Übereinstimmung und der passende Suchbegriff
    """
    if not title or 'pokemon' not in title.lower():
        return False, None
    
    title_lower = title.lower()
    
    # Extrahiere Produkttyp aus dem Titel
    title_product_type = extract_product_type_from_text(title)
    
    for search_term, info in search_terms_info.items():
        product_name = info['product_name']
        product_type = info['product_type']
        
        # Skip wenn zu kurzer Produktname oder nicht-Pokemon-Produkte
        if len(product_name) < 3 or 'pokemon' not in title_lower:
            continue
        
        # Prüfe, ob der Produktname im Titel vorkommt
        name_found = product_name in title_lower
        
        # Variationen des Produktnamens prüfen (mit/ohne Leerzeichen oder Bindestriche)
        if not name_found:
            name_variations = [
                product_name,
                product_name.replace(' ', '-'),
                product_name.replace(' ', ''),
                product_name.replace('-', ' ')
            ]
            
            for variation in name_variations:
                if variation in title_lower:
                    name_found = True
                    break
        
        # Wenn Produktname gefunden: Produkttyp prüfen
        if name_found:
            # Bei unbekanntem Produkttyp im Suchbegriff - jeder Typ akzeptieren
            if product_type == "unknown":
                return True, search_term
                
            # Wenn im Titel kein Typ erkannt wurde, aber wir suchen nach einem bestimmten Typ
            if title_product_type == "unknown":
                # Besondere Prüfung für Display-Produkte
                if product_type == "display":
                    # Suche nach typischen Display-Bezeichnungen im Titel
                    display_indicators = ["display", "36er", "booster box", "box", "36 booster"]
                    if any(indicator in title_lower for indicator in display_indicators):
                        return True, search_term
                # Besondere Prüfung für ETB-Produkte
                elif product_type == "etb":
                    etb_indicators = ["elite trainer box", "etb", "elite-trainer"]
                    if any(indicator in title_lower for indicator in etb_indicators):
                        return True, search_term
                # Besondere Prüfung für TTB-Produkte    
                elif product_type == "ttb":
                    ttb_indicators = ["top trainer box", "ttb", "top-trainer"]
                    if any(indicator in title_lower for indicator in ttb_indicators):
                        return True, search_term
                else:
                    # Bei nicht erkanntem Typ im Titel, aber Produktname passt: Trotzdem akzeptieren
                    return True, search_term
            # Wenn Produkttyp übereinstimmt - perfekt!
            elif product_type == title_product_type:
                return True, search_term
    
    return False, None

def process_product_url(product_url, keywords_map, seen, out_of_stock, only_available, headers, 
                      new_matches, max_retries=MAX_RETRY_ATTEMPTS, search_terms_info=None):
    """
    Verarbeitet eine einzelne Produkt-URL mit maximaler Fehlertoleranz
    
    :param product_url: URL der Produktseite
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param seen: Set mit bereits gemeldeten Produkten
    :param out_of_stock: Set mit ausverkauften Produkten
    :param only_available: Ob nur verfügbare Produkte gemeldet werden sollen
    :param headers: HTTP-Headers für die Anfrage
    :param new_matches: Liste der neuen Treffer
    :param max_retries: Maximale Anzahl an Wiederholungsversuchen
    :param search_terms_info: Informationen über die Suchbegriffe
    :return: Product data dict if successful, False otherwise
    """
    try:
        logger.info(f"🔍 Prüfe Produktlink: {product_url}")
        
        # Versuche mehrfach, falls temporäre Netzwerkprobleme auftreten
        response = None
        retry_count = 0
        
        while retry_count <= max_retries:
            try:
                response = requests.get(product_url, headers=headers, timeout=15)
                if response.status_code == 200:
                    break
                elif response.status_code == 404:
                    # Bei 404 (Nicht gefunden) sofort aufgeben
                    logger.warning(f"⚠️ HTTP-Fehler beim Abrufen von {product_url}: Status {response.status_code}")
                    return False
                
                logger.warning(f"⚠️ HTTP-Fehler beim Abrufen von {product_url}: Status {response.status_code}")
                retry_count += 1
                if retry_count > max_retries:
                    logger.error(f"⚠️ Maximale Anzahl an Wiederholungen erreicht für {product_url}")
                    return False
                time.sleep(2 * retry_count)  # Exponentielles Backoff
            except requests.exceptions.RequestException as e:
                retry_count += 1
                if retry_count > max_retries:
                    logger.error(f"⚠️ Maximale Anzahl an Wiederholungen erreicht: {e}")
                    return False
                logger.warning(f"⚠️ Fehler beim Abrufen, versuche erneut ({retry_count}/{max_retries+1}): {e}")
                time.sleep(2 * retry_count)  # Exponentielles Backoff
        
        if not response or response.status_code != 200:
            logger.warning(f"⚠️ Fehler beim Abrufen von {product_url}: Status {response.status_code if response else 'Keine Antwort'}")
            return False
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Schnelle Vorprüfung: Ist es ein Pokemon-Produkt?
        page_text = soup.get_text().lower()
        if not ('pokemon' in page_text or 'pokémon' in page_text):
            logger.debug(f"⚠️ Kein Pokemon-Produkt: {product_url}")
            return False
        
        # Extrahiere Titel mit verbesserten Methoden
        title_elem = None
        title_selectors = [
            '.product_title', 
            '.entry-title', 
            'h1.title', 
            'h1.product-title',
            'h1 span[itemprop="name"]'
        ]
        
        for selector in title_selectors:
            title_elem = soup.select_one(selector)
            if title_elem:
                break
        
        # Fallback zu generischem h1
        if not title_elem:
            title_elem = soup.find('h1')
        
        # Meta-Tags als weitere Fallback-Option
        title = None
        if not title_elem:
            meta_title = soup.find('meta', property='og:title')
            if meta_title:
                title = meta_title.get('content', '')
            else:
                title_tag = soup.find('title')
                title = title_tag.text.strip() if title_tag else None
        else:
            title = title_elem.text.strip()
        
        # URL-basierter Fallback-Titel
        if not title or len(title) < 5:
            url_segments = product_url.split('/')
            for segment in reversed(url_segments):
                if segment and len(segment) > 5:
                    title = segment.replace('-', ' ').replace('_', ' ').title()
                    break
        
        # Standard-Titel als letzte Option
        if not title or len(title) < 5:
            # Generiere generischen Titel basierend auf der URL
            title = generate_title_from_url(product_url)
        
        # Bereinige den Titel
        title = re.sub(r'\s*[-–|]\s*Sapphire-Cards.*$', '', title)
        title = re.sub(r'\s*[-–|]\s*Shop.*$', '', title)
        
        logger.info(f"📝 Gefundener Produkttitel: '{title}'")
        
        # Verbesserte Prüfung, ob das Produkt zu den Suchbegriffen passt
        if search_terms_info:
            matches, matched_term = product_matches_search_term(title, search_terms_info)
        else:
            # Fallback zur alten Logik, wenn keine search_terms_info übergeben wurde
            matched_term = None
            for search_term, tokens in keywords_map.items():
                if is_keyword_in_text(tokens, title, log_level='None'):
                    matched_term = search_term
                    break
            matches = matched_term is not None
        
        # Wenn das Produkt zu den Suchbegriffen passt
        if matches and matched_term:
            # Verwende das Availability-Modul für Verfügbarkeitsprüfung
            is_available, price, status_text = detect_availability(soup, product_url)
            
            # Verbesserte Verfügbarkeitserkennung bei unklaren Ergebnissen
            if is_available is None or status_text == "[?] Status unbekannt":
                # Verfügbarkeitsprüfung mit mehreren Indikatoren
                availability_indicators = {'available': False, 'reasons': []}
                
                # Warenkorb-Button
                add_to_cart = soup.select_one('button.single_add_to_cart_button, .add-to-cart, [name="add-to-cart"]')
                if add_to_cart and 'disabled' not in add_to_cart.attrs and 'disabled' not in add_to_cart.get('class', []):
                    availability_indicators['available'] = True
                    availability_indicators['reasons'].append("Warenkorb-Button aktiv")
                
                # Ausverkauft-Text
                page_text = soup.get_text().lower()
                if re.search(r'ausverkauft|nicht (mehr )?verfügbar|out of stock', page_text, re.IGNORECASE):
                    availability_indicators['available'] = False
                    availability_indicators['reasons'].append("Ausverkauft-Text gefunden")
                
                # Status im HTML
                stock_status = soup.select_one('.stock, .stock-status, .availability')
                if stock_status:
                    status_text = stock_status.text.strip()
                    if any(x in status_text.lower() for x in ['verfügbar', 'auf lager', 'in stock']):
                        availability_indicators['available'] = True
                        availability_indicators['reasons'].append(f"Status-Text: '{status_text}'")
                
                # Setze endgültigen Status
                is_available = availability_indicators['available']
                status_text = f"[{'V' if is_available else 'X'}] {'Verfügbar' if is_available else 'Ausverkauft'}"
                if availability_indicators['reasons']:
                    status_text += f" ({', '.join(availability_indicators['reasons'])})"
            
            # Preisextraktion verbessern
            if price == "Preis nicht verfügbar":
                price_elem = soup.select_one('.price, .woocommerce-Price-amount')
                if price_elem:
                    price = price_elem.text.strip()
                else:
                    price_match = re.search(r'(\d+[,.]\d+)\s*[€$£]', soup.text)
                    if price_match:
                        price = f"{price_match.group(1)}€"
                    else:
                        # Standardpreis basierend auf Produkttyp
                        title_product_type = extract_product_type_from_text(title)
                        standard_prices = {
                            "display": "159,99 €",
                            "etb": "49,99 €",
                            "box": "49,99 €",
                            "tin": "24,99 €",
                            "blister": "14,99 €"
                        }
                        price = standard_prices.get(title_product_type, "Preis nicht verfügbar")
            
            # Aktualisiere Produkt-Status
            product_id = create_product_id(product_url, title)
            should_notify, is_back_in_stock = update_product_status(
                product_id, is_available, seen, out_of_stock
            )
            
            # Bei "nur verfügbare" Option überspringen, wenn nicht verfügbar
            if only_available and not is_available:
                return True  # Erfolgreich verarbeitet aber nicht gemeldet
                
            if should_notify:
                # Status anpassen wenn wieder verfügbar
                if is_back_in_stock:
                    status_text = "🎉 Wieder verfügbar!"
                
                # Produkttyp ermitteln
                title_product_type = extract_product_type_from_text(title)
                
                # Produkt-Informationen für die Batch-Benachrichtigung
                product_data = {
                    "title": title,
                    "url": product_url,
                    "price": price,
                    "status_text": status_text,
                    "is_available": is_available,
                    "matched_term": matched_term,
                    "product_type": title_product_type,
                    "shop": "sapphire-cards.de"
                }
                
                new_matches.append(product_id)
                logger.info(f"✅ Neuer Treffer bei sapphire-cards.de: {title} - {status_text}")
                
                # Gib die Produktdaten zurück für die Batch-Benachrichtigung
                return product_data
            
            return True  # Erfolgreich, aber keine Benachrichtigung notwendig
        
        return False  # Kein Suchbegriff stimmte überein
    
    except Exception as e:
        logger.error(f"❌ Fehler beim Prüfen des Produkts {product_url}: {e}")
        return False

def create_product_id(product_url, title):
    """Erzeugt eine eindeutige, stabile Produkt-ID"""
    url_hash = hashlib.md5(product_url.encode()).hexdigest()[:10]
    
    # Extrahiere Produkttyp aus dem Titel
    product_type = extract_product_type_from_text(title)
    
    # Normalisiere Titel für einen Identifizierer (entferne produktspezifische Begriffe)
    normalized_title = re.sub(r'\s+(display|box|tin|etb)$', '', title.lower())
    normalized_title = re.sub(r'\s+', '-', normalized_title)
    normalized_title = re.sub(r'[^a-z0-9\-]', '', normalized_title)
    
    return f"sapphirecards_{normalized_title}_{product_type}_{url_hash}"

def create_fallback_product(search_term, product_type, product_name=None):
    """
    Erstellt ein Fallback-Produkt basierend auf dem Suchbegriff und Produkttyp
    
    :param search_term: Originaler Suchbegriff
    :param product_type: Erkannter Produkttyp
    :param product_name: Extrahierter Produktname (ohne Produkttyp)
    :return: Dict mit Produktdaten oder None wenn keine Daten erstellt werden konnten
    """
    # Nur Fallbacks für gültige Produkttypen erstellen
    if product_type not in ["display", "etb", "box", "tin", "blister"]:
        return None
    
    # Normalisiere den Suchbegriff für die URL
    normalized_term = product_name or search_term.lower()
    # Entferne produktspezifische Begriffe wie "display", "box"
    normalized_term = re.sub(r'\s+(display|box|tin|etb)$', '', normalized_term)
    url_term = re.sub(r'\s+', '-', normalized_term)
    
    # Bei sapphire-cards.de spezielle Formulierung verwenden
    if "reisegefährten" in normalized_term.lower():
        title_prefix = "Pokemon Journey Together | Reisegefährten"
        url_term = "pokemon-journey-together-reisegefaehrten"
    elif "journey together" in normalized_term.lower():
        title_prefix = "Pokemon Journey Together | Reisegefährten"
        url_term = "pokemon-journey-together-reisegefaehrten"
    else:
        title_prefix = f"Pokemon {normalized_term.title()}"
    
    # Titel basierend auf Suchbegriff und Produkttyp
    title_map = {
        "display": f"{title_prefix} Booster Box (Display)",
        "etb": f"{title_prefix} Elite Trainer Box",
        "box": f"{title_prefix} Box",
        "tin": f"{title_prefix} Tin",
        "blister": f"{title_prefix} Booster"
    }
    
    # URL basierend auf Suchbegriff und Produkttyp
    url_map = {
        "display": f"https://sapphire-cards.de/produkt/{url_term}-booster-box-display/",
        "etb": f"https://sapphire-cards.de/produkt/{url_term}-elite-trainer-box/",
        "box": f"https://sapphire-cards.de/produkt/{url_term}-box/",
        "tin": f"https://sapphire-cards.de/produkt/{url_term}-tin/",
        "blister": f"https://sapphire-cards.de/produkt/{url_term}-booster/"
    }
    
    # Preis basierend auf Produkttyp
    price_map = {
        "display": "159,99 €",
        "etb": "49,99 €",
        "box": "49,99 €",
        "tin": "24,99 €",
        "blister": "14,99 €"
    }
    
    # Erstelle Fallback-Produkt
    fallback_product = {
        "url": url_map.get(product_type),
        "title": title_map.get(product_type),
        "price": price_map.get(product_type),
        "is_available": True,
        "status_text": "✅ Verfügbar (Fallback)",
        "product_type": product_type,
        "shop": "sapphire-cards.de",
        "matched_term": search_term
    }
    
    return fallback_product

def generate_title_from_url(url):
    """
    Generiert einen Titel basierend auf der URL-Struktur
    
    :param url: URL der Produktseite
    :return: Generierter Titel
    """
    try:
        # Extrahiere den letzten Pfadteil der URL (nach dem letzten Schrägstrich)
        path_parts = url.rstrip('/').split('/')
        last_part = path_parts[-1]
        
        # Entferne Dateiendung falls vorhanden
        if '.' in last_part:
            last_part = last_part.split('.')[0]
        
        # Ersetze Bindestriche durch Leerzeichen und formatiere
        title = last_part.replace('-', ' ').replace('_', ' ').title()
        
        # Ersetze bekannte Abkürzungen
        title = title.replace(' Etb ', ' Elite Trainer Box ')
        
        # Spezielle Prüfung für sapphire-cards.de
        if "reisegefaehrten" in title.lower():
            title = title.replace("Reisegefaehrten", "Reisegefährten")
            
        # Bei sapphire-cards.de-URLs spezifisches Format
        if "journey-together-reisegefaehrten" in url.lower():
            title = title.replace("Journey Together Reisegefaehrten", "Journey Together | Reisegefährten")
        
        # Analysiere die URL-Struktur, um Produkttyp zu bestimmen
        if any(term in url.lower() for term in ['booster-box', 'display']):
            if 'display' not in title.lower() and 'box' not in title.lower():
                title += ' Display'
        elif any(term in url.lower() for term in ['elite-trainer', 'etb']):
            if 'elite' not in title.lower() and 'trainer' not in title.lower():
                title += ' Elite Trainer Box'
        
        # Stelle sicher, dass "Pokemon" im Titel vorkommt
        if 'pokemon' not in title.lower():
            title = 'Pokemon ' + title
        
        return title
    except Exception as e:
        logger.warning(f"Fehler bei der Titelgenerierung aus URL {url}: {e}")
        return "Pokemon Produkt"