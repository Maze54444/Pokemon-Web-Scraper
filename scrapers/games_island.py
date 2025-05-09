"""
Spezieller Scraper für games-island.eu mit IP-Blockade-Umgehung durch:
1. Verwendung von cloudflare-freundlichen Headern
2. Korrekten URL-Mustern von games-island.eu
3. Anti-Bot-Detection-Maßnahmen
"""

import requests
import logging
import re
import random
import time
import json
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote_plus
from utils.matcher import is_keyword_in_text, extract_product_type_from_text
from utils.stock import update_product_status
from utils.availability import detect_availability

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

def scrape_games_island(keywords_map, seen, out_of_stock, only_available=False):
    """
    Spezialisierter Scraper für games-island.eu mit Anti-IP-Blocking-Maßnahmen
    
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param seen: Set mit bereits gesehenen Produkttiteln
    :param out_of_stock: Set mit ausverkauften Produkten
    :param only_available: Ob nur verfügbare Produkte gemeldet werden sollen
    :return: Liste der neuen Treffer
    """
    logger.info("🌐 Starte speziellen Scraper für games-island.eu mit Anti-IP-Blocking")
    
    # Verwende direktes Kategorie-Scraping statt Suche, wenn die Website blockiert
    logger.info("🔍 Verwende direkte Kategorie-Navigation statt Suche (umgeht Cloudflare)")
    
    # Optimierte/reduzierte Liste von Suchbegriffen
    search_terms = get_optimized_search_terms(keywords_map)
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
            details = get_product_details(product_url, search_terms)
            
            if not details:
                logger.warning(f"⚠️ Keine Details für {product_url}")
                processed_count += 1
                continue
                
            # Prüfe, ob das Produkt für unsere Suche relevant ist
            title = details.get('title', '')
            if not title or not is_product_relevant(title, search_terms):
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
                
                product_type = extract_product_type_from_text(title)
                
                # Bestimme, welcher Suchbegriff getroffen wurde
                matched_term = find_matching_search_term(title, keywords_map)
                
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

def get_optimized_search_terms(keywords_map):
    """
    Erstellt eine optimierte Liste von Suchbegriffen (kürzer für bessere Kompatibilität)
    
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :return: Liste mit optimierten Suchbegriffen
    """
    search_terms = []
    
    # Extrahiere Kernbegriffe (vermeide zu lange Suchbegriffe)
    core_terms = []
    for term in keywords_map.keys():
        # Extrahiere "Journey Together" oder "Reisegefährten" als Kernbegriffe
        if "journey together" in term.lower():
            core_terms.append("journey together")
        if "reisegefährten" in term.lower():
            core_terms.append("reisegefährten")
    
    # Deduplizieren
    core_terms = list(set(core_terms))
    
    # Füge Kombinationen mit relevanten Produkttypen hinzu
    product_types = ["display", "booster box", "36er", "elite trainer box", "etb"]
    
    for core in core_terms:
        # Basis-Term hinzufügen
        search_terms.append(core)
        # Mit Produkttypen kombinieren
        for ptype in product_types:
            search_terms.append(f"{core} {ptype}")
    
    # Zusätzliche Codes für das Set
    search_terms.extend(["kp09", "sv09"])
    
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
    # Bekannte Kategorie-URLs für Pokemon-Produkte
    category_urls = [
        "https://games-island.eu/pokemon",
        "https://games-island.eu/pokemon/pokemon-displays",
        "https://games-island.eu/pokemon/pokemon-einzelbooster",
        "https://games-island.eu/pokemon/pokemon-boxen",
        "https://games-island.eu/neu-eingetroffen"  # Neue Produkte
    ]
    
    product_urls = []
    all_found_products = {}  # Dictionary zur Deduplizierung
    
    for category_url in category_urls:
        try:
            # Zufällige Pause zwischen Kategoriebesuchen
            time.sleep(3 + random.uniform(1, 3))
            
            logger.info(f"🔍 Durchsuche Kategorie: {category_url}")
            
            # Verwende Cloud-freundliche Header
            headers = get_cloudflare_friendly_headers()
            
            # Verwende Session für bessere Performance und Cookie-Handling
            session = requests.Session()
            session.headers.update(headers)
            
            # Abrufen der Kategorieseite
            response = session.get(
                category_url,
                timeout=LONG_TIMEOUT,
                allow_redirects=True
            )
            
            if response.status_code != 200:
                logger.warning(f"⚠️ HTTP-Fehlercode {response.status_code} für {category_url}")
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
            
        except Exception as e:
            logger.error(f"❌ Fehler beim Scrapen der Kategorie {category_url}: {e}")
    
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
            if any(segment in href for segment in ["/pokemon/", "product/"]):
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

