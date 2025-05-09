"""
Spezieller Scraper für games-island.eu mit IP-Blockade-Umgehung und präziser Produkterkennung

Dieses Modul implementiert einen robusten Scraper für games-island.eu mit:
1. Präziser Unterscheidung zwischen Produktnamen und Produkttypen
2. Verbesserte Synonymerkennung mit verschiedenen Schreibweisen
3. Anti-Bot-Detection-Maßnahmen für zuverlässiges Scraping
"""

import requests
import logging
import re
import random
import time
import json
import warnings
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote_plus
from utils.matcher import is_keyword_in_text, extract_product_type_from_text
from utils.stock import update_product_status
from utils.availability import detect_availability
from requests.packages.urllib3.exceptions import InsecureRequestWarning

# Unterdrücke InsecureRequestWarning
warnings.simplefilter('ignore', InsecureRequestWarning)

# Logger konfigurieren
logger = logging.getLogger(__name__)

# Konstanten für den Scraper mit konservativeren Einstellungen
MAX_RETRY_ATTEMPTS = 4
STATIC_DELAY = 4  # Feste Pause zwischen Anfragen in Sekunden erhöht
LONG_TIMEOUT = 40  # Längerer Timeout für games-island.eu
BACKOFF_FACTOR = 2  # Faktor für exponentielles Backoff

# Proxy-Konfiguration (optional)
USE_PROXIES = False  # Auf True setzen, wenn Proxies verfügbar sind
PROXIES = [
    # Format: "http://user:pass@ip:port" oder "http://ip:port"
    # Beispiel: "http://123.45.67.89:8080"
]

# Lokaler Cache für gefundene Produkte um wiederholte Anfragen zu vermeiden
PRODUCT_CACHE = {}
CACHE_EXPIRY = 24 * 60 * 60  # 24 Stunden in Sekunden

# Timeout-Schutz für Kategorien
MAX_CATEGORY_ATTEMPTS = 2
CATEGORY_FAIL_TIMEOUT = 300  # 5 Minuten in Sekunden

# Fehlgeschlagene Kategorien speichern (URL -> Zeitstempel)
FAILED_CATEGORIES = {}

