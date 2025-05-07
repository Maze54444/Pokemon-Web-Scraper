"""
Spezieller Scraper für mighty-cards.de, der die Sitemap verwendet
um Produkte zu finden und zu verarbeiten.
Optimiert mit Multithreading und verbesserter Name-vs-Typ Erkennung.
"""

import requests
import logging
import re
import json
import hashlib
import time
import concurrent.futures
from threading import Lock
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote_plus
from utils.matcher import is_keyword_in_text, extract_product_type_from_text, clean_text
from utils.stock import update_product_status
from utils.availability import detect_availability

# Logger konfigurieren
logger = logging.getLogger(__name__)

# Blacklist für Produkttitel und URLs, die nicht relevant sind
PRODUCT_BLACKLIST = [
    # Trading Card Games
    "yu-gi-oh", "yugioh", "yu gi oh", "yu-gi", 
    "union arena", "flesh and blood", "star wars", "disney lorcana", "lorcana",
    "magic the gathering", "mtg", "digimon", "one piece", "dragon ball",
    "final fantasy", "star wars unlimited", "trading card game",
    "jcc", "jumpstart", "grundstein", "himmelsleuchten", "captain",
    "metazoo", "dbscg", "weiss schwarz", "weiss", "schwarz",
    
    # Spezifische Sets/Namen anderer TCGs
    "op01", "op02", "op03", "op04", "op05", "op06", "op07", "op08", "op09", "op10",
    "bt01", "bt02", "bt03", "bt04", "bt05", "bt06", "bt07", "bt08", "bt09", "bt10",
    "ex01", "ex02", "ex03", "b01", "b02", "b03", "b04", "b05", "b06", "b07", "b08",
    "b09", "b10", "b11", "b12", "b13", "b14", "b15", "b16", "b17", "b18", "b19", "b20",
    "rb01", "eb01", "prb01", "jumpstart", "altered", "vicious", "dawn of", "royal blood",
    "romance dawn", "paramount war", "pillars of strength", "kingdom of intrigue", 
    "awakening of", "wings of", "two legends", "500 years", "memorial collection",
    "premium the best", "ursulas", "das erste kapitel", "draconic roar", "rising wind",
    "classic collection", "power absorbed", "fighters ambition", "malicious", "colossal",
    "ultimate advent", "battle evolution", "supreme rivalry", "vermilion", "ultimate squad",
    "rise of", "beyond generations", "trial by frost", "beyond the gates"
]

# Produkt-Typ Mapping (verschiedene Schreibweisen für die gleichen Produkttypen)
PRODUCT_TYPE_VARIANTS = {
    "display": [
        "display", "36er display", "36-er display", "36 booster", "36er booster",
        "booster display", "booster box", "36er box", "box", "booster-box"
    ],
    "etb": [
        "etb", "elite trainer box", "elite-trainer-box", "elite trainer", "trainer box"
    ],
    "ttb": [
        "ttb", "top trainer box", "top-trainer-box", "top trainer", "trainer box"
    ],
    "blister": [
        "blister", "3pack", "3-pack", "3er pack", "3er blister", "sleeved booster",
        "sleeve booster", "check lane", "checklane"
    ]
}

# Locks für Thread-sichere Operationen
url_lock = Lock()
data_lock = Lock()

