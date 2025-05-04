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

from utils.matcher import clean_text, is_keyword_in_text, normalize_product_name, extract_product_type_from_text
from utils.telegram import send_telegram_message, escape_markdown, send_product_notification, send_batch_notification
from utils.stock import get_status_text, update_product_status
from utils.availability import detect_availability

# Logger konfigurieren
logger = logging.getLogger(__name__)

# URL-Filterliste für allgemeine Filter, die auf alle Webseiten angewendet werden sollen
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

# Domainspezifische Filter (für bestimmte Webshops)
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

def load_product_cache(cache_file="data/product_cache.json"):
    """Lädt das Cache-Dictionary mit bekannten Produkten und ihren URLs"""
    try:
        # Stelle sicher, dass das Verzeichnis existiert
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
        # Stelle sicher, dass das Verzeichnis existiert
        Path(cache_file).parent.mkdir(parents=True, exist_ok=True)
        
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        logger.debug(f"✅ Produkt-Cache mit {len(cache)} Einträgen gespeichert")
    except Exception as e:
        logger.error(f"⚠️ Fehler beim Speichern des Produkt-Caches: {e}")

def create_fingerprint(html_content):
    """Erstellt einen Fingerprint vom HTML-Inhalt, um Änderungen zu erkennen"""
    # Wir verwenden einen Hash des Inhalts als Fingerprint
    return hashlib.md5(html_content.encode('utf-8')).hexdigest()

def extract_product_type_from_search_term(search_term):
    """Extrahiert den Produkttyp direkt aus einem Suchbegriff"""
    return extract_product_type_from_text(search_term)

def get_domain(url):
    """Extrahiert die Domain aus einer URL ohne www. Präfix"""
    try:
        parsed_url = urlparse(url)
        domain = parsed_url.netloc
        
        # Entferne www. Präfix, falls vorhanden
        if domain.startswith('www.'):
            domain = domain[4:]
            
        return domain.lower()
    except Exception:
        return url.lower()

def should_filter_url(url, link_text=""):
    """
    Prüft, ob eine URL gefiltert werden soll
    
    :param url: Die zu prüfende URL
    :param link_text: Text des Links
    :return: True wenn gefiltert werden soll, False wenn nicht
    """
    if not url:
        return True
        
    # Normalisiere URL und Link-Text
    normalized_url = url.lower()
    normalized_text = link_text.lower() if link_text else ""
    
    # Extrahiere Domain für domainspezifische Filter
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
        # Kategorieseiten nur zulassen, wenn sie relevante Begriffe enthalten
        relevant_keywords = ["pokemon", "display", "booster", "trainer", "box", "etb", "ttb"]
        if not any(keyword in normalized_url for keyword in relevant_keywords) and not any(keyword in normalized_text for keyword in relevant_keywords):
            return True
            
    return False

