import requests
import hashlib
import os
import json
import time
import re
import logging
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

from utils.matcher import clean_text, is_keyword_in_text, normalize_product_name, extract_product_type_from_text, is_strict_match
from utils.telegram import send_telegram_message, escape_markdown, send_product_notification, send_batch_notification
from utils.stock import get_status_text, update_product_status
from utils.availability import detect_availability

# Logger konfigurieren
logger = logging.getLogger(__name__)

# URL-Filterliste für allgemeine Filter
GLOBAL_URL_FILTERS = [
    # Trading Card Games und Konkurrenzprodukte
    "one-piece", "onepiece", "one piece",
    "disney-lorcana", "disney lorcana", "lorcana",
    "final-fantasy", "final fantasy",
    "yu-gi-oh", "yugioh", "yu gi oh",
    "union-arena", "union arena",
    "star-wars", "star wars",
    "mtg", "magic the gathering", "magic-the-gathering",
    "flesh-and-blood", "flesh and blood",
    "digimon", "metazoo", "grand archive", "sorcery",
    
    # Shop-Funktionalitäten
    "/login", "/account", "/cart", "/checkout", "/wishlist", "/warenkorb", 
    "/kontakt", "/contact", "/agb", "/impressum", "/datenschutz", 
    "/widerruf", "/hilfe", "/help", "/faq", "/versand", "/shipping",
    "/my-account", "/merkliste", "/newsletter", "/registrieren", 
    "passwort", "anmelden", "registrieren", "warenkorb", "merkliste",
    
    # Social Media und externe Links
    "youtube.com", "instagram.com", "facebook.com", "twitter.com",
    "twitch.tv", "discord", "whatsapp", "discord.gg",
    
    # Merchandise und Sammlerstücke
    "/figuren", "/plüsch", "/plush", "/funko-pop", "/funko", 
    "/merchandise", "/sammelkoffer", "schlüsselanhänger", "tassen",
    "/capsule", "fan-artikel", "binder", "playmat", "sleeves",
    
    # Andere Medien
    "/manga", "/comic", "/videospiele", "nintendo-switch",
    
    # Leere Links oder JavaScript-Links
    "javascript:", "#", "tel:", "mailto:",
]

# Domainspezifische Filter
DOMAIN_FILTERS = {
    "tcgviert.com": [
        "plusch-figuren", "zubehor-fur-deine-schatze", "structure-decks",
        "japanische-sleeves", "jobs", "battle-deck", "build-battle", 
        "sammelkoffer", "tin", "spielmatte", "toploader",
    ],
    "card-corner.de": [
        "einzelkarten", "seltenes", "kartenlisten", "erweiterungen", 
        "blog", "promos", "decks", "jtl-shop",
        "wunschzettel", "artikelnummer", "erscheinungsdatum", "gtin",
    ],
    "comicplanet.de": [
        "details", "kontaktformular", "defektes-produkt", "ruckgabe",
        "persönliches-profil", "adressen", "zahlungsarten", "bestellungen",
        "gutscheine", "store-events",
    ],
    "gameware.at": [
        "abenteuerspiele", "actionspiele", "beat-em-ups",
        "rennspiele", "rollenspiele", "shooterspiele", "sportspiele",
        "zombies", "endzeit", "blood", "gore", "coop", "vr", "4x",
        "ps5", "ps4", "xbox", "switch", "controller", "headset",
        "tastatur", "maus", "konsole", "consoles", "joystick",
        "englische", "mediabooks", "steelbooks",
        "statuen", "geldbörsen", "fußmatten", "pyramido", "uncut",
        "pegi", "psn-karten", "xbox-live", "warenkorb", "merkliste",
        "jtl-shop", "premium-edition", "mediabooks",
        "/gutscheine", "/boni", "/bonus", "deliverance",
        "yasha", "terminator", "ninja-turtles", "indiana-jones",
        "donkey-kong", "clair-obscur", "mario-kart", "lunar",
        "dead-island", "skull-and-bones", "doom", "saints-row",
        "horizon", "at-pegi", "directx", "gore",
    ],
    "kofuku.de": [
        "ultra-pro", "binder", "pocket", "gallery",
        "schlüsselanhänger", "tassen", "capsule-toys",
        "altraverse", "mangacult", "egmont", "tokyopop", "crunchyroll",
        "carlsen", "/alte-shop", "/old-shop", "/startseite", "/löschen",
    ],
    "mighty-cards.de": [
        "figuren-plüsch", "funko-pop", "dragon-ball", "naruto",
        "boruto", "sleeves-kartenhüllen", "toploader", "playmat",
        "deck-boxen", "van-gogh", "altered",
    ],
    "games-island.eu": [
        "brettspiele", "gesellschaftsspiele",
        "tabletop", "warhammer", "puzzles",
    ],
    "sapphire-cards.de": [
        "einzelkarten", "singles", "sleeves",
        "deckboxen", "binder", "dice", "würfel", "playmats",
    ],
    "fantasiacards.de": [
        "einzelkarten", "singles", "sleeves", "zubehör",
        "miniatur", "plush", "zubehör", "/manga", "/comics"
    ]
}

