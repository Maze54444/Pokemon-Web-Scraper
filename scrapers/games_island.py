"""
Spezieller Scraper für games-island.eu mit robusteren HTTP-Anfragen
und besserer Fehlerbehandlung für die spezifischen Timeout-Probleme dieser Seite.
"""

import requests
import logging
import re
import random
import time
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote_plus
from utils.matcher import is_keyword_in_text, extract_product_type_from_text
from utils.stock import update_product_status
from utils.availability import detect_availability
from utils.requests_handler import get_default_headers

# Logger konfigurieren
logger = logging.getLogger(__name__)

# Konstanten für den Scraper
MAX_RETRY_ATTEMPTS = 5
STATIC_DELAY = 3  # Feste Pause zwischen Anfragen in Sekunden
LONG_TIMEOUT = 30  # Längerer Timeout für games-island.eu
BACKOFF_FACTOR = 2  # Faktor für exponentielles Backoff

def scrape_games_island(keywords_map, seen, out_of_stock, only_available=False):
    """
    Spezialisierter Scraper für games-island.eu mit angepasster Timeout-Behandlung
    
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param seen: Set mit bereits gesehenen Produkttiteln
    :param out_of_stock: Set mit ausverkauften Produkten
    :param only_available: Ob nur verfügbare Produkte gemeldet werden sollen
    :return: Liste der neuen Treffer
    """
    logger.info("🌐 Starte speziellen Scraper für games-island.eu")
    new_matches = []
    all_products = []  # Liste für alle gefundenen Produkte
    
    # Extraktion der Suchbegriffe in ein Format, das sich besser für die direkte Suche eignet
    search_terms = []
    product_types = {}
    
    for search_term, tokens in keywords_map.items():
        clean_term = re.sub(r'\s+', ' ', search_term.lower().strip())
        if clean_term not in search_terms:
            search_terms.append(clean_term)
            # Extrahiere den Produkttyp aus dem Suchbegriff für spätere Filterung
            product_types[clean_term] = extract_product_type_from_text(clean_term)
    
    # Sortiere nach Länge (kürzere Terme könnten mehr Ergebnisse liefern)
    search_terms.sort(key=len)
    logger.info(f"🔍 Verwende folgende Suchbegriffe für games-island.eu: {search_terms}")
    
    # Direkte Suche mit Suchbegriffen
    for term in search_terms:
        try:
            logger.info(f"🔍 Suche nach Term: '{term}'")
            
            # Sichere Verzögerung vor jeder Anfrage
            time.sleep(STATIC_DELAY + random.uniform(0.5, 1.5))
            
            # Erstelle URL für die Suche
            search_url = f"https://games-island.eu/search?q={quote_plus(term)}"
            
            # Angepasste Anfrage mit robusterem Timeout und Retry-Mechanismus
            products = search_games_island(search_url, term, product_types.get(term))
            
            if products:
                logger.info(f"✅ {len(products)} potentielle Produkte gefunden für '{term}'")
                
                # Verarbeite die gefundenen Produkte
                for product in products:
                    try:
                        product_data = process_product(
                            product, term, seen, out_of_stock, only_available
                        )
                        
                        if product_data and isinstance(product_data, dict):
                            all_products.append(product_data)
                            new_matches.append(product_data.get("product_id"))
                    except Exception as e:
                        logger.error(f"❌ Fehler bei der Verarbeitung eines Produkts: {e}")
                        continue
            else:
                logger.info(f"⚠️ Keine Produkte gefunden für Suchbegriff '{term}'")
                
        except Exception as e:
            logger.error(f"❌ Fehler bei der Suche nach '{term}': {e}")
            continue
    
    # Sende Benachrichtigungen für gefundene Produkte
    if all_products:
        send_batch_notifications(all_products)
    
    return new_matches

