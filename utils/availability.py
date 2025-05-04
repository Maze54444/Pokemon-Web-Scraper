"""
Modul zur webseitenspezifischen Verfügbarkeitsprüfung

Dieses Modul stellt Funktionen bereit, um die Verfügbarkeit von Produkten
auf verschiedenen Webseiten zu erkennen. Jede Webseite hat ihre eigenen
Indikatoren und Muster, die hier implementiert werden.
"""

import re
import logging
from bs4 import BeautifulSoup

# Logger konfigurieren
logger = logging.getLogger(__name__)

def detect_availability(soup, url):
    """
    Erkennt die Verfügbarkeit eines Produkts basierend auf der Website-URL
    
    :param soup: BeautifulSoup-Objekt der Produktseite
    :param url: URL der Produktseite
    :return: Tuple (is_available, price, status_text)
    """
    domain = extract_domain(url)
    
    # Website-spezifische Funktionen aufrufen
    if "comicplanet.de" in domain:
        return check_comicplanet(soup)
    elif "kofuku.de" in domain:
        return check_kofuku(soup)
    elif "tcgviert.com" in domain:
        return check_tcgviert(soup)
    elif "card-corner.de" in domain:
        return check_card_corner(soup)
    elif "sapphire-cards.de" in domain:
        return check_sapphire_cards(soup)
    elif "mighty-cards.de" in domain:
        return check_mighty_cards(soup)
    elif "games-island.eu" in domain:
        return check_games_island(soup)
    elif "gameware.at" in domain:
        return check_gameware(soup)
    else:
        # Generische Erkennung für nicht speziell implementierte Websites
        return check_generic(soup)

def extract_domain(url):
    """Extrahiert die Domain aus einer URL"""
    match = re.search(r'https?://(?:www\.)?([^/]+)', url)
    return match.group(1) if match else url

def extract_price(soup, selectors=None):
    """
    Extrahiert den Preis aus der Produktseite
    
    :param soup: BeautifulSoup-Objekt der Produktseite
    :param selectors: Liste von CSS-Selektoren für den Preis (optional)
    :return: Formatierter Preis oder Standardtext
    """
    # Standardselektoren, falls keine spezifischen angegeben sind
    if selectors is None:
        selectors = [
            '.price', '.product-price', '.woocommerce-Price-amount', 
            '[itemprop="price"]', '.product__price', '.price-item',
            '.current-price', '.product-single__price', '.product-price-box',
            '.main-price', '.price-box', '.offer-price', '.price-regular',
            '.details-product-price__value'  # Speziell für mighty-cards.de
        ]
    
    # Versuche, Preis mit verschiedenen Selektoren zu finden
    for selector in selectors:
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