def scrape_games_island(keywords_map, seen, out_of_stock, only_available=False):
    """
    Spezialisierter Scraper für games-island.eu mit Anti-IP-Blocking-Maßnahmen
    und präziser Produkterkennung
    
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param seen: Set mit bereits gesehenen Produkttiteln
    :param out_of_stock: Set mit ausverkauften Produkten
    :param only_available: Ob nur verfügbare Produkte gemeldet werden sollen
    :return: Liste der neuen Treffer
    """
    logger.info("🌐 Starte speziellen Scraper für games-island.eu mit Anti-IP-Blocking")
    
    # Parse keywords_map, um Produktnamen und Produkttypen zu extrahieren
    product_info_list = parse_product_keywords(keywords_map)
    logger.info(f"🔍 {len(product_info_list)} Produktkombinationen aus Keywords extrahiert")
    
    # Optimierte/reduzierte Liste von Suchbegriffen
    search_terms = get_optimized_search_terms(product_info_list)
    logger.info(f"🔍 Verwende {len(search_terms)} optimierte Suchbegriffe")
    
    # Versuche zuerst vorbereitete Produkt-URLs
    product_list = load_cached_product_urls()
    if not product_list:
        # Wenn kein Cache, versuche mit optimierten URLs
        logger.info("🔄 Kein Produkt-Cache gefunden, verwende Kategorie-Navigation")
        product_list = fetch_products_from_categories()
    
    logger.info(f"🔍 {len(product_list)} bekannte Produkt-URLs zum Scannen")
    
    new_matches = []
    all_products = []
    
    # Zufällige Reihenfolge und erhöhte Pausen, um Bot-Erkennung zu reduzieren
    random.shuffle(product_list)
    
    # Versuche, alle bekannten Produkt-URLs zu scannen
    processed_count = 0
    for product_data in product_list:
        try:
            product_url = product_data.get('url')
            if not product_url:
                continue
                
            # Zufällige Pausen zwischen Anfragen (3-7 Sekunden)
            delay = STATIC_DELAY + random.uniform(1, 4)
            time.sleep(delay)
            
            logger.info(f"🔍 Prüfe Produkt-URL ({processed_count+1}/{len(product_list)}): {product_url}")
            
            # Versuche, die Produktdetails zu holen
            details = get_product_details(product_url, search_terms, product_info_list)
            
            if not details:
                logger.warning(f"⚠️ Keine Details für {product_url}")
                processed_count += 1
                continue
                
            # Prüfe, ob das Produkt für unsere Suche relevant ist
            title = details.get('title', '')
            if not title:
                processed_count += 1
                continue
                
            # Produktdaten vervollständigen
            details['url'] = product_url
            
            # Update Produkt-Status
            product_id = create_product_id(title)
            is_available = details.get('is_available', False)
            
            # Status aktualisieren und prüfen, ob Benachrichtigung gesendet werden soll
            should_notify, is_back_in_stock = update_product_status(
                product_id, is_available, seen, out_of_stock
            )
            
            # Bei "nur verfügbare" Option überspringen, wenn nicht verfügbar
            if only_available and not is_available:
                processed_count += 1
                continue
                
            if should_notify:
                # Zusätzliche Daten für die Benachrichtigung
                status_text = details.get('status_text', '')
                if is_back_in_stock:
                    status_text = "🎉 Wieder verfügbar!"
                
                product_type = details.get('product_type', extract_product_type_from_text(title))
                
                # Bestimme, welcher Suchbegriff getroffen wurde
                matched_term = details.get('matched_term', '')
                
                product_data = {
                    "title": title,
                    "url": product_url,
                    "price": details.get('price', 'Preis nicht verfügbar'),
                    "status_text": status_text,
                    "is_available": is_available,
                    "matched_term": matched_term,
                    "product_type": product_type,
                    "shop": "games-island.eu",
                    "product_id": product_id
                }
                
                all_products.append(product_data)
                new_matches.append(product_id)
                logger.info(f"✅ Neuer Treffer bei games-island.eu: {title} - {status_text}")
            
            processed_count += 1
            
            # Regelmäßiges Speichern des Caches
            if processed_count % 5 == 0:
                save_product_cache(PRODUCT_CACHE)
                
        except Exception as e:
            logger.error(f"❌ Fehler bei der Verarbeitung: {e}")
            processed_count += 1
            continue
    
    # Speichere den aktualisierten Cache
    if PRODUCT_CACHE:
        save_product_cache(PRODUCT_CACHE)
    
    # Sende Benachrichtigungen für gefundene Produkte
    if all_products:
        send_batch_notifications(all_products)
    
    return new_matches

def parse_product_keywords(keywords_map):
    """
    Extrahiert Produktnamen und Produkttypen aus den Suchbegriffen
    
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :return: Liste von Dictionaries mit Produktname und Produkttyp
    """
    product_info_list = []
    
    for search_term in keywords_map.keys():
        # Extrahiere Produkttyp vom Ende des Suchbegriffs
        product_type = extract_product_type_from_text(search_term)
        
        # Entferne Produkttyp vom Ende, um Produktnamen zu erhalten
        product_name = re.sub(r'\s+(display|etb|ttb|box|tin|blister)$', '', search_term.lower(), re.IGNORECASE).strip()
        
        # Erstelle Varianten des Produktnamens für besseres Matching
        name_variants = generate_name_variants(product_name)
        
        # Erstelle Varianten des Produkttyps für besseres Matching
        type_variants = generate_type_variants(product_type)
        
        # Füge Informationen zur Liste hinzu
        product_info_list.append({
            'original_term': search_term,
            'product_name': product_name,
            'product_type': product_type,
            'name_variants': name_variants,
            'type_variants': type_variants
        })
    
    return product_info_list

