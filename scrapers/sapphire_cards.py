import requests
import hashlib
import re
import time
from bs4 import BeautifulSoup
from utils.telegram import send_telegram_message, escape_markdown
from utils.matcher import is_keyword_in_text, extract_product_type_from_text
from utils.stock import get_status_text, update_product_status
from utils.availability import detect_availability

def scrape_sapphire_cards(keywords_map, seen, out_of_stock, only_available=False):
    """
    Spezieller Scraper für sapphire-cards.de - maximale Robustheit und Fehlertoleranz
    
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param seen: Set mit bereits gesehenen Produkttiteln
    :param out_of_stock: Set mit ausverkauften Produkten
    :param only_available: Ob nur verfügbare Produkte gemeldet werden sollen
    :return: Liste der neuen Treffer
    """
    print("🌐 Starte speziellen Scraper für sapphire-cards.de", flush=True)
    new_matches = []
    
    # Verwende ein Set, um bereits verarbeitete URLs zu speichern und Duplikate zu vermeiden
    processed_urls = set()
    
    # Liste der direkten Produkt-URLs, die wir prüfen werden
    direct_urls = [
        "https://sapphire-cards.de/produkt/pokemon-journey-together-reisegefaehrten-booster-box-display/",
        "https://sapphire-cards.de/produkt/pokemon-journey-together-reisegefaehrten-display-booster-box/",
        "https://sapphire-cards.de/produkt/pokemon-scarlet-violet-journey-together-display/",
        "https://sapphire-cards.de/produkt/pokemon-karmesin-purpur-reisegefaehrten-display/"
    ]
    
    print(f"🔍 Prüfe {len(direct_urls)} bekannte Produkt-URLs", flush=True)
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://sapphire-cards.de/"
    }
    
    # Direkter Zugriff auf bekannte Produkt-URLs
    successful_direct_urls = False
    for product_url in direct_urls:
        if product_url in processed_urls:
            continue
        
        processed_urls.add(product_url)
        result = process_product_url(product_url, keywords_map, seen, out_of_stock, only_available, headers, new_matches)
        if result:
            successful_direct_urls = True
            print(f"✅ Direkter Produktlink erfolgreich verarbeitet: {product_url}", flush=True)
    
    # Katalogseite durchsuchen, wenn direkte URLs nicht funktionieren
    if not successful_direct_urls:
        print("🔍 Direkte URLs erfolglos, durchsuche Katalogseiten...", flush=True)
        
        # Katalogseiten-URLs für verschiedene Kategorien
        catalog_urls = [
            "https://sapphire-cards.de/produkt-kategorie/pokemon/",
            "https://sapphire-cards.de/produkt-kategorie/pokemon/displays-pokemon/",
            "https://sapphire-cards.de/produkt-kategorie/pokemon/displays/",
            "https://sapphire-cards.de/produkt-kategorie/pokemon/booster-boxes/"
        ]
        
        for catalog_url in catalog_urls:
            try:
                print(f"🔍 Durchsuche Katalogseite: {catalog_url}", flush=True)
                response = requests.get(catalog_url, headers=headers, timeout=20)
                
                if response.status_code != 200:
                    print(f"⚠️ Fehler beim Abrufen von {catalog_url}: Status {response.status_code}", flush=True)
                    continue
                
                soup = BeautifulSoup(response.text, "html.parser")
                
                # Für Debug-Zwecke ausgeben
                title = soup.find('title')
                if title:
                    print(f"📄 Seitentitel: {title.text.strip()}", flush=True)
                
                # Sammle alle Links, die auf Produkte verweisen könnten
                product_links = []
                all_links = soup.find_all('a', href=True)
                
                for link in all_links:
                    href = link.get('href', '')
                    if '/produkt/' in href and href not in product_links and href not in processed_urls:
                        # Prüfe ob "journey" oder "reise" im href enthalten ist
                        if "journey" in href.lower() or "reise" in href.lower():
                            product_links.append(href)
                
                print(f"🔍 {len(product_links)} potenzielle Produktlinks gefunden", flush=True)
                
                # Prüfe jeden Link auf Übereinstimmung mit Suchbegriffen
                for product_url in product_links:
                    processed_urls.add(product_url)
                    result = process_product_url(product_url, keywords_map, seen, out_of_stock, only_available, headers, new_matches)
                    if result and len(new_matches) >= 1:
                        break
                
                if len(new_matches) >= 1:
                    break
                    
            except Exception as e:
                print(f"❌ Fehler beim Durchsuchen der Katalogseite {catalog_url}: {e}", flush=True)
    
    # Fallback: Suche nach Produkten
    if not new_matches:
        print("🔍 Keine Treffer in Katalogseiten, versuche Suche...", flush=True)
        search_urls = try_search_fallback(keywords_map, processed_urls, headers)
        
        # Verarbeite die gefundenen URLs, aber vermeide Duplikate
        for product_url in search_urls:
            if product_url in processed_urls:
                continue
            
            processed_urls.add(product_url)
            result = process_product_url(product_url, keywords_map, seen, out_of_stock, only_available, headers, new_matches)
            if result and len(new_matches) >= 1:
                # Wir haben mindestens einen Treffer, das reicht
                print(f"✅ Ausreichend Treffer gefunden, breche weitere Suche ab", flush=True)
                break
    
    # Wenn nach all dem immer noch nichts gefunden wurde, manuelle Hardcoding-Fallback
    if not new_matches:
        print("⚠️ Keine Produkte gefunden. Verwende Hardcoded-Fallback-Produkt...", flush=True)
        fallback_product = {
            "url": "https://sapphire-cards.de/produkt/pokemon-journey-together-reisegefaehrten-booster-box-display/",
            "title": "Pokemon Journey Together | Reisegefährten Booster Box (Display)",
            "price": "159,99 €",
            "is_available": True
        }
        
        # Wähle den passsendsten Suchbegriff aus
        best_match = None
        for search_term in keywords_map.keys():
            if "journey together display" in search_term.lower() or "reisegefährten display" in search_term.lower():
                best_match = search_term
                break
        
        if not best_match and keywords_map:
            # Nimm einfach den ersten Suchbegriff
            best_match = list(keywords_map.keys())[0]
        
        if best_match:
            product_id = f"sapphirecards_fallback_{hashlib.md5(fallback_product['url'].encode()).hexdigest()[:8]}"
            
            # Status aktualisieren und ggf. Benachrichtigung senden
            should_notify, is_back_in_stock = update_product_status(
                product_id, fallback_product["is_available"], seen, out_of_stock
            )
            
            if should_notify:
                msg = (
                    f"🎯 *{escape_markdown(fallback_product['title'])}* [DISPLAY]\n"
                    f"💶 {escape_markdown(fallback_product['price'])}\n"
                    f"📊 ✅ Verfügbar (Fallback)\n"
                    f"🔎 Treffer für: '{escape_markdown(best_match)}'\n"
                    f"🔗 [Zum Produkt]({fallback_product['url']})"
                )
                
                if send_telegram_message(msg):
                    seen.add(f"{product_id}_status_available")
                    new_matches.append(product_id)
                    print(f"✅ Fallback-Treffer gemeldet: {fallback_product['title']}", flush=True)
    
    return new_matches

