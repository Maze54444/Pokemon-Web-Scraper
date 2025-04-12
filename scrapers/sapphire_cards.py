import requests
import hashlib
import re
from bs4 import BeautifulSoup
from utils.telegram import send_telegram_message, escape_markdown
from utils.matcher import is_keyword_in_text, extract_product_type_from_text
from utils.stock import get_status_text, update_product_status
from utils.availability import detect_availability

def scrape_sapphire_cards(keywords_map, seen, out_of_stock, only_available=False):
    """
    Spezieller Scraper für sapphire-cards.de - stark optimiert basierend auf den Logfiles
    
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param seen: Set mit bereits gesehenen Produkttiteln
    :param out_of_stock: Set mit ausverkauften Produkten
    :param only_available: Ob nur verfügbare Produkte gemeldet werden sollen
    :return: Liste der neuen Treffer
    """
    print("🌐 Starte speziellen Scraper für sapphire-cards.de", flush=True)
    new_matches = []
    
    # Liste der direkten Produkt-URLs, die wir prüfen werden
    direct_urls = [
        "https://sapphire-cards.de/produkt/pokemon-journey-together-reisegefaehrten-booster-box-display/",
        "https://sapphire-cards.de/produkt/pokemon-scarlet-violet-karmesin-purpur-display-booster-box/"
    ]
    
    print(f"🔍 Überspringe Suche und prüfe direkt {len(direct_urls)} bekannte Produkt-URLs", flush=True)
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    # Direkter Zugriff auf bekannte Produkt-URLs (viel zuverlässiger)
    for product_url in direct_urls:
        try:
            print(f"🔍 Prüfe direkten Produktlink: {product_url}", flush=True)
            
            response = requests.get(product_url, headers=headers, timeout=15)
            if response.status_code != 200:
                print(f"⚠️ Fehler beim Abrufen von {product_url}: Status {response.status_code}", flush=True)
                continue
            
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Extrahiere den Produkttitel
            title_elem = soup.select_one('.product_title, .entry-title, h1.title')
            if not title_elem:
                # Erweiterte Suche nach Titeln
                title_elem = soup.find(['h1', 'h2'], class_=lambda c: c and any(x in c for x in ['title', 'product', 'entry']))
            
            if title_elem:
                title = title_elem.text.strip()
            else:
                # Fallback: Suche nach dem ersten h1-Element
                title_elem = soup.find('h1')
                title = title_elem.text.strip() if title_elem else "Pokemon Reisegefährten / Journey Together Display"
            
            print(f"📝 Gefundener Produkttitel: '{title}'", flush=True)
            
            # Überprüfe jeden Suchbegriff gegen den Titel
            matched_terms = []
            for search_term, tokens in keywords_map.items():
                # Extrahiere Produkttyp aus Suchbegriff und Titel
                search_term_type = extract_product_type_from_text(search_term)
                title_product_type = extract_product_type(title)
                
                # Erweiterte Prüfung für sapphire-cards.de
                # Wir erkennen auch "booster box" als Display an
                if title_product_type == "unknown" and "booster box" in title.lower():
                    title_product_type = "display"
                    print(f"🔍 'Booster Box' als Display erkannt in: '{title}'", flush=True)
                
                # Der Titel muss entweder "Reisegefährten" oder "Journey Together" enthalten
                title_lower = title.lower()
                if "journey together" not in title_lower and "reisegefährten" not in title_lower:
                    # Prüfe auch auf andere Varianten
                    if "journey" not in title_lower and "reise" not in title_lower:
                        continue
                
                # Bei Display-Suche, nur Displays berücksichtigen
                display_match = False
                if search_term_type == "display":
                    if title_product_type == "display" or "display" in title_lower or "booster box" in title_lower:
                        display_match = True
                    else:
                        print(f"❌ Produkttyp-Konflikt: Suche nach Display, aber Produkt ist '{title_product_type}': {title}", flush=True)
                        continue
                
                # Weniger strikte Keyword-Prüfung speziell für sapphire-cards.de
                # Da die Seite oft eigene Produktbezeichnungen verwendet
                if display_match or is_keyword_in_text(tokens, title):
                    matched_terms.append(search_term)
                    print(f"✅ Treffer für '{search_term}' im Produkt: {title}", flush=True)
            
            # Wenn mindestens ein Suchbegriff übereinstimmt
            if matched_terms:
                # Verwende das Availability-Modul für Verfügbarkeitsprüfung
                is_available, price, status_text = detect_availability(soup, product_url)
                
                # Verbesserte Verfügbarkeitserkennung speziell für sapphire-cards.de
                if is_available is None or status_text == "[?] Status unbekannt":
                    # Zusätzliche Prüfungen für sapphire-cards.de
                    add_to_cart = soup.select_one('button.single_add_to_cart_button, .add-to-cart, [name="add-to-cart"]')
                    if add_to_cart and 'disabled' not in add_to_cart.attrs and 'disabled' not in add_to_cart.get('class', []):
                        is_available = True
                        status_text = "[V] Verfügbar (Warenkorb-Button aktiv)"
                    else:
                        out_of_stock_text = soup.find(string=re.compile("ausverkauft|nicht verfügbar|out of stock", re.IGNORECASE))
                        if out_of_stock_text:
                            is_available = False
                            status_text = "[X] Ausverkauft (Text gefunden)"
                
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
                
                # Prüfe auf Sprachflaggen
                language_flags = soup.select('.flag-container, .language-flag, [class*="lang-"], .lang_flag')
                has_multiple_languages = len(language_flags) > 1
                
                if has_multiple_languages:
                    print(f"🔤 Produkt hat mehrere Sprachoptionen ({len(language_flags)} Flags gefunden)", flush=True)
                
                # Für jeden übereinstimmenden Suchbegriff eine Benachrichtigung senden
                for matched_term in matched_terms:
                    # Produkt-ID aus URL und Term erstellen
                    product_id = f"sapphirecards_{hashlib.md5((product_url + matched_term).encode()).hexdigest()[:10]}"
                    
                    # Nur verfügbare anzeigen, wenn Option aktiviert
                    if only_available and not is_available:
                        continue
                        
                    # Status aktualisieren und ggf. Benachrichtigung senden
                    should_notify, is_back_in_stock = update_product_status(
                        product_id, is_available, seen, out_of_stock
                    )
                    
                    if should_notify:
                        # Status anpassen wenn wieder verfügbar
                        if is_back_in_stock:
                            status_text = "🎉 Wieder verfügbar!"
                        
                        # Füge Produkttyp-Information hinzu
                        product_type = extract_product_type(title)
                        if product_type == "unknown" and "booster box" in title.lower():
                            product_type = "display"
                        
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
        
        except Exception as e:
            print(f"❌ Fehler beim Prüfen des Produkts {product_url}: {e}", flush=True)
    
    # Zusätzlich versuchen wir die Suche als Fallback
    if not new_matches:
        print("🔍 Keine Treffer über direkte URLs, versuche Suche als Fallback...", flush=True)
        try_search_fallback(keywords_map, seen, out_of_stock, only_available, new_matches)
    
    return new_matches