def scrape_generic(url, keywords_map, seen, out_of_stock, check_availability=True, only_available=False):
    """
    Optimierte generische Scraper-Funktion mit Cache-Unterstützung und verbesserter Produkttyp-Prüfung
    
    :param url: URL der zu scrapenden Website
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param seen: Set mit bereits gesehenen Produkttiteln
    :param out_of_stock: Set mit ausverkauften Produkten
    :param check_availability: Ob Produktdetailseiten für Verfügbarkeitsprüfung besucht werden sollen
    :param only_available: Ob nur verfügbare Produkte gemeldet werden sollen
    :return: Liste der neuen Treffer
    """
    logger.info(f"🌐 Starte generischen Scraper für {url}")
    new_matches = []
    
    # Cache laden oder neu erstellen
    product_cache = load_product_cache()
    site_id = get_domain(url)
    
    # Prüfe, ob wir neue Keywords haben, die nicht im Cache sind
    cache_key = f"{site_id}_keywords"
    cached_keywords = product_cache.get(cache_key, [])
    current_keywords = list(keywords_map.keys())
    
    new_keywords = [k for k in current_keywords if k not in cached_keywords]
    if new_keywords:
        logger.info(f"🔍 Neue Suchbegriffe gefunden: {new_keywords}")
        # Wir werden die Seite vollständig scannen, da wir neue Keywords haben
        full_scan_needed = True
    else:
        # Keine neuen Keywords, wir können den Cache nutzen
        full_scan_needed = False
    
    # Liste für alle gefundenen Produkte (für sortierte Benachrichtigung)
    all_products = []
    
    # Extrahiere den Produkttyp aus dem ersten Suchbegriff
    search_product_type = None
    if current_keywords:
        sample_search_term = current_keywords[0]
        search_product_type = extract_product_type_from_text(sample_search_term)
        logger.debug(f"🔍 Suche nach Produkttyp: '{search_product_type}' basierend auf '{sample_search_term}'")
    
    # URL-Hash zur eindeutigen Identifikation von URLs mit dynamischen Parametern
    url_hash = hashlib.md5(url.encode('utf-8')).hexdigest()[:10]
    
    # Set für Deduplizierung von gefundenen Produkten innerhalb eines Durchlaufs
    found_product_ids = set()
    
    try:
        # User-Agent setzen, um Blockierung zu vermeiden
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        
        # Prüfen, ob wir gecachte Produktpfade für diese Domain haben
        domain_paths = product_cache.get(site_id, {})
        
        # Spezielle Behandlung für bekannte Shops mit spezifischen Pfadmustern
        if site_id == "mighty-cards.de" and not domain_paths:
            logger.info(f"🔍 Spezielle Pfadmuster für {site_id} werden verwendet")
            # Generische Pfadmuster für Pokemon-Produkte bei Mighty-Cards
            shop_paths = [
                "/shop/Pokemon",
                "/pokemon/",
                "/shop/Vorbestellung-c166467816"
            ]
            
            # Füge manuelle Pfade zum Cache hinzu
            for shop_path in shop_paths:
                path_url = f"https://{site_id}{shop_path}"
                product_id = f"{site_id}_{hashlib.md5(path_url.encode()).hexdigest()[:8]}"
                domain_paths[product_id] = {
                    "url": path_url,
                    "term": current_keywords[0] if current_keywords else "Pokemon",
                    "last_checked": 0,  # Erzwinge Überprüfung
                    "is_available": False
                }
            
            # Speichere diese Pfade im Cache
            product_cache[site_id] = domain_paths
        
        # Spezielle Behandlung für FantasiaCards
        elif site_id == "fantasiacards.de" and not domain_paths:
            logger.info(f"🔍 Spezielle Pfadmuster für {site_id} werden verwendet")
            # Manuelle Pfade für FantasiaCards (generisch für Pokémon-Produkte)
            shop_paths = [
                "/collections/pokemon-1",
                "/collections/pokemon-neuheiten"
            ]
            
            # Füge manuelle Pfade zum Cache hinzu
            for shop_path in shop_paths:
                path_url = f"https://{site_id}{shop_path}"
                product_id = f"{site_id}_{hashlib.md5(path_url.encode()).hexdigest()[:8]}"
                domain_paths[product_id] = {
                    "url": path_url,
                    "term": current_keywords[0] if current_keywords else "Pokemon",
                    "last_checked": 0,  # Erzwinge Überprüfung
                    "is_available": False
                }
            
            # Speichere diese Pfade im Cache
            product_cache[site_id] = domain_paths
        
        if domain_paths and not full_scan_needed:
            logger.info(f"🔍 Nutze {len(domain_paths)} gecachte Produktpfade für {site_id}")
            
            # Alle gecachten Produkte prüfen
            checked_products = 0
            
            # Nur die bereits bekannten Produktseiten prüfen
            for product_id, product_info in list(domain_paths.items()):  # list() erstellen um während Iteration zu löschen
                # Ignoriere Cache-Key Einträge
                if product_id == cache_key:
                    continue
                
                # Zähler für Produkte erhöhen
                checked_products += 1
                
                product_url = product_info.get("url", "")
                matched_term = product_info.get("term", "")
                last_checked = product_info.get("last_checked", 0)
                
                # Nur Produkte prüfen, die für unsere aktuellen Suchbegriffe relevant sind
                if matched_term not in keywords_map:
                    continue
                
                # Prüfen, ob die Seite vor kurzem überprüft wurde (z.B. in den letzten 2 Stunden)
                if time.time() - last_checked < 7200:  # 2 Stunden in Sekunden
                    logger.debug(f"⏱️ Überspringe kürzlich geprüftes Produkt: {product_url}")
                    continue
                
                # Produktseite direkt besuchen
                try:
                    response = requests.get(product_url, headers=headers, timeout=10)
                    if response.status_code != 200:
                        logger.warning(f"⚠️ Fehler beim Abrufen von {product_url}: Status {response.status_code}")
                        
                        # Wenn Seite nicht mehr erreichbar, aus Cache entfernen
                        if response.status_code in (404, 410):
                            logger.info(f"🗑️ Entferne nicht mehr verfügbare Produktpfad: {product_url}")
                            domain_paths.pop(product_id, None)
                        continue
                    
                    # Fingerprint des aktuellen Inhalts erstellen
                    current_fingerprint = create_fingerprint(response.text)
                    stored_fingerprint = product_info.get("fingerprint", "")
                    
                    # HTML parsen
                    soup = BeautifulSoup(response.text, "html.parser")
                    
                    # Titel extrahieren
                    title_elem = soup.find('title')
                    link_text = title_elem.text.strip() if title_elem else ""
                    
                    # VERBESSERT: Strikte Prüfung auf exakte Übereinstimmung mit dem Suchbegriff
                    tokens = keywords_map.get(matched_term, [])
                    
                    # Extrahiere Produkttyp aus Suchbegriff und Titel
                    search_term_type = extract_product_type_from_search_term(matched_term)
                    title_product_type = extract_product_type_from_text(link_text)
                    
                    # Wenn nach einem bestimmten Produkttyp gesucht wird, muss dieser im Titel übereinstimmen
                    if search_term_type in ["display", "etb", "ttb"] and title_product_type != search_term_type:
                        logger.debug(f"⚠️ Produkttyp-Diskrepanz: Suche nach '{search_term_type}', aber Produkt ist '{title_product_type}': {link_text}")
                        continue
                    
                    # Strengere Keyword-Prüfung mit Berücksichtigung des Produkttyps
                    if not is_keyword_in_text(tokens, link_text, log_level='None'):
                        logger.debug(f"⚠️ Produkt entspricht nicht mehr dem Suchbegriff '{matched_term}': {link_text}")
                        continue
                    
                    # Aktualisiere die letzte Prüfzeit
                    domain_paths[product_id]["last_checked"] = time.time()
                    
                    # Wenn der Fingerprint sich geändert hat oder wir keinen haben, führe vollständige Verfügbarkeitsprüfung durch
                    if current_fingerprint != stored_fingerprint or not stored_fingerprint:
                        logger.info(f"🔄 Änderung erkannt oder erste Prüfung: {product_url}")
                        domain_paths[product_id]["fingerprint"] = current_fingerprint
                        
                        # Prüfe Verfügbarkeit
                        is_available, price, status_text = detect_availability(soup, product_url)
                        
                        # Aktualisiere Cache-Eintrag
                        domain_paths[product_id]["is_available"] = is_available
                        domain_paths[product_id]["price"] = price
                        
                        # Aktualisiere Produkt-Status und prüfe, ob Benachrichtigung gesendet werden soll
                        should_notify, is_back_in_stock = update_product_status(
                            product_id, is_available, seen, out_of_stock
                        )
                        
                        if should_notify and (not only_available or is_available):
                            # Wenn Produkt wieder verfügbar ist, anpassen
                            if is_back_in_stock:
                                status_text = "🎉 Wieder verfügbar!"
                            # Wenn kein Status-Text vorhanden ist, erstellen
                            elif not status_text:
                                status_text = get_status_text(is_available, is_back_in_stock)
                            
                            # Produkt-Informationen sammeln für Batch-Benachrichtigung
                            product_data = {
                                "title": link_text,
                                "url": product_url,
                                "price": price,
                                "status_text": status_text,
                                "is_available": is_available,
                                "matched_term": matched_term,
                                "product_type": title_product_type,
                                "shop": site_id
                            }
                            
                            # Deduplizierung innerhalb eines Durchlaufs
                            if product_id not in found_product_ids:
                                all_products.append(product_data)
                                new_matches.append(product_id)
                                found_product_ids.add(product_id)
                                logger.info(f"✅ Cache-Treffer: {link_text} - {status_text}")
                    else:
                        logger.debug(f"✓ Keine Änderung für {product_url}")
                        
                except Exception as e:
                    logger.warning(f"⚠️ Fehler bei der Verarbeitung von {product_url}: {e}")
            
            # Cache mit den aktualisierten Zeitstempeln speichern
            product_cache[site_id] = domain_paths
            save_product_cache(product_cache)
        
        # Wenn neue Keywords oder ein vollständiger Scan erforderlich ist
        if full_scan_needed or not domain_paths:
            logger.info(f"🔍 Durchführung eines vollständigen Scans für {url}")
            
            try:
                response = requests.get(url, headers=headers, timeout=15)
                if response.status_code != 200:
                    logger.warning(f"⚠️ Fehler beim Abrufen von {url}: Status {response.status_code}")
                    return new_matches
            except requests.exceptions.RequestException as e:
                logger.warning(f"⚠️ Netzwerkfehler beim Abrufen von {url}: {e}")
                return new_matches
            
            # HTML parsen
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Titel der Seite extrahieren
            page_title = soup.title.text.strip() if soup.title else url
            
            # Alle Links sammeln
            all_links = soup.find_all('a', href=True)
            
            potential_product_links = []
            
            # Schnellerer Filter für Links
            for a_tag in all_links:
                href = a_tag.get('href', '')
                if not href or href.startswith('#') or href.startswith('javascript:'):
                    continue
                
                link_text = a_tag.get_text().strip().lower()
                
                # Filter anwenden
                if should_filter_url(href, link_text):
                    continue
                
                # Nur Links mit Produktnamen-ähnlichem Text oder Produkt-Pfad verfolgen
                if '/product/' in href or '/products/' in href or '/produkt/' in href or 'detail' in href:
                    potential_product_links.append((href, a_tag.get_text().strip()))
                    continue
                
                # Spezielle Behandlung für Mighty-Cards
                if site_id == "mighty-cards.de" and ('/shop/' in href or '/p' in href):
                    potential_product_links.append((href, a_tag.get_text().strip()))
                    continue
                
                # Effizientere Keyword-Prüfung
                for search_term, tokens in keywords_map.items():
                    # Extrahiere Produkttyp aus dem Suchbegriff
                    search_term_type = extract_product_type_from_search_term(search_term)
                    
                    # Bei spezifischen Produkttypen: zusätzliche Prüfung auf entsprechende Begriffe im Linktext
                    if search_term_type == "display":
                        if not any(term in link_text for term in ["display", "36er", "booster box"]):
                            continue
                    elif search_term_type == "etb":
                        if not any(term in link_text for term in ["etb", "elite trainer", "trainer box"]):
                            continue
                    elif search_term_type == "ttb":
                        if not any(term in link_text for term in ["ttb", "top trainer", "trainer box"]):
                            continue
                    
                    if is_keyword_in_text(tokens, link_text, log_level='None'):
                        potential_product_links.append((href, a_tag.get_text().strip()))
                        break
            
            logger.info(f"🔍 {len(potential_product_links)} potenzielle Produktlinks gefunden auf {url}")
            
            # Verarbeite alle potenziellen Produktlinks
            for href, link_text in potential_product_links:
                # Vollständige URL erstellen
                if href.startswith('http'):
                    product_url = href
                elif href.startswith('/'):
                    base_url = '/'.join(url.split('/')[:3])  # http(s)://domain.com
                    product_url = f"{base_url}{href}"
                else:
                    # Relativer Pfad
                    product_url = f"{url.rstrip('/')}/{href.lstrip('/')}"
                
                # Eindeutige ID für diesen Fund erstellen
                product_id = create_product_id(link_text, site_id=site_id)
                
                # Deduplizierung innerhalb eines Durchlaufs - überspringen, wenn bereits geprüft
                if product_id in found_product_ids:
                    continue
                
                # Prüfe jeden Suchbegriff gegen den Linktext
                matched_term = None
                for search_term, tokens in keywords_map.items():
                    # Extrahiere Produkttyp aus dem Suchbegriff und dem Link-Text
                    search_term_type = extract_product_type_from_search_term(search_term)
                    link_product_type = extract_product_type_from_text(link_text)
                    
                    # Wenn nach einem bestimmten Produkttyp gesucht wird, muss dieser im Link übereinstimmen
                    if search_term_type in ["display", "etb", "ttb"] and link_product_type != search_term_type:
                        logger.debug(f"❌ Produkttyp-Konflikt: Suche nach '{search_term_type}', aber Link ist '{link_product_type}': {link_text}")
                        continue
                    
                    # VERBESSERT: Strenge Prüfung mit der neuen Funktion
                    match_result = is_keyword_in_text(tokens, link_text, log_level='None')
                    
                    if match_result:
                        matched_term = search_term
                        logger.debug(f"🔍 Treffer für '{search_term}' im Link: {link_text}")
                        break
                
                if not matched_term:
                    continue
                
                # Prüfe Verfügbarkeit
                is_available = True  # Standard
                price = "Preis nicht verfügbar"
                status_text = ""
                detail_soup = None
                
                if check_availability:
                    try:
                        # Produktdetails abrufen
                        detail_response = requests.get(product_url, headers=headers, timeout=10)
                        if detail_response.status_code != 200:
                            logger.warning(f"⚠️ Fehler beim Abrufen der Produktdetails: Status {detail_response.status_code}")
                            continue
                            
                        detail_soup = BeautifulSoup(detail_response.text, "html.parser")
                        
                        # Verwende das Availability-Modul für die Verfügbarkeitsprüfung
                        is_available, price, status_text = detect_availability(detail_soup, product_url)
                        
                        # VERBESSERT: Nochmals prüfen, ob der Produktdetailseiten-Titel dem Suchbegriff entspricht
                        detail_title = detail_soup.find('title')
                        if detail_title:
                            detail_title_text = detail_title.text.strip()
                            tokens = keywords_map.get(matched_term, [])
                            
                            # Extrahiere Produkttyp aus dem Detailtitel
                            detail_product_type = extract_product_type_from_text(detail_title_text)
                            search_term_type = extract_product_type_from_search_term(matched_term)
                            
                            # Wenn nach einem bestimmten Produkttyp gesucht wird, muss dieser im Detailtitel übereinstimmen
                            if search_term_type in ["display", "etb", "ttb"] and detail_product_type != search_term_type:
                                logger.debug(f"❌ Detailseite ist kein {search_term_type}, obwohl danach gesucht wurde: {detail_title_text}")
                                continue
                            
                            # Generelle Keyword-Übereinstimmungsprüfung
                            if not is_keyword_in_text(tokens, detail_title_text, log_level='None'):
                                logger.debug(f"❌ Detailseite passt nicht zum Suchbegriff '{matched_term}': {detail_title_text}")
                                continue
                            
                            # Wenn Detailtitel verfügbar ist, verwende ihn für die Nachricht
                            link_text = detail_title_text
                        
                        # Für den Cache: Speichere die URL und den erkannten Term
                        if site_id not in product_cache:
                            product_cache[site_id] = {}
                        
                        # Speichere Produktinfos im Cache
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
                            "product_type": extract_product_type_from_text(link_text)  # Speichere auch den Produkttyp
                        }
                        
                    except Exception as e:
                        logger.warning(f"⚠️ Fehler beim Prüfen der Verfügbarkeit für {product_url}: {e}")
                
                # Benachrichtigungslogik
                should_notify, is_back_in_stock = update_product_status(
                    product_id, is_available, seen, out_of_stock
                )
                
                if should_notify and (not only_available or is_available):
                    # Wenn Produkt wieder verfügbar ist, anpassen
                    if is_back_in_stock:
                        status_text = "🎉 Wieder verfügbar!"
                    # Status-Text erstellen oder den bereits generierten verwenden
                    elif not status_text:
                        status_text = get_status_text(is_available, is_back_in_stock)
                    
                    # Produkt-Informationen sammeln für Batch-Benachrichtigung
                    product_type = extract_product_type_from_text(link_text)
                    
                    # Deduplizierung innerhalb eines Durchlaufs
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
            
            # Aktualisiere die Liste der bekannten Keywords im Cache
            product_cache[cache_key] = current_keywords
            
            # Speichere den aktualisierten Cache
            save_product_cache(product_cache)
    
        # Sende Benachrichtigungen sortiert nach Verfügbarkeit
        if all_products:
            send_batch_notification(all_products)
    
    except Exception as e:
        logger.error(f"❌ Fehler beim generischen Scraping von {url}: {e}", exc_info=True)
    
    return new_matches