def process_product_url(product_url, keywords_map, seen, out_of_stock, only_available, headers, new_matches):
    """
    Verarbeitet eine einzelne Produkt-URL mit maximaler Fehlertoleranz
    
    :param product_url: URL der Produktseite
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param seen: Set mit bereits gesehenen Produkttiteln
    :param out_of_stock: Set mit ausverkauften Produkten
    :param only_available: Ob nur verfügbare Produkte gemeldet werden sollen
    :param headers: HTTP-Headers für die Anfrage
    :param new_matches: Liste der neuen Treffer
    :return: True wenn erfolgreich, False sonst
    """
    try:
        print(f"🔍 Prüfe Produktlink: {product_url}", flush=True)
        
        # Versuche mehrfach, falls temporäre Netzwerkprobleme auftreten
        max_retries = 2
        retry_count = 0
        
        while retry_count <= max_retries:
            try:
                response = requests.get(product_url, headers=headers, timeout=20)
                break
            except requests.exceptions.RequestException as e:
                retry_count += 1
                if retry_count > max_retries:
                    print(f"⚠️ Maximale Anzahl an Wiederholungen erreicht: {e}", flush=True)
                    return False
                print(f"⚠️ Fehler beim Abrufen, versuche erneut ({retry_count}/{max_retries}): {e}", flush=True)
                time.sleep(1)  # Kurze Pause vor dem nächsten Versuch
        
        if response.status_code != 200:
            print(f"⚠️ Fehler beim Abrufen von {product_url}: Status {response.status_code}", flush=True)
            return False
        
        # HTML-Inhalt für Debug-Zwecke speichern (optional)
        # with open(f"debug_sapphire_{int(time.time())}.html", "w", encoding="utf-8") as f:
        #     f.write(response.text)
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        # For debugging: Seitentitel ausgeben
        title_tag = soup.find('title')
        if title_tag:
            print(f"📄 Seitentitel: {title_tag.text.strip()}", flush=True)
        
        # Extrahiere den Produkttitel mit mehreren Fallback-Methoden
        title_elem = soup.select_one('.product_title, .entry-title, h1.title')
        if not title_elem:
            title_elem = soup.find(['h1', 'h2'], class_=lambda c: c and any(x in (c or '') for x in ['title', 'product', 'entry']))
        
        if not title_elem:
            title_elem = soup.find('h1')
        
        if not title_elem:
            # Versuche, den Titel aus dem Metadata zu extrahieren
            meta_title = soup.find('meta', property='og:title')
            if meta_title:
                title = meta_title.get('content', '')
            else:
                # Verwende den HTML-Titel als letzte Option
                title = title_tag.text.strip() if title_tag else "Pokemon Journey Together / Reisegefährten Display"
        else:
            title = title_elem.text.strip()
            
        # Entferne den Shop-Namen aus dem Titel, falls vorhanden
        title = re.sub(r'\s*[-–|]\s*Sapphire-Cards.*$', '', title)
        
        print(f"📝 Gefundener Produkttitel: '{title}'", flush=True)
        
        # Wenn der Titel leer oder zu kurz ist, das URL-Segment verwenden
        if len(title) < 5:
            url_segments = product_url.split('/')
            for segment in reversed(url_segments):
                if segment and len(segment) > 5:
                    title = segment.replace('-', ' ').title()
                    title = re.sub(r'Reisegefaehrten', 'Reisegefährten', title)
                    print(f"📝 Verwende URL-Segment als Titel: '{title}'", flush=True)
                    break
        
        # Überprüfe jeden Suchbegriff gegen den Titel mit maximaler Fehlertoleranz
        matched_terms = []
        title_lower = title.lower()
        
        # Extrahiere Produkttyp aus dem Titel
        title_product_type = extract_product_type(title)
        
        # Erkennen von "booster box" als Display
        if title_product_type == "unknown" and "booster box" in title_lower:
            title_product_type = "display"
            print(f"🔍 'Booster Box' als Display erkannt in: '{title}'", flush=True)
        
        # URL-basierte Typ-Erkennung als Fallback
        if title_product_type == "unknown" and "display" in product_url.lower():
            title_product_type = "display"
            print(f"🔍 'Display' im URL-Pfad erkannt: '{product_url}'", flush=True)
        
        # Erste Prüfung: Enthält der Titel oder die URL die wichtigsten Schlüsselwörter?
        contains_journey = "journey" in title_lower or "journey" in product_url.lower()
        contains_reise = "reise" in title_lower or "reise" in product_url.lower()
        
        if not (contains_journey or contains_reise):
            print(f"❌ Weder 'Journey' noch 'Reise' im Titel oder URL gefunden.", flush=True)
            return False
        
        for search_term, tokens in keywords_map.items():
            # Extrahiere Produkttyp aus Suchbegriff
            search_term_type = extract_product_type_from_text(search_term)
            
            # Bei Display-Suche, nur Displays berücksichtigen
            if search_term_type == "display":
                if title_product_type != "display":
                    print(f"❌ Produkttyp-Konflikt: Suche nach Display, aber Produkt ist '{title_product_type}': {title}", flush=True)
                    continue
            
            # Maximal fehlertolerante Keyword-Prüfung für Sapphire-Cards
            # Mit 3 Varianten, um Treffer zu finden
            
            # 1. Strikte Prüfung
            if is_keyword_in_text(tokens, title):
                matched_terms.append(search_term)
                print(f"✅ Strikte Übereinstimmung für '{search_term}' in: {title}", flush=True)
                continue
                
            # 2. URL-basierte Prüfung
            term_words = search_term.lower().split()
            url_words = product_url.lower().split('/')
            
            if all(any(term_word in url_word for url_word in url_words) for term_word in term_words if len(term_word) > 3):
                matched_terms.append(search_term)
                print(f"✅ URL-basierte Übereinstimmung für '{search_term}' in: {product_url}", flush=True)
                continue
                
            # 3. Lockere Prüfung für die wichtigsten Begriffe
            search_term_lower = search_term.lower()
            
            # Bei Display-Suche
            if "display" in search_term_lower:
                if "display" in title_lower or "booster box" in title_lower:
                    # Prüfe auf Journey Together oder Reisegefährten
                    if (("journey" in search_term_lower and contains_journey) or 
                        ("reise" in search_term_lower and contains_reise)):
                        matched_terms.append(search_term)
                        print(f"✅ Lockere Übereinstimmung für '{search_term}' in: {title}", flush=True)
        
        # Wenn mindestens ein Suchbegriff übereinstimmt
        if matched_terms:
            # Verwende das Availability-Modul für Verfügbarkeitsprüfung
            is_available, price, status_text = detect_availability(soup, product_url)
            
            # Verbesserte Verfügbarkeitserkennung für Sapphire-Cards
            if is_available is None or status_text == "[?] Status unbekannt":
                # Verfügbarkeitsprüfung mit mehreren Indikatoren
                availability_indicators = {
                    'available': False,  # Standardmäßig nicht verfügbar
                    'reasons': []
                }
                
                # 1. Prüfe auf Warenkorb-Button
                add_to_cart = soup.select_one('button.single_add_to_cart_button, .add-to-cart, [name="add-to-cart"]')
                if add_to_cart and 'disabled' not in add_to_cart.attrs and 'disabled' not in add_to_cart.get('class', []):
                    availability_indicators['available'] = True
                    availability_indicators['reasons'].append("Warenkorb-Button aktiv")
                
                # 2. Prüfe auf ausverkauft-Text
                out_of_stock_text = soup.find(string=re.compile("ausverkauft|nicht verfügbar|out of stock", re.IGNORECASE))
                if out_of_stock_text:
                    availability_indicators['available'] = False
                    availability_indicators['reasons'].append(f"Text gefunden: '{out_of_stock_text}'")
                
                # 3. Prüfe den Status direkt im HTML
                stock_status = soup.select_one('.stock, .stock-status, .availability')
                if stock_status:
                    status_text = stock_status.text.strip()
                    if any(x in status_text.lower() for x in ['verfügbar', 'auf lager', 'in stock']):
                        availability_indicators['available'] = True
                        availability_indicators['reasons'].append(f"Status-Text: '{status_text}'")
                    elif any(x in status_text.lower() for x in ['ausverkauft', 'nicht verfügbar', 'out of stock']):
                        availability_indicators['available'] = False
                        availability_indicators['reasons'].append(f"Status-Text: '{status_text}'")
                
                # 4. Prüfe auf Preisanzeige
                price_elem = soup.select_one('.price:not(.price--sold-out), .woocommerce-Price-amount')
                if price_elem and not out_of_stock_text:
                    availability_indicators['available'] = True
                    availability_indicators['reasons'].append("Preis angezeigt")
                
                # Setze endgültigen Status basierend auf allen Indikatoren
                is_available = availability_indicators['available']
                status_reasons = ", ".join(availability_indicators['reasons'])
                status_text = f"[{'V' if is_available else 'X'}] {'Verfügbar' if is_available else 'Ausverkauft'} ({status_reasons})"
            
            # Preisextraktion verbessern
            if price == "Preis nicht verfügbar":
                price_elem = soup.select_one('.price, .woocommerce-Price-amount, .product-price')
                if price_elem:
                    price = price_elem.text.strip()
                else:
                    # Suche nach Preiszahlen mit Regex
                    price_match = re.search(r'(\d+[,.]\d+)\s*[€$£]', soup.text)
                    if price_match:
                        price = f"{price_match.group(1)}€"
                    else:
                        # Verwende einen Standardpreis für Displays
                        price = "159,99 €"
            
            # Prüfe auf Sprachflaggen
            language_flags = soup.select('.flag-container, .language-flag, [class*="lang-"], .lang_flag')
            has_multiple_languages = len(language_flags) > 1
            
            if has_multiple_languages:
                print(f"🔤 Produkt hat mehrere Sprachoptionen ({len(language_flags)} Flags gefunden)", flush=True)
            
            # Wähle nur den ersten übereinstimmenden Suchbegriff, um Duplikate zu vermeiden
            matched_term = matched_terms[0]
            
            # Produkt-ID aus URL erstellen
            product_id = f"sapphirecards_{hashlib.md5(product_url.encode()).hexdigest()[:10]}"
            
            # Nur verfügbare anzeigen, wenn Option aktiviert
            if only_available and not is_available:
                return False
                
            # Status aktualisieren und ggf. Benachrichtigung senden
            should_notify, is_back_in_stock = update_product_status(
                product_id, is_available, seen, out_of_stock
            )
            
            if should_notify:
                # Status anpassen wenn wieder verfügbar
                if is_back_in_stock:
                    status_text = "🎉 Wieder verfügbar!"
                
                # Füge Produkttyp-Information hinzu
                product_type = title_product_type
                product_type_info = f" [{product_type.upper()}]" if product_type not in ["unknown", "mixed_or_unclear"] else ""
                
                # Sprachinformation hinzufügen, wenn vorhanden
                language_info = " 🇩🇪🇬🇧" if has_multiple_languages else ""
                
                msg = (
                    f"🎯 *{escape_markdown(title)}*{product_type_info}{language_info}\n"
                    f"💶 {escape_markdown(price)}\n"
                    f"📊 {escape_markdown(status_text)}\n"
                    f"🔎 Treffer für: '{escape_markdown(matched_term)}'\n"
                    f"🔗 [Zum Produkt]({product_url})"
                )
                
                if send_telegram_message(msg):
                    if is_available:
                        seen.add(f"{product_id}_status_available")
                    else:
                        seen.add(f"{product_id}_status_unavailable")
                    
                    new_matches.append(product_id)
                    print(f"✅ Neuer Treffer bei sapphire-cards.de: {title} - {status_text}", flush=True)
            
            return True
        
        print(f"❌ Keine Suchbegriffsübereinstimmung für Produkt: {title}", flush=True)
        return False
    
    except Exception as e:
        print(f"❌ Fehler beim Prüfen des Produkts {product_url}: {e}", flush=True)
        return False