def check_mighty_cards(soup):
    """
    Verbesserte Verfügbarkeitsprüfung speziell für mighty-cards.de
    
    Verfügbare Produkte:
    - "In den Warenkorb"-Button vorhanden und aktiv
    - Keine "Ausverkauft"-Texte oder deaktivierte Buttons
    
    Nicht verfügbare Produkte:
    - "Ausverkauft" Text
    - Deaktivierter oder fehlender "In den Warenkorb"-Button
    - "Produkt nicht verfügbar" Meldungen
    """
    # Extrahiere den Preis
    price = extract_price(soup, ['.details-product-price__value', '.product-details__product-price', '.price'])
    
    # Debug-Ausgabe für HTML-Struktur
    logger.debug("Checking availability for mighty-cards.de")
    
    # Prüfe auf "Ausverkauft" Text
    page_text = soup.get_text().lower()
    if "ausverkauft" in page_text or "sold out" in page_text:
        # Suche nach dem genauen Element mit "Ausverkauft"
        sold_out_elements = soup.find_all(string=re.compile(r"ausverkauft|sold out", re.IGNORECASE))
        if sold_out_elements:
            logger.debug(f"Found 'Ausverkauft' text in {len(sold_out_elements)} elements")
            return False, price, "❌ Ausverkauft"
    
    # Prüfe auf "In den Warenkorb" Button mit Ecwid-spezifischer Struktur
    add_to_cart_buttons = []
    
    # Methode 1: Suche nach Button mit spezifischen Klassen
    button_selectors = [
        'button.form-control__button',
        'button.ec-form__button',
        'button[type="submit"]',
        '.form-control__button',
        '.add-to-cart-button'
    ]
    
    for selector in button_selectors:
        buttons = soup.select(selector)
        add_to_cart_buttons.extend(buttons)
    
    # Methode 2: Suche nach Text "In den Warenkorb"
    text_elements = soup.find_all(string=re.compile(r"in den warenkorb", re.IGNORECASE))
    for element in text_elements:
        parent = element.find_parent(['button', 'div', 'span'])
        if parent and parent not in add_to_cart_buttons:
            add_to_cart_buttons.append(parent)
    
    logger.debug(f"Found {len(add_to_cart_buttons)} potential add-to-cart buttons")
    
    # Prüfe ob mindestens ein Button verfügbar und nicht deaktiviert ist
    available_button_found = False
    for button in add_to_cart_buttons:
        # Prüfe ob Button deaktiviert ist
        if button.name == 'button':
            if button.has_attr('disabled') or 'disabled' in button.get('class', []):
                logger.debug("Found disabled button")
                continue
            
            # Prüfe ob Button "In den Warenkorb" Text enthält
            button_text = button.get_text().strip().lower()
            if "warenkorb" in button_text or "cart" in button_text:
                available_button_found = True
                logger.debug("Found active add-to-cart button")
                break
    
    if available_button_found:
        return True, price, "✅ Verfügbar"
    
    # Prüfe auf Lagerbestand-Informationen
    stock_elements = soup.select('.product-details__stock-level, .stock-level, .product-stock')
    for stock_elem in stock_elements:
        stock_text = stock_elem.get_text().strip().lower()
        if "nicht" in stock_text or "out" in stock_text or "0" in stock_text:
            return False, price, "❌ Ausverkauft"
        elif "lager" in stock_text or "stock" in stock_text or "verfügbar" in stock_text:
            return True, price, "✅ Verfügbar"
    
    # Prüfe auf Ecwid-spezifische Verfügbarkeitsindikatoren
    unavailable_classes = [
        'product-details--out-of-stock',
        'product-out-of-stock',
        'ec-product-out-of-stock',
        'form-control__button--disabled'
    ]
    
    for class_name in unavailable_classes:
        if soup.select(f'.{class_name}'):
            return False, price, "❌ Ausverkauft"
    
    # Standard-Fallback: Wenn kein eindeutiger Button gefunden wurde
    logger.debug("No clear availability indicator found, assuming out of stock")
    return False, price, "❌ Ausverkauft"

def check_comicplanet(soup):
    """
    Prüft die Verfügbarkeit auf comicplanet.de
    
    Verfügbare Produkte:
    - Blaue "In den Warenkorb"-Schaltfläche
    
    Nicht verfügbare Produkte:
    - Roter Text "Nicht mehr verfügbar"
    - Oranger Benachrichtigungsbereich
    """
    # Extrahiere den Preis zuerst
    price = extract_price(soup, ['.price', '.product-price'])
    
    # Prüfe auf "Nicht mehr verfügbar"-Text
    unavailable_text = soup.find(string=re.compile("Nicht mehr verfügbar", re.IGNORECASE))
    if unavailable_text:
        return False, price, "❌ Ausverkauft (Nicht mehr verfügbar)"
    
    # Prüfe auf Benachrichtigungselement
    notify_element = soup.select_one('.product-notify-form, .form-notify-me')
    if notify_element:
        return False, price, "❌ Ausverkauft (Benachrichtigungsoption vorhanden)"
    
    # Prüfe auf "In den Warenkorb"-Button
    cart_button = soup.find('button', string=re.compile("In den Warenkorb", re.IGNORECASE))
    if cart_button:
        return True, price, "✅ Verfügbar (Warenkorb-Button vorhanden)"
    
    # Fallback: Prüfe auf "Details"-Button statt Kaufoption
    details_button = soup.find('button', string=re.compile("Details", re.IGNORECASE))
    if details_button:
        return False, price, "❌ Ausverkauft (Nur Details-Button)"
    
    # Wenn keine der bekannten Muster zutrifft, generische Methode
    is_available, _, status_text = check_generic(soup)
    return is_available, price, status_text

