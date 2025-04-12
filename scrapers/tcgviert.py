import requests
import re
from bs4 import BeautifulSoup
from utils.telegram import send_telegram_message, escape_markdown
from utils.matcher import is_keyword_in_text, extract_product_type_from_text
from utils.stock import get_status_text, update_product_status
# Importiere das neue Modul für webseitenspezifische Verfügbarkeitsprüfung
from utils.availability import detect_availability

def scrape_tcgviert(keywords_map, seen, out_of_stock, only_available=False):
    """
    Scraper für tcgviert.com mit verbesserter Produkttyp-Prüfung
    
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param seen: Set mit bereits gesehenen Produkttiteln
    :param out_of_stock: Set mit ausverkauften Produkten
    :param only_available: Ob nur verfügbare Produkte gemeldet werden sollen
    :return: Liste der neuen Treffer
    """
    print("🌐 Starte Scraper für tcgviert.com", flush=True)
    print(f"🔍 Suche nach folgenden Begriffen: {list(keywords_map.keys())}", flush=True)
    
    json_matches = []
    html_matches = []
    
    # Versuche beide Methoden und kombiniere die Ergebnisse
    try:
        json_matches = scrape_tcgviert_json(keywords_map, seen, out_of_stock, only_available)
    except Exception as e:
        print(f"❌ Fehler beim JSON-Scraping: {e}", flush=True)
    
    try:
        # Hauptseite scrapen, um die richtigen Collection-URLs zu finden
        main_page_urls = discover_collection_urls()
        if main_page_urls:
            html_matches = scrape_tcgviert_html(main_page_urls, keywords_map, seen, out_of_stock, only_available)
    except Exception as e:
        print(f"❌ Fehler beim HTML-Scraping: {e}", flush=True)
    
    # Kombiniere eindeutige Ergebnisse
    all_matches = list(set(json_matches + html_matches))
    print(f"✅ Insgesamt {len(all_matches)} einzigartige Treffer gefunden", flush=True)
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
            
            print(f"  [DEBUG] Produkt enthält 'display', aber auch andere Produkttypen: '{text}'", flush=True)
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
    """Entdeckt aktuelle Collection-URLs durch Scraping der Hauptseite"""
    print("🔍 Suche nach gültigen Collection-URLs auf der Hauptseite", flush=True)
    valid_urls = []
    
    try:
        # Starte mit der Hauptseite
        main_url = "https://tcgviert.com"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        
        response = requests.get(main_url, headers=headers, timeout=15)
        if response.status_code != 200:
            print(f"⚠️ Fehler beim Abrufen der Hauptseite: Status {response.status_code}", flush=True)
            return []
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Finde alle Links auf der Seite
        links = soup.find_all("a", href=True)
        
        # Filtern nach Collection-Links
        collection_urls = []
        for link in links:
            href = link["href"]
            if "/collections/" in href and "tcgviert.com" not in href:
                # Vollständige URL erstellen, wenn nötig
                full_url = f"{main_url}{href}" if href.startswith("/") else href
                collection_urls.append(full_url)
        
        # Duplikate entfernen
        collection_urls = list(set(collection_urls))
        print(f"🔍 {len(collection_urls)} mögliche Collection-URLs gefunden", flush=True)
        
        # Prüfe, welche URLs tatsächlich existieren
        for url in collection_urls:
            try:
                test_response = requests.get(url, headers=headers, timeout=10)
                if test_response.status_code == 200:
                    valid_urls.append(url)
                    print(f"✅ Gültige Collection-URL gefunden: {url}", flush=True)
            except Exception:
                pass
        
        # Gib immer die URL für "alle Produkte" mit zurück
        all_products_url = f"{main_url}/collections/all"
        if all_products_url not in valid_urls:
            valid_urls.append(all_products_url)
            print(f"✅ Füge Standard-URL hinzu: {all_products_url}", flush=True)
        
        print(f"🔍 Insgesamt {len(valid_urls)} gültige Collection-URLs gefunden", flush=True)
        
        # Beschränke auf eine kleinere Anzahl relevanter URLs, um Duplikate zu vermeiden
        # Priorisiere spezifische URLs, die mit den Suchbegriffen zu tun haben
        priority_urls = []
        for url in valid_urls:
            if any(term in url.lower() for term in ["journey", "together", "sv09", "reise", "kp09", "royal", "blood", "vorbestellungen"]):
                priority_urls.append(url)
        
        # Füge die Standard-URLs hinzu
        for url in ["https://tcgviert.com/collections/all", "https://tcgviert.com/collections/vorbestellungen"]:
            if url in valid_urls and url not in priority_urls:
                priority_urls.append(url)
        
        # Wenn wir priorisierte URLs haben, verwende nur diese
        if priority_urls:
            print(f"🔍 Verwende {len(priority_urls)} priorisierte URLs: {priority_urls}", flush=True)
            return priority_urls
        
        return valid_urls
        
    except Exception as e:
        print(f"❌ Fehler bei der Collection-URL-Entdeckung: {e}", flush=True)
        return ["https://tcgviert.com/collections/all"]  # Fallback zur Alle-Produkte-Seite

