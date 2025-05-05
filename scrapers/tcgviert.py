import requests
import re
import logging
import time
import random
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from utils.telegram import send_telegram_message, escape_markdown, send_batch_notification
from utils.matcher import is_keyword_in_text, extract_product_type_from_text, load_exclusion_sets
from utils.stock import get_status_text, update_product_status
from utils.availability import detect_availability

# Logger konfigurieren
logger = logging.getLogger(__name__)

# Cache für 404-Produkt-URLs und deren letzte Überprüfung
_product_404_cache = {}

def scrape_tcgviert(keywords_map, seen, out_of_stock, only_available=False):
    """
    Scraper für tcgviert.com mit verbesserter Produkttyp-Prüfung
    
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param seen: Set mit bereits gesehenen Produkttiteln
    :param out_of_stock: Set mit ausverkauften Produkten
    :param only_available: Ob nur verfügbare Produkte gemeldet werden sollen
    :return: Liste der neuen Treffer
    """
    logger.info("🌐 Starte Scraper für tcgviert.com")
    
    json_matches = []
    html_matches = []
    all_products = []  # Liste für alle gefundenen Produkte (für sortierte Benachrichtigung)
    
    # Extrahiere den Produkttyp aus dem ersten Suchbegriff (meistens "display")
    search_product_type = None
    if keywords_map:
        sample_search_term = list(keywords_map.keys())[0]
        search_product_type = extract_product_type_from_text(sample_search_term)
        logger.debug(f"🔍 Suche nach Produkttyp: '{search_product_type}'")
    
    # Set für Deduplizierung von gefundenen Produkten innerhalb eines Durchlaufs
    found_product_ids = set()
    
    # Versuche beide Methoden und kombiniere die Ergebnisse
    try:
        json_matches, json_products = scrape_tcgviert_json(keywords_map, seen, out_of_stock, only_available)
        
        # Deduplizierung für die gefundenen Produkte
        for product in json_products:
            product_id = create_product_id(product["title"])
            if product_id not in found_product_ids:
                all_products.append(product)
                found_product_ids.add(product_id)
    except Exception as e:
        logger.error(f"❌ Fehler beim JSON-Scraping: {e}", exc_info=True)
    
    # HTML-Scraping immer durchführen, auch wenn JSON-Scraping Treffer liefert
    try:
        # Hauptseite scrapen, um die richtigen Collection-URLs zu finden
        main_page_urls = discover_collection_urls()
        if main_page_urls:
            html_matches, html_products = scrape_tcgviert_html(main_page_urls, keywords_map, seen, out_of_stock, only_available)
            
            # Deduplizierung für die gefundenen Produkte
            for product in html_products:
                product_id = create_product_id(product["title"])
                if product_id not in found_product_ids:
                    all_products.append(product)
                    found_product_ids.add(product_id)
    except Exception as e:
        logger.error(f"❌ Fehler beim HTML-Scraping: {e}", exc_info=True)
    
    # Kombiniere eindeutige Ergebnisse
    all_matches = list(set(json_matches + html_matches))
    logger.info(f"✅ Insgesamt {len(all_matches)} einzigartige Treffer gefunden")
    
    # Sende Benachrichtigungen sortiert nach Verfügbarkeit
    if all_products:
        send_batch_notification(all_products)
    
    return all_matches

