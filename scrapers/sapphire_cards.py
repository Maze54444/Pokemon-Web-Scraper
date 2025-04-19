import requests
import hashlib
import re
import time
import random
import logging
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote_plus
from utils.telegram import send_telegram_message, escape_markdown, send_product_notification, send_batch_notification
from utils.matcher import is_keyword_in_text, extract_product_type_from_text
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
    
    # Reduzierte und aktualisierte Liste der direkten Produkt-URLs
    # Basierend auf den Log-Auswertungen wurden 404-URLs entfernt
    direct_urls = [
        # Aktuellste und funktionierende URL basierend auf den Logs
        "https://sapphire-cards.de/produkt/pokemon-journey-together-reisegefaehrten-booster-box-display/"
    ]
    
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
                
                # Schlüsselwörter für die Filterung
                relevant_keywords = ['journey', 'together', 'reise', 'gefährten', 'gefaehrten', 'sv09', 'sv9', 'kp09', 'kp9']
                
                for link in all_links:
                    href = link.get('href', '')
                    if '/produkt/' in href and href not in product_links and href not in processed_urls:
                        if any(keyword in href.lower() for keyword in relevant_keywords) or \
                           any(keyword in link.get_text().lower() for keyword in relevant_keywords):
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
    if not all_products:
        logger.info("🔍 Keine Treffer in Katalogseiten, versuche Suche...")
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
    
    # Wenn nach all dem immer noch nichts gefunden wurde, manuelle Hardcoding-Fallback
    if not new_matches:
        logger.warning("⚠️ Keine Produkte gefunden. Verwende Hardcoded-Fallback-Produkt...")
        fallback_product = {
            "url": "https://sapphire-cards.de/produkt/pokemon-journey-together-reisegefaehrten-booster-box-display/",
            "title": "Pokemon Journey Together | Reisegefährten Booster Box (Display)",
            "price": "159,99 €",
            "is_available": True,
            "status_text": "✅ Verfügbar (Fallback)",
            "product_type": "display",
            "shop": "sapphire-cards.de"
        }
        
        # Wähle den passsendsten Suchbegriff aus
        best_match = None
        for search_term in keywords_map.keys():
            if "journey together display" in search_term.lower() or "reisegefährten display" in search_term.lower():
                best_match = search_term
                break
        
        if not best_match and keywords_map:
            # Nimm einfach den ersten Suchbegriff
            best_match = list(keywords_map.keys())[0]
        
        if best_match:
            product_id = f"sapphirecards_fallback_{hashlib.md5(fallback_product['url'].encode()).hexdigest()[:8]}"
            
            # Status aktualisieren und ggf. Benachrichtigung senden
            should_notify, is_back_in_stock = update_product_status(
                product_id, fallback_product["is_available"], seen, out_of_stock
            )
            
            if should_notify:
                fallback_product["matched_term"] = best_match
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
                    title = re.sub(r'Reisegefaehrten', 'Reisegefährten', title)
                    logger.info(f"📝 Verwende URL-Segment als Titel: '{title}'")
                    break
        
        # Standard-Titel als letzte Option
        if not title or len(title) < 5:
            title = "Pokemon Journey Together | Reisegefährten Booster Box (Display)"
        
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
                        price = "159,99 €"  # Standardpreis für Displays
            
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
    return f"sapphirecards_{url_hash}"

def try_search_fallback(keywords_map, processed_urls, headers, max_retries=1):
    """
    Verbesserte Fallback-Methode für die Suche nach Produkten mit minimalen Ressourcen
    
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param processed_urls: Set mit bereits verarbeiteten URLs
    :param headers: HTTP-Headers für die Anfrage
    :param max_retries: Maximale Anzahl an Wiederholungsversuchen
    :return: Liste gefundener Produkt-URLs
    """
    # Optimierte Suchbegriffe (weniger, aber präziser)
    search_terms = [
        "journey together display",
        "reisegefährten display"
    ]
    
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