"""
Spezieller Scraper für mighty-cards.de mit Sitemap-Integration und zweistufigem Ansatz:
1. BeautifulSoup für schnelle URL-Filterung
2. Selenium für präzise Preis-/Verfügbarkeitserkennung der gefundenen Treffer

Diese kombinierte Lösung bietet hohe Performance und Genauigkeit.
"""

import requests
import hashlib
import re
import json
import time
import random
import logging
import os
import threading
import queue
import concurrent.futures
from pathlib import Path
from threading import Lock
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote_plus

# Importiere die neuen Module für Selenium-Funktionalität
import selenium_manager
import mighty_cards_extraction

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
        "booster display", "booster box", "36er box", "box", "booster-box", "18er display",
        "18er booster", "18-er display"
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

# Umlaut-Mapping für die URL-Suche
UMLAUT_MAPPING = {
    'ä': 'a',
    'ö': 'o',
    'ü': 'u',
    'ß': 'ss',
    'Ä': 'A',
    'Ö': 'O',
    'Ü': 'U'
}

# Locks für Thread-sichere Operationen
url_lock = Lock()
data_lock = Lock()
cache_lock = Lock()

# Cache-Datei
CACHE_FILE = "data/mighty_cards_cache.json"

def initialize_browser_pool():
    """Initialisiert den Browser-Pool für Selenium"""
    logger.info(f"🔄 Initialisiere Browser-Pool für mighty-cards.de")
    return selenium_manager.initialize_browser_pool()

def shutdown_browser_pool():
    """Schließt den Browser-Pool"""
    logger.info("🔄 Schließe Browser-Pool")
    return selenium_manager.shutdown_browser_pool()

def extract_product_info_with_selenium(product_url, timeout=15):
    """
    Extrahiert präzise Preis- und Verfügbarkeitsinformationen mit Selenium
    
    :param product_url: URL der Produktseite
    :param timeout: Timeout in Sekunden
    :return: Dictionary mit Produktdetails
    """
    return mighty_cards_extraction.extract_product_info_with_selenium(product_url, timeout)

def check_product_availability(soup):
    """
    Prüft die Verfügbarkeit eines Produkts mit BeautifulSoup
    
    :param soup: BeautifulSoup-Objekt der Produktseite
    :return: Tuple (is_available, price, status_text)
    """
    return mighty_cards_extraction.check_product_availability_with_bs4(soup)

def load_cache():
    """Lädt den Cache mit gefundenen Produkten"""
    try:
        # Stelle sicher, dass das Verzeichnis existiert
        Path(CACHE_FILE).parent.mkdir(parents=True, exist_ok=True)
        
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"products": {}, "last_update": int(time.time())}
    except Exception as e:
        logger.error(f"❌ Fehler beim Laden des Caches: {e}")
        return {"products": {}, "last_update": int(time.time())}

def save_cache(cache_data):
    """Speichert den Cache mit gefundenen Produkten"""
    try:
        # Stelle sicher, dass das Verzeichnis existiert
        Path(CACHE_FILE).parent.mkdir(parents=True, exist_ok=True)
        
        with cache_lock:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"❌ Fehler beim Speichern des Caches: {e}")
        return False