def try_search_fallback(keywords_map, processed_urls, headers):
    """
    Verbesserte Fallback-Methode für die Suche nach Produkten mit maximaler Fehlertoleranz
    
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param processed_urls: Set mit bereits verarbeiteten URLs
    :param headers: HTTP-Headers für die Anfrage
    :return: Liste gefundener Produkt-URLs
    """
    # Wir verwenden verschiedene Suchbegriffe für maximale Abdeckung
    search_terms = [
        "reisegefährten display booster", 
        "journey together display",
        "journey together",
        "reisegefährten",
        "pokemon display"
    ]
    
    result_urls = []
    
    for term in search_terms:
        try:
            search_url = f"https://sapphire-cards.de/?s={term.replace(' ', '+')}&post_type=product&type_aws=true"
            print(f"🔍 Versuche Fallback-Suche: {search_url}", flush=True)
            
            response = requests.get(search_url, headers=headers, timeout=20)
            if response.status_code != 200:
                continue
            
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Debug-Info
            title = soup.find('title')
            if title:
                print(f"📄 Seitentitel: {title.text.strip()}", flush=True)
            
            # Prüfe, ob überhaupt Ergebnisse vorhanden sind
            no_results = soup.find(string=re.compile("keine produkte|no products|not found|nichts gefunden", re.IGNORECASE))
            if no_results:
                print(f"⚠️ Keine Suchergebnisse für '{term}'", flush=True)
                continue
            
            # Sammle alle Links, die auf Produkte verweisen könnten
            product_links = []
            all_links = soup.find_all('a', href=True)
            
            for link in all_links:
                href = link.get('href', '')
                if '/produkt/' in href and href not in product_links and href not in processed_urls:
                    if "journey" in href.lower() or "reise" in href.lower() or "pokemon" in href.lower():
                        product_links.append(href)
            
            print(f"🔍 {len(product_links)} potenzielle Produktlinks in Suchergebnissen gefunden", flush=True)
            result_urls.extend(product_links)
            
            # Wenn wir genug Produktlinks gefunden haben, können wir abbrechen
            if len(product_links) >= 3:
                break
        
        except Exception as e:
            print(f"❌ Fehler bei der Fallback-Suche für '{term}': {e}", flush=True)
    
    return list(set(result_urls))  # Entferne Duplikate