def search_games_island(search_url, search_term, product_type=None):
    """
    Führt eine Suchanfrage auf games-island.eu durch mit angepasstem Retry-Mechanismus
    
    :param search_url: URL für die Suchanfrage
    :param search_term: Der verwendete Suchbegriff
    :param product_type: Optional - Produkttyp für bessere Filterung
    :return: Liste mit gefundenen Produkten
    """
    headers = get_random_headers()
    products = []
    retry_count = 0
    
    while retry_count < MAX_RETRY_ATTEMPTS:
        try:
            # Exponentielles Backoff mit Jitter
            if retry_count > 0:
                wait_time = BACKOFF_FACTOR ** retry_count + random.uniform(0.5, 1.5)
                logger.info(f"🔄 Wiederholungsversuch {retry_count}/{MAX_RETRY_ATTEMPTS} in {wait_time:.1f} Sekunden")
                time.sleep(wait_time)
            
            # Verwende eine manuelle Session mit angepassten Parametern
            session = requests.Session()
            session.headers.update(headers)
            
            # Setze den Timeout höher für games-island.eu
            response = session.get(search_url, timeout=LONG_TIMEOUT, verify=True)
            
            if response.status_code != 200:
                logger.warning(f"⚠️ HTTP-Fehlercode {response.status_code} für {search_url}")
                retry_count += 1
                continue
            
            # Parsen mit BeautifulSoup
            soup = BeautifulSoup(response.content, "html.parser")
            
            # Muster für verschiedene Arten von Produktlisten auf der Website
            product_containers = []
            
            # Primäre Produktlisten-Container versuchen
            product_containers = soup.select('.product-items .product-item, .product-grid .product-item')
            
            # Wenn primäre Selektoren nichts finden, versuche Alternative
            if not product_containers:
                product_containers = soup.select('.item-product, .product, [data-product-id]')
            
            # Wenn immer noch nichts gefunden wurde, versuche generische Listen
            if not product_containers:
                product_containers = soup.select('.grid-view .item, .list-view .item')
            
            # Letzter Versuch: Alle Links untersuchen, die auf Produktseiten zeigen könnten
            if not product_containers:
                logger.warning("⚠️ Keine Produktcontainer gefunden, versuche alle Links zu prüfen")
                for link in soup.select('a[href*="/product/"]'):
                    heading = link.find('h3') or link.find('h2') or link.find('span', class_='name')
                    if heading:
                        product_containers.append(link.parent)
            
            # Verarbeite die gefundenen Produktcontainer
            for container in product_containers:
                try:
                    # Extrahiere grundlegende Produktinformationen
                    title_elem = (container.select_one('.product-title, .item-title, .title, h2, h3') or 
                                 container.find('h4') or container.find('h5'))
                    
                    # Wenn kein Titel gefunden wird, überspringe dieses Produkt
                    if not title_elem:
                        continue
                    
                    title = title_elem.get_text().strip()
                    
                    # Prüfe, ob der Titel zum Suchbegriff passt
                    if not is_relevant_product(title, search_term, product_type):
                        continue
                    
                    # Suche nach dem Produktlink
                    link_elem = (title_elem.parent if title_elem.parent.name == 'a' else 
                                title_elem.find('a') or container.find('a', href=True))
                    
                    if not link_elem or not link_elem.get('href'):
                        continue
                    
                    # Vollständige URL erstellen
                    product_url = link_elem['href']
                    if not product_url.startswith(('http://', 'https://')):
                        product_url = urljoin("https://games-island.eu", product_url)
                    
                    # Füge das Produkt hinzu
                    products.append({
                        'title': title,
                        'url': product_url,
                        'search_term': search_term
                    })
                    
                except Exception as e:
                    logger.debug(f"Fehler bei der Extraktion der Produktdaten: {e}")
                    continue
            
            # Wenn Produkte gefunden wurden, Schleife beenden
            if products:
                logger.info(f"🔍 {len(products)} potentielle Produkte aus Suche extrahiert")
                return products
            
            # Wenn keine Produkte gefunden wurden, aber die Anfrage erfolgreich war
            retry_count += 1
            logger.warning(f"⚠️ Keine passenden Produkte in der Antwort gefunden (Versuch {retry_count})")
            
        except requests.exceptions.Timeout:
            retry_count += 1
            logger.warning(f"⚠️ Timeout bei der Anfrage an {search_url} (Versuch {retry_count})")
        except requests.exceptions.RequestException as e:
            retry_count += 1
            logger.warning(f"⚠️ Fehler bei der Anfrage an {search_url}: {e} (Versuch {retry_count})")
        except Exception as e:
            retry_count += 1
            logger.warning(f"⚠️ Unerwarteter Fehler: {e} (Versuch {retry_count})")
    
    # Wenn alle Versuche fehlgeschlagen sind
    logger.error(f"❌ Alle {MAX_RETRY_ATTEMPTS} Versuche für {search_url} fehlgeschlagen")
    return []