def extract_product_info(title):
    """
    Extrahiert wichtige Produktinformationen aus dem Titel für eine präzise ID-Erstellung
    
    :param title: Produkttitel
    :return: Tupel mit (series_code, product_type, language)
    """
    # Extrahiere Sprache (DE/EN/JP)
    if "(DE)" in title or "pro Person" in title:
        language = "DE"
    elif "(EN)" in title or "per person" in title:
        language = "EN"
    elif "(JP)" in title or "japan" in title.lower():
        language = "JP"
    else:
        language = "UNK"
    
    # Extrahiere Produkttyp mit der verbesserten Funktion
    product_type = extract_product_type_from_text(title)
    if product_type == "unknown":
        # Fallback zur alten Methode
        if re.search(r'display|36er', title.lower()):
            product_type = "display"
        elif re.search(r'booster|pack|sleeve', title.lower()):
            product_type = "booster"
        elif re.search(r'trainer box|elite trainer|box|tin', title.lower()):
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
    # Extrahiere Serien-Code aus beliebigem Text
    else:
        # Normalisiere den Titel und entferne "display", "booster", etc.
        normalized_title = title.lower()
        normalized_title = re.sub(r'display|booster|\d+er|box|pack|tin|elite|trainer', '', normalized_title)
        normalized_title = re.sub(r'\s+', ' ', normalized_title).strip()
        
        # Verwende den Anfang des normalisierten Titels als Serien-Code
        if normalized_title:
            # Begrenze auf 1-3 Wörter für den Serien-Code
            words = normalized_title.split()
            if words:
                if len(words) > 3:
                    series_code = "-".join(words[:3])
                else:
                    series_code = "-".join(words)
    
    return (series_code, product_type, language)

def create_product_id(title, base_id="tcgviert"):
    """
    Erstellt eine eindeutige Produkt-ID basierend auf Titel und Produktinformationen
    
    :param title: Produkttitel
    :param base_id: Basis-ID (z.B. Website-Name)
    :return: Eindeutige Produkt-ID
    """
    # Extrahiere strukturierte Informationen
    series_code, product_type, language = extract_product_info(title)
    
    # Erstelle eine strukturierte ID
    product_id = f"{base_id}_{series_code}_{product_type}_{language}"
    
    # Füge zusätzliche Details für spezielle Produkte hinzu
    if "premium" in title.lower():
        product_id += "_premium"
    if "elite" in title.lower():
        product_id += "_elite"
    if "top" in title.lower() and "trainer" in title.lower():
        product_id += "_top"
    
    return product_id

def discover_collection_urls():
    """
    Entdeckt aktuelle Collection-URLs durch Scraping der Hauptseite,
    mit Optimierung für schnelleren Abbruch und bessere Priorisierung
    """
    logger.info("🔍 Suche nach gültigen Collection-URLs auf der Hauptseite")
    valid_urls = []
    
    try:
        # Starte mit den wichtigsten URLs (direkt)
        priority_urls = [
            "https://tcgviert.com/collections/vorbestellungen",
            "https://tcgviert.com/collections/pokemon",
            "https://tcgviert.com/collections/all",
        ]
        
        # Bei Fehlern direkt zu diesen URLs wechseln
        fallback_urls = ["https://tcgviert.com/collections/all"]
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        
        # Prüfe zuerst die Prioritäts-URLs (schneller Weg)
        for url in priority_urls:
            try:
                logger.debug(f"Teste Prioritäts-URL: {url}")
                response = requests.get(url, headers=headers, timeout=10)
                if response.status_code == 200:
                    valid_urls.append(url)
                    logger.info(f"✅ Prioritäts-URL gefunden: {url}")
            except Exception:
                logger.warning(f"Konnte nicht auf Prioritäts-URL zugreifen: {url}")
                pass
        
        # Wenn keine Prioritäts-URLs funktionieren, Fallbacks verwenden
        if not valid_urls:
            logger.warning("Keine Prioritäts-URLs funktionieren, verwende Fallbacks")
            return fallback_urls
        
        # Wenn genug Priority-URLs gefunden wurden (mindestens 3), dann reicht das
        if len(valid_urls) >= 3:
            logger.info(f"🔍 {len(valid_urls)} Prioritäts-URLs gefunden, überspringe weitere Suche")
            return valid_urls
        
        # Hauptseiten-Scan nur durchführen, wenn wir noch nicht genug URLs haben
        main_url = "https://tcgviert.com"
        
        try:
            response = requests.get(main_url, headers=headers, timeout=10)
            if response.status_code != 200:
                logger.warning(f"⚠️ Fehler beim Abrufen der Hauptseite: Status {response.status_code}")
                if valid_urls:
                    return valid_urls
                return fallback_urls
                
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Finde alle Links
            collection_urls = []
            for link in soup.find_all("a", href=True):
                href = link["href"]
                if "/collections/" in href and "product" not in href:
                    # Vollständige URL erstellen
                    full_url = f"{main_url}{href}" if href.startswith("/") else href
                    
                    # Priorisiere relevante URLs
                    if any(term in href.lower() for term in ["pokemon", "vorbestell"]):
                        if full_url not in valid_urls:
                            valid_urls.append(full_url)
                    else:
                        collection_urls.append(full_url)
            
            # Füge Haupt-Collection-URL immer hinzu (alle Produkte)
            all_products_url = f"{main_url}/collections/all"
            if all_products_url not in valid_urls:
                valid_urls.append(all_products_url)
                
        except Exception as e:
            logger.error(f"Fehler beim Abrufen der Hauptseite: {e}")
            if valid_urls:
                return valid_urls
            return fallback_urls
        
        return valid_urls
        
    except Exception as e:
        logger.error(f"❌ Fehler bei der Collection-URL-Entdeckung: {e}", exc_info=True)
        return ["https://tcgviert.com/collections/all"]  # Fallback zur Alle-Produkte-Seite