def create_session():
    """Erstellt eine requests Session mit Retry-Mechanismus"""
    session = requests.Session()
    
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS"]
    )
    
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    return session

def load_product_cache(cache_file="data/product_cache.json"):
    """Lädt das Cache-Dictionary mit bekannten Produkten und ihren URLs"""
    try:
        Path(cache_file).parent.mkdir(parents=True, exist_ok=True)
        
        if os.path.exists(cache_file):
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        logger.info(f"ℹ️ Produkt-Cache-Datei nicht gefunden. Neuer Cache wird erstellt.")
        return {}
    except Exception as e:
        logger.error(f"⚠️ Fehler beim Laden des Produkt-Caches: {e}")
        return {}

def save_product_cache(cache, cache_file="data/product_cache.json"):
    """Speichert das Cache-Dictionary mit bekannten Produkten"""
    try:
        Path(cache_file).parent.mkdir(parents=True, exist_ok=True)
        
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        logger.debug(f"✅ Produkt-Cache mit {len(cache)} Einträgen gespeichert")
    except Exception as e:
        logger.error(f"⚠️ Fehler beim Speichern des Produkt-Caches: {e}")

def create_fingerprint(html_content):
    """Erstellt einen Fingerprint vom HTML-Inhalt, um Änderungen zu erkennen"""
    return hashlib.md5(html_content.encode('utf-8')).hexdigest()

def extract_product_type_from_search_term(search_term):
    """Extrahiert den Produkttyp direkt aus einem Suchbegriff"""
    return extract_product_type_from_text(search_term)

def get_domain(url):
    """Extrahiert die Domain aus einer URL ohne www. Präfix"""
    try:
        parsed_url = urlparse(url)
        domain = parsed_url.netloc
        
        if domain.startswith('www.'):
            domain = domain[4:]
            
        return domain.lower()
    except Exception:
        return url.lower()

def should_filter_url(url, link_text=""):
    """Prüft, ob eine URL gefiltert werden soll"""
    if not url:
        return True
        
    normalized_url = url.lower()
    normalized_text = link_text.lower() if link_text else ""
    
    domain = get_domain(url)
    
    # 1. Prüfe globale URL-Filter
    for filter_term in GLOBAL_URL_FILTERS:
        if filter_term in normalized_url:
            return True
            
    # 2. Prüfe domainspezifische Filter
    for site, filters in DOMAIN_FILTERS.items():
        if site in domain:
            for filter_term in filters:
                if filter_term in normalized_url or (normalized_text and filter_term in normalized_text):
                    return True
                    
    # 3. Zusätzliche Heuristiken für Produktlinks vs. andere Seiten
    if "/category/" in normalized_url or "/collection/" in normalized_url:
        relevant_keywords = ["pokemon", "display", "booster", "trainer", "box", "etb", "ttb"]
        if not any(keyword in normalized_url for keyword in relevant_keywords) and not any(keyword in normalized_text for keyword in relevant_keywords):
            return True
            
    return False