def generate_name_variants(product_name):
    """
    Generiert Varianten des Produktnamens für flexibles Matching
    
    :param product_name: Ursprünglicher Produktname
    :return: Liste mit Namensvarianten
    """
    variants = [product_name]
    
    # Mit und ohne Bindestriche
    if ' ' in product_name:
        variants.append(product_name.replace(' ', '-'))
    if '-' in product_name:
        variants.append(product_name.replace('-', ' '))
    
    # Ohne Leerzeichen und Bindestriche
    compact_variant = product_name.replace(' ', '').replace('-', '')
    if compact_variant != product_name and compact_variant not in variants:
        variants.append(compact_variant)
    
    # Umlaute-Varianten
    umlaut_mapping = {
        'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'ß': 'ss',
        'Ä': 'Ae', 'Ö': 'Oe', 'Ü': 'Ue'
    }
    
    # Prüfe, ob der Name Umlaute enthält
    has_umlauts = any(umlaut in product_name for umlaut in umlaut_mapping.keys())
    
    if has_umlauts:
        # Ersetze Umlaute
        umlaut_variant = product_name
        for umlaut, replacement in umlaut_mapping.items():
            umlaut_variant = umlaut_variant.replace(umlaut, replacement)
            
        if umlaut_variant not in variants:
            variants.append(umlaut_variant)
            
            # Auch Varianten mit Bindestrichen/ohne Leerzeichen für die Umlaut-Variante
            if ' ' in umlaut_variant:
                variants.append(umlaut_variant.replace(' ', '-'))
            if '-' in umlaut_variant:
                variants.append(umlaut_variant.replace('-', ' '))
    
    # Umgekehrt: Wandle "ae", "oe", "ue" in Umlaute um für URLs, die mit Umlauten kodiert sind
    if 'ae' in product_name or 'oe' in product_name or 'ue' in product_name:
        reverse_umlaut_variant = product_name
        reverse_mapping = {v: k for k, v in umlaut_mapping.items()}
        
        # Zwei-Zeichen-Ersetzungen zuerst behandeln
        for replacement, umlaut in reverse_mapping.items():
            if len(replacement) > 1:  # Nur "ae", "oe", "ue", etc.
                reverse_umlaut_variant = reverse_umlaut_variant.replace(replacement, umlaut)
                
        if reverse_umlaut_variant not in variants:
            variants.append(reverse_umlaut_variant)
    
    return variants

def generate_type_variants(product_type):
    """
    Generiert Varianten des Produkttyps für flexibles Matching
    
    :param product_type: Ursprünglicher Produkttyp
    :return: Liste mit Typvarianten
    """
    # Standard-Varianten für bekannte Produkttypen
    type_mapping = {
        "display": [
            "display", "booster display", "36er display", "36-er display", 
            "36 booster", "36er booster", "booster box", "36er box", "box", 
            "booster-box", "18er display", "18er booster", "18-er display"
        ],
        "etb": [
            "etb", "elite trainer box", "elite-trainer-box", "elite trainer",
            "trainer box", "elite-trainer", "elitetrainerbox"
        ],
        "ttb": [
            "ttb", "top trainer box", "top-trainer-box", "top trainer",
            "trainer box", "top-trainer", "toptrainerbox"
        ],
        "blister": [
            "blister", "3pack", "3-pack", "3er pack", "3er blister", 
            "sleeved booster", "sleeve booster", "check lane", "checklane"
        ],
        "tin": [
            "tin", "tin box", "metal box", "metalbox"
        ],
        "box": [
            "box", "box set", "boxset", "collector box", "collection box"
        ]
    }
    
    # Wenn unbekannter Produkttyp, leere Liste zurückgeben
    if product_type == "unknown" or product_type not in type_mapping:
        return []
    
    return type_mapping.get(product_type, [product_type])

