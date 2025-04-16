import requests
import re
import logging
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from utils.telegram import send_telegram_message, escape_markdown
from utils.matcher import is_keyword_in_text, extract_product_type_from_text
from utils.stock import get_status_text, update_product_status
from utils.availability import detect_availability

# Logger konfigurieren
logger = logging.getLogger(__name__)

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
    logger.debug(f"🔍 Suche nach folgenden Begriffen: {list(keywords_map.keys())}")
    
    json_matches = []
    html_matches = []
    
    # Versuche beide Methoden und kombiniere die Ergebnisse
    try:
        json_matches = scrape_tcgviert_json(keywords_map, seen, out_of_stock, only_available)
    except Exception as e:
        logger.error(f"❌ Fehler beim JSON-Scraping: {e}", exc_info=True)
    
    # Nur HTML-Scraping durchführen, wenn JSON-Scraping keine Treffer liefert
    if not json_matches:
        try:
            # Hauptseite scrapen, um die richtigen Collection-URLs zu finden
            main_page_urls = discover_collection_urls()
            if main_page_urls:
                html_matches = scrape_tcgviert_html(main_page_urls, keywords_map, seen, out_of_stock, only_available)
        except Exception as e:
            logger.error(f"❌ Fehler beim HTML-Scraping: {e}", exc_info=True)
    
    # Kombiniere eindeutige Ergebnisse
    all_matches = list(set(json_matches + html_matches))
    logger.info(f"✅ Insgesamt {len(all_matches)} einzigartige Treffer gefunden")
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
    product_type = extract_product_type(title)
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
    
    # Extrahiere Serien-/Set-Code
    series_code = "unknown"
    # Suche nach Standard-Codes wie SV09, KP09, etc.
    code_match = re.search(r'(?:sv|kp|op)(?:\s|-)?\d+', title.lower())
    if code_match:
        series_code = code_match.group(0).replace(" ", "").replace("-", "")
    # Spezifische Serien-Namen
    elif "journey together" in title.lower():
        series_code = "sv09"
    elif "reisegefährten" in title.lower():
        series_code = "kp09"
    elif "royal blood" in title.lower():
        series_code = "op10"
    
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