def scrape_generic(url, keywords_map, seen, out_of_stock, check_availability=True, only_available=False):
    """
    Generische Scraper-Funktion mit verbesserter SSL-Behandlung
    """
    logger.info(f"🌐 Starte generischen Scraper für {url}")
    new_matches = []
    
    # Erstelle Session mit Retry-Mechanismus
    session = create_session()
    
    # Cache laden
    product_cache = load_product_cache()
    site_id = get_domain(url)
    
    # Prüfe, ob wir neue Keywords haben
    cache_key = f"{site_id}_keywords"
    cached_keywords = product_cache.get(cache_key, [])
    current_keywords = list(keywords_map.keys())
    
    new_keywords = [k for k in current_keywords if k not in cached_keywords]
    if new_keywords:
        logger.info(f"🔍 Neue Suchbegriffe gefunden: {new_keywords}")
        full_scan_needed = True
    else:
        full_scan_needed = False
    
    all_products = []
    
    # Extrahiere den Produkttyp aus dem ersten Suchbegriff
    search_product_type = None
    if current_keywords:
        sample_search_term = current_keywords[0]
        search_product_type = extract_product_type_from_text(sample_search_term)
        logger.debug(f"🔍 Suche nach Produkttyp: '{search_product_type}' basierend auf '{sample_search_term}'")
    
    url_hash = hashlib.md5(url.encode('utf-8')).hexdigest()[:10]
    found_product_ids = set()
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        
        # SSL-Behandlung für problematische Domains
        if "gameware.at" in url:
            # Für gameware.at SSL-Verifizierung deaktivieren
            session.verify = False
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        domain_paths = product_cache.get(site_id, {})
        
        # Spezielle Pfadmuster für bekannte Shops
        if site_id == "mighty-cards.de" and not domain_paths:
            logger.info(f"🔍 Spezielle Pfadmuster für {site_id} werden verwendet")
            shop_paths = [
                "/shop/Pokemon",
                "/pokemon/",
                "/shop/Vorbestellung-c166467816"
            ]
            
            for shop_path in shop_paths:
                path_url = f"https://{site_id}{shop_path}"
                product_id = f"{site_id}_{hashlib.md5(path_url.encode()).hexdigest()[:8]}"
                domain_paths[product_id] = {
                    "url": path_url,
                    "term": current_keywords[0] if current_keywords else "Pokemon",
                    "last_checked": 0,
                    "is_available": False
                }
            
            product_cache[site_id] = domain_paths
        
        elif site_id == "fantasiacards.de" and not domain_paths:
            logger.info(f"🔍 Spezielle Pfadmuster für {site_id} werden verwendet")
            shop_paths = [
                "/collections/pokemon-1",
                "/collections/pokemon-neuheiten"
            ]
            
            for shop_path in shop_paths:
                path_url = f"https://{site_id}{shop_path}"
                product_id = f"{site_id}_{hashlib.md5(path_url.encode()).hexdigest()[:8]}"
                domain_paths[product_id] = {
                    "url": path_url,
                    "term": current_keywords[0] if current_keywords else "Pokemon",
                    "last_checked": 0,
                    "is_available": False
                }
            
            product_cache[site_id] = domain_paths
        
        if domain_paths and not full_scan_needed:
            logger.info(f"🔍 Nutze {len(domain_paths)} gecachte Produktpfade für {site_id}")
            
            checked_products = 0
            
            for product_id, product_info in list(domain_paths.items()):
                if product_id == cache_key:
                    continue
                
                checked_products += 1
                
                product_url = product_info.get("url", "")
                matched_term = product_info.get("term", "")
                last_checked = product_info.get("last_checked", 0)
                
                if matched_term not in keywords_map:
                    continue
                
                if time.time() - last_checked < 7200:  # 2 Stunden
                    logger.debug(f"⏱️ Überspringe kürzlich geprüftes Produkt: {product_url}")
                    continue
                
                try:
                    response = session.get(product_url, headers=headers, timeout=10)
                    if response.status_code != 200:
                        logger.warning(f"⚠️ Fehler beim Abrufen von {product_url}: Status {response.status_code}")
                        
                        if response.status_code in (404, 410):
                            logger.info(f"🗑️ Entferne nicht mehr verfügbare Produktpfad: {product_url}")
                            domain_paths.pop(product_id, None)
                        continue
                    
                    current_fingerprint = create_fingerprint(response.text)
                    stored_fingerprint = product_info.get("fingerprint", "")
                    
                    soup = BeautifulSoup(response.text, "html.parser")
                    
                    title_elem = soup.find('title')
                    link_text = title_elem.text.strip() if title_elem else ""
                    
                    tokens = keywords_map.get(matched_term, [])
                    
                    # Verwende strengeres Matching
                    if not is_strict_match(tokens, link_text, threshold=0.8):
                        logger.debug(f"⚠️ Produkt entspricht nicht mehr dem Suchbegriff '{matched_term}': {link_text}")
                        continue
                    
                    domain_paths[product_id]["last_checked"] = time.time()
                    
                    if current_fingerprint != stored_fingerprint or not stored_fingerprint:
                        logger.info(f"🔄 Änderung erkannt oder erste Prüfung: {product_url}")
                        domain_paths[product_id]["fingerprint"] = current_fingerprint
                        
                        is_available, price, status_text = detect_availability(soup, product_url)
                        
                        domain_paths[product_id]["is_available"] = is_available
                        domain_paths[product_id]["price"] = price
                        
                        should_notify, is_back_in_stock = update_product_status(
                            product_id, is_available, seen, out_of_stock
                        )
                        
                        if should_notify and (not only_available or is_available):
                            if is_back_in_stock:
                                status_text = "🎉 Wieder verfügbar!"
                            elif not status_text:
                                status_text = get_status_text(is_available, is_back_in_stock)
                            
                            product_data = {
                                "title": link_text,
                                "url": product_url,
                                "price": price,
                                "status_text": status_text,
                                "is_available": is_available,
                                "matched_term": matched_term,
                                "product_type": extract_product_type_from_text(link_text),
                                "shop": site_id
                            }
                            
                            if product_id not in found_product_ids:
                                all_products.append(product_data)
                                new_matches.append(product_id)
                                found_product_ids.add(product_id)
                                logger.info(f"✅ Cache-Treffer: {link_text} - {status_text}")
                    else:
                        logger.debug(f"✓ Keine Änderung für {product_url}")
                        
                except Exception as e:
                    logger.warning(f"⚠️ Fehler bei der Verarbeitung von {product_url}: {e}")
            
            product_cache[site_id] = domain_paths
            save_product_cache(product_cache)
        
        if full_scan_needed or not domain_paths:
            logger.info(f"🔍 Durchführung eines vollständigen Scans für {url}")
            
            try:
                response = session.get(url, headers=headers, timeout=15)
                if response.status_code != 200:
                    logger.warning(f"⚠️ Fehler beim Abrufen von {url}: Status {response.status_code}")
                    return new_matches
            except requests.exceptions.RequestException as e:
                logger.warning(f"⚠️ Netzwerkfehler beim Abrufen von {url}: {e}")
                return new_matches
            
            soup = BeautifulSoup(response.text, "html.parser")
            
            page_title = soup.title.text.strip() if soup.title else url
            
            all_links = soup.find_all('a', href=True)
            
            potential_product_links = []
            
            for a_tag in all_links:
                href = a_tag.get('href', '')
                if not href or href.startswith('#') or href.startswith('javascript:'):
                    continue
                
                link_text = a_tag.get_text().strip().lower()
                
                if should_filter_url(href, link_text):
                    continue
                
                if '/product/' in href or '/products/' in href or '/produkt/' in href or 'detail' in href:
                    potential_product_links.append((href, a_tag.get_text().strip()))
                    continue
                
                if site_id == "mighty-cards.de" and ('/shop/' in href or '/p' in href):
                    potential_product_links.append((href, a_tag.get_text().strip()))
                    continue
                
                for search_term, tokens in keywords_map.items():
                    # Verwende strengeres Matching
                    if is_strict_match(tokens, link_text, threshold=0.7):
                        potential_product_links.append((href, a_tag.get_text().strip()))
                        break
            
            logger.info(f"🔍 {len(potential_product_links)} potenzielle Produktlinks gefunden auf {url}")
            
            for href, link_text in potential_product_links:
                if href.startswith('http'):
                    product_url = href
                elif href.startswith('/'):
                    base_url = '/'.join(url.split('/')[:3])
                    product_url = f"{base_url}{href}"
                else:
                    product_url = f"{url.rstrip('/')}/{href.lstrip('/')}"
                
                product_id = create_product_id(link_text, site_id=site_id)
                
                if product_id in found_product_ids:
                    continue
                
                matched_term = None
                for search_term, tokens in keywords_map.items():
                    if is_strict_match(tokens, link_text, threshold=0.7):
                        matched_term = search_term
                        break
                
                if not matched_term:
                    continue
                
                is_available = True
                price = "Preis nicht verfügbar"
                status_text = ""
                detail_soup = None
                
                if check_availability:
                    try:
                        detail_response = session.get(product_url, headers=headers, timeout=10)
                        if detail_response.status_code != 200:
                            logger.warning(f"⚠️ Fehler beim Abrufen der Produktdetails: Status {detail_response.status_code}")
                            continue
                            
                        detail_soup = BeautifulSoup(detail_response.text, "html.parser")
                        
                        is_available, price, status_text = detect_availability(detail_soup, product_url)
                        
                        detail_title = detail_soup.find('title')
                        if detail_title:
                            detail_title_text = detail_title.text.strip()
                            tokens = keywords_map.get(matched_term, [])
                            
                            # Strikte Prüfung auch auf der Detailseite
                            if not is_strict_match(tokens, detail_title_text, threshold=0.7):
                                logger.debug(f"❌ Detailseite passt nicht zum Suchbegriff '{matched_term}': {detail_title_text}")
                                continue
                            
                            link_text = detail_title_text
                        
                        if site_id not in product_cache:
                            product_cache[site_id] = {}
                        
                        fingerprint = ""
                        if detail_soup:
                            html_content = str(detail_soup)
                            fingerprint = create_fingerprint(html_content)
                        
                        product_cache[site_id][product_id] = {
                            "url": product_url,
                            "term": matched_term,
                            "is_available": is_available,
                            "price": price,
                            "last_checked": time.time(),
                            "fingerprint": fingerprint,
                            "product_type": extract_product_type_from_text(link_text)
                        }
                        
                    except Exception as e:
                        logger.warning(f"⚠️ Fehler beim Prüfen der Verfügbarkeit für {product_url}: {e}")
                
                should_notify, is_back_in_stock = update_product_status(
                    product_id, is_available, seen, out_of_stock
                )
                
                if should_notify and (not only_available or is_available):
                    if is_back_in_stock:
                        status_text = "🎉 Wieder verfügbar!"
                    elif not status_text:
                        status_text = get_status_text(is_available, is_back_in_stock)
                    
                    product_type = extract_product_type_from_text(link_text)
                    
                    if product_id not in found_product_ids:
                        product_data = {
                            "title": link_text,
                            "url": product_url,
                            "price": price,
                            "status_text": status_text,
                            "is_available": is_available,
                            "matched_term": matched_term,
                            "product_type": product_type,
                            "shop": site_id
                        }
                        
                        all_products.append(product_data)
                        new_matches.append(product_id)
                        found_product_ids.add(product_id)
                        logger.info(f"✅ Neuer Treffer gefunden: {link_text} - {status_text}")
            
            product_cache[cache_key] = current_keywords
            
            save_product_cache(product_cache)
        
        if all_products:
            send_batch_notification(all_products)
    
    except Exception as e:
        logger.error(f"❌ Fehler beim generischen Scraping von {url}: {e}", exc_info=True)
    
    return new_matches