def get_optimized_search_terms(product_info_list):
    """
    Erstellt eine optimierte Liste von Suchbegriffen aus Produktinformationen
    
    :param product_info_list: Liste mit Produktinformationen
    :return: Liste mit optimierten Suchbegriffen
    """
    search_terms = []
    
    # Sammle alle Produktnamen (ohne Duplikate)
    for product_info in product_info_list:
        product_name = product_info['product_name']
        if product_name and product_name not in search_terms:
            search_terms.append(product_name)
    
    # Sammle spezifische Schlüsselwörter für bessere Suchtreffer
    special_keywords = []
    for product_info in product_info_list:
        # Sammle spezielle Kürzel wie "sv09", "kp09"
        code_match = re.search(r'(sv\d+|kp\d+)', product_info['product_name'].lower())
        if code_match and code_match.group(0) not in special_keywords:
            special_keywords.append(code_match.group(0))
            
        # Füge einzigartige Produktnamen hinzu (ohne allgemeine Begriffe)
        name_parts = product_info['product_name'].lower().split()
        for part in name_parts:
            if (len(part) > 3 and part not in special_keywords and
                part not in ["pokemon", "pokémon", "und", "and", "the"]):
                special_keywords.append(part)
    
    # Füge spezielle Keywords zur Suchbegriffsliste hinzu
    for keyword in special_keywords:
        if keyword not in search_terms:
            search_terms.append(keyword)
    
    return search_terms

def load_cached_product_urls(cache_file="data/games_island_cache.json"):
    """
    Lädt zuvor gefundene Produkt-URLs aus der Cache-Datei
    
    :param cache_file: Pfad zur Cache-Datei
    :return: Liste mit Produkt-URL-Daten
    """
    try:
        import os
        from pathlib import Path
        
        # Stelle sicher, dass das Verzeichnis existiert
        Path(os.path.dirname(cache_file)).mkdir(parents=True, exist_ok=True)
        
        if os.path.exists(cache_file):
            with open(cache_file, "r", encoding="utf-8") as f:
                cache_data = json.load(f)
                # Aktualisiere den globalen Cache
                global PRODUCT_CACHE
                PRODUCT_CACHE = cache_data
                
                # Extrahiere relevante Produkt-Einträge
                product_list = []
                current_time = time.time()
                
                for product_id, data in cache_data.items():
                    # Überspringe Metadaten-Einträge
                    if product_id == "last_update":
                        continue
                        
                    # Prüfe auf Verfall des Cache-Eintrags
                    last_checked = data.get("last_checked", 0)
                    if current_time - last_checked > CACHE_EXPIRY:
                        continue
                        
                    product_list.append({
                        'url': data.get('url', ''),
                        'title': data.get('title', '')
                    })
                
                logger.info(f"ℹ️ {len(product_list)} Produkte aus Cache geladen")
                return product_list
        
        logger.info("ℹ️ Keine Cache-Datei gefunden")
        return []
    except Exception as e:
        logger.error(f"❌ Fehler beim Laden des Produkt-Caches: {e}")
        return []

def save_product_cache(cache_data, cache_file="data/games_island_cache.json"):
    """
    Speichert gefundene Produkt-URLs in der Cache-Datei
    
    :param cache_data: Cache-Daten als Dictionary
    :param cache_file: Pfad zur Cache-Datei
    :return: True bei Erfolg, False bei Fehler
    """
    try:
        import os
        from pathlib import Path
        
        # Stelle sicher, dass das Verzeichnis existiert
        Path(os.path.dirname(cache_file)).mkdir(parents=True, exist_ok=True)
        
        # Aktualisiere Zeitstempel
        cache_data["last_update"] = int(time.time())
        
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"ℹ️ Produkt-Cache gespeichert mit {len(cache_data)-1} Einträgen")
        return True
    except Exception as e:
        logger.error(f"❌ Fehler beim Speichern des Produkt-Caches: {e}")
        return False

