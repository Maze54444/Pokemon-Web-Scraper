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
    Spezieller Scraper für sapphire-cards.de mit verbesserter Produkttyp-Filterung
    
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param seen: Set mit bereits gesehenen Produkttiteln
    :param out_of_stock: Set mit ausverkauften Produkten
    :param only_available: Ob nur verfügbare Produkte gemeldet werden sollen
    :return: Liste der neuen Treffer
    """
    print("🌐 Starte speziellen Scraper für sapphire-cards.de", flush=True)
    new_matches = []
    
    # Für jeden Suchbegriff einen direkten Suchaufruf durchführen
    for search_term, tokens in keywords_map.items():
        # Extrahiere Produkttyp aus dem Suchbegriff
        search_term_type = extract_product_type_from_text(search_term)
        
        # URL-safe Suchbegriff erstellen
        clean_term = search_term.replace(" ", "+").lower()
        search_url = f"https://sapphire-cards.de/?s={clean_term}&post_type=product&type_aws=true"
        
        print(f"🔍 Suche nach '{search_term}' (Typ: {search_term_type}) auf sapphire-cards.de", flush=True)
        print(f"🔗 Such-URL: {search_url}", flush=True)
        
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            
            # Durchführen der Suchanfrage
            response = requests.get(search_url, headers=headers, timeout=15)
            if response.status_code != 200:
                print(f"⚠️ Fehler beim Abrufen von {search_url}: Status {response.status_code}", flush=True)
                continue
            
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Debug-Ausgabe für die Suchergebnisseite
            page_title = soup.find('title')
            if page_title:
                print(f"📄 Seitentitel: {page_title.text.strip()}", flush=True)
            
            # Nach Produkten suchen (verschiedene Selektoren probieren)
            products = []
            product_selectors = [
                '.product', 
                '.woocommerce-product', 
                '.type-product',
                'li.product', 
                'div.product', 
                'article.product',
                '.products .product',
                '.woocommerce-products-header',
                '.product-item'
            ]
            
            for selector in product_selectors:
                found_products = soup.select(selector)
                if found_products:
                    print(f"🔍 {len(found_products)} Produkte mit Selektor '{selector}' gefunden", flush=True)
                    products.extend(found_products)
            
            # Wenn immer noch keine Produkte gefunden wurden, versuche alle Links zu scannen
            if not products:
                print("🔍 Keine Produkte mit Standard-Selektoren gefunden. Versuche alle Links...", flush=True)
                all_links = soup.find_all('a', href=True)
                
                # Links filtern und nur die mit Produkt-URLs behalten
                potential_product_links = []
                for link in all_links:
                    href = link.get('href', '')
                    # Nur Links zu Produktseiten berücksichtigen
                    if '/produkt/' in href or 'product' in href:
                        potential_product_links.append(link)
                
                print(f"🔍 {len(potential_product_links)} potenzielle Produkt-Links gefunden", flush=True)
                
                # Link-Texte extrahieren und prüfen
                for link in potential_product_links:
                    href = link.get('href', '')
                    link_text = link.get_text().strip()
                    
                    # Wenn kein Text im Link ist, versuche Bildtitel oder Alt-Text
                    if not link_text:
                        img = link.find('img')
                        if img:
                            link_text = img.get('title', '') or img.get('alt', '')
                    
                    if not link_text:
                        continue
                    
                    # Extrahiere Produkttyp aus dem Link-Text
                    link_product_type = extract_product_type(link_text)
                    
                    # Bei Display-Suche, nur Links zu Displays berücksichtigen
                    if search_term_type == "display" and link_product_type != "display":
                        print(f"❌ Produkttyp-Konflikt: Suche nach Display, aber Link ist '{link_product_type}': {link_text}", flush=True)
                        continue
                    
                    # Prüfe, ob der Link-Text mit dem Suchbegriff übereinstimmt
                    if is_keyword_in_text(tokens, link_text):
                        print(f"✅ Treffer für '{search_term}' im Link: {link_text}", flush=True)
                        
                        # Prüfe Verfügbarkeit und sende Benachrichtigung
                        product_url = href
                        process_product_link(product_url, link_text, search_term, new_matches, seen, out_of_stock, only_available, headers)
                
                # Wenn keine Links verarbeitet wurden, versuche direkten Produktlink
                if len(potential_product_links) == 0:
                    direct_url = f"https://sapphire-cards.de/produkt/pokemon-journey-together-reisegefaehrten-booster-box-display/"
                    print(f"🔍 Versuche direkten Produktlink: {direct_url}", flush=True)
                    process_product_link(direct_url, "Pokemon Journey Together | Reisegefährten Booster Box (Display)", 
                                         search_term, new_matches, seen, out_of_stock, only_available, headers)
            
            # Standard-Produktliste verarbeiten
            if products:
                processed_products = set()  # Set um Duplikate zu vermeiden
                
                for product in products:
                    # Titel und Link extrahieren
                    title_elem = product.select_one('.woocommerce-loop-product__title, .product-title, h2, h3, .entry-title')
                    title = title_elem.text.strip() if title_elem else "Unbekanntes Produkt"
                    
                    # Bei unbekanntem Titel, versuche es aus Bildbeschreibungen
                    if title == "Unbekanntes Produkt":
                        img = product.find('img')
                        if img:
                            alt_title = img.get('alt', '')
                            if alt_title:
                                title = alt_title
                    
                    # Link extrahieren
                    link_elem = product.select_one('a.woocommerce-loop-product__link, a.product-link, a')
                    if not link_elem or not link_elem.get('href'):
                        continue
                    
                    product_url = link_elem['href']
                    
                    # Duplikate vermeiden
                    if product_url in processed_products:
                        continue
                    processed_products.add(product_url)
                    
                    # Extrahiere Produkttyp aus dem Titel
                    product_type = extract_product_type(title)
                    
                    # Bei Display-Suche, nur Displays berücksichtigen
                    if search_term_type == "display" and product_type != "display":
                        print(f"❌ Produkttyp-Konflikt: Suche nach Display, aber Produkt ist '{product_type}': {title}", flush=True)
                        continue
                    
                    # Prüfe, ob der Produkttitel mit dem Suchbegriff übereinstimmt
                    if is_keyword_in_text(tokens, title):
                        print(f"✅ Treffer für '{search_term}' im Produkt: {title}", flush=True)
                        
                        # Besuche Detailseite, prüfe Verfügbarkeit und sende Benachrichtigung
                        process_product_link(product_url, title, search_term, new_matches, seen, out_of_stock, only_available, headers)
        
        except Exception as e:
            print(f"❌ Fehler beim Scrapen von sapphire-cards.de für '{search_term}': {e}", flush=True)
    
    return new_matches

def extract_product_type(text):
    """
    Extrahiert den Produkttyp aus einem Text mit strengeren Regeln
    
    :param text: Text, aus dem der Produkttyp extrahiert werden soll
    :return: Produkttyp als String
    """
    text = text.lower()
    
    # Display erkennen - höchste Priorität 
    if re.search(r'\bdisplay\b|\b36er\b|\b36\s+booster\b|\bbooster\s+display\b|\bbox\s+display\b', text):
        # Zusätzliche Prüfung: Wenn andere Produkttypen erwähnt werden, ist es möglicherweise kein Display
        if re.search(r'\bblister\b|\bsleeved\b|\bbuild\s?[&]?\s?battle\b|\betb\b|\belite trainer box\b', text):
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

def process_product_link(product_url, title, search_term, new_matches, seen, out_of_stock, only_available, headers):
    """
    Besucht eine Produktseite, prüft Verfügbarkeit und sendet ggf. eine Benachrichtigung
    
    :param product_url: URL der Produktseite
    :param title: Titel des Produkts
    :param search_term: Suchbegriff, für den das Produkt gefunden wurde
    :param new_matches: Liste der neuen Treffer
    :param seen: Set mit bereits gesehenen Produkttiteln
    :param out_of_stock: Set mit ausverkauften Produkten
    :param only_available: Ob nur verfügbare Produkte gemeldet werden sollen
    :param headers: HTTP-Headers für die Anfrage
    """
    try:
        print(f"🔍 Prüfe Produktdetails für {product_url}", flush=True)
        
        detail_response = requests.get(product_url, headers=headers, timeout=15)
        if detail_response.status_code == 200:
            detail_soup = BeautifulSoup(detail_response.text, "html.parser")
            
            # Extrahiere den aktuellen Titel aus der Detailseite (kann genauer sein)
            detail_title_elem = detail_soup.find('h1', class_=lambda c: c and ('product_title' in c or 'entry-title' in c))
            if detail_title_elem:
                detail_title = detail_title_elem.text.strip()
                title = detail_title  # Verwende den genaueren Titel
            
            # Extrahiere Produkttyp aus dem Detailtitel
            product_type = extract_product_type(title)
            search_term_type = extract_product_type_from_text(search_term)
            
            # Bei Display-Suche, nur Displays berücksichtigen
            if search_term_type == "display" and product_type != "display":
                print(f"❌ Detailseite ist kein Display, obwohl nach Display gesucht wurde: {title}", flush=True)
                return
            
            # Erneute Schlüsselwortprüfung mit dem detaillierten Titel
            tokens = keywords_map.get(search_term, [])
            if not is_keyword_in_text(tokens, title):
                print(f"❌ Detailseite passt nicht zum Suchbegriff '{search_term}': {title}", flush=True)
                return
            
            # Verfügbarkeit prüfen mit dem verbesserten Modul
            is_available, price, status_text = detect_availability(detail_soup, product_url)
            
            # Prüfe, ob bei sapphire-cards.de zusätzliche Sprach-Flags verfügbar sind
            language_flags = detail_soup.select('.flag-container, .language-flag, [class*="lang-"]')
            has_multiple_languages = len(language_flags) > 1
            
            if has_multiple_languages:
                print(f"🔤 Produkt hat mehrere Sprachoptionen ({len(language_flags)} Flags gefunden)", flush=True)
            
            # Produkt-ID aus URL und Titel erstellen
            product_id = f"sapphirecards_{hashlib.md5(product_url.encode()).hexdigest()[:10]}"
            
            # Nur verfügbare anzeigen, wenn Option aktiviert
            if only_available and not is_available:
                return
                
            # Status aktualisieren und ggf. Benachrichtigung senden
            should_notify, is_back_in_stock = update_product_status(
                product_id, is_available, seen, out_of_stock
            )
            
            if should_notify:
                # Status anpassen wenn wieder verfügbar
                if is_back_in_stock:
                    status_text = "🎉 Wieder verfügbar!"
                
                # Füge Produkttyp-Information hinzu
                product_type_info = f" [{product_type.upper()}]" if product_type not in ["unknown", "mixed_or_unclear"] else ""
                
                # Sprachinformation hinzufügen, wenn vorhanden
                language_info = " 🇩🇪🇬🇧" if has_multiple_languages else ""
                
                msg = (
                    f"🎯 *{escape_markdown(title)}*{product_type_info}{language_info}\n"
                    f"💶 {escape_markdown(price)}\n"
                    f"📊 {escape_markdown(status_text)}\n"
                    f"🔎 Treffer für: '{escape_markdown(search_term)}'\n"
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

# Zur Verwendung als eigenständiges Skript für Tests
if __name__ == "__main__":
    from utils.filetools import load_list
    from utils.matcher import prepare_keywords
    
    products = load_list("data/products.txt")
    keywords_map = prepare_keywords(products)
    
    seen = set()
    out_of_stock = set()
    
    scrape_sapphire_cards(keywords_map, seen, out_of_stock)