import requests
import re
import json
import time
import random
from bs4 import BeautifulSoup
from utils.telegram import send_telegram_message
from utils.matcher import is_keyword_in_text, clean_text

def create_session():
    """
    Erstellt eine robuste Session mit Retry-Logik und realistischen Headers
    
    :return: Requests Session-Objekt
    """
    session = requests.Session()
    
    # Standard-Headers für alle Anfragen in dieser Session
    session.headers.update(get_random_headers())
    
    return session

def get_random_headers():
    """
    Generiert realistische Browser-Headers mit zufälligen User-Agents
    
    :return: Dictionary mit HTTP-Headers
    """
    # Liste von realistischen User-Agents
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.4 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/112.0",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36"
    ]
    
    # Realistischer Header
    headers = {
        "User-Agent": random.choice(user_agents),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "de,en-US;q=0.7,en;q=0.3",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.google.com/",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0"
    }
    
    return headers

def make_request(url, session=None, timeout=15, delay=True):
    """
    Führt eine HTTP-Anfrage mit verbesserter Fehlerbehandlung durch
    
    :param url: URL für die Anfrage
    :param session: Bestehende Session oder None für eine neue
    :param timeout: Timeout in Sekunden
    :param delay: Ob eine zufällige Verzögerung hinzugefügt werden soll
    :return: Response-Objekt oder None bei Fehler
    """
    # Zufällige Verzögerung, um Bot-Erkennung zu vermeiden
    if delay:
        time.sleep(random.uniform(1, 3))
    
    use_session = session if session else create_session()
    
    try:
        response = use_session.get(url, timeout=timeout)
        
        # Überprüfe auf Sperren oder Captchas
        if response.status_code == 403:
            print(f"⚠️ Zugriff verweigert (403) für URL: {url}", flush=True)
            print("⚠️ Die Website hat möglicherweise Anti-Bot-Maßnahmen implementiert.", flush=True)
        elif response.status_code == 429:
            print(f"⚠️ Rate-Limit überschritten (429) für URL: {url}", flush=True)
            # Längere Wartezeit bei Rate-Limiting
            if delay:
                time.sleep(random.uniform(10, 15))
        elif response.status_code != 200:
            print(f"⚠️ Unerwarteter Status-Code {response.status_code} für URL: {url}", flush=True)
        
        return response
    
    except requests.exceptions.Timeout:
        print(f"⚠️ Timeout bei Anfrage an {url}", flush=True)
    except requests.exceptions.ConnectionError:
        print(f"⚠️ Verbindungsfehler bei Anfrage an {url}", flush=True)
    except Exception as e:
        print(f"❌ Fehler bei Anfrage an {url}: {e}", flush=True)
    
    return None

def scrape_tcgviert(keywords_map, seen):
    """
    Scraper für tcgviert.com
    
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param seen: Set mit bereits gesehenen Produkttiteln
    :return: Liste der neuen Treffer
    """
    print("🌐 Starte Scraper für tcgviert.com", flush=True)
    print(f"🔍 Suche nach folgenden Begriffen: {list(keywords_map.keys())}", flush=True)
    
    # Eine gemeinsame Session für alle Anfragen
    session = create_session()
    
    json_matches = []
    html_matches = []
    
    # Versuche beide Methoden und kombiniere die Ergebnisse
    try:
        json_matches = scrape_tcgviert_json(keywords_map, seen, session)
    except Exception as e:
        print(f"❌ Fehler beim JSON-Scraping: {e}", flush=True)
    
    try:
        # Wenn JSON-Scraping fehlschlägt oder keine Ergebnisse liefert,
        # versuche die speziellen Produkt-URLs direkt anzusteuern
        if not json_matches:
            print("ℹ️ Versuche direkten Zugriff auf Produkt-URLs", flush=True)
            html_matches = scrape_product_urls(keywords_map, seen, session)
        else:
            # Hauptseite scrapen, um die richtigen Collection-URLs zu finden
            main_page_urls = discover_collection_urls(session)
            if main_page_urls:
                html_matches = scrape_tcgviert_html(main_page_urls, keywords_map, seen, session)
    except Exception as e:
        print(f"❌ Fehler beim HTML-Scraping: {e}", flush=True)
    
    # Kombiniere eindeutige Ergebnisse
    all_matches = list(set(json_matches + html_matches))
    print(f"✅ Insgesamt {len(all_matches)} einzigartige Treffer gefunden", flush=True)
    return all_matches