def fetch_products_from_categories():
    """
    Fetcht Produkte aus den bekannten Pokemon-Kategorien bei games-island.eu
    
    :return: Liste mit Produkt-URL-Daten
    """
    product_urls = []
    all_found_products = {}  # Dictionary zur Deduplizierung
    
    # Definiere Kategorie-URLs für Pokemon Produkte
    category_urls = [
        "https://games-island.eu/Pokemon-Booster-Displays",
        "https://games-island.eu/Pokemon-Booster-Displays-deutsch",
        "https://games-island.eu/Pokemon-Booster-Displays-englisch",
        "https://games-island.eu/Pokemon-Elite-Trainer-Box"
    ]
    
    for category_url in category_urls:
        # Überprüfe, ob diese Kategorie kürzlich fehlgeschlagen ist
        if category_url in FAILED_CATEGORIES:
            last_fail_time = FAILED_CATEGORIES[category_url]
            if time.time() - last_fail_time < CATEGORY_FAIL_TIMEOUT:
                logger.info(f"⏩ Überspringe kürzlich fehlgeschlagene Kategorie: {category_url}")
                continue
        
        try:
            # Zufällige Pause zwischen Kategoriebesuchen
            time.sleep(3 + random.uniform(1, 3))
            
            logger.info(f"🔍 Durchsuche Kategorie: {category_url}")
            
            # Verwende Cloud-freundliche Header
            headers = get_cloudflare_friendly_headers()
            
            # Verwende Session für bessere Performance und Cookie-Handling
            session = requests.Session()
            session.headers.update(headers)
            
            # Abrufen der Kategorieseite mit verkleinertem Timeout
            response = session.get(
                category_url,
                timeout=30,  # Verringert von 40 auf 30 Sekunden
                allow_redirects=True,
                verify=False
            )
            
            if response.status_code != 200:
                logger.warning(f"⚠️ HTTP-Fehlercode {response.status_code} für {category_url}")
                FAILED_CATEGORIES[category_url] = time.time()
                continue
                
            # Parsen mit BeautifulSoup
            soup = BeautifulSoup(response.content, "html.parser")
            
            # Finde alle Produktlinks in dieser Kategorie
            category_products = extract_product_links_from_category(soup, category_url)
            
            for product in category_products:
                product_url = product.get('url')
                product_title = product.get('title', '')
                
                # Nur eindeutige URLs hinzufügen
                if product_url and product_url not in all_found_products:
                    all_found_products[product_url] = {
                        'url': product_url,
                        'title': product_title
                    }
                    
            logger.info(f"✅ {len(category_products)} Produkte in Kategorie {category_url} gefunden")
            
        except requests.exceptions.Timeout:
            logger.error(f"❌ Timeout beim Scrapen der Kategorie {category_url}")
            FAILED_CATEGORIES[category_url] = time.time()
        except requests.exceptions.ConnectionError:
            logger.error(f"❌ Verbindungsfehler beim Scrapen der Kategorie {category_url}")
            FAILED_CATEGORIES[category_url] = time.time()
        except Exception as e:
            logger.error(f"❌ Fehler beim Scrapen der Kategorie {category_url}: {e}")
            FAILED_CATEGORIES[category_url] = time.time()
    
    # Konvertiere das Dictionary in eine Liste
    for url, data in all_found_products.items():
        product_urls.append(data)
        
    logger.info(f"✅ Insgesamt {len(product_urls)} eindeutige Produkte aus Kategorien extrahiert")
    
    return product_urls