def process_product(product, search_term, seen, out_of_stock, only_available):
    """
    Verarbeitet ein einzelnes Produkt mit angepasster Fehlerbehandlung
    
    :param product: Produktdaten aus der Suche
    :param search_term: Der verwendete Suchbegriff
    :param seen: Set mit bereits gesehenen Produkttiteln
    :param out_of_stock: Set mit ausverkauften Produkten
    :param only_available: Ob nur verfügbare Produkte gemeldet werden sollen
    :return: Dictionary mit Produktdaten oder None bei Fehler
    """
    title = product.get('title', '')
    url = product.get('url', '')
    
    if not title or not url:
        return None
    
    try:
        # Spezielle Verzögerung zur Vermeidung von Rate-Limiting
        time.sleep(STATIC_DELAY + random.uniform(1.0, 2.0))
        
        logger.info(f"🔍 Prüfe Produkt: {title}")
        
        # Produktdetailseite mit angepasstem Retry-Mechanismus abrufen
        success, detail_soup = fetch_product_page(url)
        
        if not success or not detail_soup:
            logger.warning(f"⚠️ Konnte Produktdetails nicht abrufen für: {title}")
            return None
        
        # Verwende das Availability-Modul für die Verfügbarkeitsprüfung
        is_available, price, status_text = detect_availability(detail_soup, url)
        
        # Erstelle eindeutige Produkt-ID
        product_id = create_product_id(title)
        
        # Status aktualisieren und prüfen, ob Benachrichtigung gesendet werden soll
        should_notify, is_back_in_stock = update_product_status(
            product_id, is_available, seen, out_of_stock
        )
        
        # Bei "nur verfügbare" Option überspringen, wenn nicht verfügbar
        if only_available and not is_available:
            return None
        
        if should_notify:
            # Status anpassen wenn wieder verfügbar
            if is_back_in_stock:
                status_text = "🎉 Wieder verfügbar!"
                
            # Extrahiere Produkttyp aus dem Titel
            product_type = extract_product_type_from_text(title)
            
            # Produkt-Daten für die Benachrichtigung
            product_data = {
                "title": title,
                "url": url,
                "price": price,
                "status_text": status_text,
                "is_available": is_available,
                "matched_term": search_term,
                "product_type": product_type,
                "shop": "games-island.eu",
                "product_id": product_id
            }
            
            logger.info(f"✅ Neuer Treffer bei games-island.eu: {title} - {status_text}")
            return product_data
        
        return None
    
    except Exception as e:
        logger.error(f"❌ Fehler bei der Verarbeitung von {title}: {e}")
        return None

def fetch_product_page(url):
    """
    Ruft die Produktdetailseite mit verbesserter Fehlerbehandlung ab
    
    :param url: URL der Produktdetailseite
    :return: Tuple (success, soup)
    """
    headers = get_random_headers()
    retry_count = 0
    
    while retry_count < MAX_RETRY_ATTEMPTS:
        try:
            # Exponentielles Backoff mit Jitter
            if retry_count > 0:
                wait_time = BACKOFF_FACTOR ** retry_count + random.uniform(0.5, 1.5)
                logger.info(f"🔄 Wiederholungsversuch {retry_count}/{MAX_RETRY_ATTEMPTS} in {wait_time:.1f} Sekunden")
                time.sleep(wait_time)
            
            # Verwende eine manuelle Session mit angepassten Parametern
            session = requests.Session()
            session.headers.update(headers)
            
            # Höherer Timeout für Produktdetailseiten
            response = session.get(url, timeout=LONG_TIMEOUT, verify=True)
            
            if response.status_code != 200:
                logger.warning(f"⚠️ HTTP-Fehlercode {response.status_code} für {url}")
                retry_count += 1
                continue
            
            # Parsen mit BeautifulSoup
            soup = BeautifulSoup(response.content, "html.parser")
            return True, soup
            
        except requests.exceptions.Timeout:
            retry_count += 1
            logger.warning(f"⚠️ Timeout bei der Anfrage an {url} (Versuch {retry_count})")
        except requests.exceptions.RequestException as e:
            retry_count += 1
            logger.warning(f"⚠️ Fehler bei der Anfrage an {url}: {e} (Versuch {retry_count})")
        except Exception as e:
            retry_count += 1
            logger.warning(f"⚠️ Unerwarteter Fehler: {e} (Versuch {retry_count})")
    
    # Wenn alle Versuche fehlgeschlagen sind
    logger.error(f"❌ Alle {MAX_RETRY_ATTEMPTS} Versuche für {url} fehlgeschlagen")
    return False, None