def scrape_mighty_cards(keywords_map, seen, out_of_stock, only_available=False):
    """
    Spezieller Scraper für mighty-cards.de mit Sitemap-Integration und Multithreading
    
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param seen: Set mit bereits gesehenen Produkttiteln
    :param out_of_stock: Set mit ausverkauften Produkten
    :param only_available: Ob nur verfügbare Produkte gemeldet werden sollen
    :return: Liste der neuen Treffer
    """
    start_time = time.time()
    logger.info("🌐 Starte speziellen Scraper für mighty-cards.de mit Sitemap-Integration und Multithreading")
    
    # Thread-sichere Kollektionen
    new_matches = []
    all_products = []  # Liste für alle gefundenen Produkte
    found_product_ids = set()  # Set für Deduplizierung von gefundenen Produkten
    
    # Sammle Produkt-Information aus keywords_map
    product_info = extract_product_name_type_info(keywords_map)
    logger.info(f"🔍 Extrahierte Produktinformationen: {len(product_info)} Einträge")
    
    # Standardheader erstellen
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7"
    }
    
    # 1. Zugriff über die Sitemap mit Vorfilterung
    logger.info("🔍 Lade und filtere Produkte aus der Sitemap")
    sitemap_products = fetch_filtered_products_from_sitemap(headers, product_info)
    
    if sitemap_products:
        logger.info(f"🔍 Nach Vorfilterung verbleiben {len(sitemap_products)} relevante URLs")
        
        # 2. Parallelisierte Verarbeitung der gefilterten Produkt-URLs
        logger.info(f"🔄 Starte parallele Verarbeitung von {len(sitemap_products)} URLs")
        
        # Bestimme optimale Worker-Anzahl basierend auf CPU-Kernen und URL-Anzahl
        max_workers = min(20, len(sitemap_products))  # Max 20 Worker
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Dictionary zum Speichern der Future-Objekte mit ihren URLs
            future_to_url = {
                executor.submit(
                    process_mighty_cards_product, 
                    url, product_info, seen, out_of_stock, only_available, 
                    headers, all_products, new_matches, found_product_ids
                ): url for url in sitemap_products
            }
            
            # Sammle die Ergebnisse ein, während sie fertig werden
            completed = 0
            total = len(future_to_url)
            
            for future in concurrent.futures.as_completed(future_to_url):
                url = future_to_url[future]
                completed += 1
                
                # Gib alle 10% einen Fortschrittsindikator aus
                if completed % max(1, total // 10) == 0 or completed == total:
                    percent = (completed / total) * 100
                    logger.info(f"⏳ Fortschritt: {completed}/{total} URLs verarbeitet ({percent:.1f}%)")
                
                try:
                    # Das Ergebnis wird bereits in den übergebenen Listen gespeichert
                    future.result()
                except Exception as e:
                    logger.error(f"❌ Fehler bei der Verarbeitung von {url}: {e}")
    
    # 3. Fallback: Direkte Suche nach Produkten, wenn nichts gefunden wurde
    if len(all_products) < 2:
        logger.info("🔍 Nicht genug Produkte über Sitemap gefunden, versuche direkte Suche")
        
        # Verwende unterschiedliche Suchbegriffe für die direkte Suche
        search_terms = []
        for product_item in product_info:
            for name_variant in product_item["name_variants"]:
                if name_variant not in search_terms:
                    search_terms.append(name_variant)
                    if len(search_terms) >= 5:  # Begrenze auf max. 5 Suchbegriffe
                        break
        
        # Füge auch immer die Produktcodes hinzu
        for product_item in product_info:
            if product_item["product_code"] and product_item["product_code"] not in search_terms:
                search_terms.append(product_item["product_code"])
        
        # Direktsuche mit den generierten Suchbegriffen
        for search_term in search_terms:
            search_products = search_mighty_cards_products(search_term, headers)
            
            # Verarbeite gefundene Produkte sequentiell (meist weniger)
            for product_url in search_products:
                with url_lock:  # Thread-sicher prüfen, ob URL bereits verarbeitet wurde
                    if product_url in sitemap_products:
                        continue  # Vermeidet Duplikate
                
                process_mighty_cards_product(product_url, product_info, seen, out_of_stock, only_available, 
                                             headers, all_products, new_matches, found_product_ids)
    
    # 4. Sende Benachrichtigungen in Batches, um Telegram-Limits zu umgehen
    if all_products:
        from utils.telegram import send_batch_notification
        
        # Gruppiere Produkte in kleinere Batches (max. 20 pro Batch)
        batch_size = 20
        product_batches = [all_products[i:i+batch_size] for i in range(0, len(all_products), batch_size)]
        
        for i, batch in enumerate(product_batches):
            logger.info(f"📤 Sende Batch {i+1}/{len(product_batches)} mit {len(batch)} Produkten")
            send_batch_notification(batch)
            # Kurze Pause zwischen Batches
            if i < len(product_batches) - 1:
                time.sleep(1)
    
    # Messung der Gesamtlaufzeit
    elapsed_time = time.time() - start_time
    logger.info(f"✅ Scraping abgeschlossen in {elapsed_time:.2f} Sekunden, {len(new_matches)} neue Treffer gefunden")
    
    return new_matches

def extract_product_name_type_info(keywords_map):
    """
    Extrahiert detaillierte Produkt-Informationen aus dem Keywords-Map.
    Trennt Produktnamen von Produkttypen und erstellt Varianten für verschiedene Schreibweisen.
    
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :return: Liste von Produktinformationen mit Name- und Typ-Varianten
    """
    product_info = []
    
    for search_term in keywords_map.keys():
        search_term_lower = search_term.lower()
        
        # 1. Extrahiere den Produkttyp
        product_type = extract_product_type_from_text(search_term_lower)
        
        # 2. Extrahiere den Produktnamen (ohne Produkttyp)
        product_name = re.sub(r'\s+(display|box|tin|etb|ttb|booster|36er)$', '', search_term_lower).strip()
        
        # 3. Extrahiere Produktcode (kp09, sv09, etc.) falls vorhanden
        product_code = None
        code_match = re.search(r'(kp\d+|sv\d+)', search_term_lower)
        if code_match:
            product_code = code_match.group(0)
        
        # 4. Erstelle Varianten für den Produktnamen (mit/ohne Bindestriche, etc.)
        name_variants = [product_name]
        
        # Mit Bindestrichen
        if ' ' in product_name:
            name_variants.append(product_name.replace(' ', '-'))
        
        # Ohne Leerzeichen
        if ' ' in product_name:
            name_variants.append(product_name.replace(' ', ''))
            
        # Mit Leerzeichen statt Bindestrichen
        if '-' in product_name:
            name_variants.append(product_name.replace('-', ' '))
        
        # Entferne Leerzeichen und Bindestriche für ein reines Keyword
        pure_name = re.sub(r'[\s\-]', '', product_name)
        if pure_name not in name_variants:
            name_variants.append(pure_name)
            
        # 5. Erstelle Varianten für den Produkttyp
        type_variants = []
        
        if product_type in PRODUCT_TYPE_VARIANTS:
            type_variants = PRODUCT_TYPE_VARIANTS[product_type]
        else:
            # Wenn der Typ nicht bekannt ist, verwende den erkannten Typ
            if product_type != "unknown":
                type_variants = [product_type]
        
        # 6. Füge das Produktinfo-Dictionary hinzu
        product_info.append({
            "original_term": search_term,
            "product_name": product_name,
            "product_type": product_type,
            "product_code": product_code,
            "name_variants": name_variants,
            "type_variants": type_variants,
            "tokens": keywords_map[search_term]  # Original-Tokens behalten
        })
    
    return product_info

def fetch_filtered_products_from_sitemap(headers, product_info):
    """
    Extrahiert und filtert Produkt-URLs aus der Sitemap von mighty-cards.de
    
    :param headers: HTTP-Headers für die Anfragen
    :param product_info: Liste mit extrahierten Produktinformationen
    :return: Liste mit vorgefilterterten Produkt-URLs
    """
    sitemap_url = "https://www.mighty-cards.de/wp-sitemap-ecstore-1.xml"
    
    try:
        logger.info(f"🔍 Lade Sitemap von {sitemap_url}")
        response = requests.get(sitemap_url, headers=headers, timeout=15)
        
        if response.status_code != 200:
            logger.error(f"❌ Fehler beim Abrufen der Sitemap: Status {response.status_code}")
            return []
            
        # Versuche, die XML mit verschiedenen Parsern zu verarbeiten
        try:
            # Versuche zuerst mit lxml-xml Parser
            soup = BeautifulSoup(response.content, "lxml-xml")
        except Exception:
            try:
                # Fallback zu html.parser
                soup = BeautifulSoup(response.content, "html.parser")
                logger.warning("⚠️ Verwende html.parser statt lxml-xml für XML-Parsing")
            except Exception as e:
                logger.error(f"❌ Fehler beim Parsen der Sitemap: {e}")
                return []
        
        # Alle URLs aus der Sitemap extrahieren
        all_product_urls = []
        for url_tag in soup.find_all("url"):
            loc_tag = url_tag.find("loc")
            if loc_tag and loc_tag.text:
                url = loc_tag.text.strip()
                # Nur Shop-URLs hinzufügen
                if "/shop/" in url:
                    all_product_urls.append(url)
        
        logger.info(f"🔍 {len(all_product_urls)} Produkt-URLs aus Sitemap extrahiert")
        
        # Sammle alle relevanten Keyword-Varianten für die Filterung
        relevant_keywords = []
        product_codes = []
        
        for product in product_info:
            # Produktnamen-Varianten
            for variant in product["name_variants"]:
                if variant and len(variant) > 3 and variant not in relevant_keywords:
                    relevant_keywords.append(variant)
            
            # Produktcodes
            if product["product_code"] and product["product_code"] not in product_codes:
                product_codes.append(product["product_code"])
        
        logger.info(f"🔍 Filterung mit {len(relevant_keywords)} Namen-Varianten und {len(product_codes)} Produktcodes")
        
        # Vorfilterung der URLs direkt nach dem Laden
        filtered_urls = []
        for url in all_product_urls:
            url_lower = url.lower()
            
            # 1. Muss "pokemon" im URL enthalten
            if "pokemon" not in url_lower:
                continue
                
            # 2. Darf keine Blacklist-Begriffe enthalten
            if contains_blacklist_terms(url_lower):
                continue
            
            # 3. Sollte idealerweise eines der relevanten Keywords enthalten
            relevant_match = False
            
            # Prüfe zuerst auf exakte Produktcodes (höchste Priorität)
            for code in product_codes:
                if code in url_lower:
                    relevant_match = True
                    break
            
            # Wenn kein Code gefunden, prüfe auf Namens-Varianten
            if not relevant_match:
                for kw in relevant_keywords:
                    if kw in url_lower:
                        relevant_match = True
                        break
            
            # URLs mit relevanten Keywords werden priorisiert
            if relevant_match:
                filtered_urls.append(url)
            # URLs, die allgemein Pokemon sind, auch hinzufügen (als Fallback)
            elif "pokemon" in url_lower and ("scarlet" in url_lower or "violet" in url_lower or 
                                           "karmesin" in url_lower or "purpur" in url_lower):
                # Aber nur, wenn sie Scarlet/Violet oder Karmesin/Purpur enthalten
                filtered_urls.append(url)
        
        return filtered_urls
        
    except Exception as e:
        logger.error(f"❌ Fehler beim Laden der Sitemap: {e}")
        return []

def contains_blacklist_terms(text):
    """
    Prüft, ob der Text Blacklist-Begriffe enthält
    
    :param text: Zu prüfender Text
    :return: True wenn Blacklist-Begriff gefunden, False sonst
    """
    for term in PRODUCT_BLACKLIST:
        if term in text:
            return True
    return False

def search_mighty_cards_products(search_term, headers):
    """
    Sucht Produkte mit dem gegebenen Suchbegriff auf mighty-cards.de
    
    :param search_term: Suchbegriff
    :param headers: HTTP-Headers für die Anfragen
    :return: Liste mit gefundenen Produkt-URLs
    """
    product_urls = []
    
    try:
        # URL-Encoding für den Suchbegriff
        encoded_term = quote_plus(search_term)
        search_url = f"https://www.mighty-cards.de/shop/search?keyword={encoded_term}&limit=20"
        
        logger.info(f"🔍 Suche nach Produkten mit Begriff: {search_term}")
        response = requests.get(search_url, headers=headers, timeout=15)
        
        if response.status_code != 200:
            logger.warning(f"⚠️ Fehler bei der Suche nach {search_term}: Status {response.status_code}")
            return product_urls
            
        soup = BeautifulSoup(response.content, "html.parser")
        
        # Suche nach Produktlinks
        for link in soup.find_all("a", href=True):
            href = link.get('href', '')
            if '/shop/' in href and 'p' in href.split('/')[-1]:
                # Prüfe, ob der Link relevante Pokemon-Produkte enthält
                href_lower = href.lower()
                
                # Nur Pokemon-Links und keine Blacklist-Begriffe
                if "pokemon" in href_lower and not contains_blacklist_terms(href_lower):
                    # Vollständige URL erstellen
                    product_url = href if href.startswith('http') else urljoin("https://www.mighty-cards.de", href)
                    if product_url not in product_urls:
                        product_urls.append(product_url)
        
        logger.info(f"🔍 {len(product_urls)} Produkte gefunden für Suchbegriff '{search_term}'")
        
    except Exception as e:
        logger.warning(f"⚠️ Fehler bei der Suche nach {search_term}: {e}")
    
    return product_urls

def process_mighty_cards_product(product_url, product_info, seen, out_of_stock, only_available, 
                               headers, all_products, new_matches, found_product_ids):
    """
    Verarbeitet ein einzelnes Produkt von mighty-cards.de (Thread-sicher) mit verbesserter
    Produkttyp- und Produktnamen-Validierung.
    
    :param product_url: URL des Produkts
    :param product_info: Liste mit extrahierten Produktinformationen
    :param seen: Set mit bereits gesehenen Produkten
    :param out_of_stock: Set mit ausverkauften Produkten
    :param only_available: Ob nur verfügbare Produkte angezeigt werden sollen
    :param headers: HTTP-Headers für die Anfragen
    :param all_products: Liste für gefundene Produkte (wird aktualisiert)
    :param new_matches: Liste für neue Treffer (wird aktualisiert)
    :param found_product_ids: Set für Deduplizierung (wird aktualisiert)
    :return: True bei Erfolg, False bei Fehler
    """
    try:
        # Extra URL-Validierung mit strengeren Bedingungen
        url_lower = product_url.lower()
        
        # 1. Prüfe, ob die URL schon verarbeitet wurde (Thread-sicher)
        with url_lock:
            if any(product_url in pid for pid in found_product_ids):
                return False
        
        # 2. Muss "pokemon" als relevanten Kontext haben
        if "pokemon" not in url_lower:
            return False
            
        # 3. Darf keine Blacklist-Begriffe enthalten
        if contains_blacklist_terms(url_lower):
            return False
        
        # Produkt-Detailseite abrufen
        try:
            response = requests.get(product_url, headers=headers, timeout=15)
            if response.status_code != 200:
                logger.warning(f"⚠️ Fehler beim Abrufen von {product_url}: Status {response.status_code}")
                return False
        except requests.exceptions.RequestException as e:
            logger.warning(f"⚠️ Fehler beim Abrufen von {product_url}: {e}")
            return False
        
        soup = BeautifulSoup(response.content, "html.parser")
        
        # Titel extrahieren und validieren
        title_elem = soup.find('h1', {'class': 'product-details__product-title'})
        if not title_elem:
            title_elem = soup.find('h1')
        
        if not title_elem:
            # Wenn kein Titel gefunden wird, versuche aus URL zu generieren
            title = extract_title_from_url(product_url)
            logger.debug(f"⚠️ Kein Titel für {product_url} gefunden, generiere aus URL: {title}")
        else:
            title = title_elem.text.strip()
        
        # Strikte Titel-Validierung mit verbesserter Typ-vs-Name Unterscheidung
        title_lower = title.lower()
        
        # 1. "Pokemon" muss korrekt im Titel positioniert sein
        # Bei mighty-cards ist "Pokemon" oft am Ende des Titels, daher prüfen wir beide Positionen
        is_valid_pokemon_product = False
        
        # Muster 1: Pokemon ist am Anfang (Standard)
        if title_lower.startswith("pokemon"):
            is_valid_pokemon_product = True
        
        # Muster 2: Pokemon steht am Ende (typisch für mighty-cards.de)
        if title_lower.endswith("pokemon"):
            is_valid_pokemon_product = True
            
        # Muster 3: Pokémon TCG am Anfang
        if title_lower.startswith("pokémon") or "pokemon tcg" in title_lower:
            is_valid_pokemon_product = True
        
        # Wenn kein gültiges Pokemon-Produkt, abbrechen
        if not is_valid_pokemon_product:
            return False
            
        # 2. Enthält keine Blacklist-Begriffe
        if contains_blacklist_terms(title_lower):
            # Explizit "one piece card game" prüfen, da dieser häufig falsch erkannt wird
            if "one piece" in title_lower or "op01" in title_lower or "op02" in title_lower:
                return False
                
            logger.debug(f"❌ Titel enthält Blacklist-Begriff: {title}")
            return False
        
        # Produkttyp aus dem Titel extrahieren
        detected_product_type = extract_product_type_from_text(title)
        
        # Bereinigter Titel für besseres Matching (ohne Sonderzeichen)
        clean_title_lower = clean_text(title).lower()
        
        # 3. Verbesserte Prüfung: Exakte Übereinstimmung von Produktname + Produkttyp
        matched_product = None
        matching_score = 0
        
        for product in product_info:
            current_score = 0
            name_match = False
            type_match = False
            
            # 3.1 Prüfe Produktcode-Match (höchste Priorität)
            if product["product_code"] and product["product_code"] in clean_title_lower:
                current_score += 10
                name_match = True  # Wenn Produktcode stimmt, gilt der Name als übereinstimmend
            
            # 3.2 Prüfe Produktnamen-Match in verschiedenen Varianten
            if not name_match:
                for name_variant in product["name_variants"]:
                    if name_variant and name_variant in clean_title_lower:
                        name_match = True
                        current_score += 5
                        break
            
            # Wenn kein Name-Match, keine weitere Prüfung
            if not name_match:
                continue
                
            # 3.3 Prüfe Produkttyp-Match in verschiedenen Varianten
            for type_variant in product["type_variants"]:
                # Prüfe, ob der Variantentyp im Titel vorkommt
                if type_variant and type_variant in clean_title_lower:
                    type_match = True
                    current_score += 5
                    break
                
            # Alternative: Prüfe, ob der erkannte Produkttyp mit dem gesuchten übereinstimmt
            if not type_match and product["product_type"] == detected_product_type:
                type_match = True
                current_score += 3
            
            # 3.4 Wähle das Produkt mit dem höchsten Score
            if current_score > matching_score:
                matched_product = product
                matching_score = current_score
        
        # Wenn kein passendes Produkt gefunden oder Score zu niedrig
        # (Ein Match braucht mindestens einen Namen-Match -> mind. Score 5)
        if not matched_product or matching_score < 5:
            logger.debug(f"❌ Produkt passt nicht zu Suchbegriffen (Score {matching_score}): {title}")
            return False
        
        # Bei Produkttyp-Unstimmigkeit: Strengere Prüfung
        if matching_score >= 5 and matched_product["product_type"] != "unknown" and detected_product_type != "unknown":
            # Wenn sowohl der gesuchte als auch der erkannte Typ bekannt sind und nicht übereinstimmen
            if matched_product["product_type"] != detected_product_type:
                # Beispiel: Wir suchen nach "reisegefährten display", aber gefunden wird "reisegefährten blister"
                logger.debug(f"❌ Produkttyp stimmt nicht überein: Gesucht {matched_product['product_type']}, gefunden {detected_product_type} - {title}")
                return False
        
        # Verwende das Availability-Modul für Verfügbarkeitserkennnung
        is_available, price, status_text = detect_availability(soup, product_url)
        
        # Eindeutige ID für das Produkt erstellen
        product_id = create_product_id(title)
        
        # Thread-sichere Prüfung auf Duplikate
        with url_lock:
            if product_id in found_product_ids:
                return False
        
        # Status aktualisieren
        should_notify, is_back_in_stock = update_product_status(
            product_id, is_available, seen, out_of_stock
        )
        
        # Bei "nur verfügbare" Option, nicht verfügbare Produkte überspringen
        if only_available and not is_available:
            return False
        
        if should_notify:
            # Status anpassen wenn wieder verfügbar
            if is_back_in_stock:
                status_text = "🎉 Wieder verfügbar!"
            
            # Produkt-Daten sammeln
            product_data = {
                "title": title,
                "url": product_url,
                "price": price,
                "status_text": status_text,
                "is_available": is_available,
                "matched_term": matched_product["original_term"],
                "product_type": detected_product_type,
                "shop": "mighty-cards.de"
            }
            
            # Thread-sicher zu Ergebnissen hinzufügen
            with data_lock:
                all_products.append(product_data)
                new_matches.append(product_id)
                found_product_ids.add(product_id)
                
            logger.info(f"✅ Neuer Treffer gefunden: {title} - {status_text}")
            return True
    
    except Exception as e:
        logger.error(f"❌ Fehler bei der Verarbeitung von {product_url}: {e}")
    
    return False

def extract_title_from_url(url):
    """
    Extrahiert einen Titel aus der URL-Struktur
    
    :param url: URL der Produktseite
    :return: Extrahierter Titel
    """
    try:
        # Extrahiere den letzten Teil des Pfads
        path_parts = url.rstrip('/').split('/')
        last_part = path_parts[-1]
        
        # Entferne produktID am Ende (zB -p12345)
        last_part = re.sub(r'-p\d+$', '', last_part)
        
        # Ersetze Bindestriche durch Leerzeichen und formatiere
        title = last_part.replace('-', ' ').title()
        
        # Stelle sicher, dass "Pokemon" im Titel vorkommt (am Ende, wie typisch für mighty-cards)
        if "pokemon" not in title.lower():
            title = title + " Pokemon"
        
        return title
    except Exception as e:
        return "Pokemon Produkt"

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
    product_id = f"{base_id}_{product_code}_{product_type}_{language}_{normalized_title}"
    
    # Zusatzinformationen
    if "18er" in title_lower:
        product_id += "_18er"
    elif "36er" in title_lower:
        product_id += "_36er"
    
    return product_id