def check_product_availability(url, headers):
    """Besucht die Produktdetailseite und prüft die Verfügbarkeit"""
    logger.info(f"🔍 Prüfe Produktdetails für {url}")
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return None, False, "Preis nicht verfügbar", "❌ Ausverkauft (Fehler beim Laden)"
    except requests.exceptions.RequestException as e:
        logger.warning(f"⚠️ Netzwerkfehler beim Abrufen von {url}: {e}")
        return None, False, "Preis nicht verfügbar", "❌ Ausverkauft (Fehler beim Laden)"
    
    soup = BeautifulSoup(response.text, "html.parser")
    
    is_available, price, status_text = detect_availability(soup, url)
    
    logger.debug(f"  - Verfügbarkeit für {url}: {status_text}")
    logger.debug(f"  - Preis: {price}")
    
    return soup, is_available, price, status_text

def extract_product_type(text):
    """Extrahiert den Produkttyp aus einem Text"""
    return extract_product_type_from_text(text)

def create_product_id(product_title, site_id="generic"):
    """Erstellt eine eindeutige Produkt-ID"""
    series_code, product_type, language = extract_product_info(product_title)
    
    product_id = f"{site_id}_{series_code}_{product_type}_{language}"
    
    if "premium" in product_title.lower():
        product_id += "_premium"
    if "elite" in product_title.lower():
        product_id += "_elite"
    if "top" in product_title.lower() and "trainer" in product_title.lower():
        product_id += "_top"
    
    return product_id

