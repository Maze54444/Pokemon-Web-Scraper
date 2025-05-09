"""
Spezieller Scraper für tcgviert.com mit Cache-System für gefundene Produkte.
Implementiert JSON-API und HTML-Methoden zur effizienten Überwachung von 
Pokemon-Produkten mit dauerhafter URL-Speicherung und Verfügbarkeitsüberwachung.
"""

import requests
import re
import logging
import time
import json
import os
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from utils.telegram import send_batch_notification
from utils.matcher import is_keyword_in_text, extract_product_type_from_text, load_exclusion_sets
from utils.stock import get_status_text, update_product_status
from utils.availability import detect_availability
from utils.requests_handler import get_page_content, get_default_headers

# Logger konfigurieren
logger = logging.getLogger(__name__)

# Cache-Datei für gefundene Produkt-URLs
PRODUCT_CACHE_FILE = "data/tcgviert_cache.json"

def load_product_cache():
    """Lädt den Cache mit gefundenen Produkt-URLs"""
    try:
        Path(PRODUCT_CACHE_FILE).parent.mkdir(parents=True, exist_ok=True)
        
        if os.path.exists(PRODUCT_CACHE_FILE):
            with open(PRODUCT_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        
        logger.info("ℹ️ Produkt-Cache-Datei nicht gefunden. Neuer Cache wird erstellt.")
        return {"products": {}, "last_update": int(time.time())}
    except Exception as e:
        logger.error(f"⚠️ Fehler beim Laden des Produkt-Caches: {e}")
        return {"products": {}, "last_update": int(time.time())}

def save_product_cache(cache_data):
    """Speichert den Cache mit gefundenen Produkt-URLs"""
    try:
        Path(PRODUCT_CACHE_FILE).parent.mkdir(parents=True, exist_ok=True)
        
        with open(PRODUCT_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"⚠️ Fehler beim Speichern des Produkt-Caches: {e}")
        return False

def extract_product_info(title):
    """
    Extrahiert wichtige Produktinformationen aus dem Titel für die ID-Erstellung
    
    :param title: Produkttitel
    :return: Tupel mit (series_code, product_type, language)
    """
    # Extrahiere Sprache (DE/EN)
    if "(DE)" in title or "pro Person" in title:
        language = "DE"
    elif "(EN)" in title or "per person" in title:
        language = "EN"
    else:
        language = "UNK"
    
    # Extrahiere Produkttyp
    product_type = extract_product_type_from_text(title)
    if product_type == "unknown":
        # Fallback zur einfachen Methode
        if re.search(r'display|36er', title.lower()):
            product_type = "display"
        elif re.search(r'etb|elite trainer box', title.lower()):
            product_type = "etb"
        elif re.search(r'booster|pack', title.lower()):
            product_type = "booster"
        else:
            product_type = "unknown"
    
    # Extrahiere Serien-/Set-Code
    series_code = "unknown"
    # Suche nach Standard-Codes wie SV09, KP09, etc.
    code_match = re.search(r'(?:sv|kp)(?:\s|-)?\d+', title.lower())
    if code_match:
        series_code = code_match.group(0).replace(" ", "").replace("-", "")
    
    return (series_code, product_type, language)

def create_product_id(title, base_id="tcgviert"):
    """
    Erstellt eine eindeutige Produkt-ID basierend auf dem Titel
    
    :param title: Produkttitel
    :param base_id: Basis-ID (z.B. Website-Name)
    :return: Eindeutige Produkt-ID
    """
    # Extrahiere strukturierte Informationen
    series_code, product_type, language = extract_product_info(title)
    
    # Erstelle eine strukturierte ID
    product_id = f"{base_id}_{series_code}_{product_type}_{language}"
    
    return product_id

def add_url_to_cache(url, title, search_term, is_available, price):
    """
    Fügt eine URL zum permanenten Cache hinzu
    
    :param url: Produktseiten-URL
    :param title: Produkttitel
    :param search_term: Übereinstimmender Suchbegriff
    :param is_available: Ob das Produkt verfügbar ist
    :param price: Produktpreis
    """
    # Lade aktuellen Cache
    cache_data = load_product_cache()
    
    # Erstelle eindeutige ID
    product_id = create_product_id(title)
    
    # Füge zur Produkte-Map hinzu
    cache_data["products"][product_id] = {
        "url": url,
        "title": title,
        "search_term": search_term,
        "last_checked": int(time.time()),
        "is_available": is_available,
        "price": price
    }
    
    # Aktualisiere Zeitstempel
    cache_data["last_update"] = int(time.time())
    
    # Speichere Cache
    save_product_cache(cache_data)
    logger.debug(f"URL zu Cache hinzugefügt: {url}")

def check_cached_products(keywords_map, seen, out_of_stock, only_available=False):
    """
    Überprüft gespeicherte URLs im Cache und aktualisiert deren Status
    
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param seen: Set mit bereits gesehenen Produkten
    :param out_of_stock: Set mit ausverkauften Produkten
    :param only_available: Ob nur verfügbare Produkte gemeldet werden sollen
    :return: Tuple (new_matches, all_products)
    """
    logger.info("🔍 Überprüfe gespeicherte Produkt-URLs aus dem Cache")
    cache_data = load_product_cache()
    
    new_matches = []
    all_products = []
    found_product_ids = set()
    
    # Überprüfe jedes Produkt im Cache
    for product_id, product_info in list(cache_data["products"].items()):
        url = product_info.get("url")
        title = product_info.get("title")
        search_term = product_info.get("search_term")
        last_checked = product_info.get("last_checked", 0)
        current_time = int(time.time())
        
        # Überprüfe nur alle 2 Stunden
        if current_time - last_checked < 7200:
            logger.debug(f"⏱️ Überspringe kürzlich geprüftes Produkt: {title}")
            continue
        
        # Prüfe, ob der Suchbegriff noch aktuell ist
        if search_term not in keywords_map:
            logger.debug(f"⏭️ Überspringe Produkt mit nicht mehr aktuellem Suchbegriff: {title}")
            continue
        
        # Prüfe die URL
        try:
            logger.info(f"🔍 Überprüfe Cache-URL: {url}")
            headers = get_default_headers()
            
            # Verwende den verbesserten Request-Handler für robuste HTTP-Anfragen 
            success, soup, status_code, error = get_page_content(
                url,
                headers=headers,
                verify_ssl=True,
                timeout=15
            )
            
            if not success:
                if status_code == 404:
                    # URL existiert nicht mehr, aus Cache entfernen
                    del cache_data["products"][product_id]
                    logger.warning(f"⚠️ Produkt nicht mehr verfügbar (404): {title}")
                    continue
                else:
                    logger.warning(f"⚠️ Fehler beim Abrufen von {url}: {error}")
                    # Aktualisiere Zeitstempel, um nicht zu oft erfolglos zu versuchen
                    product_info["last_checked"] = current_time
                    continue
            
            # Verwende das Availability-Modul für Verfügbarkeitsprüfung
            is_available, price, status_text = detect_availability(soup, url)
            
            # Aktualisiere Produkt-Status und Zeitstempel im Cache
            product_info["is_available"] = is_available
            product_info["price"] = price
            product_info["last_checked"] = current_time
            
            # Aktualisiere Produkt-Status und prüfe, ob Benachrichtigung gesendet werden soll
            should_notify, is_back_in_stock = update_product_status(
                product_id, is_available, seen, out_of_stock
            )
            
            if should_notify and (not only_available or is_available):
                # Status-Text aktualisieren, wenn Produkt wieder verfügbar ist
                if is_back_in_stock:
                    status_text = "🎉 Wieder verfügbar!"
                
                # Produkt-Informationen für Batch-Benachrichtigung
                product_type = extract_product_type_from_text(title)
                
                product_data = {
                    "title": title,
                    "url": url,
                    "price": price,
                    "status_text": status_text,
                    "is_available": is_available,
                    "matched_term": search_term,
                    "product_type": product_type,
                    "shop": "tcgviert.com"
                }
                
                # Deduplizierung innerhalb eines Durchlaufs
                if product_id not in found_product_ids:
                    all_products.append(product_data)
                    new_matches.append(product_id)
                    found_product_ids.add(product_id)
                    logger.info(f"✅ Status-Update für gecachtes Produkt: {title} - {status_text}")
            
        except Exception as e:
            logger.error(f"❌ Fehler beim Überprüfen von {url}: {e}")
            # Aktualisiere den Zeitstempel trotzdem, um endlose Wiederholungen zu vermeiden
            product_info["last_checked"] = current_time
    
    # Speichere den aktualisierten Cache
    save_product_cache(cache_data)
    
    return new_matches, all_products

def discover_collection_urls():
    """
    Entdeckt aktuelle Collection-URLs durch Scraping der Hauptseite
    """
    logger.info("🔍 Suche nach Collection-URLs auf der Hauptseite")
    valid_urls = []
    
    try:
        # Start mit wichtigsten URLs
        priority_urls = [
            "https://tcgviert.com/collections/vorbestellungen",
            "https://tcgviert.com/collections/pokemon",
            "https://tcgviert.com/collections/all",
        ]
        
        headers = get_default_headers()
        
        # Hauptseite abrufen
        main_url = "https://tcgviert.com"
        
        response = requests.get(main_url, headers=headers, timeout=10)
        if response.status_code != 200:
            logger.warning(f"⚠️ Fehler beim Abrufen der Hauptseite: Status {response.status_code}")
            return priority_urls
                
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Finde alle Links
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if "/collections/" in href and "product" not in href:
                # Vollständige URL erstellen
                full_url = f"{main_url}{href}" if href.startswith("/") else href
                
                # Priorisiere relevante URLs
                if any(term in href.lower() for term in ["pokemon", "vorbestell"]):
                    if full_url not in valid_urls:
                        valid_urls.append(full_url)
        
        # Füge Haupt-Collection-URL immer hinzu (alle Produkte)
        all_products_url = f"{main_url}/collections/all"
        if all_products_url not in valid_urls:
            valid_urls.append(all_products_url)
            
        # Wenn keine gültigen URLs gefunden wurden, verwende Priority-URLs
        if not valid_urls:
            return priority_urls
            
        return valid_urls
        
    except Exception as e:
        logger.error(f"❌ Fehler bei der Collection-URL-Entdeckung: {e}")
        return priority_urls

def scrape_tcgviert_json(keywords_map, seen, out_of_stock, only_available=False):
    """
    JSON-Scraper für tcgviert.com mit verbesserter Produkttyp-Filterung
    
    :return: Tuple (new_matches, all_products)
    """
    new_matches = []
    all_products = []
    
    # Extrahiere den Produkttyp aus dem ersten Suchbegriff
    search_product_type = None
    if keywords_map:
        sample_search_term = list(keywords_map.keys())[0]
        search_product_type = extract_product_type_from_text(sample_search_term)
    
    try:
        # Versuche den JSON-Endpunkt
        response = requests.get("https://tcgviert.com/products.json", timeout=10)
        if response.status_code != 200:
            logger.warning("⚠️ API antwortet nicht mit Status 200")
            return [], []
        
        data = response.json()
        if "products" not in data or not data["products"]:
            logger.warning("⚠️ Keine Produkte im JSON gefunden")
            return [], []
        
        products = data["products"]
        logger.info(f"🔍 {len(products)} Produkte zum Prüfen gefunden (JSON)")
        
        # Relevante Produkte filtern
        relevant_products = []
        for product in products:
            title = product["title"]
            # Produkttyp aus dem Titel extrahieren
            product_type = extract_product_type_from_text(title)
            
            # Nur Produkte, die in der Suche sind und vom richtigen Typ
            is_relevant = False
            for search_term, tokens in keywords_map.items():
                search_term_type = extract_product_type_from_text(search_term)
                
                # Wenn wir nach Display suchen, nur Displays berücksichtigen
                if search_term_type == "display" and product_type != "display":
                    continue
                
                # Prüfe auf Ausschlusslisten
                exclusion_sets = load_exclusion_sets()
                
                # Wenn wir nach einem bestimmten Suchbegriff und Typ suchen, prüfe Relevanz
                if is_keyword_in_text(tokens, title, log_level='None'):
                    # Wenn relevant, prüfe auf Ausschlusslisten
                    should_exclude = False
                    
                    for exclusion in exclusion_sets:
                        if exclusion in title.lower():
                            should_exclude = True
                            break
                    
                    if not should_exclude:
                        is_relevant = True
                        break
            
            if is_relevant:
                relevant_products.append(product)
        
        logger.info(f"🔍 {len(relevant_products)} relevante Produkte gefunden")
        
        # Falls keine relevanten Produkte direkt gefunden wurden
        if not relevant_products and search_product_type == "display":
            # Suche nach Display-Produkten in allen Produkten
            for product in products:
                title = product["title"]
                product_type = extract_product_type_from_text(title)
                
                # Nur Displays hinzufügen
                if product_type == "display":
                    for search_term, tokens in keywords_map.items():
                        if is_keyword_in_text(tokens, title, log_level='None'):
                            relevant_products.append(product)
                            break
        
        # Set für Deduplizierung
        found_product_ids = set()
                
        for product in relevant_products:
            title = product["title"]
            handle = product["handle"]
            
            # Erstelle eine eindeutige ID
            product_id = create_product_id(title)
            
            # Deduplizierung
            if product_id in found_product_ids:
                continue
            
            # Prüfe jeden Suchbegriff gegen den Produkttitel
            matched_term = None
            for search_term, tokens in keywords_map.items():
                # Extrahiere Produkttyp aus Suchbegriff und Titel
                search_term_type = extract_product_type_from_text(search_term)
                title_product_type = extract_product_type_from_text(title)
                
                # Wenn nach einem Display gesucht wird, aber der Titel keins ist, überspringen
                if search_term_type == "display" and title_product_type != "display":
                    continue
                
                # Strikte Keyword-Prüfung
                if is_keyword_in_text(tokens, title, log_level='None'):
                    matched_term = search_term
                    break
            
            if matched_term:
                # Preis aus der ersten Variante extrahieren
                price = "Preis unbekannt"
                if product.get("variants") and len(product["variants"]) > 0:
                    price = f"{product['variants'][0].get('price', 'N/A')}€"
                
                # Status prüfen (verfügbar/ausverkauft)
                available = False
                for variant in product.get("variants", []):
                    if variant.get("available", False):
                        available = True
                        break
                
                # URL erstellen
                url = f"https://tcgviert.com/products/{handle}"
                
                # Füge URL zum permanenten Cache hinzu
                add_url_to_cache(url, title, matched_term, available, price)
                
                # Aktualisiere Produkt-Status und prüfe, ob Benachrichtigung gesendet werden soll
                should_notify, is_back_in_stock = update_product_status(
                    product_id, available, seen, out_of_stock
                )
                
                if should_notify and (not only_available or available):
                    # Status-Text erstellen
                    status_text = get_status_text(available, is_back_in_stock)
                    
                    # Produkt-Informationen für Batch-Benachrichtigung
                    product_type = extract_product_type_from_text(title)
                    
                    product_data = {
                        "title": title,
                        "url": url,
                        "price": price,
                        "status_text": status_text,
                        "is_available": available,
                        "matched_term": matched_term,
                        "product_type": product_type,
                        "shop": "tcgviert.com"
                    }
                    
                    all_products.append(product_data)
                    new_matches.append(product_id)
                    found_product_ids.add(product_id)
                    logger.info(f"✅ Neuer Treffer gefunden (JSON): {title} - {status_text}")
        
    except Exception as e:
        logger.error(f"❌ Fehler beim TCGViert JSON-Scraping: {e}", exc_info=True)
    
    return new_matches, all_products

def scrape_tcgviert_html(urls, keywords_map, seen, out_of_stock, only_available=False):
    """
    HTML-Scraper für tcgviert.com mit verbesserter Produkttyp-Prüfung
    
    :return: Tuple (new_matches, all_products)
    """
    logger.info("🔄 Starte HTML-Scraping für tcgviert.com")
    new_matches = []
    all_products = []
    
    # Cache für bereits verarbeitete Links
    processed_links = set()
    
    # Set für Deduplizierung
    found_product_ids = set()
    
    for url in urls:
        try:
            logger.info(f"🔍 Durchsuche {url}")
            headers = get_default_headers()
            
            # Verwende den verbesserten Request-Handler
            success, soup, status_code, error = get_page_content(
                url,
                headers=headers,
                verify_ssl=True,
                timeout=15
            )
            
            if not success:
                logger.warning(f"⚠️ Fehler beim Abrufen von {url}: {error}")
                continue
            
            # Versuche verschiedene CSS-Selektoren für Produktkarten
            product_selectors = [
                ".product-card", 
                ".grid__item", 
                ".grid-product",
                "[data-product-card]",
                ".product-item",
                ".card", 
                ".product",
                "[data-product-id]"
            ]
            
            products = []
            for selector in product_selectors:
                products = soup.select(selector)
                if products:
                    logger.debug(f"🔍 {len(products)} Produkte mit Selektor '{selector}' gefunden")
                    break
            
            # Wenn keine Produkte gefunden wurden, versuche Link-basiertes Scraping
            if not products:
                logger.warning(f"⚠️ Keine Produktkarten auf {url} gefunden. Versuche alle Links...")
                
                all_links = soup.find_all("a", href=True)
                relevant_links = []
                
                for link in all_links:
                    href = link.get("href", "")
                    text = link.get_text().strip()
                    
                    if not text or not href:
                        continue
                    
                    # Prüfe ob es sich um Produktlinks handelt
                    is_product_link = "/products/" in href
                    
                    # Prüfe ob der Link zu Pokémon-Produkten führt
                    is_pokemon_link = "pokemon" in href.lower() or "pokemon" in text.lower()
                    
                    # Vollständige URL erstellen
                    if not href.startswith('http'):
                        product_url = urljoin("https://tcgviert.com", href)
                    else:
                        product_url = href
                    
                    # Duplikate vermeiden
                    if product_url in processed_links:
                        continue
                    
                    # Links mit Produktinformationen bevorzugen
                    if (is_product_link and is_pokemon_link):
                        relevant_links.append((product_url, text))
                        processed_links.add(product_url)
                
                # Verarbeite relevante Links
                for product_url, text in relevant_links:
                    # Produktdetailseite abrufen
                    success, detail_soup, status_code, error = get_page_content(
                        product_url,
                        headers=headers,
                        verify_ssl=True,
                        timeout=15
                    )
                    
                    if not success:
                        continue
                    
                    # Titel aus der Detailseite extrahieren
                    title_elem = detail_soup.find('h1', {'class': 'product-single__title'}) or detail_soup.find('h1')
                    if not title_elem:
                        continue
                    
                    title = title_elem.text.strip()
                    
                    # Erstelle eine eindeutige ID
                    product_id = create_product_id(title)
                    
                    # Deduplizierung
                    if product_id in found_product_ids:
                        continue
                    
                    # Prüfe jeden Suchbegriff gegen den Titel
                    matched_term = None
                    for search_term, tokens in keywords_map.items():
                        # Extrahiere Produkttyp aus Suchbegriff und Titel
                        search_term_type = extract_product_type_from_text(search_term)
                        title_product_type = extract_product_type_from_text(title)
                        
                        # Wenn nach einem Display gesucht wird, aber der Titel keins ist, überspringen
                        if search_term_type == "display" and title_product_type != "display":
                            continue
                        
                        # Strikte Keyword-Prüfung
                        if is_keyword_in_text(tokens, title, log_level='None'):
                            matched_term = search_term
                            break
                    
                    if matched_term:
                        # Verfügbarkeit prüfen
                        is_available, price, status_text = detect_availability(detail_soup, product_url)
                        
                        # Füge URL zum permanenten Cache hinzu
                        add_url_to_cache(product_url, title, matched_term, is_available, price)
                            
                        # Aktualisiere Produkt-Status
                        should_notify, is_back_in_stock = update_product_status(
                            product_id, is_available, seen, out_of_stock
                        )
                        
                        if should_notify and (not only_available or is_available):
                            # Status anpassen wenn wieder verfügbar
                            if is_back_in_stock:
                                status_text = "🎉 Wieder verfügbar!"
                            
                            # Produkt-Informationen für Batch-Benachrichtigung
                            product_type = extract_product_type_from_text(title)
                            
                            product_data = {
                                "title": title,
                                "url": product_url,
                                "price": price,
                                "status_text": status_text,
                                "is_available": is_available,
                                "matched_term": matched_term,
                                "product_type": product_type,
                                "shop": "tcgviert.com"
                            }
                            
                            all_products.append(product_data)
                            new_matches.append(product_id)
                            found_product_ids.add(product_id)
                            logger.info(f"✅ Neuer Treffer gefunden (HTML-Link): {title} - {status_text}")
                
                continue
            
            # Verarbeite die gefundenen Produktkarten
            for product in products:
                # Extrahiere Titel mit verschiedenen Selektoren
                title_selectors = [
                    ".product-card__title", 
                    ".grid-product__title", 
                    ".product-title", 
                    ".product-item__title", 
                    "h3", "h2", ".title", ".card-title"
                ]
                
                title_elem = None
                for selector in title_selectors:
                    title_elem = product.select_one(selector)
                    if title_elem:
                        break
                
                if not title_elem:
                    continue
                
                title = title_elem.text.strip()
                
                # Link extrahieren
                link_elem = product.find("a", href=True)
                if not link_elem:
                    continue
                
                relative_url = link_elem.get("href", "")
                product_url = urljoin("https://tcgviert.com", relative_url)
                
                # Duplikate vermeiden
                if product_url in processed_links:
                    continue
                    
                processed_links.add(product_url)
                
                # Erstelle eine eindeutige ID
                product_id = create_product_id(title)
                
                # Deduplizierung
                if product_id in found_product_ids:
                    continue
                
                # Prüfe jeden Suchbegriff gegen den Titel
                matched_term = None
                for search_term, tokens in keywords_map.items():
                    # Extrahiere Produkttyp aus Suchbegriff und Titel
                    search_term_type = extract_product_type_from_text(search_term)
                    title_product_type = extract_product_type_from_text(title)
                    
                    # Wenn nach einem Display gesucht wird, aber der Titel keins ist, überspringen
                    if search_term_type == "display" and title_product_type != "display":
                        continue
                    
                    # Strikte Keyword-Prüfung
                    if is_keyword_in_text(tokens, title, log_level='None'):
                        matched_term = search_term
                        break
                
                if matched_term:
                    try:
                        # Besuche Produktdetailseite für genaue Verfügbarkeitsprüfung
                        success, detail_soup, status_code, error = get_page_content(
                            product_url,
                            headers=headers,
                            verify_ssl=True,
                            timeout=15
                        )
                        
                        if not success:
                            continue
                        
                        # Nochmal den Titel aus der Detailseite extrahieren (ist oft genauer)
                        detail_title = detail_soup.find('h1', {'class': 'product-single__title'}) or detail_soup.find('h1')
                        if detail_title:
                            title = detail_title.text.strip()
                        
                        # Verwende das Availability-Modul zur Verfügbarkeitsprüfung
                        is_available, price, status_text = detect_availability(detail_soup, product_url)
                        
                        # Füge URL zum permanenten Cache hinzu
                        add_url_to_cache(product_url, title, matched_term, is_available, price)
                            
                        # Aktualisiere Produkt-Status und prüfe, ob Benachrichtigung gesendet werden soll
                        should_notify, is_back_in_stock = update_product_status(
                            product_id, is_available, seen, out_of_stock
                        )
                        
                        if should_notify and (not only_available or is_available):
                            # Status-Text aktualisieren, wenn Produkt wieder verfügbar ist
                            if is_back_in_stock:
                                status_text = "🎉 Wieder verfügbar!"
                            
                            # Produkt-Informationen für Batch-Benachrichtigung
                            product_type = extract_product_type_from_text(title)
                            
                            product_data = {
                                "title": title,
                                "url": product_url,
                                "price": price,
                                "status_text": status_text,
                                "is_available": is_available,
                                "matched_term": matched_term,
                                "product_type": product_type,
                                "shop": "tcgviert.com"
                            }
                            
                            all_products.append(product_data)
                            new_matches.append(product_id)
                            found_product_ids.add(product_id)
                            logger.info(f"✅ Neuer Treffer gefunden (HTML): {title} - {status_text}")
                    except Exception as e:
                        logger.warning(f"Fehler beim Prüfen der Verfügbarkeit: {e}")
        
        except Exception as e:
            logger.error(f"❌ Fehler beim Scrapen von {url}: {e}", exc_info=True)
    
    return new_matches, all_products

def scrape_tcgviert(keywords_map, seen, out_of_stock, only_available=False):
    """
    Hauptfunktion, die den Scraping-Prozess für tcgviert.com koordiniert.
    Kombiniert JSON-API und HTML-Scraping Methoden und implementiert
    ein robustes Cache-System, das gefundene Produkt-URLs dauerhaft speichert.
    
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param seen: Set mit bereits gesehenen Produkttiteln
    :param out_of_stock: Set mit ausverkauften Produkten
    :param only_available: Ob nur verfügbare Produkte gemeldet werden sollen
    :return: Liste der neuen Treffer
    """
    logger.info("🌐 Starte Scraper für tcgviert.com")
    
    json_matches = []
    html_matches = []
    cache_matches = []
    all_products = []  # Liste für alle gefundenen Produkte
    
    # SCHRITT 1: Zuerst den Cache überprüfen - schnellster Weg
    try:
        cache_matches, cache_products = check_cached_products(keywords_map, seen, out_of_stock, only_available)
        
        # Deduplizierung für die gefundenen Produkte
        found_product_ids = set()
        for product in cache_products:
            product_id = create_product_id(product["title"])
            if product_id not in found_product_ids:
                all_products.append(product)
                found_product_ids.add(product_id)
                
        if cache_matches:
            logger.info(f"✅ {len(cache_matches)} Produkte im Cache aktualisiert")
    except Exception as e:
        logger.error(f"❌ Fehler beim Cache-Überprüfen: {e}", exc_info=True)
    
    # SCHRITT 2: JSON-API Scraping versuchen - schneller als HTML-Parsing
    try:
        json_matches, json_products = scrape_tcgviert_json(keywords_map, seen, out_of_stock, only_available)
        
        # Deduplizierung für die gefundenen Produkte
        found_product_ids = set()
        for product in json_products:
            product_id = create_product_id(product["title"])
            if product_id not in found_product_ids:
                all_products.append(product)
                found_product_ids.add(product_id)
    except Exception as e:
        logger.error(f"❌ Fehler beim JSON-Scraping: {e}", exc_info=True)
    
    # SCHRITT 3: HTML-Scraping nur durchführen, wenn JSON weniger als 3 Ergebnisse liefert
    if len(json_matches) < 3:
        try:
            # Hauptseite scrapen, um die richtigen Collection-URLs zu finden
            main_page_urls = discover_collection_urls()
            if main_page_urls:
                html_matches, html_products = scrape_tcgviert_html(main_page_urls, keywords_map, seen, out_of_stock, only_available)
                
                # Deduplizierung für die gefundenen Produkte
                found_product_ids = set()
                for product in html_products:
                    product_id = create_product_id(product["title"])
                    if product_id not in found_product_ids:
                        all_products.append(product)
                        found_product_ids.add(product_id)
        except Exception as e:
            logger.error(f"❌ Fehler beim HTML-Scraping: {e}", exc_info=True)
    else:
        logger.info(f"🔍 JSON-Scraping lieferte bereits {len(json_matches)} Treffer - HTML-Scraping übersprungen")
    
    # Kombiniere eindeutige Ergebnisse
    all_matches = list(set(json_matches + html_matches + cache_matches))
    logger.info(f"✅ Insgesamt {len(all_matches)} einzigartige Treffer gefunden")
    
    # Sende Benachrichtigungen sortiert nach Verfügbarkeit
    if all_products:
        send_batch_notification(all_products)
    
    return all_matches