def scrape_tcgviert_json(keywords_map, seen, out_of_stock, only_available=False):
    """JSON-Scraper für tcgviert.com mit verbesserter Produkttyp-Filterung"""
    new_matches = []
    
    try:
        # Versuche zuerst den JSON-Endpunkt
        response = requests.get("https://tcgviert.com/products.json", timeout=10)
        if response.status_code != 200:
            print("⚠️ API antwortet nicht mit Status 200", flush=True)
            return []
        
        data = response.json()
        if "products" not in data or not data["products"]:
            print("⚠️ Keine Produkte im JSON gefunden", flush=True)
            return []
        
        products = data["products"]
        print(f"🔍 {len(products)} Produkte zum Prüfen gefunden (JSON)", flush=True)
        
        # Debug-Ausgabe für alle Produkte mit bestimmten Keywords
        print("🔍 Alle Produkte mit Journey Together oder Reisegefährten im Titel:", flush=True)
        journey_products = []
        for product in products:
            title = product["title"]
            if "journey together" in title.lower() or "reisegefährten" in title.lower():
                print(f"  - {title}", flush=True)
                journey_products.append(product)
        
        print(f"🔍 {len(journey_products)} Produkte mit gesuchten Keywords gefunden", flush=True)
        
        for product in products:
            title = product["title"]
            handle = product["handle"]
            
            print(f"🔍 Prüfe Produkt: '{title}'", flush=True)
            
            # Erstelle eine eindeutige ID basierend auf den Produktinformationen
            product_id = create_product_id(title)
            
            # Prüfe jeden Suchbegriff gegen den Produkttitel
            matched_term = None
            for search_term, tokens in keywords_map.items():
                # Extrahiere Produkttyp aus Suchbegriff und Titel
                search_term_type = extract_product_type_from_text(search_term)
                title_product_type = extract_product_type(title)
                
                # VERBESSERT: Wenn nach einem Display gesucht wird, aber der Titel keins ist, überspringen
                if search_term_type == "display" and title_product_type != "display":
                    print(f"  ❌ Produkttyp-Konflikt: Suche nach 'display', aber Produkt ist '{title_product_type}'", flush=True)
                    continue
                
                # Strikte Keyword-Prüfung
                match_result = is_keyword_in_text(tokens, title)
                print(f"  - Vergleiche mit '{search_term}' (Tokens: {tokens}): {match_result}", flush=True)
                
                if match_result:
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
                        print(f"✅ Neuer Treffer gemeldet: {title} - {status_text}", flush=True)
        
    except Exception as e:
        print(f"❌ Fehler beim TCGViert JSON-Scraping: {e}", flush=True)
    
    return new_matches