def extract_product_type(text):
    """
    Extrahiert den Produkttyp aus einem Text mit strengeren Regeln
    
    :param text: Text, aus dem der Produkttyp extrahiert werden soll
    :return: Produkttyp als String
    """
    if not text:
        return "unknown"
        
    text = text.lower()
    
    # Display erkennen - höchste Priorität und strenge Prüfung
    if re.search(r'\bdisplay\b|\b36er\b|\b36\s+booster\b|\bbooster\s+display\b', text):
        # Zusätzliche Prüfung: Wenn andere Produkttypen erwähnt werden, ist es möglicherweise kein Display
        if re.search(r'\bblister\b|\bpack\b|\bbuilder\b|\bbuild\s?[&]?\s?battle\b|\betb\b|\belite trainer box\b', text):
            # Prüfe, ob "display" tatsächlich prominenter ist als andere Erwähnungen
            display_pos = text.find('display')
            if display_pos >= 0:
                blister_pos = text.find('blister')
                pack_pos = text.find('pack')
                
                if (blister_pos < 0 or display_pos < blister_pos) and (pack_pos < 0 or display_pos < pack_pos):
                    return "display"
            
            logger.debug(f"Produkt enthält 'display', aber auch andere Produkttypen: '{text}'")
            return "mixed_or_unclear"
        return "display"
    
    # Blister erkennen - klare Abgrenzung
    elif re.search(r'\bblister\b|\b3er\s+blister\b|\b3-pack\b|\bsleeve(d)?\s+booster\b|\bcheck\s?lane\b', text):
        return "blister"
    
    # Elite Trainer Box eindeutig erkennen
    elif re.search(r'\belite trainer box\b|\betb\b|\btrainer box\b', text):
        return "etb"
    
    # Build & Battle Box eindeutig erkennen
    elif re.search(r'\bbuild\s?[&]?\s?battle\b|\bprerelease\b', text):
        return "build_battle"
    
    # Premium Collectionen oder Special Produkte
    elif re.search(r'\bpremium\b|\bcollector\b|\bcollection\b|\bspecial\b', text):
        return "premium"

    # Einzelne Booster erkennen - aber nur wenn "display" definitiv nicht erwähnt wird
    elif re.search(r'\bbooster\b|\bpack\b', text) and not re.search(r'display', text):
        return "single_booster"
    
    # Wenn nichts erkannt wurde
    return "unknown"

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
        
        # Wenn wir bereits Prioritäts-URLs haben, können wir die aufwendigere Suche überspringen
        if len(valid_urls) >= 2:
            logger.info(f"🔍 {len(valid_urls)} Prioritäts-URLs gefunden, überspringe weitere Suche")
            return valid_urls
        
        # Wenn keine Prioritäts-URLs funktionieren, Fallbacks verwenden
        if not valid_urls:
            logger.warning("Keine Prioritäts-URLs funktionieren, verwende Fallbacks")
            return fallback_urls
        
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
                    if any(term in href.lower() for term in ["journey", "together", "reise", "pokemon", "vorbestell"]):
                        if full_url not in valid_urls:
                            valid_urls.append(full_url)
                    else:
                        collection_urls.append(full_url)
            
            # Füge Haupt-Collection-URL immer hinzu (alle Produkte)
            all_products_url = f"{main_url}/collections/all"
            if all_products_url not in valid_urls:
                valid_urls.append(all_products_url)
                
            # Begrenze die Anzahl der URLs auf max. 3
            if len(valid_urls) > 3:
                logger.info(f"⚙️ Begrenze URLs auf 3 (von {len(valid_urls)})")
                valid_urls = valid_urls[:3]
                
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
    
    try:
        # Versuche zuerst den JSON-Endpunkt mit kürzerem Timeout
        response = requests.get("https://tcgviert.com/products.json", timeout=8)
        if response.status_code != 200:
            logger.warning("⚠️ API antwortet nicht mit Status 200")
            return []
        
        data = response.json()
        if "products" not in data or not data["products"]:
            logger.warning("⚠️ Keine Produkte im JSON gefunden")
            return []
        
        products = data["products"]
        logger.info(f"🔍 {len(products)} Produkte zum Prüfen gefunden (JSON)")
        
        # Relevante Produkte filtern (für Journey Together/Reisegefährten)
        # Optimiert: Nur filtern, nicht alles ausgeben
        relevant_products = []
        for product in products:
            title = product["title"]
            if ("journey together" in title.lower() or 
                "reisegefährten" in title.lower() or 
                "sv09" in title.lower() or 
                "kp09" in title.lower()):
                relevant_products.append(product)
        
        logger.info(f"🔍 {len(relevant_products)} relevante Produkte gefunden")
        
        # Falls keine relevanten Produkte direkt gefunden wurden, prüfe alle
        if not relevant_products:
            relevant_products = products
        
        for product in relevant_products:
            title = product["title"]
            handle = product["handle"]
            
            # Erstelle eine eindeutige ID basierend auf den Produktinformationen
            product_id = create_product_id(title)
            
            # Prüfe jeden Suchbegriff gegen den Produkttitel mit reduziertem Logging
            matched_term = None
            for search_term, tokens in keywords_map.items():
                # Extrahiere Produkttyp aus Suchbegriff und Titel
                search_term_type = extract_product_type_from_text(search_term)
                title_product_type = extract_product_type(title)
                
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
                
                # Bei "nur verfügbare" Option, nicht-verfügbare Produkte überspringen
                if only_available and not available:
                    continue
                    
                # Aktualisiere Produkt-Status und prüfe, ob Benachrichtigung gesendet werden soll
                should_notify, is_back_in_stock = update_product_status(
                    product_id, available, seen, out_of_stock
                )
                
                if should_notify:
                    # Status-Text erstellen
                    status_text = get_status_text(available, is_back_in_stock)
                    
                    # URL erstellen
                    url = f"https://tcgviert.com/products/{handle}"
                    
                    # Füge Produkttyp-Information hinzu
                    product_type = extract_product_type(title)
                    product_type_info = f" [{product_type.upper()}]" if product_type not in ["unknown", "mixed_or_unclear"] else ""
                    
                    # Nachricht zusammenstellen
                    msg = (
                        f"🎯 *{escape_markdown(title)}*{product_type_info}\n"
                        f"💶 {escape_markdown(price)}\n"
                        f"📊 {escape_markdown(status_text)}\n"
                        f"🔎 Treffer für: '{escape_markdown(matched_term)}'\n"
                        f"🔗 [Zum Produkt]({url})"
                    )
                    
                    # Telegram-Nachricht senden
                    if send_telegram_message(msg):
                        # Je nach Verfügbarkeit unterschiedliche IDs speichern
                        if available:
                            seen.add(f"{product_id}_status_available")
                        else:
                            seen.add(f"{product_id}_status_unavailable")
                        
                        new_matches.append(product_id)
                        logger.info(f"✅ Neuer Treffer gemeldet: {title} - {status_text}")
        
    except Exception as e:
        logger.error(f"❌ Fehler beim TCGViert JSON-Scraping: {e}", exc_info=True)
    
    return new_matches