def check_kofuku(soup):
    """
    Verbesserte Prüfung der Verfügbarkeit auf kofuku.de
    
    Verfügbare Produkte:
    - "IN DEN WARENKORB"-Button ist aktiv und nicht ausgegraut
    - Kein Ausverkauft-Text oder -Badge
    
    Nicht verfügbare Produkte:
    - Ausverkauft-Badge oder ausgegrauer "AUSVERKAUFT"-Button
    - Schloss-Symbol
    """
    # Extrahiere den Preis
    price = extract_price(soup, ['.price', '.product-price', '.product__price'])
    page_text = soup.get_text().lower()
    
    # 1. Prüfe auf einen aktiven "In den Warenkorb"-Button
    cart_button = soup.find('button', string=re.compile("In den Warenkorb", re.IGNORECASE))
    if cart_button:
        # Prüfe, ob der Button aktiviert ist
        is_disabled = 'disabled' in cart_button.get('class', []) or 'disabled' in cart_button.attrs
        if not is_disabled:
            return True, price, "✅ Verfügbar (Warenkorb-Button aktiv)"
    
    # 2. Prüfe auf "Buy Now"-Button oder ähnliche Kaufoptionen
    buy_button = soup.select_one('.btn-buy, .buy-now, .add-to-cart:not(.disabled)')
    if buy_button:
        return True, price, "✅ Verfügbar (Kauf-Button vorhanden)"
    
    # 3. Prüfe auf "Ausverkauft"-Text im Seiteninhalt
    sold_out_matches = []
    for elem in soup.find_all(string=re.compile("Ausverkauft|ausverkauft", re.IGNORECASE)):
        sold_out_matches.append(elem.strip())
    
    if sold_out_matches:
        return False, price, "❌ Ausverkauft (Text gefunden)"
    
    # 4. Prüfe auf ausverkaufte Buttons/Elemente
    sold_out_classes = [
        'btn--sold-out', 'sold-out', 'product-price--sold-out',
        'disabled', 'btn-sold-out'
    ]
    
    for cls in sold_out_classes:
        found_elements = soup.select(f'.{cls}')
        if found_elements:
            return False, price, f"❌ Ausverkauft (Element mit Klasse '{cls}' gefunden)"
    
    # 5. Prüfe auf Schloss-Symbol (oft bei ausverkauften Produkten)
    lock_icon = soup.select_one('.icon-lock, .sold-out-overlay')
    if lock_icon:
        return False, price, "❌ Ausverkauft (Schloss-Symbol vorhanden)"
    
    # 6. Prüfe auf "ausverkauft" im Text der Seite
    if "ausverkauft" in page_text:
        return False, price, "❌ Ausverkauft (Text im Seiteninhalt)"
    
    # 7. Suche nach Hinweisen auf Verfügbarkeit
    availability_indicators = [
        'auf lager', 'verfügbar', 'lieferbar', 'in den warenkorb'
    ]
    
    for indicator in availability_indicators:
        if indicator in page_text:
            return True, price, f"✅ Verfügbar (Text enthält '{indicator}')"
    
    # WICHTIG: Wenn keine eindeutigen Indikatoren gefunden, als nicht verfügbar annehmen
    return False, price, "❌ Ausverkauft (keine eindeutigen Verfügbarkeitsindikatoren)"

