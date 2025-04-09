import requests
import hashlib
from bs4 import BeautifulSoup
import re
from utils.matcher import clean_text, is_keyword_in_text
from utils.telegram import send_telegram_message
from utils.stock import get_status_text, update_product_status

def scrape_generic(url, keywords_map, seen, out_of_stock, check_availability=True, only_available=False):
    """
    Generischer Scraper für beliebige Websites
    
    :param url: URL der zu scrapenden Website
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param seen: Set mit bereits gesehenen Produkttiteln
    :param out_of_stock: Set mit ausverkauften Produkten
    :param check_availability: Ob Produktdetailseiten für Verfügbarkeitsprüfung besucht werden sollen
    :param only_available: Ob nur verfügbare Produkte gemeldet werden sollen
    :return: Liste der neuen Treffer
    """
    print(f"🌐 Starte generischen Scraper für {url}", flush=True)
    new_matches = []
    
    try:
        # User-Agent setzen, um Blockierung zu vermeiden
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            print(f"⚠️ Fehler beim Abrufen von {url}: Status {response.status_code}", flush=True)
            return new_matches
        
        # HTML parsen
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Titel der Seite extrahieren
        page_title = soup.title.text.strip() if soup.title else url
        
        # Alle Links auf der Seite finden
        potential_product_links = []
        for a_tag in soup.find_all('a', href=True):
            href = a_tag.get('href')
            link_text = a_tag.get_text().strip()
            
            # Prüfe ob der Link zu einem Produkt führen könnte
            if not href or href.startswith('#') or href.startswith('javascript:'):
                continue
                
            # Nur Links mit Produktnamen-ähnlichem Text oder Produkt-Pfad verfolgen
            if '/product/' in href or '/products/' in href or 'detail' in href:
                potential_product_links.append((href, link_text))
                continue
                
            # Prüfe jeden Suchbegriff gegen den Linktext
            for search_term, tokens in keywords_map.items():
                if is_keyword_in_text(tokens, link_text):
                    potential_product_links.append((href, link_text))
                    break
        
        print(f"🔍 {len(potential_product_links)} potenzielle Produktlinks gefunden auf {url}", flush=True)
        
        # Für gefundene Produktlinks prüfen
        for href, link_text in potential_product_links:
            # Vollständige URL erstellen
            if href.startswith('http'):
                product_url = href
            elif href.startswith('/'):
                base_url = '/'.join(url.split('/')[:3])  # http(s)://domain.com
                product_url = f"{base_url}{href}"
            else:
                # Relativer Pfad
                product_url = f"{url.rstrip('/')}/{href.lstrip('/')}"
            
            # Eindeutige ID für diesen Fund erstellen
            site_id = url.split('//')[1].split('/')[0].replace('www.', '')
            product_id = create_product_id(link_text, site_id=site_id)
            
            # Prüfe jeden Suchbegriff gegen den Linktext
            matched_term = None
            for search_term, tokens in keywords_map.items():
                if is_keyword_in_text(tokens, link_text):
                    matched_term = search_term
                    print(f"🔍 Treffer für '{search_term}' im Link: {link_text}", flush=True)
                    break
            
            if not matched_term:
                continue
                
            # Wenn erforderlich, Produktdetailseite besuchen, um Verfügbarkeit zu prüfen
            is_available = True  # Standard: verfügbar, wenn wir es nicht besser wissen
            price = "Preis nicht verfügbar"
            
            if check_availability:
                try:
                    detail_soup, is_available, price = check_product_availability(product_url, headers)
                    
                    # Falls auf der Detailseite mehr Keywords gefunden werden können
                    if not matched_term and detail_soup:
                        page_text = clean_text(detail_soup.get_text())
                        for search_term, tokens in keywords_map.items():
                            if is_keyword_in_text(tokens, page_text):
                                matched_term = search_term
                                print(f"🔍 Treffer für '{search_term}' auf Detailseite von {link_text}", flush=True)
                                break
                except Exception as e:
                    print(f"⚠️ Fehler beim Prüfen der Verfügbarkeit für {product_url}: {e}", flush=True)
            
            # Bei "nur verfügbare" Option, nicht-verfügbare Produkte überspringen
            if only_available and not is_available:
                continue
                
            # Aktualisiere Produkt-Status und prüfe, ob Benachrichtigung gesendet werden soll
            should_notify, is_back_in_stock = update_product_status(
                product_id, is_available, seen, out_of_stock
            )
            
            if should_notify:
                # Status-Text erstellen
                status_text = get_status_text(is_available, is_back_in_stock)
                
                # Nachricht zusammenstellen
                msg = (
                    f"🎯 *{link_text}*\n"
                    f"💶 {price}\n"
                    f"📊 {status_text}\n"
                    f"🔎 Treffer für: '{matched_term}'\n"
                    f"🔗 [Zum Produkt]({product_url})"
                )
                
                # Telegram-Nachricht senden
                if send_telegram_message(msg):
                    # Je nach Verfügbarkeit unterschiedliche IDs speichern
                    if is_available:
                        seen.add(f"{product_id}_status_available")
                    else:
                        seen.add(f"{product_id}_status_unavailable")
                    
                    new_matches.append(product_id)
                    print(f"✅ Neuer Treffer gemeldet: {link_text} - {status_text}", flush=True)
    
    except Exception as e:
        print(f"❌ Fehler beim generischen Scraping von {url}: {e}", flush=True)
    
    return new_matches