def try_search_fallback(keywords_map, seen, out_of_stock, only_available, new_matches):
    """Fallback-Methode, die versucht über die Suchfunktion Produkte zu finden"""
    # Wir suchen nur nach einem repräsentativen Begriff
    search_terms = ["reisegefährten display booster", "journey together display"]
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    for term in search_terms:
        try:
            search_url = f"https://sapphire-cards.de/?s={term.replace(' ', '+')}&post_type=product&type_aws=true"
            print(f"🔍 Versuche Fallback-Suche: {search_url}", flush=True)
            
            response = requests.get(search_url, headers=headers, timeout=15)
            if response.status_code != 200:
                continue
            
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Sammle alle Links, die auf Produkte verweisen könnten
            product_links = []
            all_links = soup.find_all('a', href=True)
            
            for link in all_links:
                href = link.get('href', '')
                if '/produkt/' in href and href not in product_links:
                    product_links.append(href)
            
            print(f"🔍 {len(product_links)} potenzielle Produktlinks gefunden", flush=True)
            
            # Prüfe jeden Link
            for product_url in product_links:
                try:
                    detail_response = requests.get(product_url, headers=headers, timeout=15)
                    if detail_response.status_code != 200:
                        continue
                    
                    detail_soup = BeautifulSoup(detail_response.text, "html.parser")
                    
                    # Titel extrahieren
                    title_elem = detail_soup.select_one('.product_title, .entry-title, h1.title')
                    if not title_elem:
                        title_elem = detail_soup.find('h1')
                    
                    if not title_elem:
                        continue
                    
                    title = title_elem.text.strip()
                    title_lower = title.lower()
                    
                    # Prüfen, ob es sich um ein Journey Together/Reisegefährten Display handelt
                    if (("journey together" in title_lower or "reisegefährten" in title_lower) and 
                            ("display" in title_lower or "booster box" in title_lower)):
                        
                        print(f"✅ Fallback-Treffer gefunden: {title}", flush=True)
                        
                        # Hier können wir den Rest der Produktverarbeitung aus dem Hauptcode wiederverwenden
                        process_product(detail_soup, product_url, title, keywords_map, seen, out_of_stock, only_available, new_matches)
                
                except Exception as e:
                    print(f"❌ Fehler beim Prüfen des Produkts {product_url}: {e}", flush=True)
        
        except Exception as e:
            print(f"❌ Fehler bei der Fallback-Suche für '{term}': {e}", flush=True)