def check_product_availability(url, headers):
    """
    Besucht die Produktdetailseite und prüft die Verfügbarkeit
    
    :param url: Produkt-URL
    :param headers: HTTP-Headers für die Anfrage
    :return: Tuple (BeautifulSoup-Objekt, Verfügbarkeitsstatus, Preis, Status-Text)
    """
    logger.info(f"🔍 Prüfe Produktdetails für {url}")
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return None, False, "Preis nicht verfügbar", "❌ Ausverkauft (Fehler beim Laden)"
    except requests.exceptions.RequestException as e:
        logger.warning(f"⚠️ Netzwerkfehler beim Abrufen von {url}: {e}")
        return None, False, "Preis nicht verfügbar", "❌ Ausverkauft (Fehler beim Laden)"
    
    soup = BeautifulSoup(response.text, "html.parser")
    
    # Verwende das Availability-Modul für webseitenspezifische Erkennung
    is_available, price, status_text = detect_availability(soup, url)
    
    logger.debug(f"  - Verfügbarkeit für {url}: {status_text}")
    logger.debug(f"  - Preis: {price}")
    
    return soup, is_available, price, status_text

def extract_product_type(text):
    """
    Extrahiert den Produkttyp aus einem Text mit strengeren Regeln
    
    :param text: Text, aus dem der Produkttyp extrahiert werden soll
    :return: Produkttyp als String
    """
    return extract_product_type_from_text(text)