def check_product_availability(url, headers):
    """
    Besucht die Produktdetailseite und prüft die Verfügbarkeit
    
    :param url: Produkt-URL
    :param headers: HTTP-Headers für die Anfrage
    :return: Tuple (BeautifulSoup-Objekt, Verfügbarkeitsstatus, Preis)
    """
    print(f"🔍 Prüfe Produktdetails für {url}", flush=True)
    
    response = requests.get(url, headers=headers, timeout=15)
    if response.status_code != 200:
        return None, False, "Preis nicht verfügbar"
    
    soup = BeautifulSoup(response.text, "html.parser")
    page_text = soup.get_text().lower()
    
    # Preis extrahieren
    price = extract_price(soup)
    
    # Verfügbarkeit prüfen - Verschiedene Muster
    unavailable_patterns = [
        'ausverkauft', 'sold out', 'out of stock', 'nicht verfügbar', 
        'nicht auf lager', 'vergriffen', 'derzeit nicht verfügbar'
    ]
    
    # Suche nach Add-to-Cart / Buy-Buttons als positives Signal
    available_buttons = soup.select('button[type="submit"], input[type="submit"], .add-to-cart, .buy-now, #AddToCart, .product-form__cart-submit')
    has_add_button = len(available_buttons) > 0 and not any(
        'disabled' in str(btn) or 'ausverkauft' in btn.get_text().lower() or 'sold out' in btn.get_text().lower()
        for btn in available_buttons
    )
    
    # Prüfe auf "Vorbestellbar" oder "Pre-order" als Form der Verfügbarkeit
    preorder_patterns = ['vorbestellbar', 'vorbestellung', 'pre-order', 'preorder']
    is_preorder = any(pattern in page_text for pattern in preorder_patterns)
    
    # Prüfe auf diverse "Nicht verfügbar" Signale
    is_unavailable = any(pattern in page_text for pattern in unavailable_patterns)
    
    # Entscheidungslogik
    is_available = (has_add_button or is_preorder) and not is_unavailable
    
    print(f"  - Verfügbarkeit für {url}: {'✅ Verfügbar' if is_available else '❌ Ausverkauft'}", flush=True)
    print(f"  - Preis: {price}", flush=True)
    
    return soup, is_available, price

def extract_price(soup):
    """
    Extrahiert den Preis aus der Produktseite
    
    :param soup: BeautifulSoup-Objekt der Produktseite
    :return: Formatierter Preis oder Standardtext
    """
    # Gemeinsame Preis-Selektoren
    price_selectors = [
        '.price', '.product-price', '.woocommerce-Price-amount', 
        '[itemprop="price"]', '.product__price', '.price-item',
        '.current-price', '.product-single__price'
    ]
    
    # Versuche, Preis mit verschiedenen Selektoren zu finden
    for selector in price_selectors:
        price_elem = soup.select_one(selector)
        if price_elem:
            price_text = price_elem.get_text().strip()
            # Bereinige Preis
            price_text = re.sub(r'\s+', ' ', price_text)
            return price_text
    
    # Wenn kein strukturiertes Element gefunden wurde, versuche Regex
    page_text = soup.get_text()
    price_patterns = [
        r'(\d+[,.]\d+)\s*[€$£]',  # 19,99 € oder 19.99 €
        r'[€$£]\s*(\d+[,.]\d+)',  # € 19,99 oder € 19.99
        r'(\d+[,.]\d+)',          # Nur Zahl als letzter Versuch
    ]
    
    for pattern in price_patterns:
        match = re.search(pattern, page_text)
        if match:
            return f"{match.group(1)}€"
    
    return "Preis nicht verfügbar"

def create_product_id(product_title, site_id="generic"):
    """
    Erstellt eine eindeutige Produkt-ID basierend auf Titel und Website
    
    :param product_title: Produkttitel
    :param site_id: ID der Website (z.B. 'tcgviert', 'kofuku')
    :return: Eindeutige Produkt-ID
    """
    # Extrahiere strukturierte Informationen
    series_code, product_type, language = extract_product_info(product_title)
    
    # Erstelle eine strukturierte ID
    product_id = f"{site_id}_{series_code}_{product_type}_{language}"
    
    # Füge zusätzliche Details für spezielle Produkte hinzu
    if "premium" in product_title.lower():
        product_id += "_premium"
    if "elite" in product_title.lower():
        product_id += "_elite"
    if "top" in product_title.lower() and "trainer" in product_title.lower():
        product_id += "_top"
    
    return product_id

def extract_product_info(title):
    """
    Extrahiert wichtige Produktinformationen aus dem Titel für eine präzise ID-Erstellung
    
    :param title: Produkttitel
    :return: Tupel mit (series_code, product_type, language)
    """
    # Extrahiere Sprache (DE/EN/JP)
    if "(DE)" in title or "pro Person" in title or "deutsch" in title.lower():
        language = "DE"
    elif "(EN)" in title or "per person" in title or "english" in title.lower():
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