def get_product_details(url, search_terms):
    """
    Holt Produktdetails mit Cloud-freundlichen Headern
    
    :param url: Produkt-URL
    :param search_terms: Liste mit Suchbegriffen zur Relevanzprüfung
    :return: Dictionary mit Produktdetails oder None bei Fehler
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
    
    # Verwende Session für bessere Performance und Cookie-Handling
    session = requests.Session()
    session.headers.update(headers)
    
    retry_count = 0
    while retry_count < MAX_RETRY_ATTEMPTS:
        try:
            # Bei Wiederholungsversuchen: Exponentielles Backoff mit Jitter
            if retry_count > 0:
                wait_time = BACKOFF_FACTOR ** retry_count + random.uniform(1.0, 3.0)
                logger.info(f"🔄 Wiederholungsversuch {retry_count}/{MAX_RETRY_ATTEMPTS} in {wait_time:.1f} Sekunden")
                time.sleep(wait_time)
                
                # Bei Wiederholungen: Header rotieren
                session.headers.update(get_cloudflare_friendly_headers())
            
            # Zweistufiger Ansatz: Zuerst GET, dann verarbeiten
            response = session.get(
                url,
                timeout=LONG_TIMEOUT,
                allow_redirects=True
            )
            
            # Prüfe auf Erfolg
            if response.status_code == 200:
                # Parsen mit BeautifulSoup
                soup = BeautifulSoup(response.content, "html.parser")
                
                # Extrahiere den Titel
                title = extract_title(soup)
                
                # Prüfe Relevanz
                if not title or not is_product_relevant(title, search_terms):
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

def is_product_relevant(title, search_terms):
    """
    Prüft, ob ein Produkttitel für die Suche relevant ist
    
    :param title: Produkttitel
    :param search_terms: Liste mit Suchbegriffen
    :return: True wenn relevant, False sonst
    """
    if not title:
        return False
        
    title_lower = title.lower()
    
    # Grundlegende Relevanzprüfung für Pokemon-Produkte
    if not any(term in title_lower for term in ["pokemon", "pokémon"]):
        return False
    
    # Prüfe alle Suchbegriffe
    for term in search_terms:
        term_lower = term.lower()
        # Tokenisiere den Suchbegriff für flexibleres Matching
        tokens = term_lower.split()
        
        # Verwende die is_keyword_in_text-Funktion für besseres Matching
        if is_keyword_in_text(tokens, title_lower, log_level='None'):
            return True
    
    # Kein Treffer für Suchbegriffe
    return False

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

def find_matching_search_term(title, keywords_map):
    """
    Findet den am besten passenden Suchbegriff für einen Produkttitel
    
    :param title: Produkttitel
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :return: Passender Suchbegriff oder Standardwert
    """
    title_lower = title.lower()
    best_match = None
    max_tokens = 0
    
    for search_term, tokens in keywords_map.items():
        # Prüfe, wie viele Tokens übereinstimmen
        matching_tokens = sum(1 for token in tokens if token in title_lower)
        
        if matching_tokens > max_tokens:
            max_tokens = matching_tokens
            best_match = search_term
    
    # Wenn keine Übereinstimmung gefunden wurde, verwende einen Standardwert
    if not best_match:
        if "journey" in title_lower or "together" in title_lower:
            best_match = "Journey Together display"
        elif "reisegefährten" in title_lower:
            best_match = "Reisegefährten display"
        else:
            best_match = "Pokemon Display"
    
    return best_match

def send_batch_notifications(products):
    """Sendet Benachrichtigungen für gefundene Produkte"""
    from utils.telegram import send_batch_notification
    
    if products:
        logger.info(f"📤 Sende Benachrichtigung für {len(products)} Produkte")
        send_batch_notification(products)
    else:
        logger.info("ℹ️ Keine Produkte für Benachrichtigung gefunden")