def scrape_product_urls(keywords_map, seen, session=None):
    """
    Direkte Suche nach Produkt-URLs für die gesuchten Produkte
    Mit verbesserter Fehlerbehandlung und Logging
    
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param seen: Set mit bereits gesehenen Produkttiteln
    :param session: Requests Session oder None
    :return: Liste der neuen Treffer
    """
    new_matches = []
    
    # Bekannte, funktionierende URLs direkt testen
    known_urls = [
        "https://tcgviert.com/products/pokemon-tcg-journey-together-sv09-36er-display-en-max-1-per-person",
        "https://tcgviert.com/products/pokemon-tcg-journey-together-sv09-checklane-blister-en-max-6-per-person",
        "https://tcgviert.com/products/pokemon-tcg-journey-together-sv09-premium-checklane-blister-en-max-6-per-person",
        "https://tcgviert.com/products/pokemon-tcg-journey-together-sv09-elite-trainer-box-en-max-1-per-person"
    ]
    
    # Zuerst bekannte URLs prüfen
    print(f"🔍 Teste zuerst {len(known_urls)} bekannte Produkt-URLs", flush=True)
    for url in known_urls:
        try:
            response = make_request(url, session)
            
            if not response:
                print(f"⚠️ Keine Antwort für URL: {url}", flush=True)
                continue
                
            if response.status_code != 200:
                print(f"⚠️ Status-Code {response.status_code} für URL: {url}", flush=True)
                continue
            
            # Die Seite erfolgreich geladen
            print(f"✅ Seite erfolgreich geladen: {url}", flush=True)
            
            soup = BeautifulSoup(response.text, "html.parser")
            product_title_elem = soup.select_one(".product__title h1, .product-single__title, h1.title")
            
            if not product_title_elem:
                print(f"⚠️ Kein Produkttitel gefunden auf: {url}", flush=True)
                continue
            
            product_title = product_title_elem.text.strip()
            print(f"✅ Produkt gefunden: {product_title}", flush=True)
            
            # Prüfe, ob das Produkt zu einem der Suchbegriffe passt
            matched_term = None
            for search_term, tokens in keywords_map.items():
                if is_keyword_in_text(tokens, product_title):
                    matched_term = search_term
                    break
            
            if matched_term:
                # Erstelle eine eindeutige ID basierend auf den Produktinformationen
                product_id = create_product_id(product_title)
                
                if product_id not in seen:
                    # Rufe detaillierte Produktinformationen ab
                    product_details = fetch_product_details_from_soup(soup, url)
                    
                    msg = (
                        f"🎯 *{product_title}*\n"
                        f"💶 {product_details['price']}\n"
                        f"📊 {product_details['status']}\n"
                        f"🔎 Treffer für: '{matched_term}'\n"
                        f"🔗 [Zum Produkt]({url})"
                    )
                    
                    if send_telegram_message(msg):
                        seen.add(product_id)
                        new_matches.append(product_id)
                        print(f"✅ Neuer Treffer gefunden (bekannte URL): {product_title}", flush=True)
        except Exception as e:
            print(f"❌ Fehler beim Überprüfen der bekannten URL {url}: {e}", flush=True)
    
    # Wenn wir bereits Matches gefunden haben, können wir hier aufhören
    if new_matches:
        print(f"✅ {len(new_matches)} Treffer mit bekannten URLs gefunden - keine weiteren URLs werden überprüft", flush=True)
        return new_matches
    
    # Andernfalls generiere systematisch potenzielle URLs
    
    # Generiere wahrscheinliche Produkt-URLs basierend auf Suchbegriffen
    print("🔍 Generiere systematisch potenzielle Produkt-URLs", flush=True)
    potential_urls = []
    
    # Mapping für Suchbegriffe zu möglichen URL-Slugs
    search_to_slug = {
        "journey together": ["journey-together", "pokemon-tcg-journey-together-sv09"],
        "sv09": ["journey-together", "sv09"],
        "reisegefährten": ["reisegefaehrten", "reisegefaehrten-kp09", "pokemon-tcg-reisegefaehrten-kp09"],
        "kp09": ["reisegefaehrten", "kp09"],
        "royal blood": ["royal-blood", "piece-royal-blood", "op10-royal-blood"]
    }
    
    # Produkt-Typen für die URL-Generierung
    product_types = [
        "36er-display",
        "elite-trainer-box",
        "top-trainer-box",
        "checklane-blister",
        "premium-checklane-blister",
        "sleeved-booster"
    ]
    
    # Sprachen für die URL-Generierung
    languages = ["en", "de"]  # Reduziert auf die häufigsten Sprachen
    
    # Stückzahl-Limitierungen
    limits = ["max-1-per-person", "max-6-per-person"]
    
    # Generiere URLs basierend auf Kombinationen
    base_url = "https://tcgviert.com/products/"
    
    for search_term in keywords_map:
        search_lower = search_term.lower()
        
        # Finde passende Slug-Kandidaten
        slug_candidates = []
        for key, slugs in search_to_slug.items():
            if key in search_lower:
                slug_candidates.extend(slugs)
        
        if not slug_candidates:
            # Fallback: Versuche den Suchbegriff selbst zu slugifizieren
            slug = search_lower.replace(" ", "-").replace(":", "").replace("(", "").replace(")", "")
            slug_candidates.append(slug)
        
        # Generiere mögliche URLs - jetzt mit weniger Permutationen für schnellere Ausführung
        for slug in slug_candidates:
            for lang in languages:
                for prod_type in product_types:
                    # Für die häufigsten Kombinationen
                    for limit in limits:
                        # Format: pokemon-tcg-journey-together-sv09-36er-display-en-max-1-per-person
                        url = f"{base_url}pokemon-tcg-{slug}-{prod_type}-{lang}-{limit}"
                        potential_urls.append(url)
    
    # Entferne Duplikate und begrenzen die Gesamtzahl
    potential_urls = list(set(potential_urls))
    max_urls_to_check = 30  # Reduziert auf eine vernünftigere Zahl
    potential_urls = potential_urls[:max_urls_to_check]
    
    print(f"🔍 Teste {len(potential_urls)} potenzielle Produkt-URLs", flush=True)
    
    # Überprüfe die URLs
    for url in potential_urls:
        try:
            response = make_request(url, session)
            
            if not response:
                continue
                
            if response.status_code != 200:
                # Nur noch 404-Fehler loggen wir nicht mehr, um die Logs sauberer zu halten
                if response.status_code != 404:
                    print(f"⚠️ Status-Code {response.status_code} für URL: {url}", flush=True)
                continue
            
            soup = BeautifulSoup(response.text, "html.parser")
            product_title_elem = soup.select_one(".product__title h1, .product-single__title, h1.title")
            
            if not product_title_elem:
                continue
            
            product_title = product_title_elem.text.strip()
            print(f"✅ Gültiges Produkt gefunden: {product_title} unter {url}", flush=True)
            
            # Prüfe, ob das Produkt zu einem der Suchbegriffe passt
            matched_term = None
            for search_term, tokens in keywords_map.items():
                if is_keyword_in_text(tokens, product_title):
                    matched_term = search_term
                    break
            
            if matched_term:
                # Erstelle eine eindeutige ID basierend auf den Produktinformationen
                product_id = create_product_id(product_title)
                
                if product_id not in seen:
                    # Rufe detaillierte Produktinformationen ab
                    product_details = fetch_product_details_from_soup(soup, url)
                    
                    msg = (
                        f"🎯 *{product_title}*\n"
                        f"💶 {product_details['price']}\n"
                        f"📊 {product_details['status']}\n"
                        f"🔎 Treffer für: '{matched_term}'\n"
                        f"🔗 [Zum Produkt]({url})"
                    )
                    
                    if send_telegram_message(msg):
                        seen.add(product_id)
                        new_matches.append(product_id)
                        print(f"✅ Neuer Treffer gefunden (potenzielle URL): {product_title}", flush=True)
        except Exception as e:
            print(f"❌ Fehler beim Überprüfen der URL {url}: {e}", flush=True)
    
    return new_matches