def scrape_tcgviert_html(urls, keywords_map, seen, out_of_stock, only_available=False):
    """
    HTML-Scraper für tcgviert.com mit verbesserter Produkttyp-Prüfung und Effizienz
    """
    logger.info("🔄 Starte HTML-Scraping für tcgviert.com")
    new_matches = []
    
    # Maximale Anzahl zu prüfender URLs
    max_urls = 3
    if len(urls) > max_urls:
        logger.info(f"⚙️ Begrenze URLs auf {max_urls} (von {len(urls)})")
        urls = urls[:max_urls]
    
    # Cache für bereits verarbeitete Links
    processed_links = set()
    
    for url in urls:
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
            
            # Versuche verschiedene CSS-Selektoren für Produktkarten
            product_selectors = [
                ".product-card", 
                ".grid__item", 
                ".grid-product",
                "[data-product-card]",
                ".product-item"
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
                    
                    if not text or "products/" not in href:
                        continue
                    
                    # Vollständige URL erstellen
                    if not href.startswith('http'):
                        product_url = urljoin(url, href)
                    else:
                        product_url = href
                    
                    # Duplikate vermeiden
                    if product_url in processed_links:
                        continue
                    
                    processed_links.add(product_url)
                    
                    # Prüfe, ob der Link relevant für Suchbegriffe ist
                    link_text = text.lower()
                    if ("journey" in link_text or "reise" in link_text or 
                        "gefährten" in link_text or "sv09" in link_text or 
                        "kp09" in link_text):
                        relevant_links.append((product_url, text))
                
                # Begrenze die Anzahl der zu prüfenden Links
                max_relevant_links = 5
                if len(relevant_links) > max_relevant_links:
                    logger.info(f"⚙️ Begrenze relevante Links auf {max_relevant_links} (von {len(relevant_links)})")
                    relevant_links = relevant_links[:max_relevant_links]
                
                # Verarbeite relevante Links
                for product_url, text in relevant_links:
                    # Erstelle eine eindeutige ID
                    product_id = create_product_id(text)
                    
                    # Prüfe jeden Suchbegriff gegen den Linktext
                    matched_term = None
                    for search_term, tokens in keywords_map.items():
                        # Extrahiere Produkttyp aus Suchbegriff und Linktext
                        search_term_type = extract_product_type_from_text(search_term)
                        link_product_type = extract_product_type(text)
                        
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
                            
                            # Wenn Detailseite geladen werden konnte, Titel aus der Detailseite extrahieren
                            detail_title = detail_soup.find("title")
                            if detail_title:
                                detail_title_text = detail_title.text.strip()
                                # Erneute Prüfung auf korrekte Produkttypübereinstimmung
                                detail_product_type = extract_product_type(detail_title_text)
                                if search_term_type == "display" and detail_product_type != "display":
                                    continue
                                
                                # Wenn Titel verfügbar ist, verwende diesen für die Nachricht
                                text = detail_title_text
                            
                            # Verfügbarkeit prüfen
                            is_available, price, status_text = detect_availability(detail_soup, product_url)
                            
                            # Bei "nur verfügbare" Option, nicht-verfügbare Produkte überspringen
                            if only_available and not is_available:
                                continue
                                
                            # Aktualisiere Produkt-Status
                            should_notify, is_back_in_stock = update_product_status(
                                product_id, is_available, seen, out_of_stock
                            )
                            
                            if should_notify:
                                # Status anpassen wenn wieder verfügbar
                                if is_back_in_stock:
                                    status_text = "🎉 Wieder verfügbar!"
                                
                                # Füge Produkttyp-Information hinzu
                                product_type = extract_product_type(text)
                                product_type_info = f" [{product_type.upper()}]" if product_type not in ["unknown", "mixed_or_unclear"] else ""
                                
                                msg = (
                                    f"🎯 *{escape_markdown(text)}*{product_type_info}\n"
                                    f"💶 {escape_markdown(price)}\n"
                                    f"📊 {escape_markdown(status_text)}\n"
                                    f"🔎 Treffer für: '{escape_markdown(matched_term)}'\n"
                                    f"🔗 [Zum Produkt]({product_url})"
                                )
                                
                                if send_telegram_message(msg):
                                    # Status in ID speichern
                                    if is_available:
                                        seen.add(f"{product_id}_status_available")
                                    else:
                                        seen.add(f"{product_id}_status_unavailable")
                                    
                                    new_matches.append(product_id)
                                    logger.info(f"✅ Neuer Treffer gefunden (HTML-Link): {text} - {status_text}")
                                    
                                    # Nach erstem Treffer abbrechen
                                    if len(new_matches) >= 1:
                                        return new_matches
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
                    "h3", "h2"
                ]
                
                title_elem = None
                for selector in title_selectors:
                    title_elem = product.select_one(selector)
                    if title_elem:
                        break
                
                if not title_elem:
                    continue
                
                title = title_elem.text.strip()
                
                # Prüfe, ob das Produkt relevant ist
                title_lower = title.lower()
                if not ("journey" in title_lower or "reise" in title_lower or 
                        "gefährten" in title_lower or "sv09" in title_lower or 
                        "kp09" in title_lower):
                    continue
                
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
                
                # Prüfe jeden Suchbegriff gegen den Produkttitel
                matched_term = None
                for search_term, tokens in keywords_map.items():
                    # Extrahiere Produkttyp aus Suchbegriff und Titel
                    search_term_type = extract_product_type_from_text(search_term)
                    title_product_type = extract_product_type(title)
                    
                    # Wenn nach einem Display gesucht wird, aber der Titel keins ist, überspringen
                    if search_term_type == "display" and title_product_type != "display":
                        continue
                    
                    # Strikte Keyword-Prüfung
                    if is_keyword_in_text(tokens, title, log_level='None'):
                        matched_term = search_term
                        break
                
                if matched_term:
                    # Verwende webseitenspezifische Verfügbarkeitsprüfung für tcgviert.com
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
                            detail_product_type = extract_product_type(detail_title_text)
                            if search_term_type == "display" and detail_product_type != "display":
                                continue
                            
                            # Wenn Titel verfügbar ist, verwende diesen für die Nachricht
                            title = detail_title_text
                        
                        # Verwende das neue Modul zur Verfügbarkeitsprüfung
                        is_available, price, status_text = detect_availability(detail_soup, product_url)
                        
                        # Bei "nur verfügbare" Option, nicht-verfügbare Produkte überspringen
                        if only_available and not is_available:
                            continue
                            
                        # Aktualisiere Produkt-Status und prüfe, ob Benachrichtigung gesendet werden soll
                        should_notify, is_back_in_stock = update_product_status(
                            product_id, is_available, seen, out_of_stock
                        )
                        
                        if should_notify:
                            # Status-Text aktualisieren, wenn Produkt wieder verfügbar ist
                            if is_back_in_stock:
                                status_text = "🎉 Wieder verfügbar!"
                            
                            # Füge Produkttyp-Information hinzu
                            product_type = extract_product_type(title)
                            product_type_info = f" [{product_type.upper()}]" if product_type not in ["unknown", "mixed_or_unclear"] else ""
                            
                            msg = (
                                f"🎯 *{escape_markdown(title)}*{product_type_info}\n"
                                f"💶 {escape_markdown(price)}\n"
                                f"📊 {escape_markdown(status_text)}\n"
                                f"🔎 Treffer für: '{escape_markdown(matched_term)}'\n"
                                f"🔗 [Zum Produkt]({product_url})"
                            )
                            
                            if send_telegram_message(msg):
                                # Je nach Verfügbarkeit unterschiedliche IDs speichern
                                if is_available:
                                    seen.add(f"{product_id}_status_available")
                                else:
                                    seen.add(f"{product_id}_status_unavailable")
                                
                                new_matches.append(product_id)
                                logger.info(f"✅ Neuer Treffer gefunden (HTML): {title} - {status_text}")
                                
                                # Nach erstem Treffer abbrechen
                                if len(new_matches) >= 1:
                                    return new_matches
                    except Exception as e:
                        logger.warning(f"Fehler beim Prüfen der Verfügbarkeit: {e}")
            
        except Exception as e:
            logger.error(f"❌ Fehler beim Scrapen von {url}: {e}", exc_info=True)
    
    return new_matches