def process_product(soup, product_url, title, keywords_map, seen, out_of_stock, only_available, new_matches):
    """Verarbeitet ein gefundenes Produkt und sendet ggf. eine Benachrichtigung"""
    # Matched Terms finden
    matched_terms = []
    for search_term, tokens in keywords_map.items():
        # Weniger strikte Prüfung für den Fallback
        search_term_lower = search_term.lower()
        title_lower = title.lower()
        
        if ("display" in search_term_lower and "display" in title_lower) or ("display" in search_term_lower and "booster box" in title_lower):
            if ("journey" in search_term_lower and "journey" in title_lower) or ("reise" in search_term_lower and "reise" in title_lower):
                matched_terms.append(search_term)
    
    if not matched_terms:
        return
    
    # Verfügbarkeit prüfen
    is_available, price, status_text = detect_availability(soup, product_url)
    
    # Verbesserte Verfügbarkeitserkennung
    if is_available is None or status_text == "[?] Status unbekannt":
        add_to_cart = soup.select_one('button.single_add_to_cart_button, .add-to-cart, [name="add-to-cart"]')
        if add_to_cart and 'disabled' not in add_to_cart.attrs and 'disabled' not in add_to_cart.get('class', []):
            is_available = True
            status_text = "[V] Verfügbar (Warenkorb-Button aktiv)"
        else:
            out_of_stock_text = soup.find(string=re.compile("ausverkauft|nicht verfügbar|out of stock", re.IGNORECASE))
            if out_of_stock_text:
                is_available = False
                status_text = "[X] Ausverkauft (Text gefunden)"
    
    # Sprachflaggen prüfen
    language_flags = soup.select('.flag-container, .language-flag, [class*="lang-"], .lang_flag')
    has_multiple_languages = len(language_flags) > 1
    
    # Für jeden übereinstimmenden Suchbegriff
    for matched_term in matched_terms:
        # Produkt-ID erstellen
        product_id = f"sapphirecards_{hashlib.md5((product_url + matched_term).encode()).hexdigest()[:10]}"
        
        # Bei nur verfügbaren Produkten
        if only_available and not is_available:
            continue
        
        # Status aktualisieren
        should_notify, is_back_in_stock = update_product_status(
            product_id, is_available, seen, out_of_stock
        )
        
        if should_notify:
            # Status anpassen wenn wieder verfügbar
            if is_back_in_stock:
                status_text = "🎉 Wieder verfügbar!"
            
            # Produkttyp-Info
            product_type = "display" if "display" in title.lower() or "booster box" in title.lower() else "unknown"
            product_type_info = f" [{product_type.upper()}]" if product_type != "unknown" else ""
            
            # Sprachinformation
            language_info = " 🇩🇪🇬🇧" if has_multiple_languages else ""
            
            # Nachricht zusammenstellen
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