def scrape_tcgviert_json(keywords_map, seen, session=None):
    """
    JSON-Scraper für tcgviert.com mit verbesserter Fehlerbehandlung
    
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param seen: Set mit bereits gesehenen Produkttiteln
    :param session: Optional - existierende Session für die Anfrage
    :return: Liste der neuen Treffer
    """
    new_matches = []
    
    try:
        # Versuche zuerst den JSON-Endpunkt
        response = make_request("https://tcgviert.com/products.json", session)
        if not response or response.status_code != 200:
            print("⚠️ API antwortet nicht mit Status 200", flush=True)
            return []
        
        # Prüfe, ob die Antwort tatsächlich JSON ist
        content_type = response.headers.get('Content-Type', '')
        if 'application/json' not in content_type and 'text/json' not in content_type:
            print(f"⚠️ Server hat kein JSON zurückgegeben. Content-Type: {content_type}", flush=True)
            
            # Versuche, die ersten 100 Zeichen der Antwort zu loggen
            try:
                print(f"⚠️ Antwortinhalt (Auszug): {response.text[:100]}...", flush=True)
            except:
                pass
            
            return []
        
        # Debuggen der JSON-Antwort
        try:
            # Versuche, die ersten 100 Zeichen der Antwort zu loggen
            response_preview = response.text[:100].replace('\n', ' ')
            print(f"📝 JSON-Antwort (Auszug): {response_preview}...", flush=True)
            
            data = response.json()
        except json.JSONDecodeError as e:
            print(f"❌ Fehler beim Dekodieren der JSON-Antwort: {e}", flush=True)
            print(f"❌ Dies kann passieren, wenn die Website Ihren Zugriff blockiert oder ihr Format geändert hat.", flush=True)
            
            # Weitere Debug-Informationen
            try:
                print(f"❌ Fehlerposition: Zeile {e.lineno}, Spalte {e.colno}", flush=True)
                print(f"❌ Fehlerkontext: {e.doc[max(0, e.pos-20):e.pos+20]}", flush=True)
            except:
                pass
                
            return []
        
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