def replace_umlauts(text):
    """
    Ersetzt deutsche Umlaute durch ihre ASCII-Entsprechungen
    
    :param text: Text mit möglichen Umlauten
    :return: Text mit ersetzten Umlauten
    """
    if not text:
        return ""
        
    result = text
    for umlaut, replacement in UMLAUT_MAPPING.items():
        result = result.replace(umlaut, replacement)
    return result

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
            
        # WICHTIG: Varianten ohne Umlaute hinzufügen
        umlaut_variants = []
        for variant in name_variants:
            replaced_variant = replace_umlauts(variant)
            if replaced_variant != variant and replaced_variant not in name_variants:
                umlaut_variants.append(replaced_variant)
        
        # Füge die Umlaut-Varianten hinzu
        name_variants.extend(umlaut_variants)
            
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
        # Verwende Original-Suchbegriff
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
        
        # Versuche Variante ohne Umlaute, wenn es keine Ergebnisse gab
        if not product_urls and any(umlaut in search_term for umlaut in UMLAUT_MAPPING.keys()):
            no_umlaut_term = replace_umlauts(search_term)
            logger.info(f"🔍 Versuche auch Suche ohne Umlaute: {no_umlaut_term}")
            
            encoded_term = quote_plus(no_umlaut_term)
            search_url = f"https://www.mighty-cards.de/shop/search?keyword={encoded_term}&limit=20"
            
            try:
                response = requests.get(search_url, headers=headers, timeout=15)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.content, "html.parser")
                    
                    for link in soup.find_all("a", href=True):
                        href = link.get('href', '')
                        if '/shop/' in href and 'p' in href.split('/')[-1]:
                            href_lower = href.lower()
                            
                            if "pokemon" in href_lower and not contains_blacklist_terms(href_lower):
                                product_url = href if href.startswith('http') else urljoin("https://www.mighty-cards.de", href)
                                if product_url not in product_urls:
                                    product_urls.append(product_url)
            except Exception as e:
                logger.warning(f"⚠️ Fehler bei der Suche ohne Umlaute nach {no_umlaut_term}: {e}")
        
        logger.info(f"🔍 {len(product_urls)} Produkte gefunden für Suchbegriff '{search_term}'")
        
    except Exception as e:
        logger.warning(f"⚠️ Fehler bei der Suche nach {search_term}: {e}")
    
    return product_urls

def fetch_filtered_products_from_sitemap_with_retry(headers, product_info, max_retries=4, timeout=15):
    """
    Lädt und filtert Produkt-URLs aus der Sitemap mit verbessertem Retry-Mechanismus
    
    :param headers: HTTP-Headers für die Anfragen
    :param product_info: Liste mit extrahierten Produktinformationen
    :param max_retries: Maximale Anzahl von Wiederholungsversuchen (3-4)
    :param timeout: Timeout pro Versuch in Sekunden
    :return: Liste mit vorgefilterterten Produkt-URLs
    """
    sitemap_url = "https://www.mighty-cards.de/wp-sitemap-ecstore-1.xml"
    
    # Mehrere Versuche, die Sitemap zu laden
    for retry in range(max_retries):
        try:
            logger.info(f"🔍 Lade Sitemap von {sitemap_url} (Versuch {retry+1}/{max_retries})")
            response = requests.get(sitemap_url, headers=headers, timeout=timeout)
            
            if response.status_code == 200:
                # Sitemap erfolgreich geladen
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
                        continue  # Zum nächsten Versuch
                
                # Alle URLs aus der Sitemap extrahieren
                all_product_urls = []
                for url_tag in soup.find_all("url"):
                    loc_tag = url_tag.find("loc")
                    if loc_tag and loc_tag.text:
                        url = loc_tag.text.strip()
                        # Nur Shop-URLs hinzufügen
                        if "/shop/" in url:
                            all_product_urls.append(url)
                
                if all_product_urls:
                    logger.info(f"🔍 {len(all_product_urls)} Produkt-URLs aus Sitemap extrahiert")
                    
                    # Filtern der URLs wie zuvor
                    return filter_sitemap_products(all_product_urls, product_info)
                else:
                    logger.warning(f"⚠️ Keine Produkt-URLs in der Sitemap gefunden (Versuch {retry+1}/{max_retries})")
            else:
                logger.warning(f"⚠️ Fehler beim Laden der Sitemap: Status {response.status_code} (Versuch {retry+1}/{max_retries})")
        
        except requests.exceptions.Timeout:
            logger.warning(f"⚠️ Timeout beim Laden der Sitemap (Versuch {retry+1}/{max_retries})")
        except Exception as e:
            logger.warning(f"⚠️ Fehler beim Laden der Sitemap: {e} (Versuch {retry+1}/{max_retries})")
        
        # Warte exponentiell länger vor dem nächsten Versuch, wenn nicht der letzte Versuch
        if retry < max_retries - 1:
            wait_time = 2 ** retry  # 1, 2, 4, 8 Sekunden...
            logger.info(f"🕒 Warte {wait_time} Sekunden vor dem nächsten Versuch...")
            time.sleep(wait_time)
    
    # Wenn alle Versuche fehlschlagen, leere Liste zurückgeben
    logger.error(f"❌ Alle {max_retries} Versuche zum Laden der Sitemap sind fehlgeschlagen")
    return []