def check_tcgviert(soup):
    """
    Prüft die Verfügbarkeit auf tcgviert.com
    
    Verfügbare Produkte:
    - Schwarze "IN DEN EINKAUFSWAGEN LEGEN"-Schaltfläche
    
    Nicht verfügbare Produkte:
    - Grauer Kreis mit "AUSVERKAUFT"
    - Schwarze Schaltfläche mit "BEI VERFÜGBARKEIT INFORMIEREN!"
    """
    # Extrahiere den Preis
    price = extract_price(soup, ['.price', '.product-price', '.product__price'])
    
    # Prüfe auf "AUSVERKAUFT"-Text auf der Seite
    sold_out_text = soup.find(string=re.compile("AUSVERKAUFT", re.IGNORECASE))
    if sold_out_text:
        return False, price, "❌ Ausverkauft (AUSVERKAUFT-Text gefunden)"
    
    # Prüfe auf Benachrichtigungsbutton
    notify_button = soup.find('button', string=re.compile("BEI VERFÜGBARKEIT INFORMIEREN", re.IGNORECASE))
    if notify_button:
        return False, price, "❌ Ausverkauft (Benachrichtigungsbutton vorhanden)"
    
    # Prüfe auf Einkaufswagen-Button
    cart_button = soup.find('button', string=re.compile("IN DEN EINKAUFSWAGEN LEGEN", re.IGNORECASE))
    if cart_button:
        return True, price, "✅ Verfügbar (Einkaufswagen-Button vorhanden)"
    
    # Prüfe auf "sold out"-Klassen
    sold_out_classes = soup.select_one('.sold-out, .sold_out, .product-tag--sold-out')
    if sold_out_classes:
        return False, price, "❌ Ausverkauft (Ausverkauft-Klasse gefunden)"
    
    # Generischer Ansatz für alte oder neue Shopify-Layouts
    add_to_cart = soup.select_one('button[name="add"]')
    if add_to_cart and 'disabled' not in add_to_cart.get('class', []) and 'disabled' not in add_to_cart.attrs:
        return True, price, "✅ Verfügbar (Add-to-Cart Button)"
    
    # Wenn keine der bekannten Muster zutrifft, generische Methode
    is_available, _, status_text = check_generic(soup)
    return is_available, price, status_text

def check_card_corner(soup):
    """
    Verbesserte Prüfung der Verfügbarkeit auf card-corner.de
    
    Verfügbare Produkte:
    - Grüner Status "Verfügbar"
    - Grüner "In den Warenkorb" Button
    - Produkt mit grüner Umrandung
    
    Nicht verfügbare Produkte:
    - AUSVERKAUFT-Badge
    - Roter Status "Momentan nicht verfügbar"
    """
    # Extrahiere den Preis
    price = extract_price(soup, ['.price', '.product-price', '.product__price'])
    page_text = soup.get_text().lower()
    
    # 1. Prüfe auf Verfügbar-Text
    available_text = soup.find(string=re.compile("(Verfügbar|Auf Lager|Sofort lieferbar)", re.IGNORECASE))
    if available_text:
        return True, price, "✅ Verfügbar (Verfügbar-Text)"
    
    # 2. Prüfe auf aktiven Warenkorb-Button
    cart_button = soup.select_one('.btn-primary:not([disabled]), .add-to-cart:not(.disabled), .btn-success')
    if cart_button:
        return True, price, "✅ Verfügbar (Warenkorb-Button aktiv)"
    
    # 3. Prüfe auf "Momentan nicht verfügbar" oder "Ausverkauft" Text
    unavailable_text = soup.find(string=re.compile("(Momentan nicht verfügbar|Ausverkauft|Artikel ist leider nicht)", re.IGNORECASE))
    if unavailable_text:
        return False, price, "❌ Ausverkauft (Text gefunden)"
    
    # 4. Prüfe auf ausverkauft Badge oder Element
    soldout_elem = soup.select_one('.sold-out, .badge-danger, .out-of-stock')
    if soldout_elem:
        return False, price, "❌ Ausverkauft (Badge gefunden)"
    
    # 5. Prüfe auf deaktivierte Buttons
    disabled_button = soup.select_one('button[disabled], .btn.disabled, .add-to-cart.disabled')
    if disabled_button:
        return False, price, "❌ Ausverkauft (Button deaktiviert)"
    
    # Wenn nichts eindeutiges gefunden wurde, prüfe generisch
    is_available, _, status_text = check_generic(soup)
    return is_available, price, status_text