def scrape_tcgviert_json(keywords_map, seen, out_of_stock, only_available=False):
    """
    JSON-Scraper für tcgviert.com mit verbesserter Produkttyp-Filterung und Effizienz
    """
    new_matches = []
    all_products = []  # Liste für alle gefundenen Produkte (für sortierte Benachrichtigung)
    
    # Extrahiere den Produkttyp aus dem ersten Suchbegriff (meistens "display")
    search_product_type = None
    if keywords_map:
        sample_search_term = list(keywords_map.keys())[0]
        search_product_type = extract_product_type_from_text(sample_search_term)
        logger.debug(f"🔍 Suche nach Produkttyp mittels JSON-API: '{search_product_type}'")
    
    try:
        # Versuche zuerst den JSON-Endpunkt mit kürzerem Timeout
        response = requests.get("https://tcgviert.com/products.json", timeout=8)
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
        # Optimiert: Nur filtern, nicht alles ausgeben
        relevant_products = []
        for product in products:
            title = product["title"]
            # Produkttyp aus dem Titel extrahieren
            product_type = extract_product_type_from_text(title)
            
            # Nur Produkte, die in der Suche sind und vom richtigen Typ (nur wenn es Displays im Suchbegriff gibt)
            is_relevant = False
            for search_term in keywords_map.keys():
                search_term_type = extract_product_type_from_text(search_term)
                
                # Wenn wir nach Display suchen, nur Displays berücksichtigen
                if search_term_type == "display" and product_type != "display":
                    continue
                
                # Erweitern: Generalisierte Relevanzprüfung
                # Präpare Ausschlusslisten für die Serienprüfung
                exclusion_sets = load_exclusion_sets()
                
                # Wenn wir nach einem bestimmten Suchbegriff und Typ suchen, prüfe Relevanz
                tokens = keywords_map.get(search_term, [])
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
        
        # Falls keine relevanten Produkte direkt gefunden wurden, prüfe alle
        if not relevant_products:
            # Suche nach Display-Produkten in allen Produkten, wenn nach Display gesucht wird
            if search_product_type == "display":
                for product in products:
                    title = product["title"]
                    product_type = extract_product_type_from_text(title)
                    
                    # Nur Displays hinzufügen
                    if product_type == "display":
                        for search_term, tokens in keywords_map.items():
                            if is_keyword_in_text(tokens, title, log_level='None'):
                                relevant_products.append(product)
                                break
            
            # Wenn immer noch nichts gefunden, verwende alle Produkte
            if not relevant_products:
                relevant_products = products
        
        # Set für Deduplizierung von gefundenen Produkten innerhalb eines Durchlaufs
        found_product_ids = set()
                
        for product in relevant_products:
            title = product["title"]
            handle = product["handle"]
            
            # Erstelle eine eindeutige ID basierend auf den Produktinformationen
            product_id = create_product_id(title)
            
            # Deduplizierung innerhalb eines Durchlaufs
            if product_id in found_product_ids:
                continue
            
            # Prüfe jeden Suchbegriff gegen den Produkttitel mit reduziertem Logging
            matched_term = None
            for search_term, tokens in keywords_map.items():
                # Extrahiere Produkttyp aus Suchbegriff und Titel
                search_term_type = extract_product_type_from_text(search_term)
                title_product_type = extract_product_type_from_text(title)
                
                # Wenn nach einem Display gesucht wird, aber der Titel keins ist, überspringen
                if search_term_type == "display" and title_product_type != "display":
                    continue
                
                # Strikte Keyword-Prüfung ohne übermäßiges Logging
                if is_keyword_in_text(tokens, title, log_level='None'):
                    matched_term = search_term
                    break
            
            if matched_term:
                # Preis aus der ersten Variante extrahieren, falls vorhanden
                price = "Preis unbekannt"
                if product.get("variants") and len(product["variants"]) > 0:
                    price = f"{product['variants'][0].get('price', 'N/A')}€"
                
                # Status prüfen (verfügbar/ausverkauft)
                available = False
                for variant in product.get("variants", []):
                    if variant.get("available", False):
                        available = True
                        break
                
                # Aktualisiere Produkt-Status und prüfe, ob Benachrichtigung gesendet werden soll
                should_notify, is_back_in_stock = update_product_status(
                    product_id, available, seen, out_of_stock
                )
                
                if should_notify and (not only_available or available):
                    # Status-Text erstellen
                    status_text = get_status_text(available, is_back_in_stock)
                    
                    # URL erstellen
                    url = f"https://tcgviert.com/products/{handle}"
                                        
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
    HTML-Scraper für tcgviert.com mit verbesserter Produkttyp-Prüfung und Effizienz
    """
    logger.info("🔄 Starte HTML-Scraping für tcgviert.com")
    new_matches = []
    all_products = []  # Liste für alle gefundenen Produkte (für sortierte Benachrichtigung)
    
    # Extrahiere den Produkttyp aus dem ersten Suchbegriff (meistens "display")
    search_product_type = None
    if keywords_map:
        sample_search_term = list(keywords_map.keys())[0]
        search_product_type = extract_product_type_from_text(sample_search_term)
        logger.debug(f"🔍 Suche nach Produkttyp mittels HTML: '{search_product_type}'")
    
    # Cache für bereits verarbeitete Links
    processed_links = set()
    
    # Set für Deduplizierung von gefundenen Produkten innerhalb eines Durchlaufs
    found_product_ids = set()
    
    for url in urls:
        # Überprüfe, ob es sich um eine direkte Produkt-URL handelt
        is_product_url = '/products/' in url
        
        try:
            logger.info(f"🔍 Durchsuche {url}")
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            
            try:
                response = requests.get(url, headers=headers, timeout=10)
                if response.status_code != 200:
                    logger.warning(f"⚠️ Fehler beim Abrufen von {url}: Status {response.status_code}")
                    continue
            except requests.exceptions.RequestException as e:
                logger.warning(f"⚠️ Fehler beim Abrufen von {url}: {e}")
                continue
            
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Wenn es sich um eine direkte Produkt-URL handelt, diese direkt verarbeiten
            if is_product_url:
                # Extrahiere Titel
                title_elem = soup.find('h1', {'class': 'product-single__title'}) or soup.find('h1')
                if not title_elem:
                    continue
                
                title = title_elem.text.strip()
                product_url = url
                
                # Erstelle eine eindeutige ID
                product_id = create_product_id(title)
                
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
                
                if matched_term and product_id not in found_product_ids:
                    # Verwende das neue Modul zur Verfügbarkeitsprüfung
                    is_available, price, status_text = detect_availability(soup, product_url)
                    
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
                        logger.info(f"✅ Neuer Treffer gefunden (direkte Produkt-URL): {title} - {status_text}")
                
                # Bei direkter Produkt-URL keine weitere Verarbeitung nötig
                continue
            
            # Verbesserte Produktkarten-Erkennung für Shopify-Layout
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
                    is_product_link = ("/products/" in href or 
                                      "/product/" in href or 
                                      "detail" in href)
                    
                    # Prüfe ob der Link zu Pokémon-Produkten führt
                    is_pokemon_link = ("pokemon" in href.lower() or 
                                      "pokemon" in text.lower())
                    
                    # Generische Relevanzprüfung für beliebige Produkte
                    is_relevant = False
                    for search_term, tokens in keywords_map.items():
                        if is_keyword_in_text(tokens, text, log_level='None') or is_keyword_in_text(tokens, href, log_level='None'):
                            is_relevant = True
                            break
                    
                    # Vollständige URL erstellen
                    if not href.startswith('http'):
                        product_url = urljoin("https://tcgviert.com", href)
                    else:
                        product_url = href
                    
                    # Duplikate vermeiden
                    if product_url in processed_links:
                        continue
                    
                    # Links mit Produktinformationen bevorzugen
                    if (is_product_link and is_pokemon_link) or is_relevant:
                        relevant_links.append((product_url, text))
                        processed_links.add(product_url)
                
                # Verarbeite relevante Links
                for product_url, text in relevant_links:
                    # Erstelle eine eindeutige ID
                    product_id = create_product_id(text)
                    
                    # Deduplizierung innerhalb eines Durchlaufs
                    if product_id in found_product_ids:
                        continue
                    
                    # Prüfe jeden Suchbegriff gegen den Linktext
                    matched_term = None
                    for search_term, tokens in keywords_map.items():
                        # Extrahiere Produkttyp aus Suchbegriff und Linktext
                        search_term_type = extract_product_type_from_text(search_term)
                        link_product_type = extract_product_type_from_text(text)
                        
                        # Wenn nach einem Display gesucht wird, aber der Link keins ist, überspringen
                        if search_term_type == "display" and link_product_type != "display":
                            continue
                        
                        # Strikte Keyword-Prüfung
                        if is_keyword_in_text(tokens, text, log_level='None'):
                            matched_term = search_term
                            break
                    
                    if matched_term:
                        try:
                            # Verfügbarkeit prüfen
                            try:
                                detail_response = requests.get(product_url, headers=headers, timeout=8)
                                if detail_response.status_code != 200:
                                    continue
                                detail_soup = BeautifulSoup(detail_response.text, "html.parser")
                            except requests.exceptions.RequestException:
                                continue
                            
                            # Nochmal den Titel aus der Detailseite extrahieren (ist oft genauer)
                            detail_title = detail_soup.find("title")
                            if detail_title:
                                detail_title_text = detail_title.text.strip()
                                # Erneute Prüfung auf korrekte Produkttypübereinstimmung
                                detail_product_type = extract_product_type_from_text(detail_title_text)
                                if search_term_type == "display" and detail_product_type != "display":
                                    continue
                                
                                # Wenn Titel verfügbar ist, verwende diesen für die Nachricht
                                text = detail_title_text
                            
                            # Verwende das neue Modul zur Verfügbarkeitsprüfung
is_available, price, status_text = detect_availability(detail_soup, product_url)
                            
# Aktualisiere Produkt-Status und prüfe, ob Benachrichtigung gesendet werden soll
should_notify, is_back_in_stock = update_product_status(
    product_id, is_available, seen, out_of_stock
)
                            
if should_notify and (not only_available or is_available):
    # Status anpassen wenn wieder verfügbar
    if is_back_in_stock:
        status_text = "🎉 Wieder verfügbar!"
    
    # Produkt-Informationen für Batch-Benachrichtigung
    product_type = extract_product_type_from_text(text)
    
    product_data = {
        "title": text,
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
    logger.info(f"✅ Neuer Treffer gefunden (HTML-Link): {text} - {status_text}")
                        except Exception as e:
                            logger.warning(f"Fehler beim Prüfen der Produktdetails: {e}")
                
                # Nächste URL
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
                
                # Frühe Prüfung auf relevante Produkte - Filter nach Produktart
                title_product_type = extract_product_type_from_text(title)
                
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
                
                # Erstelle eine eindeutige ID basierend auf den Produktinformationen
                product_id = create_product_id(title)
                
                # Deduplizierung innerhalb eines Durchlaufs
                if product_id in found_product_ids:
                    continue
                
                # Prüfe jeden Suchbegriff gegen den Produkttitel
                matched_term = None
                for search_term, tokens in keywords_map.items():
                    # Extrahiere Produkttyp aus Suchbegriff und Titel
                    search_term_type = extract_product_type_from_text(search_term)
                    
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
                        try:
                            detail_response = requests.get(product_url, headers=headers, timeout=8)
                            if detail_response.status_code != 200:
                                continue
                            detail_soup = BeautifulSoup(detail_response.text, "html.parser")
                        except requests.exceptions.RequestException:
                            continue
                        
                        # Nochmal den Titel aus der Detailseite extrahieren (ist oft genauer)
                        detail_title = detail_soup.find("title")
                        if detail_title:
                            detail_title_text = detail_title.text.strip()
                            # Erneute Prüfung auf korrekte Produkttypübereinstimmung
                            detail_product_type = extract_product_type_from_text(detail_title_text)
                            if search_term_type == "display" and detail_product_type != "display":
                                continue
                            
                            # Wenn Titel verfügbar ist, verwende diesen für die Nachricht
                            title = detail_title_text
                        
                        # Verwende das neue Modul zur Verfügbarkeitsprüfung
                        is_available, price, status_text = detect_availability(detail_soup, product_url)
                            
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

# Generische Version für Anpassung an andere Webseiten
def generic_scrape_product(url, product_title, product_url, price, status, matched_term, seen, out_of_stock, new_matches, all_products, site_id="generic", is_available=True):
    """
    Generische Funktion zur Verarbeitung gefundener Produkte für beliebige Websites
    
    :param url: URL der aktuellen Seite
    :param product_title: Produkttitel
    :param product_url: Produkt-URL 
    :param price: Produktpreis
    :param status: Status-Text für die Nachricht
    :param matched_term: Übereinstimmender Suchbegriff
    :param seen: Set mit bereits gemeldeten Produkten
    :param out_of_stock: Set mit ausverkauften Produkten
    :param new_matches: Liste der neu gefundenen Produkt-IDs
    :param all_products: Liste für alle gefundenen Produkte (für sortierte Benachrichtigung)
    :param site_id: ID der Website (für Produkt-ID-Erstellung)
    :param is_available: Ob das Produkt verfügbar ist (True/False)
    :return: None
    """
    # Erstelle eine eindeutige ID basierend auf den Produktinformationen
    product_id = create_product_id(product_title, base_id=site_id)
    
    # Extrahiere Produkttyp aus Suchbegriff und Produkttitel
    search_term_type = extract_product_type_from_text(matched_term)
    product_type = extract_product_type_from_text(product_title)
    
    # Wenn nach einem Display gesucht wird, aber das Produkt keins ist, überspringen
    if search_term_type == "display" and product_type != "display":
        logger.debug(f"Produkttyp-Konflikt: Suche nach Display, aber Produkt ist '{product_type}': {product_title}")
        return
    
    # Aktualisiere Produkt-Status und prüfe, ob Benachrichtigung gesendet werden soll
    should_notify, is_back_in_stock = update_product_status(
        product_id, is_available, seen, out_of_stock
    )
    
    if should_notify:
        # Status-Text aktualisieren, wenn Produkt wieder verfügbar ist
        if is_back_in_stock:
            status = "🎉 Wieder verfügbar!"
        
        # Produkt-Informationen für Batch-Benachrichtigung
        product_data = {
            "title": product_title,
            "url": product_url,
            "price": price,
            "status_text": status,
            "is_available": is_available,
            "matched_term": matched_term,
            "product_type": product_type,
            "shop": site_id
        }
        
        all_products.append(product_data)
        new_matches.append(product_id)
        logger.info(f"✅ Neuer Treffer gefunden ({site_id}): {product_title} - {status}")