def fetch_product_details_from_soup(soup, url):
    """
    Extrahiert Produktdetails aus einem bereits geparsten BeautifulSoup-Objekt
    
    :param soup: BeautifulSoup-Objekt der Produktseite
    :param url: URL der Produktseite (für Debugging)
    :return: Dictionary mit Preis und Verfügbarkeitsstatus
    """
    details = {
        "price": "Preis nicht verfügbar",
        "status": "Status unbekannt"
    }
    
    try:
        # Preis extrahieren - verschiedene mögliche Selektoren
        price_selectors = [
            ".product__price", 
            ".price", 
            ".product-single__price",
            "[data-product-price]",
            ".product-price",
            ".product-single__price",
            "#product-variants"
        ]
        
        for selector in price_selectors:
            price_elem = soup.select_one(selector)
            if price_elem:
                price_text = price_elem.get_text().strip()
                # Entferne nicht-numerische Zeichen außer Punkt und Komma
                price_clean = re.sub(r'[^\d,.]', '', price_text)
                if price_clean:
                    details["price"] = price_clean + "€"
                    print(f"✅ Preis gefunden: {details['price']}", flush=True)
                    break
        
        # Verfügbarkeitsstatus extrahieren
        # Prüfe auf "Ausverkauft"-Indikatoren
        sold_out_indicators = ["ausverkauft", "sold out", "out of stock", "nicht verfügbar", "not available"]
        page_text = soup.get_text().lower()
        
        # Suche nach Verfügbarkeitsindikator im Text
        availability_selectors = [
            ".product-form__inventory", 
            ".product__availability",
            ".stock-status",
            "[data-stock-status]",
            ".inventoryMessage"
        ]
        
        availability_text = ""
        for selector in availability_selectors:
            availability_elem = soup.select_one(selector)
            if availability_elem:
                availability_text = availability_elem.get_text().lower().strip()
                break
        
        # Bestimme Status basierend auf Text
        if any(indicator in page_text for indicator in sold_out_indicators) or any(indicator in availability_text for indicator in sold_out_indicators):
            details["status"] = "❌ Ausverkauft"
        elif "vorbestellung" in page_text or "pre-order" in page_text:
            details["status"] = "🔜 Vorbestellung"
        elif "add to cart" in page_text or "in den warenkorb" in page_text:
            details["status"] = "✅ Verfügbar"
        
        # Prüfe zusätzlich auf Add-to-Cart-Button
        cart_button = soup.select_one("button[name='add'], .add-to-cart, .product-form__cart-submit")
        if cart_button and "disabled" not in cart_button.get("class", []) and "sold-out" not in cart_button.get("class", []):
            details["status"] = "✅ Verfügbar"
        
        print(f"✅ Status gefunden: {details['status']}", flush=True)
        
        # Alternativ: JSON-Daten aus der Seite extrahieren
        # Dies ist eine robustere Methode, da viele Shops Produktdaten als JSON in die Seite einbetten
        script_tags = soup.find_all("script", type="application/ld+json")
        for script in script_tags:
            try:
                json_data = json.loads(script.string)
                
                # Suche nach Produktdaten im JSON
                if isinstance(json_data, dict) and "offers" in json_data:
                    offers = json_data["offers"]
                    if isinstance(offers, dict):
                        # Preis extrahieren
                        if "price" in offers and offers["price"]:
                            details["price"] = str(offers["price"]) + "€"
                            print(f"✅ Preis aus JSON gefunden: {details['price']}", flush=True)
                        
                        # Verfügbarkeit extrahieren
                        if "availability" in offers:
                            availability = offers["availability"].lower()
                            if "outofstock" in availability:
                                details["status"] = "❌ Ausverkauft"
                            elif "preorder" in availability:
                                details["status"] = "🔜 Vorbestellung"
                            elif "instock" in availability:
                                details["status"] = "✅ Verfügbar"
                            print(f"✅ Status aus JSON gefunden: {details['status']}", flush=True)
            except Exception as e:
                print(f"⚠️ Fehler beim Parsen der JSON-Daten: {e}", flush=True)
        
    except Exception as e:
        print(f"❌ Fehler beim Extrahieren der Produktdetails: {e}", flush=True)
    
    return details

