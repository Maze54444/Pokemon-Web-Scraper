"""
Spezieller Scraper für mighty-cards.de, der die Sitemap verwendet
um Produkte zu finden und zu verarbeiten.
Optimiert mit Multithreading und verbesserten Filterregeln.
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
from utils.matcher import is_keyword_in_text, extract_product_type_from_text
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
    
    # Standardheader erstellen
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7"
    }
    
    # 1. Zugriff über die Sitemap mit Vorfilterung
    logger.info("🔍 Lade und filtere Produkte aus der Sitemap")
    sitemap_products = fetch_filtered_products_from_sitemap(headers, keywords_map)
    
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
                    url, keywords_map, seen, out_of_stock, only_available, 
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
        
        # Verwende unterschiedliche Suchbegriffe, um die Chancen zu erhöhen
        for search_term in keywords_map.keys():
            search_products = search_mighty_cards_products(search_term, headers)
            
            # Verarbeite gefundene Produkte sequentiell (meist weniger)
            for product_url in search_products:
                with url_lock:  # Thread-sicher prüfen, ob URL bereits verarbeitet wurde
                    if product_url in sitemap_products:
                        continue  # Vermeidet Duplikate
                
                process_mighty_cards_product(product_url, keywords_map, seen, out_of_stock, only_available, 
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

def fetch_filtered_products_from_sitemap(headers, keywords_map):
    """
    Extrahiert und filtert Produkt-URLs aus der Sitemap von mighty-cards.de
    
    :param headers: HTTP-Headers für die Anfragen
    :param keywords_map: Dictionary mit Suchbegriffen für die Filterung
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
        
        # Extrahiere relevante Keywords für die Vorfilterung
        relevant_keywords = extract_relevant_keywords(keywords_map)
        logger.info(f"🔍 Verwende relevante Keywords für Vorfilterung: {relevant_keywords}")
        
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
            for kw in relevant_keywords:
                if kw in url_lower:
                    relevant_match = True
                    break
            
            # URLs mit relevanten Keywords werden priorisiert
            if relevant_match:
                filtered_urls.append(url)
            # URLs, die allgemein Pokemon sind, auch hinzufügen (als Fallback)
            elif "pokemon" in url_lower:
                filtered_urls.append(url)
        
        return filtered_urls
        
    except Exception as e:
        logger.error(f"❌ Fehler beim Laden der Sitemap: {e}")
        return []

def extract_relevant_keywords(keywords_map):
    """
    Extrahiert relevante Keywords für die URL-Vorfilterung
    
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :return: Liste mit relevanten Keywords
    """
    result = []
    
    # Extrahiere Produktcodes und spezifische Namen
    for search_term in keywords_map.keys():
        search_term_lower = search_term.lower()
        
        # 1. Extrahiere Produktcodes (kp09, sv09, etc.)
        code_match = re.search(r'(kp\d+|sv\d+)', search_term_lower)
        if code_match and code_match.group(0) not in result:
            result.append(code_match.group(0))
        
        # 2. Extrahiere spezifische Produkt-/Setnamen (ohne Produkttyp)
        clean_term = re.sub(r'\s+(display|box|tin|etb|ttb|booster|36er)$', '', search_term_lower)
        
        # Spezifische Set-Namen und -Identifikatoren
        set_keywords = [
            "reisegefährten", "reisegefahrten", "journey", "together", "togehter",
            "karmesin", "purpur", "scarlet", "violet", "sv09", "kp09",
            "temporal", "forces", "paradox", "paldea", "obsidian"
        ]
        
        for kw in set_keywords:
            if kw in clean_term and kw not in result:
                result.append(kw)
                
    return result

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

def process_mighty_cards_product(product_url, keywords_map, seen, out_of_stock, only_available, 
                               headers, all_products, new_matches, found_product_ids):
    """
    Verarbeitet ein einzelnes Produkt von mighty-cards.de (Thread-sicher)
    
    :param product_url: URL des Produkts
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
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
        
        # Strikte Titel-Validierung
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
        product_type = extract_product_type_from_text(title)
        
        # Prüfe, ob der Titel einem der Suchbegriffe entspricht - hier strenger!
        matched_term = None
        matching_score = 0  # Wie gut der Treffer ist
        
        for search_term, tokens in keywords_map.items():
            search_term_type = extract_product_type_from_text(search_term)
            search_term_lower = search_term.lower()
            
            # Bei Display-Suche: Nur Displays berücksichtigen
            if search_term_type == "display" and product_type != "display":
                continue
            
            # Verbesserte Keyword-Prüfung mit Produkttyp-Validierung
            # Extrahiere Produktcodes (KP09, SV09, etc.)
            code_match = re.search(r'(kp\d+|sv\d+)', search_term_lower)
            key_term = None
            if code_match:
                key_term = code_match.group(0)
                
            # Ist der Produktcode im Titel?
            if key_term and key_term in title_lower:
                current_score = 10  # Höchster Score für exakten Produktcode
                
                # Wenn auch der Produkttyp übereinstimmt, noch höherer Score
                if search_term_type == product_type:
                    current_score += 5
                
                # Nur den Suchbegriff mit dem höchsten Score verwenden
                if current_score > matching_score:
                    matched_term = search_term
                    matching_score = current_score
                continue  # Weiter mit dem nächsten Suchbegriff
            
            # Genereller Check über Token-Matching als Fallback
            if is_keyword_in_text(tokens, title, log_level='None'):
                current_score = 5  # Mittlerer Score für Token-Matching
                
                # Wenn auch der Produkttyp übereinstimmt, höherer Score
                if search_term_type == product_type:
                    current_score += 3
                
                # Nur den Suchbegriff mit dem höchsten Score verwenden
                if current_score > matching_score:
                    matched_term = search_term
                    matching_score = current_score
        
        # Wenn kein Match mit ausreichendem Score gefunden wurde
        if not matched_term or matching_score < 3:
            logger.debug(f"❌ Produkt passt nicht zu Suchbegriffen (Score {matching_score}): {title}")
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
                "matched_term": matched_term,
                "product_type": product_type,
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