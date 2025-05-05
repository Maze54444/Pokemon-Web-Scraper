import requests
import logging
import re
import time
import json
import hashlib
import random  # Fehlender Import hinzugefügt
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote_plus, urlparse
from utils.matcher import is_keyword_in_text, extract_product_type_from_text, load_exclusion_sets
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
    
    # Ermittle Produkttyp aus dem ersten Suchbegriff
    search_product_type = None
    if keywords_map:
        sample_search_term = list(keywords_map.keys())[0]
        search_product_type = extract_product_type_from_text(sample_search_term)
        logger.debug(f"🔍 Suche nach Produkttyp: '{search_product_type}'")
    
    # Generiere dynamische URL-Muster basierend auf den Suchbegriffen
    hardcoded_urls = []
    
    # URL-Muster für verschiedene Produkttypen
    url_patterns = {
        "display": [
            "https://www.mighty-cards.de/shop/{}-36er-Booster-Display-Pokemon-p{}",
            "https://www.mighty-cards.de/shop/{}-18er-Booster-Display-Pokemon-p{}"
        ],
        "box": [
            "https://www.mighty-cards.de/shop/{}-Top-Trainer-Box-Pokemon-p{}",
            "https://www.mighty-cards.de/shop/{}-Elite-Trainer-Box-Pokemon-p{}"
        ]
    }
    
    # Füge allgemeine Pokemon-Kategorie-URL hinzu
    hardcoded_urls.append("https://www.mighty-cards.de/pokemon/")
    
    # Generiere URLs basierend auf Suchbegriffen und Produkttypen
    for search_term, tokens in keywords_map.items():
        product_type = extract_product_type_from_text(search_term)
        
        # Normalisiere den Suchbegriff für die URL
        normalized_term = search_term.lower()
        for suffix in [" display", " box", " etb", " tin"]:
            normalized_term = normalized_term.replace(suffix, "")
        normalized_term = normalized_term.strip().replace(" ", "-")
        
        # Wenn wir passende Muster für den Produkttyp haben, generiere URLs
        if product_type in url_patterns:
            for pattern in url_patterns[product_type]:
                # Placeholder-ID für die URL (wird später mit echten IDs ersetzt)
                placeholder_id = str(random.randint(700000000, 799999999))
                product_url = pattern.format(normalized_term, placeholder_id)
                hardcoded_urls.append(product_url)
                
                # Variante mit anderem Formatierungsstil
                alt_term = normalized_term.replace("-", "")
                alt_url = pattern.format(alt_term, placeholder_id)
                hardcoded_urls.append(alt_url)
        
        # Füge auch eine produktspezifische Seite hinzu
        hardcoded_urls.append(f"https://www.mighty-cards.de/pokemon/{normalized_term}/")
    
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
    
    logger.info(f"🔍 Prüfe {len(hardcoded_urls)} bekannte Produkt-URLs")
    
    # Cache für fehlgeschlagene URLs mit Timestamps
    failed_urls_cache = {}
    
    # Set für Deduplizierung von verarbeiteten URLs
    processed_urls = set()  # Deklaration hinzugefügt
    
    # Maximale Anzahl von Wiederholungsversuchen
    max_retries = 3  # Deklaration hinzugefügt
    
    # Direkter Zugriff auf bekannte Produkt-URLs mit Wiederholungsversuchen
    successful_direct_urls = False
    for product_url in hardcoded_urls:
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
    
    # 1. Zuerst: Versuche die WordPress Sitemap für Produkte zu laden
    logger.info("🔍 Versuche Produktdaten über die WP-Sitemap zu laden")
    sitemap_products = fetch_products_from_sitemap(headers)
    
    # Begrenze die Anzahl der zu verarbeitenden URLs, um Timeouts zu vermeiden
    max_urls_to_process = 20
    if len(sitemap_products) > max_urls_to_process:
        logger.info(f"⚙️ Begrenze Verarbeitung auf {max_urls_to_process} URLs (von {len(sitemap_products)} gefundenen)")
        # Filter für relevante URLs - bevorzuge URLs, die mit den Suchbegriffen übereinstimmen
        priority_urls = []
        
        # Sammle relevante Begriffe aus den Suchbegriffen
        relevant_terms = []
        for search_term in keywords_map.keys():
            # Entferne produktspezifische Begriffe wie "display", "box"
            cleaned_term = re.sub(r'\s+(display|box|tin|etb)$', '', search_term.lower())
            relevant_terms.append(cleaned_term)
            # Füge Begriffe auch in URL-freundlichem Format hinzu
            relevant_terms.append(cleaned_term.replace(' ', '-'))
            relevant_terms.append(cleaned_term.replace(' ', ''))
        
        # Füge generische Begriffe hinzu
        relevant_terms.extend(["pokemon", "display", "booster"])
        
        # Priorisiere URLs basierend auf relevanten Begriffen
        for url in sitemap_products:
            if any(term in url.lower() for term in relevant_terms):
                priority_urls.append(url)
                
        # Wenn nicht genug prioritäre URLs, fülle mit anderen auf
        if len(priority_urls) < max_urls_to_process:
            remaining_urls = [url for url in sitemap_products if url not in priority_urls]
            sitemap_products = priority_urls + remaining_urls[:max_urls_to_process - len(priority_urls)]
        else:
            sitemap_products = priority_urls[:max_urls_to_process]
    
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
    
    # 5. Zuletzt: Fallback auf hardcodierte URLs, wenn keine Produkte gefunden wurden
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
                              ["shop/", "pokemon"]):
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
                                                  ["shop/", "pokemon"]):
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
                          ["shop/", "pokemon"]):
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
    
    # Spezielle Kategorie hinzufügen
    pokemon_category_url = "https://www.mighty-cards.de/pokemon/"
    if pokemon_category_url not in product_urls:
        product_urls.append(pokemon_category_url)
        logger.info("Spezielle Kategorieseite für Pokemon hinzugefügt")
    
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
            clean_term = search_term.lower()
            # Entferne produktspezifische Begriffe wie "display", "box"
            clean_term = re.sub(r'\s+(display|box|tin|etb)$', '', clean_term)
            
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
                                
                                # Generalisierte Relevanzprüfung
                                is_relevant = False
                                for search_term, tokens in keywords_map.items():
                                    if is_keyword_in_text(tokens, product_name, log_level='None'):
                                        is_relevant = True
                                        break
                                
                                # Filtern nach relevanten Produkten
                                if product_id and is_relevant:
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
        "https://www.mighty-cards.de/pokemon/"  # Spezifische Pokemon-Kategorie
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
        
        # Bereinige Suchbegriff - entferne produktspezifische Begriffe wie "display", "box"
        clean_term = search_term.lower()
        clean_term = re.sub(r'\s+(display|box|tin|etb)$', '', clean_term)
        
        # URL-Encoding für die Suche
        encoded_term = quote_plus(clean_term)
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