def filter_sitemap_products(all_product_urls, product_info):
    """
    Filtert Produkt-URLs aus der Sitemap basierend auf den Produktinformationen
    
    :param all_product_urls: Liste aller Produkt-URLs aus der Sitemap
    :param product_info: Liste mit extrahierten Produktinformationen
    :return: Liste mit gefilterten Produkt-URLs
    """
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
    direct_matches = []  # Für besonders relevante URLs (direkte Treffer)
    
    for url in all_product_urls:
        url_lower = url.lower()
        
        # 1. Muss "pokemon" im URL enthalten
        if "pokemon" not in url_lower:
            continue
            
        # 2. Darf keine Blacklist-Begriffe enthalten
        if contains_blacklist_terms(url_lower):
            continue
        
        # Prüfe auf direkte Übereinstimmung mit Produktcode oder Setnamen
        # z.B. "kp09" oder "reisegefahrten" im URL
        is_direct_match = False
        
        # Prüfe zuerst auf Produktcodes (höchste Priorität)
        for code in product_codes:
            if code and code.lower() in url_lower:
                is_direct_match = True
                direct_matches.append(url)
                break
        
        if is_direct_match:
            continue  # Wurde bereits zu direct_matches hinzugefügt
        
        # Prüfe auf alle Namen-Varianten (inkl. ohne Umlaute)
        relevant_match = False
        for kw in relevant_keywords:
            if kw and kw.lower() in url_lower:
                relevant_match = True
                break
        
        # URLs mit relevantem Keyword hinzufügen
        if relevant_match:
            filtered_urls.append(url)
        # URLs, die allgemein relevante Begriffe enthalten, als Fallback
        elif any(term in url_lower for term in ["karmesin", "purpur", "scarlet", "violet", "kp09", "sv09"]):
            filtered_urls.append(url)
    
    # Direkte Matches haben höchste Priorität
    # (Diese sollten definitiv Ergebnisse liefern)
    logger.info(f"🔍 {len(direct_matches)} direkte Treffer und {len(filtered_urls)} potentielle Treffer gefunden")
    
    # Direkte Matches zuerst, dann andere gefilterte URLs
    result = direct_matches + [url for url in filtered_urls if url not in direct_matches]
    return result

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

def process_product_matches_with_selenium(positive_matches):
    """
    Verarbeitet die positiven Treffer mit Selenium für präzise Preis- und Verfügbarkeitsinformationen
    
    :param positive_matches: Liste der positiven Treffer aus dem BeautifulSoup-Scanning
    :return: Liste der aktualisierten Produktinformationen
    """
    return mighty_cards_extraction.process_product_matches_with_selenium(positive_matches)