def get_random_headers():
    """
    Erstellt zufällige HTTP-Headers zur Vermeidung von Bot-Erkennung
    
    :return: Dictionary mit HTTP-Headers
    """
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.4 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.159 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36 Edg/90.0.818.66"
    ]
    
    # Zufällige User-Agent-Rotation
    random_agent = random.choice(user_agents)
    
    # Länderspezifische Akzeptanz-Header für DE
    accept_language = "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7"
    
    # Zufällige Referer von bekannten Webseiten
    referers = [
        "https://www.google.de/",
        "https://www.bing.com/",
        "https://duckduckgo.com/",
        "https://www.pokemon.com/de/",
        "https://www.pokemoncenter.com/"
    ]
    random_referer = random.choice(referers)
    
    return {
        "User-Agent": random_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": accept_language,
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": random_referer,
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0"
    }

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
    elif "english" in title_lower or "(en)" in title_lower:
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

def is_relevant_product(title, search_term, product_type=None):
    """
    Prüft, ob ein Produkttitel relevant für den Suchbegriff ist
    
    :param title: Produkttitel
    :param search_term: Suchbegriff
    :param product_type: Optional - Erwarteter Produkttyp
    :return: True wenn relevant, False sonst
    """
    if not title or not search_term:
        return False
    
    title_lower = title.lower()
    search_term_lower = search_term.lower()
    
    # Prüfe grundlegende Relevanz mit Matcher-Funktion
    tokens = search_term_lower.split()
    if not is_keyword_in_text(tokens, title_lower, log_level='None'):
        return False
    
    # Wenn ein bestimmter Produkttyp erwartet wird, prüfe ob er mit dem Titel übereinstimmt
    if product_type and product_type != "unknown":
        title_product_type = extract_product_type_from_text(title_lower)
        
        # Bei speziellen Produkttypen sind wir strenger
        if product_type in ["display", "etb", "ttb"]:
            # Wenn Produkttyp nicht übereinstimmt, aber bestimmte Begriffe im Titel vorkommen
            if title_product_type != product_type:
                if product_type == "display":
                    # Prüfe auf Display-spezifische Begriffe
                    if not any(term in title_lower for term in ["display", "36er", "booster box", "36 booster"]):
                        return False
                elif product_type == "etb":
                    # Prüfe auf ETB-spezifische Begriffe
                    if not any(term in title_lower for term in ["etb", "elite trainer", "trainer box"]):
                        return False
                elif product_type == "ttb":
                    # Prüfe auf TTB-spezifische Begriffe
                    if not any(term in title_lower for term in ["ttb", "top trainer", "top-trainer"]):
                        return False
    
    # Grundlegende Relevanzprüfung für Pokemon-Produkte
    if not any(term in title_lower for term in ["pokemon", "pokémon"]):
        return False
    
    # Ausschluss von nicht relevanten Sets/Produkten
    exclusion_terms = [
        "astral", "brilliant", "fusion", "stellar", "paldea", "karmesin", "purpur",
        "silberne", "schatten", "gold", "scarlet", "violet", "paradox", "obsidian"
    ]
    
    # Prüfe, ob der Titel einen der ausgeschlossenen Begriffe enthält, aber nicht im Suchbegriff enthalten ist
    for term in exclusion_terms:
        if term in title_lower and term not in search_term_lower:
            return False
    
    return True

def send_batch_notifications(products):
    """Sendet Benachrichtigungen für gefundene Produkte"""
    from utils.telegram import send_batch_notification
    
    if products:
        logger.info(f"📤 Sende Benachrichtigung für {len(products)} Produkte")
        send_batch_notification(products)
    else:
        logger.info("ℹ️ Keine Produkte für Benachrichtigung gefunden")