def extract_product_links_from_category(soup, category_url):
    """
    Extrahiert Produktlinks aus einer Kategorieseite
    
    :param soup: BeautifulSoup-Objekt der Kategorieseite
    :param category_url: URL der Kategorieseite für Basis-URLs
    :return: Liste mit Produkt-URL-Daten
    """
    products = []
    
    # Bekannte Selektoren für Produktelemente bei games-island.eu
    product_item_selectors = [
        ".product-item-info",  # Standard
        ".product.item",       # Alternative
        ".product-items .item" # Fallback
    ]
    
    # Probiere verschiedene Selektoren
    product_items = []
    for selector in product_item_selectors:
        items = soup.select(selector)
        if items:
            product_items = items
            break
    
    # Falls keine Produkte gefunden wurden, versuche einen alternativen Ansatz
    if not product_items:
        # Suche nach allen Links, die auf Produktseiten führen könnten
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if any(segment in href for segment in ["/Pokemon-", "product/"]):
                title_elem = link.select_one("span.product-item-name, .product-name, .name")
                title = title_elem.get_text().strip() if title_elem else link.get_text().strip()
                
                # Prüfe auf "Pokemon" im Titel
                if "pokemon" in title.lower() or "pokémon" in title.lower():
                    products.append({
                        "url": href if href.startswith("http") else urljoin(category_url, href),
                        "title": title
                    })
    
    # Verarbeite gefundene Produktelemente
    for item in product_items:
        # Suche nach dem Link und dem Titel
        link = item.select_one("a.product-item-link, a.product-name, a[title], a.name")
        if not link:
            continue
            
        href = link.get("href", "")
        if not href:
            continue
            
        # Extrahiere den Titel
        title = link.get("title") or link.get_text().strip()
        
        # Absoluten Link erstellen
        product_url = href if href.startswith("http") else urljoin(category_url, href)
        
        # Nur Pokemon-Produkte hinzufügen
        if "pokemon" in title.lower() or "pokémon" in title.lower():
            products.append({
                "url": product_url,
                "title": title
            })
    
    return products

def get_cloudflare_friendly_headers():
    """
    Erstellt Cloudflare-freundliche HTTP-Headers mit zufälligem User-Agent
    
    :return: Dictionary mit HTTP-Headers
    """
    user_agents = [
        # Desktop Browser
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.45 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.93 Safari/537.36 Edg/96.0.1054.43",
    ]
    
    # Länderspezifische Akzeptanz-Header für DE
    accept_language = "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7"
    
    # Zufällige Referer von bekannten Webseiten
    referers = [
        "https://www.google.de/",
        "https://www.google.com/",
        "https://www.bing.com/",
        "https://duckduckgo.com/",
        "https://www.pokemon.com/de/",
        "https://www.pokemoncenter.com/",
        "https://games-island.eu/"  # Selbst-Referenzierung für mehr Natürlichkeit
    ]
    
    # Cloudflare prüft diese Header besonders
    return {
        "User-Agent": random.choice(user_agents),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": accept_language,
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": random.choice(referers),
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
        "sec-ch-ua": '"Not A;Brand";v="99", "Chromium";v="96", "Google Chrome";v="96"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"'
    }

