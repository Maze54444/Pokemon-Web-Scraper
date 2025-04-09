import requests
import re
from utils.telegram import send_telegram_message
from utils.matcher import is_keyword_in_text

def scrape_tcgviert(keywords_map, seen):
    """
    Scraper für tcgviert.com
    
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param seen: Set mit bereits gesehenen Produkttiteln
    :return: Liste der neuen Treffer
    """
    print("🌐 Starte Scraper für tcgviert.com", flush=True)
    print(f"🔍 Suche nach folgenden Begriffen: {list(keywords_map.keys())}", flush=True)
    
    json_matches = []
    html_matches = []
    
    # Versuche beide Methoden und kombiniere die Ergebnisse
    try:
        json_matches = scrape_tcgviert_json(keywords_map, seen)
    except Exception as e:
        print(f"❌ Fehler beim JSON-Scraping: {e}", flush=True)
    
    try:
        # Hauptseite scrapen, um die richtigen Collection-URLs zu finden
        main_page_urls = discover_collection_urls()
        if main_page_urls:
            html_matches = scrape_tcgviert_html(main_page_urls, keywords_map, seen)
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
    
    # Extrahiere Produkttyp
    product_type = "unknown"
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

def discover_collection_urls():
    """Entdeckt aktuelle Collection-URLs durch Scraping der Hauptseite"""
    from bs4 import BeautifulSoup
    
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

def scrape_tcgviert_json(keywords_map, seen):
    """JSON-Scraper für tcgviert.com"""
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
                match_result = is_keyword_in_text(tokens, title)
                print(f"  - Vergleiche mit '{search_term}' (Tokens: {tokens}): {match_result}", flush=True)
                
                if match_result:
                    matched_term = search_term
                    break
            
            if matched_term and product_id not in seen:
                # Produkt wurde noch nicht gemeldet
                url = f"https://tcgviert.com/products/{handle}"
                
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
                
                status = "✅ Verfügbar" if available else "❌ Ausverkauft"
                
                # Nachricht zusammenstellen
                msg = (
                    f"🎯 *{title}*\n"
                    f"💶 {price}\n"
                    f"📊 {status}\n"
                    f"🔎 Treffer für: '{matched_term}'\n"
                    f"🔗 [Zum Produkt]({url})"
                )
                
                # Telegram-Nachricht senden
                if send_telegram_message(msg):
                    seen.add(product_id)
                    new_matches.append(product_id)
                    print(f"✅ Neuer Treffer gefunden: {title}", flush=True)
        
    except Exception as e:
        print(f"❌ Fehler beim TCGViert JSON-Scraping: {e}", flush=True)
    
    return new_matches

def scrape_tcgviert_html(urls, keywords_map, seen):
    """HTML-Scraper für tcgviert.com"""
    print("🔄 Starte HTML-Scraping für tcgviert.com", flush=True)
    new_matches = []
    
    from bs4 import BeautifulSoup
    
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
                    
                    matched_term = None
                    for search_term, tokens in keywords_map.items():
                        if is_keyword_in_text(tokens, text):
                            matched_term = search_term
                            break
                    
                    if matched_term and product_id not in seen:
                        # Vollständige URL erstellen
                        product_url = f"https://tcgviert.com{href}" if href.startswith("/") else href
                        
                        msg = (
                            f"🎯 *{text}*\n"
                            f"💶 Preis nicht verfügbar\n"
                            f"📊 Status unbekannt\n"
                            f"🔎 Treffer für: '{matched_term}'\n"
                            f"🔗 [Zum Produkt]({product_url})"
                        )
                        
                        if send_telegram_message(msg):
                            seen.add(product_id)
                            new_matches.append(product_id)
                            print(f"✅ Neuer Treffer gefunden (HTML-Link): {text}", flush=True)
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
                
                # Preis extrahieren
                price_selectors = [
                    ".product-card__price", 
                    ".grid-product__price", 
                    ".product-price", 
                    ".price", 
                    "[data-price]"
                ]
                
                price_elem = None
                for selector in price_selectors:
                    price_elem = product.select_one(selector)
                    if price_elem:
                        break
                
                price = price_elem.text.strip() if price_elem else "Preis unbekannt"
                
                # Erstelle eine eindeutige ID basierend auf den Produktinformationen
                product_id = create_product_id(title)
                
                # Prüfe jeden Suchbegriff gegen den Produkttitel
                matched_term = None
                for search_term, tokens in keywords_map.items():
                    match_result = is_keyword_in_text(tokens, title)
                    print(f"  - Vergleiche mit '{search_term}' (Tokens: {tokens}): {match_result}", flush=True)
                    
                    if match_result:
                        matched_term = search_term
                        break
                
                if matched_term and product_id not in seen:
                    # Status bestimmen
                    status = "Unbekannt"
                    if "ausverkauft" in product.text.lower() or "sold out" in product.text.lower():
                        status = "❌ Ausverkauft"
                    elif "vorbestellung" in product.text.lower() or "pre-order" in product.text.lower():
                        status = "🔜 Vorbestellung"
                    else:
                        status = "✅ Verfügbar"
                    
                    msg = (
                        f"🎯 *{title}*\n"
                        f"💶 {price}\n"
                        f"📊 {status}\n"
                        f"🔎 Treffer für: '{matched_term}'\n"
                        f"🔗 [Zum Produkt]({product_url})"
                    )
                    
                    if send_telegram_message(msg):
                        seen.add(product_id)
                        new_matches.append(product_id)
                        print(f"✅ Neuer Treffer gefunden (HTML): {title}", flush=True)
            
        except Exception as e:
            print(f"❌ Fehler beim Scrapen von {url}: {e}", flush=True)
    
    return new_matches

# Generische Version für Anpassung an andere Webseiten
def generic_scrape_product(url, product_title, product_url, price, status, matched_term, seen, new_matches, site_id="generic"):
    """
    Generische Funktion zur Verarbeitung gefundener Produkte für beliebige Websites
    
    :param url: URL der aktuellen Seite
    :param product_title: Produkttitel
    :param product_url: Produkt-URL 
    :param price: Produktpreis
    :param status: Verfügbarkeitsstatus
    :param matched_term: Übereinstimmender Suchbegriff
    :param seen: Set mit bereits gesehenen Produkt-IDs
    :param new_matches: Liste der neu gefundenen Produkt-IDs
    :param site_id: ID der Website (für Produkt-ID-Erstellung)
    :return: None
    """
    # Erstelle eine eindeutige ID basierend auf den Produktinformationen
    product_id = create_product_id(product_title, base_id=site_id)
    
    if product_id not in seen:
        msg = (
            f"🎯 *{product_title}*\n"
            f"💶 {price}\n"
            f"📊 {status}\n"
            f"🔎 Treffer für: '{matched_term}'\n"
            f"🔗 [Zum Produkt]({product_url})"
        )
        
        if send_telegram_message(msg):
            seen.add(product_id)
            new_matches.append(product_id)
            print(f"✅ Neuer Treffer gefunden ({site_id}): {product_title}", flush=True)