def create_product_id(product_title, site_id="generic"):
    """
    Erstellt eine eindeutige Produkt-ID basierend auf Titel und Website
    
    :param product_title: Produkttitel
    :param site_id: ID der Website (z.B. 'tcgviert', 'kofuku')
    :return: Eindeutige Produkt-ID
    """
    # Extrahiere strukturierte Informationen
    series_code, product_type, language = extract_product_info(product_title)
    
    # Erstelle eine strukturierte ID
    product_id = f"{site_id}_{series_code}_{product_type}_{language}"
    
    # Füge zusätzliche Details für spezielle Produkte hinzu
    if "premium" in product_title.lower():
        product_id += "_premium"
    if "elite" in product_title.lower():
        product_id += "_elite"
    if "top" in product_title.lower() and "trainer" in product_title.lower():
        product_id += "_top"
    
    return product_id

def extract_product_info(title):
    """
    Extrahiert wichtige Produktinformationen aus dem Titel für eine präzise ID-Erstellung
    
    :param title: Produkttitel
    :return: Tupel mit (series_code, product_type, language)
    """
    # Extrahiere Sprache (DE/EN/JP)
    if "(DE)" in title or "pro Person" in title or "deutsch" in title.lower() or "deu" in title.lower():
        language = "DE"
    elif "(EN)" in title or "per person" in title or "english" in title.lower() or "eng" in title.lower():
        language = "EN"
    elif "(JP)" in title or "japan" in title.lower() or "jpn" in title.lower():
        language = "JP"
    else:
        language = "UNK"
    
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
        else:
            product_type = "unknown"
    
    # Extrahiere Serien-/Set-Code
    series_code = "unknown"
    # Suche nach Standard-Codes wie SV09, KP09, etc.
    code_match = re.search(r'(?:sv|kp|op)(?:\s|-)?\d+', title.lower())
    if code_match:
        series_code = code_match.group(0).replace(" ", "").replace("-", "")
    # Ansonsten versuche, aus dem Titel abzuleiten
    else:
        # Extrahiere Tokens und versuche, eine Serie zu identifizieren
        tokens = clean_text(title).split()
        # Entferne allgemeine Begriffe wie "Pokemon", "Trainer", "Box", etc.
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