def scrape_tcgviert_html(urls, keywords_map, seen, out_of_stock, only_available=False):
    """HTML-Scraper für tcgviert.com mit verbesserter Produkttyp-Prüfung"""
    print("🔄 Starte HTML-Scraping für tcgviert.com", flush=True)
    new_matches = []
    
    for url in urls:
        try:
            print(f"🔍 Durchsuche {url}", flush=True)
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code != 200:
                print(f"⚠️ Fehler beim Abrufen von {url}: Status {response.status_code}", flush=True)
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
                    print(f"🔍 {len(products)} Produkte mit Selektor '{selector}' gefunden", flush=True)
                    break
            
            if not products:
                print(f"⚠️ Keine Produktkarten auf {url} gefunden. Versuche alle Links...", flush=True)
                # Fallback: Suche alle Links und analysiere Text
                all_links = soup.find_all("a", href=True)
                for link in all_links:
                    href = link.get("href", "")
                    text = link.get_text().strip()
                    
                    if not text or "products/" not in href:
                        continue
                    
                    # Erstelle eine eindeutige ID basierend auf den Produktinformationen
                    product_id = create_product_id(text)
                    
                    # Prüfe jeden Suchbegriff gegen den Linktext
                    matched_term = None
                    for search_term, tokens in keywords_map.items():
                        # Extrahiere Produkttyp aus Suchbegriff und Linktext
                        search_term_type = extract_product_type_from_text(search_term)
                        link_product_type = extract_product_type(text)
                        
                        # Wenn nach einem Display gesucht wird, aber der Link keins ist, überspringen
                        if search_term_type == "display" and link_product_type != "display":
                            print(f"  ❌ Produkttyp-Konflikt: Suche nach 'display', aber Link ist '{link_product_type}'", flush=True)
                            continue
                        
                        # Strikte Keyword-Prüfung
                        if is_keyword_in_text(tokens, text):
                            matched_term = search_term
                            break
                    
                    if matched_term:
                        # Vollständige URL erstellen
                        product_url = f"https://tcgviert.com{href}" if href.startswith("/") else href
                        
                        # Produktdetailseite besuchen, um Verfügbarkeit zu prüfen
                        try:
                            detail_response = requests.get(product_url, headers=headers, timeout=10)
                            detail_soup = BeautifulSoup(detail_response.text, "html.parser")
                            
                            # Verwende das neue Modul zur Verfügbarkeitsprüfung
                            is_available, price, status_text = detect_availability(detail_soup, product_url)
                            
                            # Nochmal den Titel aus der Detailseite extrahieren (ist oft genauer)
                            detail_title = detail_soup.find("title")
                            if detail_title:
                                detail_title_text = detail_title.text.strip()
                                # Erneute Prüfung auf korrekte Produkttypübereinstimmung
                                detail_product_type = extract_product_type(detail_title_text)
                                if search_term_type == "display" and detail_product_type != "display":
                                    print(f"  ❌ Detailseite ist kein Display, obwohl nach Display gesucht wurde: {detail_title_text}", flush=True)
                                    continue
                                
                                # Wenn Titel verfügbar ist, verwende diesen für die Nachricht
                                text = detail_title_text
                            
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
                                    print(f"✅ Neuer Treffer gefunden (HTML-Link): {text} - {status_text}", flush=True)
                        except Exception as e:
                            print(f"❌ Fehler beim Prüfen der Produktdetails: {e}", flush=True)
                continue
            
            # Debug-Ausgabe für Journey Together oder Reisegefährten Produkte
            journey_products = []
            for product in products:
                # Verschiedene Selektoren für Produkttitel versuchen
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
                
                if "journey together" in title.lower() or "reisegefährten" in title.lower():
                    print(f"  - HTML-Produkt: {title}", flush=True)
                    journey_products.append(title)
            
            print(f"🔍 {len(journey_products)} HTML-Produkte mit gesuchten Keywords gefunden", flush=True)
            
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
                print(f"🔍 Prüfe HTML-Produkt: '{title}'", flush=True)
                
                # Link extrahieren
                link_elem = product.find("a", href=True)
                if not link_elem:
                    continue
                
                relative_url = link_elem.get("href", "")
                product_url = f"https://tcgviert.com{relative_url}" if relative_url.startswith("/") else relative_url
                
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
                        print(f"  ❌ Produkttyp-Konflikt: Suche nach 'display', aber Produkt ist '{title_product_type}'", flush=True)
                        continue
                    
                    # Strikte Keyword-Prüfung
                    match_result = is_keyword_in_text(tokens, title)
                    print(f"  - Vergleiche mit '{search_term}' (Tokens: {tokens}): {match_result}", flush=True)
                    
                    if match_result:
                        matched_term = search_term
                        break
                
                if matched_term:
                    # Verwende webseitenspezifische Verfügbarkeitsprüfung für tcgviert.com
                    try:
                        # Besuche Produktdetailseite für genaue Verfügbarkeitsprüfung
                        detail_response = requests.get(product_url, headers=headers, timeout=10)
                        detail_soup = BeautifulSoup(detail_response.text, "html.parser")
                        
                        # Nochmal den Titel aus der Detailseite extrahieren (ist oft genauer)
                        detail_title = detail_soup.find("title")
                        if detail_title:
                            detail_title_text = detail_title.text.strip()
                            # Erneute Prüfung auf korrekte Produkttypübereinstimmung
                            detail_product_type = extract_product_type(detail_title_text)
                            if search_term_type == "display" and detail_product_type != "display":
                                print(f"  ❌ Detailseite ist kein Display, obwohl nach Display gesucht wurde: {detail_title_text}", flush=True)
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
                                print(f"✅ Neuer Treffer gefunden (HTML): {title} - {status_text}", flush=True)
                    except Exception as e:
                        print(f"❌ Fehler beim Prüfen der Verfügbarkeit: {e}", flush=True)
            
        except Exception as e:
            print(f"❌ Fehler beim Scrapen von {url}: {e}", flush=True)
    
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
        print(f"❌ Produkttyp-Konflikt: Suche nach Display, aber Produkt ist '{product_type}': {product_title}", flush=True)
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
            print(f"✅ Neuer Treffer gefunden ({site_id}): {product_title} - {status}", flush=True)