def extract_product_info(title):
    """Extrahiert wichtige Produktinformationen aus dem Titel"""
    # Initialisiere Standardwerte
    series_code = "unknown"
    product_type = "unknown"
    language = "UNK"
    
    # Erkenne Sprache
    if "(DE)" in title or "pro Person" in title or "deutsch" in title.lower() or "deu" in title.lower():
        language = "DE"
    elif "(EN)" in title or "per person" in title or "english" in title.lower() or "eng" in title.lower():
        language = "EN"
    elif "(JP)" in title or "japan" in title.lower() or "jpn" in title.lower():
        language = "JP"
    
    # Extrahiere Produkttyp mit der verbesserten Funktion
    detected_type = extract_product_type_from_text(title)
    if detected_type != "unknown":
        product_type = detected_type
    else:
        # Fallback zur alten Methode
        if re.search(r'display|36er', title.lower()):
            product_type = "display"
        elif re.search(r'etb|elite trainer box', title.lower()):
            product_type = "etb"
        elif re.search(r'ttb|top trainer box', title.lower()):
            product_type = "ttb"
        elif re.search(r'booster|pack|sleeve', title.lower()):
            product_type = "booster"
        elif re.search(r'box|tin', title.lower()):
            product_type = "box"
        elif re.search(r'blister|check\s?lane', title.lower()):
            product_type = "blister"
    
    # Extrahiere Seriencode (oder versuche es)
    code_match = re.search(r'(?:sv|kp|op)(?:\s|-)?\d+', title.lower())
    if code_match:
        series_code = code_match.group(0).replace(" ", "").replace("-", "")
    else:
        # Fallback: Verwende bereinigten Titel als Seriencode
        tokens = clean_text(title).split()
        # Entferne allgemeine Begriffe
        exclude_tokens = ["pokemon", "pokémon", "display", "box", "elite", "top", "trainer", 
                          "etb", "ttb", "booster", "pack", "box", "tin", "blister"]
        product_tokens = [t for t in tokens if t.lower() not in exclude_tokens and len(t) > 2]
        
        if product_tokens:
            # Verwende die ersten beiden übrigen Token als Serie
            series_code = "_".join(product_tokens[:2])
            # Begrenzte Länge
            if len(series_code) > 20:
                series_code = series_code[:20]
    
    return (series_code, product_type, language)

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