def fetch_product_details(product_url, session=None):
    """
    Ruft detaillierte Produktinformationen direkt von der Produktseite ab
    
    :param product_url: URL der Produktseite
    :param session: Optional - existierende Session für die Anfrage
    :return: Dictionary mit Preis und Verfügbarkeitsstatus
    """
    print(f"🔍 Rufe Produktdetails von {product_url} ab", flush=True)
    details = {
        "price": "Preis nicht verfügbar",
        "status": "Status unbekannt"
    }
    
    response = make_request(product_url, session)
    
    if not response or response.status_code != 200:
        return details
    
    soup = BeautifulSoup(response.text, "html.parser")
    return fetch_product_details_from_soup(soup, product_url)

def discover_collection_urls(session=None):
    """
    Entdeckt aktuelle Collection-URLs durch Scraping der Hauptseite
    
    :param session: Optional - existierende Session für die Anfrage
    :return: Liste der gefundenen Collection-URLs
    """
    print("🔍 Suche nach gültigen Collection-URLs", flush=True)
    
    # Fallback-URLs (für den Fall, dass die Hauptseite nicht gescrapt werden kann)
    fallback_urls = [
        "https://tcgviert.com/collections/all",
        "https://tcgviert.com/collections/vorbestellungen",
        "https://tcgviert.com/collections/pokemon",
        "https://tcgviert.com/collections/pokemon-tcg"
    ]
    
    # Da wir oft Probleme mit der Hauptseite haben, versuchen wir zuerst direkt die Sammlungs-URLs
    if not session:
        session = create_session()
    
    valid_urls = []
    for url in fallback_urls:
        response = make_request(url, session, delay=False)  # Keine Verzögerung, da wir nur wenige URLs testen
        if response and response.status_code == 200:
            valid_urls.append(url)
            print(f"✅ Gültige Collection-URL gefunden: {url}", flush=True)
    
    if valid_urls:
        return valid_urls
    
    # Falls keine Fallback-URLs funktionieren, versuchen wir die Hauptseite
    try:
        main_url = "https://tcgviert.com"
        response = make_request(main_url, session)
        
        if not response or response.status_code != 200:
            print(f"⚠️ Fehler beim Abrufen der Hauptseite: Status {response.status_code if response else 'keine Antwort'}", flush=True)
            return fallback_urls  # Fallback zu Standard-URLs
        
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
            response = make_request(url, session, delay=False)  # Keine Verzögerung innerhalb der Schleife
            if response and response.status_code == 200:
                valid_urls.append(url)
                print(f"✅ Gültige Collection-URL gefunden: {url}", flush=True)
        
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
        for url in fallback_urls:
            if url in valid_urls and url not in priority_urls:
                priority_urls.append(url)
        
        # Wenn wir priorisierte URLs haben, verwende nur diese
        if priority_urls:
            print(f"🔍 Verwende {len(priority_urls)} priorisierte URLs: {priority_urls}", flush=True)
            return priority_urls
        
        return valid_urls
        
    except Exception as e:
        print(f"❌ Fehler bei der Collection-URL-Entdeckung: {e}", flush=True)
        return fallback_urls  # Fallback zur Alle-Produkte-Seite