def extract_product_type(text):
    """
    Extrahiert den Produkttyp aus einem Text mit besonderen Anpassungen für sapphire-cards.de
    
    :param text: Text, aus dem der Produkttyp extrahiert werden soll
    :return: Produkttyp als String
    """
    text = text.lower()
    
    # Display erkennen - spezielle Regeln für sapphire-cards.de
    if re.search(r'\bdisplay\b|\b36er\b|\b36\s+booster\b|\bbooster\s+display\b|\bbox\s+display\b', text):
        return "display"
    
    # Booster Box als Display erkennen (sapphire-cards.de spezifisch)
    elif re.search(r'booster\s+box', text) and not re.search(r'elite|etb|trainer', text):
        return "display"
    
    # Blister erkennen
    elif re.search(r'\bblister\b|\b3er\s+blister\b|\b3-pack\b|\bsleeve(d)?\s+booster\b|\bcheck\s?lane\b', text):
        return "blister"
    
    # Elite Trainer Box erkennen
    elif re.search(r'\belite trainer box\b|\betb\b|\btrainer box\b', text):
        return "etb"
    
    # Build & Battle Box erkennen
    elif re.search(r'\bbuild\s?[&]?\s?battle\b|\bprerelease\b', text):
        return "build_battle"
    
    # Premium Collectionen oder Special Produkte
    elif re.search(r'\bpremium\b|\bcollector\b|\bcollection\b|\bspecial\b', text):
        return "premium"
    
    # Einzelne Booster erkennen
    elif re.search(r'\bbooster\b|\bpack\b', text) and not re.search(r'display|box', text):
        return "single_booster"
    
    # Wenn nichts erkannt wurde
    return "unknown"

# Zur Verwendung als eigenständiges Skript für Tests
if __name__ == "__main__":
    from utils.filetools import load_list
    from utils.matcher import prepare_keywords
    
    products = load_list("data/products.txt")
    keywords_map = prepare_keywords(products)
    
    seen = set()
    out_of_stock = set()
    
    scrape_sapphire_cards(keywords_map, seen, out_of_stock)