def get_product_details(url, search_terms, product_info_list):
    """
    Holt Produktdetails und prüft auf Übereinstimmung mit Suchkriterien
    
    :param url: Produkt-URL
    :param search_terms: Liste mit Suchbegriffen zur Relevanzprüfung
    :param product_info_list: Liste mit Produktinformationen (Name + Typ)
    :return: Dictionary mit Produktdetails oder None bei Fehler/Nichtübereinstimmung
    """
    # Zuerst im Cache suchen
    product_id = url_to_id(url)
    if product_id in PRODUCT_CACHE:
        cache_entry = PRODUCT_CACHE[product_id]
        # Prüfe, ob der Cache-Eintrag noch gültig ist
        if time.time() - cache_entry.get("last_checked", 0) < CACHE_EXPIRY:
            logger.info(f"ℹ️ Verwende Cache-Eintrag für {url}")
            return cache_entry
    
    # Verwende Cloud-freundliche Header
    headers = get_cloudflare_friendly_headers()
    
    retry_count = 0
    while retry_count < MAX_RETRY_ATTEMPTS:
        try:
            # Bei Wiederholungsversuchen: Exponentielles Backoff mit Jitter
            if retry_count > 0:
                wait_time = BACKOFF_FACTOR ** retry_count + random.uniform(1.0, 3.0)
                logger.info(f"🔄 Wiederholungsversuch {retry_count}/{MAX_RETRY_ATTEMPTS} in {wait_time:.1f} Sekunden")
                time.sleep(wait_time)
                
                # Bei Wiederholungen: Header rotieren
                headers = get_cloudflare_friendly_headers()
            
            # Zweistufiger Ansatz: Zuerst GET, dann verarbeiten
            response = requests.get(
                url,
                headers=headers,
                timeout=30,  # Verringert von 40 auf 30 Sekunden
                allow_redirects=True,
                verify=False
            )
            
            # Prüfe auf Erfolg
            if response.status_code == 200:
                # Parsen mit BeautifulSoup
                soup = BeautifulSoup(response.content, "html.parser")
                
                # Extrahiere den Titel
                title = extract_title(soup)
                
                if not title:
                    logger.info(f"ℹ️ Kein Titel gefunden für {url}")
                    return None
                
                # Prüfe Übereinstimmung mit den Produktinformationen
                matched_info = match_product_info(title, product_info_list)
                
                if not matched_info:
                    logger.info(f"ℹ️ Produkt nicht relevant: {title}")
                    return None
                
                # Verwende das Availability-Modul für die Verfügbarkeitsprüfung
                is_available, price, status_text = detect_availability(soup, url)
                
                # Erstelle Produktdetails
                product_details = {
                    "title": title,
                    "price": price,
                    "is_available": is_available,
                    "status_text": status_text,
                    "url": url,
                    "matched_term": matched_info.get("original_term", ""),
                    "product_type": matched_info.get("product_type", ""),
                    "last_checked": int(time.time())
                }
                
                # In Cache speichern
                PRODUCT_CACHE[product_id] = product_details
                
                return product_details
                
            elif response.status_code in [403, 429]:
                # Cloudflare- oder Rate-Limiting-Probleme
                logger.warning(f"⚠️ Anti-Bot-Schutz erkannt: Status {response.status_code} für {url}")
                retry_count += 1
                # Längere Wartezeit bei 403/429
                time.sleep(5 + random.uniform(3, 7))
                continue
                
            else:
                logger.warning(f"⚠️ HTTP-Fehlercode {response.status_code} für {url}")
                retry_count += 1
                continue
                
        except requests.exceptions.Timeout:
            retry_count += 1
            logger.warning(f"⚠️ Timeout bei der Anfrage an {url} (Versuch {retry_count})")
        except requests.exceptions.RequestException as e:
            retry_count += 1
            logger.warning(f"⚠️ Fehler bei der Anfrage an {url}: {e} (Versuch {retry_count})")
        except Exception as e:
            retry_count += 1
            logger.warning(f"⚠️ Unerwarteter Fehler: {e} (Versuch {retry_count})")
    
    # Alle Versuche fehlgeschlagen
    logger.error(f"❌ Alle {MAX_RETRY_ATTEMPTS} Versuche für {url} fehlgeschlagen")
    return None

def extract_title(soup):
    """
    Extrahiert den Titel aus der Produktseite
    
    :param soup: BeautifulSoup-Objekt
    :return: Titel oder None wenn nicht gefunden
    """
    # Verschiedene Muster für Titel-Elemente probieren
    title_selectors = [
        "h1.product-title", "h1.product-name", "h1.title", "h1.page-title", "h1",
        ".product-title h1", ".product-name h1", ".product-detail h1",
        "title"  # Fallback auf <title>-Tag
    ]
    
    for selector in title_selectors:
        title_elem = soup.select_one(selector)
        if title_elem:
            title = title_elem.get_text().strip()
            # Bereinige den Titel (entferne Shop-Namen, etc.)
            title = re.sub(r'\s*[-|]\s*Games-Island.*$', '', title)
            title = re.sub(r'\s*[-|–]\s*Jetzt kaufen.*$', '', title)
            return title
    
    # Fallback auf Meta-Tags für den Titel
    meta_title = soup.find("meta", property="og:title")
    if meta_title and meta_title.get("content"):
        title = meta_title["content"].strip()
        title = re.sub(r'\s*[-|]\s*Games-Island.*$', '', title)
        return title
        
    return None