def scrape_tcgviert_html(urls, keywords_map, seen, session=None):
    """HTML-Scraper für tcgviert.com"""
    print("🔄 Starte HTML-Scraping für tcgviert.com", flush=True)
    new_matches = []
    
    for url in urls:
        try:
            print(f"🔍 Durchsuche {url}", flush=True)
            
            response = make_request(url, session)
            if not response or response.status_code != 200:
                print(f"⚠️ Fehler beim Abrufen von {url}: Status {response.status_code if response else 'keine Antwort'}", flush=True)
                continue
            
            soup = BeautifulSoup(response.text, "html.parser")
            
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
                all_links = soup.find_all("a", href=True)
                for link in all_links:
                    href = link.get("href", "")
                    text = link.get_text().strip()
                    
                    if not text or "products/" not in href:
                        continue
                    
                    product_id = create_product_id(text)
                    
                    matched_term = None
                    for search_term, tokens in keywords_map.items():
                        if is_keyword_in_text(tokens, text):
                            matched_term = search_term
                            break
                    
                    if matched_term and product_id not in seen:
                        product_url = f"https://tcgviert.com{href}" if href.startswith("/") else href
                        
                        # NEU: Rufe detaillierte Produktinformationen ab
                        product_details = fetch_product_details(product_url, session)
                        
                        msg = (
                            f"🎯 *{text}*\n"
                            f"💶 {product_details['price']}\n"
                            f"📊 {product_details['status']}\n"
                            f"🔎 Treffer für: '{matched_term}'\n"
                            f"🔗 [Zum Produkt]({product_url})"
                        )
                        
                        if send_telegram_message(msg):
                            seen.add(product_id)
                            new_matches.append(product_id)
                            print(f"✅ Neuer Treffer gefunden (HTML-Link): {text}", flush=True)
                continue
            
            journey_products = []
            for product in products:
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
                    journey_products.append(title)
            
            print(f"🔍 {len(journey_products)} HTML-Produkte mit gesuchten Keywords gefunden", flush=True)
            
            for product in products:
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
                
                link_elem = product.find("a", href=True)
                if not link_elem:
                    continue
                
                relative_url = link_elem.get("href", "")
                product_url = f"https://tcgviert.com{relative_url}" if relative_url.startswith("/") else relative_url
                
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
                
                initial_price = price_elem.text.strip() if price_elem else "Preis nicht verfügbar"
                
                # Erstelle eine eindeutige ID basierend auf den Produktinformationen
                product_id = create_product_id(title)
                
                matched_term = None
                for search_term, tokens in keywords_map.items():
                    match_result = is_keyword_in_text(tokens, title)
                    if match_result:
                        matched_term = search_term
                        break
                
                if matched_term and product_id not in seen:
                    # Status initial bestimmen
                    initial_status = "Unbekannt"
                    if "ausverkauft" in product.text.lower() or "sold out" in product.text.lower():
                        initial_status = "❌ Ausverkauft"
                    elif "vorbestellung" in product.text.lower() or "pre-order" in product.text.lower():
                        initial_status = "🔜 Vorbestellung"
                    else:
                        initial_status = "✅ Verfügbar"
                    
                    # NEU: Wenn Preis oder Status unbekannt/nicht verfügbar sind, rufe Produktdetails ab
                    if initial_price == "Preis nicht verfügbar" or initial_status == "Unbekannt" or initial_status == "Status unbekannt":
                        print(f"🔍 Fehlende Informationen - rufe Produktseite für Details ab: {product_url}", flush=True)
                        product_details = fetch_product_details(product_url, session)
                        price = product_details["price"]
                        status = product_details["status"]
                    else:
                        price = initial_price
                        status = initial_status
                    
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
def generic_scrape_product(url, product_title, product_url, price, status, matched_term, seen, new_matches, site_id="generic", session=None):
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
    :param session: Optional - existierende Session für die Anfrage
    :return: None
    """
    product_id = create_product_id(product_title, base_id=site_id)
    
    # NEU: Wenn Preis oder Status unbekannt/nicht verfügbar sind, rufe Produktdetails ab
    if price == "Preis nicht verfügbar" or status == "Status unbekannt" or status == "Unbekannt":
        print(f"🔍 Fehlende Informationen - rufe Produktseite für Details ab: {product_url}", flush=True)
        product_details = fetch_product_details(product_url, session)
        price = product_details["price"]
        status = product_details["status"]
    
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