# Generische Version für Anpassung an andere Webseiten
def generic_scrape_product(url, product_title, product_url, price, status, matched_term, seen, out_of_stock, new_matches, site_id="generic", is_available=True):
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
    :param site_id: ID der Website (für Produkt-ID-Erstellung)
    :param is_available: Ob das Produkt verfügbar ist (True/False)
    :return: None
    """
    # Erstelle eine eindeutige ID basierend auf den Produktinformationen
    product_id = create_product_id(product_title, base_id=site_id)
    
    # Extrahiere Produkttyp aus Suchbegriff und Produkttitel
    search_term_type = extract_product_type_from_text(matched_term)
    product_type = extract_product_type(product_title)
    
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
        
        # Füge Produkttyp-Information hinzu
        product_type_info = f" [{product_type.upper()}]" if product_type not in ["unknown", "mixed_or_unclear"] else ""
        
        msg = (
            f"🎯 *{escape_markdown(product_title)}*{product_type_info}\n"
            f"💶 {escape_markdown(price)}\n"
            f"📊 {escape_markdown(status)}\n"
            f"🔎 Treffer für: '{escape_markdown(matched_term)}'\n"
            f"🔗 [Zum Produkt]({product_url})"
        )
        
        if send_telegram_message(msg):
            # Je nach Verfügbarkeit unterschiedliche IDs speichern
            if is_available:
                seen.add(f"{product_id}_status_available")
            else:
                seen.add(f"{product_id}_status_unavailable")
            
            new_matches.append(product_id)
            logger.info(f"✅ Neuer Treffer gefunden ({site_id}): {product_title} - {status}")