def match_product_info(title, product_info_list):
    """
    Prüft, ob ein Produkttitel mit einem der gesuchten Produkte übereinstimmt
    
    :param title: Der zu prüfende Produkttitel
    :param product_info_list: Liste mit Produktinformationen
    :return: Passendes Produktinfo-Dict oder None wenn nicht relevant
    """
    if not title:
        return None
        
    title_lower = title.lower()
    
    # Grundlegende Relevanzprüfung für Pokemon-Produkte
    if not any(term in title_lower for term in ["pokemon", "pokémon"]):
        return None
    
    # Extrahiere Produkttyp aus dem Titel
    title_product_type = extract_product_type_from_text(title)
    
    # Für jede Produktinfo-Kombination prüfen
    for product_info in product_info_list:
        product_name = product_info['product_name']
        product_type = product_info['product_type']
        name_variants = product_info['name_variants']
        type_variants = product_info['type_variants']
        
        # 1. Prüfe, ob der Produktname im Titel vorkommt (in einer der Varianten)
        name_match = False
        for variant in name_variants:
            if variant in title_lower:
                name_match = True
                break
        
        if not name_match:
            continue
        
        # 2. Prüfe, ob der Produkttyp übereinstimmt
        type_match = False
        
        # Wenn der extrahierte Typ im Titel mit dem gesuchten Typ übereinstimmt
        if title_product_type == product_type:
            type_match = True
        else:
            # Oder wenn einer der Typ-Varianten im Titel vorkommt
            for variant in type_variants:
                if variant in title_lower:
                    type_match = True
                    break
        
        # 3. Nur wenn sowohl Name als auch Typ übereinstimmen, gilt das Produkt als relevant
        if name_match and type_match:
            return product_info
    
    # Keine Übereinstimmung gefunden
    return None

def url_to_id(url):
    """
    Konvertiert eine URL in eine eindeutige ID für den Cache
    
    :param url: URL
    :return: Cache-ID
    """
    import hashlib
    return hashlib.md5(url.encode()).hexdigest()

def create_product_id(title, base_id="gamesisland"):
    """
    Erstellt eine eindeutige Produkt-ID basierend auf dem Titel
    
    :param title: Produkttitel
    :param base_id: Basis-ID (z.B. Website-Name)
    :return: Eindeutige Produkt-ID
    """
    # Extrahiere relevante Informationen für die ID
    title_lower = title.lower()
    
    # Sprache (DE/EN)
    if "deutsch" in title_lower or "(de)" in title_lower:
        language = "DE"
    elif "english" in title_lower or "(en)" in title_lower or "eng" in title_lower:
        language = "EN"
    else:
        language = "UNK"
    
    # Produkttyp
    product_type = extract_product_type_from_text(title)
    
    # Produktcode (sv09, kp09, etc.)
    code_match = re.search(r'(kp\d+|sv\d+)', title_lower)
    product_code = code_match.group(0) if code_match else "unknown"
    
    # Normalisiere Titel für einen Identifizierer
    normalized_title = re.sub(r'\s+(display|box|tin|etb)$', '', title_lower)
    normalized_title = re.sub(r'\s+', '-', normalized_title)
    normalized_title = re.sub(r'[^a-z0-9\-]', '', normalized_title)
    
    # Begrenze die Länge
    if len(normalized_title) > 50:
        normalized_title = normalized_title[:50]
    
    # Erstelle eine strukturierte ID
    product_id = f"{base_id}_{product_code}_{product_type}_{language}"
    
    return product_id

def send_batch_notifications(all_products):
    """Sendet Benachrichtigungen in Batches"""
    from utils.telegram import send_batch_notification
    
    if all_products:
        logger.info(f"📤 Sende Benachrichtigung für {len(all_products)} Produkte")
        send_batch_notification(all_products)
    else:
        logger.info("ℹ️ Keine Produkte für Benachrichtigung gefunden")