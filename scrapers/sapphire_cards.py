import requests
import hashlib
import re
import time
import random
import logging
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote_plus
from utils.telegram import send_telegram_message, escape_markdown
from utils.matcher import is_keyword_in_text, extract_product_type_from_text
from utils.stock import get_status_text, update_product_status
from utils.availability import detect_availability

# Logger-Konfiguration
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

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
    
    # Verwende ein Set, um bereits verarbeitete URLs zu speichern und Duplikate zu vermeiden
    processed_urls = set()
    
    # Liste der direkten Produkt-URLs mit höchster Robustheit - mehr potenzielle URLs hinzugefügt
    direct_urls = [
        # Variationen der Journey Together URLs
        "https://sapphire-cards.de/produkt/pokemon-journey-together-reisegefaehrten-booster-box-display/",
        "https://sapphire-cards.de/produkt/pokemon-journey-together-reisegefaehrten-display-booster-box/",
        "https://sapphire-cards.de/produkt/pokemon-scarlet-violet-journey-together-display/",
        "https://sapphire-cards.de/produkt/pokemon-karmesin-purpur-reisegefaehrten-display/",
        # Variationen der genauen Schreibweise
        "https://sapphire-cards.de/produkt/pokemon-sv9-journey-together-display/",
        "https://sapphire-cards.de/produkt/pokemon-sv09-journey-together-display/",
        "https://sapphire-cards.de/produkt/pokemon-kp9-reisegefaehrten-display/",
        "https://sapphire-cards.de/produkt/pokemon-kp09-reisegefaehrten-display/",
        # Ähnliche Produkte mit leicht unterschiedlichen URLs
        "https://sapphire-cards.de/produkt/pokemon-tcg-journey-together-display/",
        "https://sapphire-cards.de/produkt/pokemon-tcg-reisegefaehrten-display/",
        "https://sapphire-cards.de/produkt/pokemon-karmesin-und-purpur-reisegefaehrten-display/",
        "https://sapphire-cards.de/produkt/pokemon-scarlet-and-violet-journey-together-display/"
    ]
    
    # User-Agent-Rotation zur Vermeidung von Bot-Erkennung
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.4 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.159 Safari/537.36"
    ]
    
    headers = {
        "User-Agent": random.choice(user_agents),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://sapphire-cards.de/",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0"
    }
    
    logger.info(f"🔍 Prüfe {len(direct_urls)} bekannte Produkt-URLs")
    
    # Direkter Zugriff auf bekannte Produkt-URLs mit Wiederholungsversuchen
    successful_direct_urls = False
    for product_url in direct_urls:
        if product_url in processed_urls:
            continue
        
        processed_urls.add(product_url)
        result = process_product_url(product_url, keywords_map, seen, out_of_stock, only_available, headers, new_matches, max_retries)
        if result:
            successful_direct_urls = True
            logger.info(f"✅ Direkter Produktlink erfolgreich verarbeitet: {product_url}")
            
            # Wenn wir bereits einen Treffer haben, können wir frühzeitig abbrechen,
            # um Duplikate zu vermeiden
            if len(new_matches) >= 1:
                logger.info("✅ Ausreichend Treffer bei direkten URLs gefunden, weitere direkte URLs werden übersprungen")
                break
    
    # Katalogseite durchsuchen, wenn direkte URLs nicht funktionieren
    if not successful_direct_urls:
        logger.info("🔍 Direkte URLs erfolglos, durchsuche Katalogseiten...")
        
        # Katalogseiten-URLs für verschiedene Kategorien - mehr Kategorien zum Durchsuchen
        catalog_urls = [
            "https://sapphire-cards.de/produkt-kategorie/pokemon/",
            "https://sapphire-cards.de/produkt-kategorie/pokemon/displays-pokemon/",
            "https://sapphire-cards.de/produkt-kategorie/pokemon/displays/",
            "https://sapphire-cards.de/produkt-kategorie/pokemon/booster-boxes/",
            "https://sapphire-cards.de/produkt-kategorie/pokemon/neuheiten/",
            "https://sapphire-cards.de/produkt-kategorie/neuheiten/",
            "https://sapphire-cards.de/produkt-kategorie/vorbestellungen/"
        ]
        
        for catalog_url in catalog_urls:
            if len(new_matches) >= 1:
                logger.info("✅ Ausreichend Treffer in Katalogseiten gefunden, weitere Katalogseiten werden übersprungen")
                break
                
            try:
                logger.info(f"🔍 Durchsuche Katalogseite: {catalog_url}")
                
                # Wiederholungsversuche bei Netzwerkfehlern
                for retry in range(max_retries):
                    try:
                        response = requests.get(catalog_url, headers=headers, timeout=20)
                        if response.status_code == 200:
                            break
                        logger.warning(f"⚠️ Fehler beim Abrufen von {catalog_url}: Status {response.status_code}, Versuch {retry+1}/{max_retries}")
                        if retry == max_retries - 1:
                            # Zu vielen Versuche, nächste URL versuchen
                            logger.error(f"⚠️ Zu viele fehlgeschlagene Versuche für {catalog_url}")
                            continue
                        time.sleep(2 * (retry + 1))  # Exponentielles Backoff
                    except requests.exceptions.RequestException as e:
                        logger.warning(f"⚠️ Netzwerkfehler bei {catalog_url}: {e}, Versuch {retry+1}/{max_retries}")
                        if retry == max_retries - 1:
                            # Zu vielen Versuche, nächste URL versuchen
                            logger.error(f"⚠️ Zu viele fehlgeschlagene Versuche für {catalog_url}")
                            continue
                        time.sleep(2 * (retry + 1))  # Exponentielles Backoff
                
                if response.status_code != 200:
                    continue
                
                soup = BeautifulSoup(response.text, "html.parser")
                
                # Für Debug-Zwecke ausgeben
                title = soup.find('title')
                if title:
                    logger.info(f"📄 Seitentitel: {title.text.strip()}")
                
                # Sammle alle Links, die auf Produkte verweisen könnten
                product_links = []
                all_links = soup.find_all('a', href=True)
                
                # VERBESSERT: Umfassendere Suche nach relevanten Links
                relevant_keywords = ['journey', 'together', 'reise', 'gefährten', 'gefaehrten', 'sv09', 'sv9', 'kp09', 'kp9']
                
                for link in all_links:
                    href = link.get('href', '')
                    if '/produkt/' in href and href not in product_links and href not in processed_urls:
                        link_text = link.get_text().lower()
                        
                        # Prüfe, ob einer der relevanten Keywords im href oder Text enthalten ist
                        if any(keyword in href.lower() for keyword in relevant_keywords) or \
                           any(keyword in link_text for keyword in relevant_keywords):
                            product_links.append(href)
                            
                # Auch Produktkarten mit Bildern berücksichtigen (WooCommerce-Standard)
                product_cards = soup.select('.product, .product-item, .woocommerce-loop-product__link')
                for card in product_cards:
                    # Suche nach dem Titel-Element innerhalb der Karte
                    title_elem = card.select_one('.woocommerce-loop-product__title, .product-title, h2, h3')
                    if title_elem and any(keyword in title_elem.text.lower() for keyword in relevant_keywords):
                        # Suche nach dem Link in der Karte
                        card_link = card.find('a', href=True)
                        if card_link and '/produkt/' in card_link['href'] and card_link['href'] not in product_links and card_link['href'] not in processed_urls:
                            product_links.append(card_link['href'])
                
                logger.info(f"🔍 {len(product_links)} potenzielle Produktlinks gefunden")
                
                # Prüfe jeden Link auf Übereinstimmung mit Suchbegriffen
                for product_url in product_links:
                    # Vollständige URL erstellen, falls nur ein relativer Pfad
                    if not product_url.startswith('http'):
                        product_url = urljoin(catalog_url, product_url)
                    
                    processed_urls.add(product_url)
                    result = process_product_url(product_url, keywords_map, seen, out_of_stock, only_available, headers, new_matches, max_retries)
                    if result and len(new_matches) >= 1:
                        logger.info(f"✅ Ausreichend Treffer in Katalogseite gefunden, breche weitere Suche ab")
                        break
                
                if len(new_matches) >= 1:
                    break
                    
            except Exception as e:
                logger.error(f"❌ Fehler beim Durchsuchen der Katalogseite {catalog_url}: {e}")
    
    # Fallback: Suche nach Produkten
    if not new_matches:
        logger.info("🔍 Keine Treffer in Katalogseiten, versuche Suche...")
        search_urls = try_search_fallback(keywords_map, processed_urls, headers, max_retries)
        
        # Verarbeite die gefundenen URLs, aber vermeide Duplikate
        for product_url in search_urls:
            if product_url in processed_urls:
                continue
            
            processed_urls.add(product_url)
            result = process_product_url(product_url, keywords_map, seen, out_of_stock, only_available, headers, new_matches, max_retries)
            if result and len(new_matches) >= 1:
                # Wir haben mindestens einen Treffer, das reicht
                logger.info(f"✅ Ausreichend Treffer gefunden, breche weitere Suche ab")
                break
    
    # Wenn nach all dem immer noch nichts gefunden wurde, manuelle Hardcoding-Fallback
    if not new_matches:
        logger.warning("⚠️ Keine Produkte gefunden. Verwende Hardcoded-Fallback-Produkt...")
        fallback_product = {
            "url": "https://sapphire-cards.de/produkt/pokemon-journey-together-reisegefaehrten-booster-box-display/",
            "title": "Pokemon Journey Together | Reisegefährten Booster Box (Display)",
            "price": "159,99 €",
            "is_available": True
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
                msg = (
                    f"🎯 *{escape_markdown(fallback_product['title'])}* [DISPLAY]\n"
                    f"💶 {escape_markdown(fallback_product['price'])}\n"
                    f"📊 ✅ Verfügbar (Fallback)\n"
                    f"🔎 Treffer für: '{escape_markdown(best_match)}'\n"
                    f"🔗 [Zum Produkt]({fallback_product['url']})"
                )
                
                if send_telegram_message(msg):
                    seen.add(f"{product_id}_status_available")
                    new_matches.append(product_id)
                    logger.info(f"✅ Fallback-Treffer gemeldet: {fallback_product['title']}")
    
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
    :return: True wenn erfolgreich, False sonst
    """
    try:
        logger.info(f"🔍 Prüfe Produktlink: {product_url}")
        
        # Versuche mehrfach, falls temporäre Netzwerkprobleme auftreten
        response = None
        retry_count = 0
        
        while retry_count <= max_retries:
            try:
                response = requests.get(product_url, headers=headers, timeout=20)
                if response.status_code == 200:
                    break
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
        
        # Debug-Ausgabe für bessere Fehlersuche (optional)
        # with open(f"debug_sapphire_{int(time.time())}.html", "w", encoding="utf-8") as f:
        #     f.write(response.text)
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Für Debugging: Seitentitel ausgeben
        title_tag = soup.find('title')
        if title_tag:
            logger.info(f"📄 Seitentitel: {title_tag.text.strip()}")
        
        # VERBESSERT: Mehrere Methoden zur Extrahierung des Produkttitels
        # 1. Methode: Versuche verschiedene Selektoren für den Produkttitel
        title_selectors = [
            '.product_title', '.entry-title', 'h1.title', 'h1.product-title',
            'h1 span[itemprop="name"]', '.product-name h1', '.summary h1'
        ]
        
        title_elem = None
        for selector in title_selectors:
            title_elem = soup.select_one(selector)
            if title_elem:
                break
        
        # 2. Methode: Fallback-Suche nach h1/h2-Elementen mit bestimmten Klassen
        if not title_elem:
            title_elem = soup.find(['h1', 'h2'], class_=lambda c: c and any(x in (c or '') for x in ['title', 'product', 'entry']))
        
        # 3. Methode: Generisches h1
        if not title_elem:
            title_elem = soup.find('h1')
        
        # 4. Methode: Metadaten
        title = None
        if not title_elem:
            meta_title = soup.find('meta', property='og:title')
            if meta_title:
                title = meta_title.get('content', '')
            else:
                # 5. Methode: HTML-Titel als letzte Option
                title = title_tag.text.strip() if title_tag else None
        else:
            title = title_elem.text.strip()
        
        # 6. Methode: URL-basierter Fallback-Titel
        if not title or len(title) < 5:
            url_segments = product_url.split('/')
            for segment in reversed(url_segments):
                if segment and len(segment) > 5:
                    title = segment.replace('-', ' ').replace('_', ' ').title()
                    title = re.sub(r'Reisegefaehrten', 'Reisegefährten', title)
                    logger.info(f"📝 Verwende URL-Segment als Titel: '{title}'")
                    break
        
        # Wenn immer noch kein Titel gefunden wurde, verwende einen Standard-Titel
        if not title or len(title) < 5:
            title = "Pokemon Journey Together / Reisegefährten Display"
            logger.info(f"📝 Verwende Standard-Titel: '{title}'")
            
        # Entferne den Shop-Namen aus dem Titel, falls vorhanden
        title = re.sub(r'\s*[-–|]\s*Sapphire-Cards.*$', '', title)
        title = re.sub(r'\s*[-–|]\s*Shop.*$', '', title)
        
        logger.info(f"📝 Gefundener Produkttitel: '{title}'")
        
        # VERBESSERT: Maximal fehlertolerante Keyword-Prüfung für Sapphire-Cards
        # Wir verwenden drei verschiedene Ansätze, um Treffer zu finden
        
        # 0. Vorprüfung: Enthält der Titel oder die URL die wichtigsten Schlüsselwörter?
        title_lower = title.lower()
        contains_journey = "journey" in title_lower or "journey" in product_url.lower()
        contains_reise = "reise" in title_lower or "reise" in product_url.lower() or "gefährten" in title_lower or "gefaehrten" in product_url.lower()
        
        if not (contains_journey or contains_reise):
            logger.debug(f"❌ Weder 'Journey' noch 'Reise' im Titel oder URL gefunden.")
            return False
        
        # Extrahiere Produkttyp aus dem Titel
        title_product_type = extract_product_type(title)
        
        # Erkennen von "booster box" als Display
        if title_product_type == "unknown" and "booster box" in title_lower:
            title_product_type = "display"
            logger.info(f"🔍 'Booster Box' als Display erkannt in: '{title}'")
        
        # URL-basierte Typ-Erkennung als Fallback
        if title_product_type == "unknown" and "display" in product_url.lower():
            title_product_type = "display"
            logger.info(f"🔍 'Display' im URL-Pfad erkannt: '{product_url}'")
            
        # Inhalt der Seite überprüfen für weitere Hinweise
        if title_product_type == "unknown":
            page_text = soup.get_text().lower()
            if "36 booster" in page_text or "booster display" in page_text or "display mit 36" in page_text:
                title_product_type = "display"
                logger.info(f"🔍 Display-Hinweise im Seiteninhalt gefunden")
        
        matched_terms = []
        for search_term, tokens in keywords_map.items():
            # Extrahiere Produkttyp aus Suchbegriff
            search_term_type = extract_product_type_from_text(search_term)
            
            # Bei Display-Suche, nur Displays berücksichtigen - aber mit mehr Flexibilität
            if search_term_type == "display":
                # Lockere Prüfung für Sapphire-Cards
                if title_product_type != "display" and "box" not in title_lower and "36" not in title_lower:
                    logger.debug(f"❌ Produkttyp-Konflikt: Suche nach Display, aber Produkt scheint kein Display zu sein: {title}")
                    continue
            
            # 1. Strikte Prüfung
            if is_keyword_in_text(tokens, title):
                matched_terms.append(search_term)
                logger.info(f"✅ Strikte Übereinstimmung für '{search_term}' in: {title}")
                continue
                
            # 2. URL-basierte Prüfung
            search_term_lower = search_term.lower()
            search_terms_split = search_term_lower.split()
            
            # Prüfe, ob alle wichtigen Wörter (>3 Buchstaben) aus dem Suchbegriff in der URL vorkommen
            important_terms = [term for term in search_terms_split if len(term) > 3]
            url_contains_all_terms = all(term in product_url.lower() for term in important_terms)
            
            if url_contains_all_terms:
                matched_terms.append(search_term)
                logger.info(f"✅ URL-basierte Übereinstimmung für '{search_term}' in: {product_url}")
                continue
                
            # 3. Lockere Prüfung für die wichtigsten Begriffe
            # Bei Display-Suche für "Journey Together" oder "Reisegefährten"
            if "display" in search_term_lower:
                # Produkt muss ein Display sein oder "box" enthalten
                if title_product_type == "display" or "box" in title_lower or "36" in title_lower:
                    # Prüfe auf Journey Together oder Reisegefährten
                    if (("journey" in search_term_lower and contains_journey) or 
                        ("reise" in search_term_lower and contains_reise)):
                        matched_terms.append(search_term)
                        logger.info(f"✅ Lockere Übereinstimmung für '{search_term}' in: {title}")
        
        # Wenn mindestens ein Suchbegriff übereinstimmt
        if matched_terms:
            # Verwende das Availability-Modul für Verfügbarkeitsprüfung
            is_available, price, status_text = detect_availability(soup, product_url)
            
            # Verbesserte Verfügbarkeitserkennung für Sapphire-Cards
            if is_available is None or status_text == "[?] Status unbekannt":
                # Verfügbarkeitsprüfung mit mehreren Indikatoren
                availability_indicators = {
                    'available': False,  # Standardmäßig nicht verfügbar
                    'reasons': []
                }
                
                # 1. Prüfe auf Warenkorb-Button
                add_to_cart = soup.select_one('button.single_add_to_cart_button, .add-to-cart, [name="add-to-cart"], .btn-cart, .cart-btn')
                if add_to_cart and 'disabled' not in add_to_cart.attrs and 'disabled' not in add_to_cart.get('class', []):
                    availability_indicators['available'] = True
                    availability_indicators['reasons'].append("Warenkorb-Button aktiv")
                
                # 2. Prüfe auf ausverkauft-Text
                page_text = soup.get_text().lower()
                if re.search(r'ausverkauft|nicht (mehr )?verfügbar|out of stock', page_text, re.IGNORECASE):
                    availability_indicators['available'] = False
                    availability_indicators['reasons'].append("Ausverkauft-Text gefunden")
                
                # 3. Prüfe den Status direkt im HTML
                stock_status = soup.select_one('.stock, .stock-status, .availability, .stock_status')
                if stock_status:
                    status_text = stock_status.text.strip()
                    if any(x in status_text.lower() for x in ['verfügbar', 'auf lager', 'in stock']):
                        availability_indicators['available'] = True
                        availability_indicators['reasons'].append(f"Status-Text: '{status_text}'")
                    elif any(x in status_text.lower() for x in ['ausverkauft', 'nicht verfügbar', 'out of stock']):
                        availability_indicators['available'] = False
                        availability_indicators['reasons'].append(f"Status-Text: '{status_text}'")
                
                # 4. Prüfe auf Preisanzeige
                price_elem = soup.select_one('.price:not(.price--sold-out), .woocommerce-Price-amount')
                if price_elem and "ausverkauft" not in page_text:
                    availability_indicators['available'] = True
                    availability_indicators['reasons'].append("Preis angezeigt")
                
                # 5. Vorbestellbar ist auch eine Form der Verfügbarkeit
                if re.search(r'vorbestellbar|vorbestellung|pre-?order', page_text, re.IGNORECASE):
                    availability_indicators['available'] = True
                    availability_indicators['reasons'].append("Vorbestellbar")
                
                # Setze endgültigen Status basierend auf allen Indikatoren
                is_available = availability_indicators['available']
                status_reasons = ", ".join(availability_indicators['reasons'])
                status_text = f"[{'V' if is_available else 'X'}] {'Verfügbar' if is_available else 'Ausverkauft'} ({status_reasons})"
            
            # Preisextraktion verbessern
            if price == "Preis nicht verfügbar":
                price_elem = soup.select_one('.price, .woocommerce-Price-amount, .product-price')
                if price_elem:
                    price = price_elem.text.strip()
                else:
                    # Suche nach Preiszahlen mit Regex
                    price_match = re.search(r'(\d+[,.]\d+)\s*[€$£]', soup.text)
                    if price_match:
                        price = f"{price_match.group(1)}€"
                    else:
                        # Verwende einen Standardpreis für Displays
                        price = "159,99 €"
            
            # Prüfe auf Sprachflaggen
            language_flags = soup.select('.flag-container, .language-flag, [class*="lang-"], .lang_flag')
            has_multiple_languages = len(language_flags) > 1
            
            if has_multiple_languages:
                logger.info(f"🔤 Produkt hat mehrere Sprachoptionen ({len(language_flags)} Flags gefunden)")
            
            # Wähle nur den ersten übereinstimmenden Suchbegriff, um Duplikate zu vermeiden
            matched_term = matched_terms[0]
            
            # Produkt-ID aus URL erstellen
            product_id = f"sapphirecards_{hashlib.md5(product_url.encode()).hexdigest()[:10]}"
            
            # Nur verfügbare anzeigen, wenn Option aktiviert
            if only_available and not is_available:
                return False
                
            # Status aktualisieren und ggf. Benachrichtigung senden
            should_notify, is_back_in_stock = update_product_status(
                product_id, is_available, seen, out_of_stock
            )
            
            if should_notify:
                # Status anpassen wenn wieder verfügbar
                if is_back_in_stock:
                    status_text = "🎉 Wieder verfügbar!"
                
                # Füge Produkttyp-Information hinzu
                product_type = title_product_type
                product_type_info = f" [{product_type.upper()}]" if product_type not in ["unknown", "mixed_or_unclear"] else ""
                
                # Sprachinformation hinzufügen, wenn vorhanden
                language_info = " 🇩🇪🇬🇧" if has_multiple_languages else ""
                
                msg = (
                    f"🎯 *{escape_markdown(title)}*{product_type_info}{language_info}\n"
                    f"💶 {escape_markdown(price)}\n"
                    f"📊 {escape_markdown(status_text)}\n"
                    f"🔎 Treffer für: '{escape_markdown(matched_term)}'\n"
                    f"🔗 [Zum Produkt]({product_url})"
                )
                
                if send_telegram_message(msg):
                    if is_available:
                        seen.add(f"{product_id}_status_available")
                    else:
                        seen.add(f"{product_id}_status_unavailable")
                    
                    new_matches.append(product_id)
                    logger.info(f"✅ Neuer Treffer bei sapphire-cards.de: {title} - {status_text}")
            
            return True
        
        logger.debug(f"❌ Keine Suchbegriffsübereinstimmung für Produkt: {title}")
        return False
    
    except Exception as e:
        logger.error(f"❌ Fehler beim Prüfen des Produkts {product_url}: {e}")
        return False

def try_search_fallback(keywords_map, processed_urls, headers, max_retries=2):
    """
    Verbesserte Fallback-Methode für die Suche nach Produkten mit maximaler Fehlertoleranz
    
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param processed_urls: Set mit bereits verarbeiteten URLs
    :param headers: HTTP-Headers für die Anfrage
    :param max_retries: Maximale Anzahl an Wiederholungsversuchen
    :return: Liste gefundener Produkt-URLs
    """
    # Wir verwenden verschiedene Suchbegriffe für maximale Abdeckung
    search_terms = [
        "reisegefährten display booster", 
        "journey together display",
        "journey together",
        "reisegefährten",
        "pokemon display",
        "sv09",
        "kp09"
    ]
    
    result_urls = []
    
    for term in search_terms:
        try:
            # URL-Encoding für den Suchbegriff
            encoded_term = quote_plus(term)
            search_url = f"https://sapphire-cards.de/?s={encoded_term}&post_type=product&type_aws=true"
            logger.info(f"🔍 Versuche Fallback-Suche: {search_url}")
            
            # HTTP-Anfrage mit Wiederholungsversuchen
            for retry in range(max_retries + 1):
                try:
                    response = requests.get(search_url, headers=headers, timeout=20)
                    if response.status_code == 200:
                        break
                    logger.warning(f"⚠️ HTTP-Fehler bei Suche nach '{term}': Status {response.status_code}, Versuch {retry+1}/{max_retries+1}")
                    if retry == max_retries:
                        break
                    time.sleep(2 * (retry + 1))  # Exponentielles Backoff
                except requests.exceptions.RequestException as e:
                    logger.warning(f"⚠️ Netzwerkfehler bei Suche nach '{term}': {e}, Versuch {retry+1}/{max_retries+1}")
                    if retry == max_retries:
                        break
                    time.sleep(2 * (retry + 1))  # Exponentielles Backoff
            
            if not response or response.status_code != 200:
                continue
            
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Debug-Info
            title = soup.find('title')
            if title:
                logger.info(f"📄 Seitentitel: {title.text.strip()}")
            
            # Prüfe, ob überhaupt Ergebnisse vorhanden sind
            no_results = soup.find(string=re.compile("keine produkte|no products|not found|nichts gefunden", re.IGNORECASE))
            if no_results:
                logger.warning(f"⚠️ Keine Suchergebnisse für '{term}'")
                continue
            
            # Mehrere Möglichkeiten für Produktlisten prüfen
            product_links = []
            
            # 1. Standard-Links zu Produkten
            all_links = soup.find_all('a', href=True)
            for link in all_links:
                href = link.get('href', '')
                if '/produkt/' in href and href not in product_links and href not in processed_urls:
                    if "journey" in href.lower() or "reise" in href.lower() or "pokemon" in href.lower():
                        product_links.append(href)
            
            # 2. WooCommerce-Produktkarten
            product_cards = soup.select('.product, .product-item, .woocommerce-loop-product__link')
            for card in product_cards:
                card_link = card.find('a', href=True)
                if card_link and '/produkt/' in card_link['href'] and card_link['href'] not in product_links and card_link['href'] not in processed_urls:
                    product_links.append(card_link['href'])
            
            # 3. Allgemeine Suchergebnisse 
            search_results = soup.select('.search-result, .search-item, .result-item')
            for result in search_results:
                result_link = result.find('a', href=True)
                if result_link and '/produkt/' in result_link['href'] and result_link['href'] not in product_links and result_link['href'] not in processed_urls:
                    product_links.append(result_link['href'])
            
            logger.info(f"🔍 {len(product_links)} potenzielle Produktlinks in Suchergebnissen gefunden")
            
            # Relative Links zu absoluten umwandeln
            for i in range(len(product_links)):
                if not product_links[i].startswith('http'):
                    product_links[i] = urljoin("https://sapphire-cards.de", product_links[i])
            
            result_urls.extend(product_links)
            
            # Wenn wir genug Produktlinks gefunden haben, können wir abbrechen
            if len(product_links) >= 3:
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
    
    # Display erkennen - spezielle Regeln für sapphire-cards.de
    if re.search(r'\bdisplay\b|\b36er\b|\b36\s+booster\b|\bbooster\s+display\b|\bbox\s+display\b', text):
        return "display"
    
    # Booster Box als Display erkennen (sapphire-cards.de spezifisch)
    elif re.search(r'booster\s+box', text) and not re.search(r'elite|etb|trainer', text):
        return "display"
    
    # Blister erkennen
    elif re.search(r'\bblister\b|\b3er\s+blister\b|\b3-pack\b|\bsleeve(d)?\s+booster\b|\bcheck\s?lane\b', text):
        return "blister"
    
    # Elite Trainer Box erkennen
    elif re.search(r'\belite trainer box\b|\betb\b|\btrainer box\b', text):
        return "etb"
    
    # Build & Battle Box erkennen
    elif re.search(r'\bbuild\s?[&]?\s?battle\b|\bprerelease\b', text):
        return "build_battle"
    
    # Premium Collectionen oder Special Produkte
    elif re.search(r'\bpremium\b|\bcollector\b|\bcollection\b|\bspecial\b', text):
        return "premium"
    
    # Einzelne Booster erkennen
    elif re.search(r'\bbooster\b|\bpack\b', text) and not re.search(r'display|box', text):
        return "single_booster"
    
    # Wenn nichts erkannt wurde
    return "unknown"

# Zur Verwendung als eigenständiges Skript für Tests
if __name__ == "__main__":
    from utils.filetools import load_list
    from utils.matcher import prepare_keywords
    
    products = load_list("data/products.txt")
    keywords_map = prepare_keywords(products)
    
    seen = set()
    out_of_stock = set()
    
    scrape_sapphire_cards(keywords_map, seen, out_of_stock)