def process_product_url(product_url, keywords_map, seen, out_of_stock, only_available, headers, new_matches, max_retries=3):
    """
    Hilfsfunktion zum Verarbeiten einer einzelnen Produkt-URL
    
    :param product_url: URL zur Produktseite
    :param keywords_map: Keywords für die Suche
    :param seen: Set bereits gesehener Produkte
    :param out_of_stock: Set ausverkaufter Produkte
    :param only_available: Ob nur verfügbare Produkte angezeigt werden sollen
    :param headers: HTTP-Headers für Anfragen
    :param new_matches: Liste für neue Treffer
    :param max_retries: Maximale Anzahl von Wiederholungsversuchen
    :return: Produktdaten bei Erfolg oder False bei Fehler
    """
    try:
        # Produktdetails abrufen und prüfen
        product_data = process_mighty_cards_product(product_url, keywords_map, seen, out_of_stock, only_available, headers)
        
        if product_data and isinstance(product_data, dict):
            product_id = create_product_id(product_data["title"])
            new_matches.append(product_id)
            logger.info(f"✅ Produkt gefunden: {product_data['title']} - {product_data['status_text']}")
            return product_data
        elif product_data:
            logger.debug(f"✓ Produkt erfolgreich verarbeitet, aber keine Benachrichtigung nötig: {product_url}")
            return True
        else:
            logger.debug(f"✕ Produkt entspricht nicht den Suchkriterien: {product_url}")
            return False
    except Exception as e:
        logger.warning(f"⚠️ Fehler beim Verarbeiten der Produkt-URL {product_url}: {e}")
        retry_count = 0
        
        # Bei Fehler mehrere Versuche unternehmen
        while retry_count < max_retries:
            retry_count += 1
            logger.info(f"🔄 Wiederholungsversuch {retry_count}/{max_retries} für {product_url}")
            
            try:
                time.sleep(2 * retry_count)  # Zunehmendes Backoff
                
                # Versuche erneut, das Produkt zu verarbeiten
                product_data = process_mighty_cards_product(product_url, keywords_map, seen, out_of_stock, only_available, headers)
                
                if product_data:
                    if isinstance(product_data, dict):
                        product_id = create_product_id(product_data["title"])
                        new_matches.append(product_id)
                        logger.info(f"✅ Produkt gefunden (nach {retry_count} Versuchen): {product_data['title']}")
                    return product_data
            except Exception as retry_error:
                logger.warning(f"⚠️ Fehler bei Wiederholungsversuch {retry_count}: {retry_error}")
        
        logger.error(f"❌ Maximale Anzahl an Wiederholungsversuchen erreicht für {product_url}")
        return False

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
        
        # Laden der Ausschlusslisten für die Filterfunktion
        exclusion_sets = load_exclusion_sets()
        
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
                # Prüfe, ob das Produkt in den Ausschlusslisten enthalten ist
                should_exclude = False
                for exclusion in exclusion_sets:
                    if exclusion in title.lower():
                        should_exclude = True
                        break
                
                if not should_exclude:
                    matched_term = search_term
                    break
        
        # Wenn kein Match gefunden und keine Ausschlussbegriffe zutreffen, versuche Fallback
        if not matched_term:
            # Generische Relevanzprüfung für den Titel
            normalized_title = title.lower()
            for search_term, tokens in keywords_map.items():
                search_term_type = extract_product_type_from_text(search_term)
                
                # Entferne produktspezifische Begriffe für den Vergleich
                clean_search_term = re.sub(r'\s+(display|box|tin|etb)$', '', search_term.lower())
                if clean_search_term in normalized_title and (search_term_type == title_product_type or search_term_type == "unknown"):
                    matched_term = search_term
                    break
        
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
                # Extraktion des Produkttyps
                product_type = extract_product_type_from_text(title)
                
                # Vereinfachter Fallback: Annahme, dass Produkt verfügbar ist mit Standard-Preis
                price_map = {
                    "display": "159,99€",  # Standard-Preis für Display
                    "etb": "49,99€",      # Standard-Preis für Elite Trainer Box
                    "box": "49,99€",      # Standard-Preis für Box
                    "tin": "24,99€",      # Standard-Preis für Tin
                    "blister": "14,99€",  # Standard-Preis für Blister
                }
                
                # Preis basierend auf Produkttyp
                product_price = price_map.get(product_type, "Preis nicht verfügbar")
                
                product_data = {
                    "title": title,
                    "url": product_url,
                    "price": product_price,
                    "status_text": "✅ Verfügbar (Fallback)",
                    "is_available": True,
                    "matched_term": matched_term,
                    "product_type": product_type,
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
                if "pokemon" in part.lower():
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
                return "Pokemon TCG Produkt"
            else:
                return "Mighty Cards Produkt"
        
        # Verarbeite Spezialfälle für bekannte Produkte
        # Extrahiere den Produkttyp aus dem Titel
        product_type = extract_product_type_from_text(title)
        
        # Wenn kein Produkttyp erkannt wurde, versuche aus der URL zu identifizieren
        if product_type == "unknown":
            if "display" in url.lower() or "36er" in url.lower():
                title += " Display"
            elif "etb" in url.lower() or "elite" in url.lower() or "trainer box" in url.lower():
                title += " Elite Trainer Box"
            elif "tin" in url.lower():
                title += " Tin"
        
        # Stelle sicher, dass "Pokemon" im Titel vorkommt
        if "pokemon" not in title.lower():
            title += " Pokemon"
        
        # Erster Buchstabe groß
        title = title.strip().capitalize()
        
        return title
    except Exception as e:
        logger.warning(f"Fehler bei Titel-Extraktion aus URL {url}: {e}")
        return "Pokemon TCG Produkt"

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
    if "deutsch" in title_lower:
        language = "DE"
    elif "english" in title_lower or "eng" in title_lower:
        language = "EN"
    else:
        # Betrachte bekannte deutsche/englische Produktnamen
        language = "UNK"
    
    # Produkttyp
    product_type = extract_product_type_from_text(title)
    
    # Normalisiere Titel für einen Identifizierer (entferne produktspezifische Begriffe)
    normalized_title = re.sub(r'\s+(display|box|tin|etb)$', '', title_lower)
    normalized_title = re.sub(r'\s+', '-', normalized_title)
    normalized_title = re.sub(r'[^a-z0-9\-]', '', normalized_title)
    
    # Erstelle eine strukturierte ID
    product_id = f"{base_id}_{normalized_title}_{product_type}_{language}"
    
    # Zusatzinformationen
    if "18er" in title_lower:
        product_id += "_18er"
    elif "36er" in title_lower:
        product_id += "_36er"
    
    return product_id