def check_sapphire_cards(soup):
    """
    Prüft die Verfügbarkeit auf sapphire-cards.de
    
    Verfügbare Produkte:
    - Blauer "In den Warenkorb"-Button
    - Grüner Rahmen um die Sprachflagge
    
    Nicht verfügbare Produkte:
    - Roter "In den Warenkorb"-Button
    """
    # Extrahiere den Preis
    price = extract_price(soup, ['.price', '.product-price', '.product__price'])
    
    # Prüfe auf roten "In den Warenkorb"-Button (nicht verfügbar)
    red_cart_button = soup.select_one('button.btn-danger, button.btn-outline-danger, .btn-cart.unavailable')
    if red_cart_button:
        return False, price, "❌ Ausverkauft (Roter Warenkorb-Button)"
    
    # Prüfe auf blauen "In den Warenkorb"-Button (verfügbar)
    blue_cart_button = soup.select_one('button.btn-primary, button.btn-outline-primary, .btn-cart:not(.unavailable)')
    if blue_cart_button:
        return True, price, "✅ Verfügbar (Blauer Warenkorb-Button)"
    
    # Prüfe auf aktive Sprachauswahl mit grünem Rahmen
    lang_selection = soup.select_one('.lang-selection.active, .flag-container.selected')
    if lang_selection:
        return True, price, "✅ Verfügbar (Aktive Sprachauswahl)"
    
    # Prüfe auf "In den Warenkorb"-Text (als zusätzlichen Indikator)
    cart_text = soup.find(string=re.compile("In den Warenkorb", re.IGNORECASE))
    if cart_text and not red_cart_button:
        # Wenn wir Warenkorb-Text haben, aber keinen roten Button, ist es wahrscheinlich verfügbar
        return True, price, "✅ Verfügbar (Warenkorb-Text)"
    
    # Prüfe auf ausverkauft-Text
    if soup.find(string=re.compile("(ausverkauft|nicht verfügbar|out of stock)", re.IGNORECASE)):
        return False, price, "❌ Ausverkauft (Text gefunden)"
    
    # Prüfe auf Benachrichtigungsoptionen
    notify_elem = soup.select_one('.stockinfo-soldout, .out-of-stock-notification, .notify-me')
    if notify_elem:
        return False, price, "❌ Ausverkauft (Benachrichtigungsfunktion)"
    
    # Wenn keine der bekannten Muster zutrifft, generische Methode
    is_available, _, status_text = check_generic(soup)
    return is_available, price, status_text

def check_games_island(soup):
    """
    Prüft die Verfügbarkeit auf games-island.eu
    
    Verfügbare Produkte:
    - Statusindikator "AUF LAGER"
    - Grüner "Sofort verfügbar"-Text
    - Grüner "In den Warenkorb"-Button
    
    Nicht verfügbare Produkte:
    - "Momentan nicht verfügbar" in roter Schrift
    - "Benachrichtigung anfordern"-Button
    """
    # Extrahiere den Preis
    price = extract_price(soup, ['.price', '.product-price', '.current-price'])
    
    # Prüfe auf "Momentan nicht verfügbar"-Text
    unavailable_text = soup.find(string=re.compile("Momentan nicht verfügbar", re.IGNORECASE))
    if unavailable_text:
        return False, price, "❌ Ausverkauft (Momentan nicht verfügbar)"
    
    # Prüfe auf "Benachrichtigung anfordern"-Button
    notify_button = soup.find('button', string=re.compile("Benachrichtigung anfordern", re.IGNORECASE))
    if notify_button:
        return False, price, "❌ Ausverkauft (Benachrichtigungsbutton)"
    
    # Prüfe auf "AUF LAGER"-Status
    in_stock_badge = soup.find(string=re.compile("AUF LAGER", re.IGNORECASE))
    if in_stock_badge:
        return True, price, "✅ Verfügbar (AUF LAGER-Badge)"
    
    # Prüfe auf "Sofort verfügbar"-Text
    available_text = soup.find(string=re.compile("Sofort verfügbar", re.IGNORECASE))
    if available_text:
        return True, price, "✅ Verfügbar (Sofort verfügbar)"
    
    # Prüfe auf "In den Warenkorb"-Button
    cart_button = soup.find('button', string=re.compile("In den Warenkorb", re.IGNORECASE))
    if cart_button:
        return True, price, "✅ Verfügbar (Warenkorb-Button)"
    
    # Wenn keine der bekannten Muster zutrifft, generische Methode
    is_available, _, status_text = check_generic(soup)
    return is_available, price, status_text

