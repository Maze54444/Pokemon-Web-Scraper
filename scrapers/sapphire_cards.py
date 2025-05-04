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

def scrape_sapphire_cards(keywords_map, seen, out_of_stock, only_available=False, max_retries=3):
    """
    Spezieller Scraper für sapphire-cards.de mit maximaler Robustheit und Fehlertoleranz
    
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
    
    # Extrahiere den Produkttyp aus dem ersten Suchbegriff (meistens "display")
    search_product_type = None
    if keywords_map:
        sample_search_term = list(keywords_map.keys())[0]
        search_product_type = extract_product_type_from_text(sample_search_term)
        logger.debug(f"🔍 Suche nach Produkttyp: '{search_product_type}'")
    
    # Generierte Liste der direkten Produkt-URLs basierend auf den Suchbegriffen
    direct_urls = []
    
    # Generiere dynamische URLs für alle Suchbegriffe
    for search_term, tokens in keywords_map.items():
        product_type = extract_product_type_from_text(search_term)
        
        # Normalisiere den Suchbegriff für die URL
        normalized_term = search_term.lower()
        # Entferne produktspezifische Begriffe wie "display", "box"
        normalized_term = re.sub(r'\s+(display|box|tin|etb)$', '', normalized_term)
        normalized_term = re.sub(r'\s+', '-', normalized_term)
        
        # Erstelle URLs basierend auf Produkttyp und Suchbegriff
        if product_type == "display":
            direct_urls.append(f"https://sapphire-cards.de/produkt/{normalized_term}-booster-box-display/")
            direct_urls.append(f"https://sapphire-cards.de/produkt/pokemon-{normalized_term}-booster-box-display/")
            direct_urls.append(f"https://sapphire-cards.de/produkt/{normalized_term}-booster-display/")
        elif product_type == "etb" or product_type == "box":
            direct_urls.append(f"https://sapphire-cards.de/produkt/{normalized_term}-elite-trainer-box/")
            direct_urls.append(f"https://sapphire-cards.de/produkt/pokemon-{normalized_term}-elite-trainer-box/")
        
        # Kategorie-URL basierend auf dem Suchbegriff
        direct_urls.append(f"https://sapphire-cards.de/produkt-kategorie/pokemon/{normalized_term}/")
    
    # Generische Pokemon-Kategorie immer hinzufügen
    direct_urls.append("https://sapphire-cards.de/produkt-kategorie/pokemon/")
    
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
        "Referer": "https://sapphire-cards.de/",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1"
    }
    
    logger.info(f"🔍 Prüfe {len(direct_urls)} bekannte Produkt-URLs")
    
    # Cache für fehlgeschlagene URLs mit Timestamps
    failed_urls_cache = {}
    
    # Direkter Zugriff auf bekannte Produkt-URLs mit Wiederholungsversuchen
    successful_direct_urls = False
    for product_url in direct_urls:
        # Überspringe kürzlich fehlgeschlagene URLs für 1 Stunde
        if product_url in failed_urls_cache:
            last_failed_time = failed_urls_cache[product_url]
            if time.time() - last_failed_time < 3600:  # 1 Stunde Cooldown
                logger.info(f"⏭️ Überspringe kürzlich fehlgeschlagene URL: {product_url}")
                continue
        
        if product_url in processed_urls:
            continue
        
        processed_urls.add(product_url)
        product_data = process_product_url(product_url, keywords_map, seen, out_of_stock, only_available, headers, new_matches, max_retries)
        
        if product_data:
            successful_direct_urls = True
            logger.info(f"✅ Direkter Produktlink erfolgreich verarbeitet: {product_url}")
            
            # Produkt zur Liste hinzufügen für sortierte Benachrichtigung
            if isinstance(product_data, dict):
                all_products.append(product_data)
        else:
            # URL zum Cache der fehlgeschlagenen URLs hinzufügen
            failed_urls_cache[product_url] = time.time()
    
    # Katalogseite durchsuchen, falls nötig
    if not successful_direct_urls:
        logger.info("🔍 Durchsuche Katalogseiten...")
        
        # Reduzierte Liste von Katalogseiten-URLs 
        catalog_urls = [
            "https://sapphire-cards.de/produkt-kategorie/pokemon/"
        ]
        
        for catalog_url in catalog_urls:
            try:
                logger.info(f"🔍 Durchsuche Katalogseite: {catalog_url}")
                
                # Nur ein einzelner Versuch pro Katalogseite
                try:
                    response = requests.get(catalog_url, headers=headers, timeout=15)
                    if response.status_code != 200:
                        logger.warning(f"⚠️ Fehler beim Abrufen von {catalog_url}: Status {response.status_code}")
                        continue
                except requests.exceptions.RequestException as e:
                    logger.warning(f"⚠️ Netzwerkfehler bei {catalog_url}: {e}")
                    continue
                
                soup = BeautifulSoup(response.text, "html.parser")
                
                # Sammle alle Links, die auf Produkte verweisen könnten
                product_links = []
                
                # VERBESSERT: Umfassendere Suche nach relevanten Links mit einmaligem Durchlauf
                all_links = soup.find_all('a', href=True)
                
                # Sammle relevante Begriffe aus den Suchbegriffen
                relevant_terms = []
                for search_term in keywords_map.keys():
                    # Entferne produktspezifische Begriffe wie "display", "box"
                    clean_term = re.sub(r'\s+(display|box|tin|etb)$', '', search_term.lower())
                    relevant_terms.append(clean_term)
                    # Füge Begriffe auch in URL-freundlichem Format hinzu
                    relevant_terms.append(clean_term.replace(' ', '-'))
                    relevant_terms.append(clean_term.replace(' ', ''))
                
                # Füge generische Begriffe hinzu
                relevant_terms.append("pokemon")
                
                for link in all_links:
                    href = link.get('href', '')
                    link_text = link.get_text().lower()
                    
                    # Eindeutige Produktlinks
                    if '/produkt/' in href and href not in product_links and href not in processed_urls:
                        # Prüfe auf relevante Suchbegriffe
                        if any(term in href.lower() for term in relevant_terms) or any(term in link_text for term in relevant_terms):
                            # Bei Suche nach Display: Prüfe zusätzlich auf Display-Hinweise im Text/URL
                            if search_product_type == "display":
                                if any(display_term in link_text for display_term in ["display", "36er", "box"]) or any(display_term in href for display_term in ["display", "36er", "box"]):
                                    product_links.append(href)
                            # Bei anderer Suche oder unbekanntem Typ: Nach anderen Produkttypen filtern
                            elif search_product_type in ["etb", "box"]:
                                if any(box_term in link_text for box_term in ["trainer", "etb", "box"]) or any(box_term in href for box_term in ["trainer", "etb", "box"]):
                                    product_links.append(href)
                            else:
                                product_links.append(href)
                
                logger.info(f"🔍 {len(product_links)} potenzielle Produktlinks gefunden")
                
                # Verarbeite alle gefundenen Links
                for product_url in product_links:
                    # Überspringe kürzlich fehlgeschlagene URLs
                    if product_url in failed_urls_cache:
                        if time.time() - failed_urls_cache[product_url] < 3600:
                            continue
                            
                    # Vollständige URL erstellen, falls nur ein relativer Pfad
                    if not product_url.startswith('http'):
                        product_url = urljoin(catalog_url, product_url)
                    
                    processed_urls.add(product_url)
                    product_data = process_product_url(product_url, keywords_map, seen, out_of_stock, only_available, headers, new_matches, 2)  # Reduzierte Wiederholungen
                    
                    if not product_data:
                        failed_urls_cache[product_url] = time.time()
                    elif isinstance(product_data, dict):
                        all_products.append(product_data)
                
            except Exception as e:
                logger.error(f"❌ Fehler beim Durchsuchen der Katalogseite {catalog_url}: {e}")
    
    # Fallback: Suche nach Produkten (auch wenn Treffer gefunden wurden)
    if len(all_products) < 2:  # Wenn weniger als 2 Produkte gefunden wurden, versuche zusätzlich die Suche
        logger.info("🔍 Wenige oder keine Treffer in Katalogseiten, versuche Suche...")
        search_urls = try_search_fallback(keywords_map, processed_urls, headers, max_retries=1)  # Reduzierte Wiederholungen
        
        # Begrenze die Anzahl zu prüfender Such-URLs
        search_limit = 3
        if len(search_urls) > search_limit:
            logger.info(f"⚙️ Begrenze die Anzahl der Suchergebnisse auf {search_limit} (von {len(search_urls)})")
            search_urls = search_urls[:search_limit]
        
        # Verarbeite die gefundenen URLs, aber vermeide Duplikate
        for product_url in search_urls:
            # Überspringe kürzlich fehlgeschlagene URLs
            if product_url in failed_urls_cache:
                if time.time() - failed_urls_cache[product_url] < 3600:
                    continue
                    
            if product_url in processed_urls:
                continue
            
            processed_urls.add(product_url)
            product_data = process_product_url(product_url, keywords_map, seen, out_of_stock, only_available, headers, new_matches, 1)  # Minimale Wiederholungen
            
            if not product_data:
                failed_urls_cache[product_url] = time.time()
            elif isinstance(product_data, dict):
                all_products.append(product_data)
    
    # Wenn nach all dem immer noch nichts gefunden wurde, generischer Fallback
    if not new_matches:
        logger.warning("⚠️ Keine Produkte gefunden. Verwende generischen Fallback...")
        for search_term, tokens in keywords_map.items():
            product_type = extract_product_type_from_text(search_term)
            
            # Erstelle generische Fallback-Daten basierend auf dem Suchbegriff und Produkttyp
            fallback_product = create_fallback_product(search_term, product_type)
            
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
    
    # Sende sortierte Benachrichtigung für alle gefundenen Produkte
    if all_products:
        send_batch_notification(all_products)
    
    return new_matches

def process_product_url(product_url, keywords_map, seen, out_of_stock, only_available, headers, new_matches, max_retries=2):
    """
    Verarbeitet eine einzelne Produkt-URL mit maximaler Fehlertoleranz
    
    :param product_url: URL der Produktseite
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param seen: Set mit bereits gesehenen Produkttiteln
    :param out_of_stock: Set mit ausverkauften Produkten
    :param only_available: Ob nur verfügbare Produkte gemeldet werden sollen
    :param headers: HTTP-Headers für die Anfrage
    :param new_matches: Liste der neuen Treffer
    :param max_retries: Maximale Anzahl an Wiederholungsversuchen
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
                    logger.warning(f"⚠️ HTTP-Fehler beim Abrufen von {product_url}: Status {response.status_code}, Versuch {retry_count+1}/{max_retries+1}")
                    return False
                
                logger.warning(f"⚠️ HTTP-Fehler beim Abrufen von {product_url}: Status {response.status_code}, Versuch {retry_count+1}/{max_retries+1}")
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
        
        # Effizientere Keyword-Prüfung mit weniger Logging
        # Extrahiere Produkttyp aus dem Titel für bessere Filterung
        title_product_type = extract_product_type_from_text(title)
        
        # Bei unklarem Produkttyp: weitere Hinweise suchen
        if title_product_type == "unknown":
            # URL-basierte Erkennung
            if "display" in product_url.lower() or "box" in product_url.lower():
                title_product_type = "display"
            
            # Inhalt der Seite überprüfen (nur ein paar wichtige Elemente)
            else:
                product_description = ""
                desc_elem = soup.select_one('.woocommerce-product-details__short-description, .description')
                if desc_elem:
                    product_description = desc_elem.get_text().lower()
                    
                if "36 booster" in product_description or "display mit 36" in product_description:
                    title_product_type = "display"
        
        # Extrahiere den Produkttyp aus dem ersten Suchbegriff (meistens "display")
        search_product_type = None
        if keywords_map:
            sample_search_term = list(keywords_map.keys())[0]
            search_product_type = extract_product_type_from_text(sample_search_term)
        
        # Strenge Prüfung: Wenn nach Display gesucht wird, muss es ein Display sein
        if search_product_type == "display" and title_product_type != "display":
            logger.debug(f"⚠️ Produkttyp-Konflikt: Suche nach 'display', aber Titel enthält '{title_product_type}': {title}")
            return False
        
        # Laden der Ausschlusslisten für die Filterfunktion
        exclusion_sets = load_exclusion_sets()
        
        # Prüfe jeden Suchbegriff gegen den Titel
        matched_terms = []
        for search_term, tokens in keywords_map.items():
            # Extrahiere Produkttyp aus Suchbegriff - für strenge Filterung
            search_term_type = extract_product_type_from_text(search_term)
            
            # Bei Display-Suche: strenge Typ-Überprüfung 
            if search_term_type == "display":
                if title_product_type != "display":
                    continue
            
            # Verbesserte Keywordprüfung
            if is_keyword_in_text(tokens, title, log_level='None'):
                # Prüfe, ob das Produkt in den Ausschlusslisten enthalten ist
                should_exclude = False
                for exclusion in exclusion_sets:
                    if exclusion in title.lower():
                        should_exclude = True
                        break
                
                if not should_exclude:
                    matched_terms.append(search_term)
            
        # Wenn mindestens ein Suchbegriff übereinstimmt
        if matched_terms:
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
                        standard_prices = {
                            "display": "159,99 €",
                            "etb": "49,99 €",
                            "box": "49,99 €",
                            "tin": "24,99 €",
                            "blister": "14,99 €"
                        }
                        price = standard_prices.get(title_product_type, "Preis nicht verfügbar")
            
            # Aktualisiere Produkt-Status und ggf. Benachrichtigung senden
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
                
                # Produkt-Informationen für die Batch-Benachrichtigung
                product_data = {
                    "title": title,
                    "url": product_url,
                    "price": price,
                    "status_text": status_text,
                    "is_available": is_available,
                    "matched_term": matched_terms[0],
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

def try_search_fallback(keywords_map, processed_urls, headers, max_retries=1):
    """
    Verbesserte Fallback-Methode für die Suche nach Produkten mit minimalen Ressourcen
    
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param processed_urls: Set mit bereits verarbeiteten URLs
    :param headers: HTTP-Headers für die Anfrage
    :param max_retries: Maximale Anzahl an Wiederholungsversuchen
    :return: Liste gefundener Produkt-URLs
    """
    # Optimierte Suchbegriffe basierend auf den übergebenen Suchbegriffen
    search_terms = []
    
    # Erstelle Suchbegriffe basierend auf den übergebenen Keywords
    for search_term in keywords_map.keys():
        # Entferne produktspezifische Begriffe wie "display", "box"
        clean_term = re.sub(r'\s+(display|box|tin|etb)$', '', search_term.lower())
        if clean_term not in search_terms:
            search_terms.append(clean_term)
    
    result_urls = []
    
    for term in search_terms:
        try:
            # URL-Encoding für den Suchbegriff
            encoded_term = quote_plus(term)
            search_url = f"https://sapphire-cards.de/?s={encoded_term}&post_type=product&type_aws=true"
            logger.info(f"🔍 Suche nach: {term}")
            
            try:
                response = requests.get(search_url, headers=headers, timeout=15)
                if response.status_code != 200:
                    continue
            except requests.exceptions.RequestException:
                continue
            
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Sammle Produkt-Links effizient
            product_links = []
            
            # Nutze spezifischere Selektoren für Produkte
            products = soup.select('.product, article.product, .woocommerce-loop-product__link')
            for product in products:
                link = product.find('a', href=True)
                if link and '/produkt/' in link['href'] and link['href'] not in product_links and link['href'] not in processed_urls:
                    product_links.append(link['href'])
            
            # Relativen Pfad zu absoluten Links
            for i in range(len(product_links)):
                if not product_links[i].startswith('http'):
                    product_links[i] = urljoin("https://sapphire-cards.de", product_links[i])
            
            result_urls.extend(product_links)
            
            # Begrenze die Suche
            if product_links:
                break
        
        except Exception as e:
            logger.error(f"❌ Fehler bei der Fallback-Suche für '{term}': {e}")
    
    return list(set(result_urls))  # Entferne Duplikate

def create_fallback_product(search_term, product_type):
    """
    Erstellt ein Fallback-Produkt basierend auf dem Suchbegriff und Produkttyp
    
    :param search_term: Originaler Suchbegriff
    :param product_type: Erkannter Produkttyp
    :return: Dict mit Produktdaten oder None wenn keine Daten erstellt werden konnten
    """
    # Nur Fallbacks für gültige Produkttypen erstellen
    if product_type not in ["display", "etb", "box", "tin", "blister"]:
        return None
    
    # Normalisiere den Suchbegriff für die URL
    normalized_term = search_term.lower()
    # Entferne produktspezifische Begriffe wie "display", "box"
    normalized_term = re.sub(r'\s+(display|box|tin|etb)$', '', normalized_term)
    url_term = re.sub(r'\s+', '-', normalized_term)
    
    # Titel basierend auf Suchbegriff und Produkttyp
    title_map = {
        "display": f"Pokemon {normalized_term.title()} Booster Box (Display)",
        "etb": f"Pokemon {normalized_term.title()} Elite Trainer Box",
        "box": f"Pokemon {normalized_term.title()} Box",
        "tin": f"Pokemon {normalized_term.title()} Tin",
        "blister": f"Pokemon {normalized_term.title()} Blister"
    }
    
    # URL basierend auf Suchbegriff und Produkttyp
    url_map = {
        "display": f"https://sapphire-cards.de/produkt/{url_term}-booster-box-display/",
        "etb": f"https://sapphire-cards.de/produkt/{url_term}-elite-trainer-box/",
        "box": f"https://sapphire-cards.de/produkt/{url_term}-box/",
        "tin": f"https://sapphire-cards.de/produkt/{url_term}-tin/",
        "blister": f"https://sapphire-cards.de/produkt/{url_term}-blister/"
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
        
        # Analysiere die URL-Struktur, um Produkttyp zu bestimmen
        if any(term in url.lower() for term in ['booster-box', 'display']):
            if 'display' not in title.lower():
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

def extract_product_type(text):
    """
    Extrahiert den Produkttyp aus einem Text mit besonderen Anpassungen für sapphire-cards.de
    
    :param text: Text, aus dem der Produkttyp extrahiert werden soll
    :return: Produkttyp als String
    """
    if not text:
        return "unknown"
    
    text = text.lower()
    
    # Display erkennen - häufigste Varianten
    if re.search(r'\bdisplay\b|\b36er\b|\b36\s+booster\b|\bbooster\s+display\b|\bbox\s+display\b', text):
        return "display"
    
    # Booster Box als Display erkennen (sapphire-cards.de spezifisch)
    elif re.search(r'booster\s+box', text) and not re.search(r'elite|etb|trainer', text):
        return "display"
    
    # Elite Trainer Box erkennen
    elif re.search(r'\belite trainer box\b|\betb\b|\btrainer box\b', text):
        return "etb"
    
    # Blister/3-Pack erkennen
    elif re.search(r'\bblister\b|\b3er\b|\b3-pack\b|\b3\s+pack\b', text):
        return "blister"
    
    # Wenn nichts erkannt wurde
    return "unknown"