def process_mighty_cards_product(product_url, product_info, seen, out_of_stock, only_available, 
                               headers, all_products, new_matches, found_product_ids, cached_products=None):
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
    :param cached_products: Optional - Cache-Dictionary für gefundene Produkte
    :return: True bei Erfolg, False bei Fehler
    """
    try:
        # DEBUG: Zeige URL für Debugging-Zwecke
        logger.debug(f"Prüfe URL: {product_url}")
        
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
        
        # DEBUG: Zeige Titel für Debugging-Zwecke
        logger.debug(f"Titel: {title}")
        
        # VERBESSERT: Verwende die neue Verfügbarkeitsprüfung
        is_available, price, status_text = check_product_availability(soup)
        
        # URL-Segmente für zuverlässigere Erkennung aufteilen
        url_segments = product_url.split('/')
        url_filename = url_segments[-1].lower() if url_segments else ""
        
        # Produktcode aus URL extrahieren (z.B. KP09, SV09)
        url_code_match = re.search(r'(kp\d+|sv\d+)', url_filename, re.IGNORECASE)
        url_product_code = url_code_match.group(0).lower() if url_code_match else None
        
        # Produkttyp aus dem Titel extrahieren
        detected_product_type = extract_product_type_from_text(title)
        
        # Bereinigter Titel für besseres Matching (ohne Sonderzeichen)
        clean_title_lower = clean_text(title).lower()
        
        # 3. Verbesserte URL-basierte Prüfung: Wenn KP09/SV09 in der URL ist, direkt annehmen
        direct_url_match = False
        matched_product = None
        matching_score = 0
        
        # Spezialfall: URL enthält KP09/SV09 und Display/Booster - sofort akzeptieren
        if url_product_code and any(term in url_filename for term in ["display", "booster", "36er", "18er"]):
            logger.debug(f"✅ Direkter Treffer in URL: {url_product_code} + Display/Booster")
            
            # Finde das passende Produkt aus unserer Liste
            for product in product_info:
                if product["product_code"] and product["product_code"].lower() == url_product_code:
                    matched_product = product
                    matching_score = 15  # Sehr hoher Score für direkten Code-Match
                    direct_url_match = True
                    break
                    
                # Prüfe auf Produktnamen-Match in URL
                for name_variant in product["name_variants"]:
                    # Sowohl mit als auch ohne Umlaute prüfen
                    name_match = name_variant and name_variant.lower() in url_filename
                    umlaut_match = name_variant and replace_umlauts(name_variant).lower() in url_filename
                    
                    if name_match or umlaut_match:
                        # Auch auf Produkttyp in URL prüfen
                        for type_variant in product["type_variants"]:
                            if type_variant and type_variant.lower() in url_filename:
                                matched_product = product
                                matching_score = 12  # Hoher Score für Name+Typ in URL
                                direct_url_match = True
                                break
                        
                        if direct_url_match:
                            break
            
        # Wenn kein direkter URL-Match, dann Titel-basierte Prüfung
        if not direct_url_match:
            for product in product_info:
                current_score = 0
                name_match = False
                type_match = False
                
                # 3.1 Prüfe Produktcode-Match (höchste Priorität)
                if product["product_code"] and product["product_code"].lower() in clean_title_lower:
                    current_score += 10
                    name_match = True  # Wenn Produktcode stimmt, gilt der Name als übereinstimmend
                
                # 3.2 Prüfe Produktnamen-Match in verschiedenen Varianten
                if not name_match:
                    for name_variant in product["name_variants"]:
                        if name_variant and name_variant.lower() in clean_title_lower:
                            name_match = True
                            current_score += 5
                            break
                
                # Wenn kein Name-Match, keine weitere Prüfung
                if not name_match:
                    continue
                    
                # 3.3 Prüfe Produkttyp-Match in verschiedenen Varianten
                for type_variant in product["type_variants"]:
                    # Prüfe, ob der Variantentyp im Titel vorkommt
                    if type_variant and type_variant.lower() in clean_title_lower:
                        type_match = True
                        current_score += 5
                        break
                    
                # Alternative: Prüfe, ob der erkannte Produkttyp mit dem gesuchten übereinstimmt
                if not type_match and product["product_type"] == detected_product_type:
                    type_match = True
                    current_score += 3
                
                # VERBESSERT: Striktere Typprüfung - wenn gesuchter Typ und erkannter Typ bekannt
                # sind und nicht übereinstimmen, reduziere den Score
                if product["product_type"] != "unknown" and detected_product_type != "unknown":
                    if product["product_type"] != detected_product_type:
                        # Bei Display besonders streng sein
                        if product["product_type"] == "display" and detected_product_type != "display":
                            current_score -= 20  # Stark reduzieren, wenn wir Display suchen aber etwas anderes finden
                        else:
                            current_score -= 5  # Weniger stark reduzieren für andere Typen
                
                # 3.4 Wähle das Produkt mit dem höchsten Score
                if current_score > matching_score:
                    matched_product = product
                    matching_score = current_score
        
        # Wenn kein passendes Produkt gefunden oder Score zu niedrig
        # (Ein Match braucht mindestens einen Namen-Match -> mind. Score 5)
        if not matched_product or matching_score < 5:
            # Eine letzte Chance: Wenn wir eine KP09/SV09 URL haben, nehmen wir das Produkt mit diesem Code
            if url_product_code:
                for product in product_info:
                    if product["product_code"] and product["product_code"].lower() == url_product_code:
                        matched_product = product
                        matching_score = 10  # Hoher Score für Code-Match in URL
                        logger.info(f"🔍 KP09/SV09-basierter Treffer: {url_product_code} -> {product['original_term']}")
                        break
            
            # Wenn immer noch kein Match, dann ablehnen
            if not matched_product or matching_score < 5:
                logger.debug(f"❌ Produkt passt nicht zu Suchbegriffen (Score {matching_score}): {title}")
                return False
        
        # VERBESSERT: Bei Blister/ETB Produkten, wenn wir eigentlich Display suchen, ablehnen
        if matched_product["product_type"] == "display" and detected_product_type != "unknown" and detected_product_type != "display":
            logger.debug(f"❌ Produkttyp stimmt nicht überein: Gesucht '{matched_product['product_type']}', gefunden '{detected_product_type}': {title}")
            return False
        
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
            # Allerdings zum Cache hinzufügen, wenn möglich
            if cached_products is not None:
                with cache_lock:
                    cached_products[product_id] = {
                        "product_id": product_id,
                        "title": title,
                        "url": product_url,
                        "search_term": matched_product["original_term"],
                        "is_available": is_available,
                        "price": price,
                        "last_checked": int(time.time())
                    }
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
            
            # Zum Cache hinzufügen, wenn möglich
            if cached_products is not None:
                with cache_lock:
                    cached_products[product_id] = {
                        "product_id": product_id,
                        "title": title,
                        "url": product_url,
                        "search_term": matched_product["original_term"],
                        "is_available": is_available,
                        "price": price,
                        "last_checked": int(time.time())
                    }
            
            return True
    
    except Exception as e:
        logger.error(f"❌ Fehler bei der Verarbeitung von {product_url}: {e}")
    
    return False

# Import für extract_product_type_from_text
def extract_product_type_from_text(text):
    """
    Extrahiert den Produkttyp aus einem Text für strengere Filterung
    
    :param text: Text, aus dem der Produkttyp extrahiert werden soll
    :return: Produkttyp als String oder "unknown" wenn nicht eindeutig
    """
    # Diese Funktion muss importiert werden von utils.matcher
    from utils.matcher import extract_product_type_from_text as extract_type
    return extract_type(text)

# Import für clean_text
def clean_text(text):
    """
    Bereinigt einen Text (Kleinbuchstaben, ohne Sonderzeichen)
    
    :param text: Zu bereinigender Text
    :return: Bereinigter Text
    """
    # Diese Funktion muss importiert werden von utils.matcher
    from utils.matcher import clean_text as clean
    return clean(text)

def scrape_mighty_cards(keywords_map, seen, out_of_stock, only_available=False):
    """
    Hauptfunktion: Zweistufiger Scaper mit BeautifulSoup zur schnellen URL-Filterung
    und Selenium für die präzise Preis-/Verfügbarkeitserkennung bei positiven Treffern
    
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param seen: Set mit bereits gesehenen Produkten
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
    
    # Cache laden
    cache_data = load_cache()
    cached_products = cache_data.get("products", {})
    last_update = cache_data.get("last_update", 0)
    current_time = int(time.time())
    
    # Cache-Kriterien
    cache_valid = len(cached_products) > 0
    force_refresh = current_time - last_update > 86400  # Alle 24 Stunden Cache aktualisieren
    
    # Prüfen, ob wir neue Keywords haben, die nicht im Cache sind
    found_all_products = True
    
    # Prüfen, ob alle gesuchten Produkte im Cache sind
    for item in product_info:
        original_term = item["original_term"]
        if not any(original_term == cached["search_term"] for cached in cached_products.values()):
            found_all_products = False
            break
    
    # Entscheiden, ob wir den Cache verwenden oder neu scannen
    if cache_valid and found_all_products and not force_refresh:
        logger.info(f"✅ Verwende Cache mit {len(cached_products)} Produkten")
        
        # Überprüfe jedes zwischengespeicherte Produkt erneut
        valid_product_urls = []
        cached_items_to_remove = []
        
        for product_id, product_data in cached_products.items():
            product_url = product_data.get("url")
            if not product_url:
                cached_items_to_remove.append(product_id)
                continue
                
            valid_product_urls.append((product_url, product_data))
        
        # Entferne ungültige Einträge aus dem Cache
        for item_id in cached_items_to_remove:
            del cached_products[item_id]
        
        # Wenn wir gültige Produkt-URLs haben, verarbeite sie direkt
        if valid_product_urls:
            logger.info(f"🔄 Überprüfe {len(valid_product_urls)} zwischengespeicherte Produkte")
            
            # Parallelisierte Verarbeitung der gecachten Produkt-URLs
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(valid_product_urls), 10)) as executor:
                futures = []
                
                for product_url, product_data in valid_product_urls:
                    future = executor.submit(
                        process_cached_product,
                        product_url, product_data, product_info, seen, out_of_stock, only_available,
                        headers, all_products, new_matches, found_product_ids, cached_products
                    )
                    futures.append((future, product_url))
                
                # Sammle Ergebnisse und prüfe auf 404-Fehler
                need_rescan = False
                completed = 0
                
                for future, url in futures:
                    try:
                        result, error_404 = future.result()
                        completed += 1
                        
                        # Wenn einer der URLs 404 zurückgibt, müssen wir neu scannen
                        if error_404:
                            need_rescan = True
                            logger.warning(f"⚠️ Gecachte URL nicht mehr erreichbar: {url}")
                            
                            # Entferne URL aus dem Cache
                            for pid, pdata in list(cached_products.items()):
                                if pdata.get("url") == url:
                                    del cached_products[pid]
                    except Exception as e:
                        logger.error(f"❌ Fehler bei der Verarbeitung von {url}: {e}")
                        completed += 1
                
                # Zeige Fortschritt
                if len(futures) > 0:
                    logger.info(f"✅ {completed}/{len(futures)} cache URLs verarbeitet")
            
            # Wenn wir einen 404-Fehler hatten oder nicht alle Produkte gefunden haben, scannen wir neu
            if need_rescan or not new_matches:
                logger.info("🔄 Einige gecachte URLs lieferten 404 oder keine Treffer - führe vollständigen Scan durch")
                # Führe einen vollständigen Scan mit Sitemap durch (siehe unten)
            else:
                # Produkte für die zweite Stufe (Selenium) sammeln
                if all_products:
                    # Verarbeite die positiven Treffer mit Selenium für präzise Daten
                    # Prüfen, ob Selenium verfügbar ist
                    if selenium_manager.is_selenium_available():
                        updated_products = process_product_matches_with_selenium(all_products)
                        
                        # Überschreibe die vorherigen Ergebnisse
                        all_products = updated_products
                    else:
                        logger.warning("⚠️ Selenium nicht verfügbar - verwende BeautifulSoup-Daten ohne Validierung")
                
                    # Sende Benachrichtigungen für die aktualisierten Produkte
                    from utils.telegram import send_batch_notification
                    send_batch_notification(all_products)
                
                # Cache aktualisieren
                cache_data["products"] = cached_products
                cache_data["last_update"] = current_time
                save_cache(cache_data)
                
                # Messung der Gesamtlaufzeit
                elapsed_time = time.time() - start_time
                logger.info(f"✅ Cache-basiertes Scraping abgeschlossen in {elapsed_time:.2f} Sekunden, {len(new_matches)} Treffer gefunden")
                
                return new_matches
    
    # Vollständiger Scan erforderlich
    logger.info("🔍 Führe vollständigen Scan mit Sitemap durch")
    
    # 1. Zugriff über die Sitemap mit Vorfilterung
    logger.info("🔍 Lade und filtere Produkte aus der Sitemap")
    sitemap_products = fetch_filtered_products_from_sitemap_with_retry(headers, product_info)
    
    if sitemap_products:
        logger.info(f"🔍 Nach Vorfilterung verbleiben {len(sitemap_products)} relevante URLs")
        
        # 2. Parallelisierte Verarbeitung der gefilterten Produkt-URLs
        logger.info(f"🔄 Starte parallele Verarbeitung von {len(sitemap_products)} URLs")
        
        # Bestimme optimale Worker-Anzahl basierend auf CPU-Kernen und URL-Anzahl
        max_workers = min(20, len(sitemap_products))  # Max 20 Worker
        
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Dictionary zum Speichern der Future-Objekte mit ihren URLs
            future_to_url = {
                executor.submit(
                    process_mighty_cards_product, 
                    url, product_info, seen, out_of_stock, only_available, 
                    headers, all_products, new_matches, found_product_ids, cached_products
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
            # Verwende Original-Term und Ersetzungsversion (ohne Umlaute)
            search_products = search_mighty_cards_products(search_term, headers)
            
            # Verarbeite gefundene Produkte sequentiell (meist weniger)
            for product_url in search_products:
                with url_lock:  # Thread-sicher prüfen, ob URL bereits verarbeitet wurde
                    if product_url in sitemap_products:
                        continue  # Vermeidet Duplikate
                
                process_mighty_cards_product(product_url, product_info, seen, out_of_stock, only_available, 
                                            headers, all_products, new_matches, found_product_ids, cached_products)
    
    # Cache aktualisieren
    if cached_products:
        cache_data["products"] = cached_products
        cache_data["last_update"] = current_time
        save_cache(cache_data)
    
    # 4. Zweite Stufe: Verarbeite positive Treffer mit Selenium für präzise Daten
    if all_products:
        # Prüfen, ob Selenium verfügbar ist
        if selenium_manager.is_selenium_available():
            updated_products = process_product_matches_with_selenium(all_products)
            
            # Überschreibe die vorherigen Ergebnisse
            all_products = updated_products
        else:
            logger.warning("⚠️ Selenium nicht verfügbar - verwende BeautifulSoup-Daten ohne Validierung")
        
        # Sende Benachrichtigungen für die aktualisierten Produkte
        from utils.telegram import send_batch_notification
        send_batch_notification(all_products)
    else:
        logger.info("ℹ️ Keine Produkte für Selenium-Verarbeitung gefunden")
    
    # Messung der Gesamtlaufzeit
    elapsed_time = time.time() - start_time
    logger.info(f"✅ Scraping abgeschlossen in {elapsed_time:.2f} Sekunden, {len(new_matches)} neue Treffer gefunden")
    
    return new_matches

def process_cached_product(product_url, product_data, product_info, seen, out_of_stock, only_available,
                         headers, all_products, new_matches, found_product_ids, cached_products):
    """
    Verarbeitet ein bereits im Cache gespeichertes Produkt
    
    :return: (success, error_404) - Erfolg und ob ein 404-Fehler aufgetreten ist
    """
    search_term = product_data.get("search_term")
    
    try:
        # Produkt-Detailseite abrufen
        try:
            response = requests.get(product_url, headers=headers, timeout=15)
            
            # Wenn 404 zurückgegeben wird, müssen wir die Sitemap neu scannen
            if response.status_code == 404:
                return False, True
                
            if response.status_code != 200:
                logger.warning(f"⚠️ Fehler beim Abrufen von {product_url}: Status {response.status_code}")
                return False, False
        except requests.exceptions.RequestException as e:
            logger.warning(f"⚠️ Fehler beim Abrufen von {product_url}: {e}")
            return False, False
        
        soup = BeautifulSoup(response.content, "html.parser")
        
        # Titel extrahieren
        title_elem = soup.find('title')
        link_text = title_elem.text.strip() if title_elem else ""
        
        # VERBESSERT: Strikte Prüfung auf exakte Übereinstimmung mit dem Suchbegriff
        tokens = keywords_map.get(search_term, [])
        
        # Extrahiere Produkttyp aus Suchbegriff und Titel
        search_term_type = extract_product_type_from_text(search_term)
        title_product_type = extract_product_type_from_text(link_text)
        
        # Wenn nach einem bestimmten Produkttyp gesucht wird, muss dieser im Titel übereinstimmen
        if search_term_type in ["display", "etb", "ttb"] and title_product_type != search_term_type:
            logger.debug(f"⚠️ Produkttyp-Diskrepanz: Suche nach '{search_term_type}', aber Produkt ist '{title_product_type}': {link_text}")
            return True, False
        
        # Strengere Keyword-Prüfung mit Berücksichtigung des Produkttyps
        from utils.matcher import is_keyword_in_text
        if not is_keyword_in_text(tokens, link_text, log_level='None'):
            logger.debug(f"⚠️ Produkt entspricht nicht mehr dem Suchbegriff '{search_term}': {link_text}")
            return True, False
        
        # Aktualisiere die letzte Prüfzeit
        product_data["last_checked"] = time.time()
        
        # Prüfe Verfügbarkeit mit BeautifulSoup
        is_available, price, status_text = check_product_availability(soup)
        
        # Falls BeautifulSoup keine klare Erkennung liefert und Selenium verfügbar ist,
        # verwende Selenium für präzisere Erkennung
        if is_available is None and selenium_manager.is_selenium_available():
            try:
                selenium_data = extract_product_info_with_selenium(product_url)
                is_available = selenium_data.get("is_available", False)
                price = selenium_data.get("price", price)
                status_text = selenium_data.get("status_text", status_text)
            except Exception as e:
                logger.warning(f"⚠️ Selenium-Extraktion fehlgeschlagen, verwende BeautifulSoup-Daten: {e}")
                # Fallback auf konservative Annahme bei unklarer BeautifulSoup-Erkennung
                is_available = False
        elif is_available is None:
            # Fallback auf konservative Annahme, wenn Selenium nicht verfügbar
            is_available = False
        
        # Aktualisiere Cache-Eintrag
        product_data["is_available"] = is_available
        product_data["price"] = price
        
        # Aktualisiere Produkt-Status und prüfe, ob Benachrichtigung gesendet werden soll
        product_id = product_data.get("product_id") or create_product_id(link_text)
        should_notify, is_back_in_stock = update_product_status(
            product_id, is_available, seen, out_of_stock
        )
        
        if should_notify and (not only_available or is_available):
            # Wenn Produkt wieder verfügbar ist, anpassen
            if is_back_in_stock:
                status_text = "🎉 Wieder verfügbar!"
            # Wenn kein Status-Text vorhanden ist, erstellen
            elif not status_text or status_text == "[?] Status unbekannt":
                from utils.stock import get_status_text
                status_text = get_status_text(is_available, is_back_in_stock)
            
            # Produkt-Informationen sammeln für Batch-Benachrichtigung
            product_data = {
                "title": link_text,
                "url": product_url,
                "price": price,
                "status_text": status_text,
                "is_available": is_available,
                "matched_term": search_term,
                "product_type": title_product_type,
                "shop": "mighty-cards.de"
            }
            
            # Deduplizierung innerhalb eines Durchlaufs
            if product_id not in found_product_ids:
                all_products.append(product_data)
                new_matches.append(product_id)
                found_product_ids.add(product_id)
                logger.info(f"✅ Cache-Treffer: {link_text} - {status_text}")
        
        return True, False
    
    except Exception as e:
        logger.error(f"❌ Fehler bei der Verarbeitung von gecachtem Produkt {product_url}: {e}")
        return False, False