def check_gameware(soup):
    """
    Verbesserte Prüfung der Verfügbarkeit auf gameware.at
    
    Verfügbare Produkte:
    - Text "lagernd, in 1-3 Werktagen bei dir"
    - Grüner Status-Punkt
    - Grüner "IN DEN WARENKORB"-Button
    
    Nicht verfügbare Produkte:
    - Text "Bestellung momentan nicht möglich"
    - Grauer "AUSVERKAUFT"-Button
    """
    # Extrahiere den Preis
    price = extract_price(soup, ['.price', '.product-price', '.price-box'])
    page_text = soup.get_text().lower()
    
    # 1. Prüfe auf "lagernd" oder Lieferzeit-Texte
    if re.search(r"lagernd|in 1-3 werktagen|verfügbar", page_text):
        return True, price, "✅ Verfügbar (Lagernd-Text)"
    
    # 2. Prüfe auf grünen Status-Indikator
    green_status = soup.select_one('.stock-state.success, .stock-state.available, .badge-success')
    if green_status:
        return True, price, "✅ Verfügbar (Grüner Status)"
    
    # 3. Prüfe auf aktiven "IN DEN WARENKORB"-Button
    cart_button = soup.select_one('button:not(.disabled) .fa-shopping-cart, .btn-add-to-cart:not(.disabled)')
    if cart_button:
        return True, price, "✅ Verfügbar (Warenkorb-Button aktiv)"
    
    # 4. Explizite Prüfung auf "IN DEN WARENKORB"-Text im Button
    cart_text_button = soup.find(string=re.compile("IN DEN WARENKORB", re.IGNORECASE))
    if cart_text_button and not soup.select_one('button.disabled, [disabled]'):
        return True, price, "✅ Verfügbar (Warenkorb-Text vorhanden)"
    
    # 5. Prüfe auf "Bestellung momentan nicht möglich"-Text
    unavailable_text = soup.find(string=re.compile("Bestellung momentan nicht möglich", re.IGNORECASE))
    if unavailable_text:
        return False, price, "❌ Ausverkauft (Bestellung nicht möglich)"
    
    # 6. Prüfe auf orangefarbenen/roten Status-Indikator
    warning_status = soup.select_one('.stock-state.warning, .stock-state.unavailable, .badge-danger')
    if warning_status:
        return False, price, "❌ Ausverkauft (Warnungs-Status)"
    
    # 7. Prüfe auf "ausverkauft"-Text oder Badge
    if "ausverkauft" in page_text:
        return False, price, "❌ Ausverkauft (Text im Seiteninhalt)"
    
    # 8. Prüfe auf "nicht verfügbar"-Text
    if "nicht verfügbar" in page_text:
        return False, price, "❌ Ausverkauft (Nicht verfügbar)"
    
    # Generische Methode als Fallback
    is_available, _, status_text = check_generic(soup)
    return is_available, price, status_text

def check_generic(soup):
    """
    Generische Methode zur Verfügbarkeitsprüfung, die auf verschiedenen Websites funktioniert
    
    Diese Methode verwendet allgemeine Muster, die auf vielen E-Commerce-Seiten zu finden sind.
    """
    page_text = soup.get_text().lower()
    
    # Extrahiere den Preis
    price = extract_price(soup)
    
    # Prüfe auf eindeutige Nichtverfügbarkeits-Signale
    unavailable_patterns = [
        'ausverkauft', 'sold out', 'out of stock', 'nicht verfügbar', 
        'nicht auf lager', 'vergriffen', 'derzeit nicht verfügbar',
        'momentan nicht', 'benachrichtigen'
    ]
    
    for pattern in unavailable_patterns:
        if pattern in page_text:
            return False, price, f"❌ Ausverkauft (Muster: '{pattern}')"
    
    # Suche nach Add-to-Cart / Buy-Buttons als positives Signal
    available_buttons = soup.select('button[type="submit"], input[type="submit"], .add-to-cart, .buy-now, #AddToCart, .product-form__cart-submit')
    has_add_button = len(available_buttons) > 0 and not any(
        'disabled' in str(btn) or 'ausverkauft' in btn.get_text().lower() or 'sold out' in btn.get_text().lower()
        for btn in available_buttons
    )
    
    # Prüfe auf Verfügbarkeitshinweise
    available_patterns = ['auf lager', 'verfügbar', 'available', 'in stock', 'lieferbar']
    has_available_text = any(pattern in page_text for pattern in available_patterns)
    
    # Entscheidungslogik
    if has_add_button and not any(pattern in page_text for pattern in unavailable_patterns):
        return True, price, "✅ Verfügbar (Warenkorb-Button vorhanden)"
    elif has_available_text:
        return True, price, "✅ Verfügbar (Verfügbarkeitstext)"
    else:
        # Bei Unsicherheit eher als "nicht verfügbar" behandeln
        return False, price, "❌ Status unbekannt (als nicht verfügbar behandelt)"