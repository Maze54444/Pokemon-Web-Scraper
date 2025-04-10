"""
Modul zur webseitenspezifischen Verfügbarkeitsprüfung

Dieses Modul stellt Funktionen bereit, um die Verfügbarkeit von Produkten
auf verschiedenen Webseiten zu erkennen. Jede Webseite hat ihre eigenen
Indikatoren und Muster, die hier implementiert werden.
"""

import re
from bs4 import BeautifulSoup

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
            '.main-price', '.price-box', '.offer-price', '.price-regular'
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

def check_comicplanet(soup):
    """
    Prüft die Verfügbarkeit auf comicplanet.de
    
    Verfügbare Produkte:
    - Blaue "In den Warenkorb"-Schaltfläche
    
    Nicht verfügbare Produkte:
    - Roter Text "Nicht mehr verfügbar"
    - Oranger Benachrichtigungsbereich
    """
    # Prüfe auf "Nicht mehr verfügbar"-Text
    unavailable_text = soup.find(string=re.compile("Nicht mehr verfügbar", re.IGNORECASE))
    if unavailable_text:
        price = extract_price(soup, ['.price', '.product-price'])
        return False, price, "❌ Ausverkauft (Nicht mehr verfügbar)"
    
    # Prüfe auf Benachrichtigungselement
    notify_element = soup.select_one('.product-notify-form, .form-notify-me')
    if notify_element:
        price = extract_price(soup, ['.price', '.product-price'])
        return False, price, "❌ Ausverkauft (Benachrichtigungsoption vorhanden)"
    
    # Prüfe auf "In den Warenkorb"-Button
    cart_button = soup.find('button', string=re.compile("In den Warenkorb", re.IGNORECASE))
    if cart_button:
        price = extract_price(soup, ['.price', '.product-price'])
        return True, price, "✅ Verfügbar (Warenkorb-Button vorhanden)"
    
    # Fallback: Prüfe auf "Details"-Button statt Kaufoption
    details_button = soup.find('button', string=re.compile("Details", re.IGNORECASE))
    if details_button:
        price = extract_price(soup, ['.price', '.product-price'])
        return False, price, "❌ Ausverkauft (Nur Details-Button)"
    
    # Wenn keine der bekannten Muster zutrifft, generische Methode
    return check_generic(soup)

def check_kofuku(soup):
    """
    Prüft die Verfügbarkeit auf kofuku.de
    
    Verfügbare Produkte:
    - Dunkelblauer "In den Warenkorb"-Button
    
    Nicht verfügbare Produkte:
    - Schloss-Symbol mit "Ausverkauft"
    - Grauer Button mit "AUSVERKAUFT"
    """
    # Prüfe auf "Ausverkauft"-Text
    sold_out_text = soup.find(string=re.compile("Ausverkauft", re.IGNORECASE))
    if sold_out_text:
        price = extract_price(soup, ['.price', '.product-price', '.product__price'])
        return False, price, "❌ Ausverkauft (Text gefunden)"
    
    # Prüfe auf ausgegrauten Button
    sold_out_button = soup.select_one('button.disabled, button[disabled], .btn--sold-out')
    if sold_out_button:
        price = extract_price(soup, ['.price', '.product-price', '.product__price'])
        return False, price, "❌ Ausverkauft (Button deaktiviert)"
    
    # Prüfe auf Schloss-Symbol
    lock_icon = soup.select_one('.icon-lock, .sold-out-overlay')
    if lock_icon:
        price = extract_price(soup, ['.price', '.product-price', '.product__price'])
        return False, price, "❌ Ausverkauft (Schloss-Symbol vorhanden)"
    
    # Prüfe auf "In den Warenkorb"-Button
    cart_button = soup.find('button', string=re.compile("In den Warenkorb", re.IGNORECASE))
    if cart_button:
        price = extract_price(soup, ['.price', '.product-price', '.product__price'])
        return True, price, "✅ Verfügbar (Warenkorb-Button vorhanden)"
    
    # Wenn keine der bekannten Muster zutrifft, generische Methode
    return check_generic(soup)

def check_tcgviert(soup):
    """
    Prüft die Verfügbarkeit auf tcgviert.com
    
    Verfügbare Produkte:
    - Schwarze "IN DEN EINKAUFSWAGEN LEGEN"-Schaltfläche
    
    Nicht verfügbare Produkte:
    - Grauer Kreis mit "AUSVERKAUFT"
    - Schwarze Schaltfläche mit "BEI VERFÜGBARKEIT INFORMIEREN!"
    """
    # Prüfe auf "AUSVERKAUFT"-Text auf der Seite
    sold_out_text = soup.find(string=re.compile("AUSVERKAUFT", re.IGNORECASE))
    if sold_out_text:
        price = extract_price(soup, ['.price', '.product-price', '.product__price'])
        return False, price, "❌ Ausverkauft (AUSVERKAUFT-Text gefunden)"
    
    # Prüfe auf Benachrichtigungsbutton
    notify_button = soup.find('button', string=re.compile("BEI VERFÜGBARKEIT INFORMIEREN", re.IGNORECASE))
    if notify_button:
        price = extract_price(soup, ['.price', '.product-price', '.product__price'])
        return False, price, "❌ Ausverkauft (Benachrichtigungsbutton vorhanden)"
    
    # Prüfe auf Einkaufswagen-Button
    cart_button = soup.find('button', string=re.compile("IN DEN EINKAUFSWAGEN LEGEN", re.IGNORECASE))
    if cart_button:
        price = extract_price(soup, ['.price', '.product-price', '.product__price'])
        return True, price, "✅ Verfügbar (Einkaufswagen-Button vorhanden)"
    
    # Prüfe auf "sold out"-Klassen
    sold_out_classes = soup.select_one('.sold-out, .sold_out, .product-tag--sold-out')
    if sold_out_classes:
        price = extract_price(soup, ['.price', '.product-price', '.product__price'])
        return False, price, "❌ Ausverkauft (Ausverkauft-Klasse gefunden)"
    
    # Wenn keine der bekannten Muster zutrifft, generische Methode
    return check_generic(soup)

def check_card_corner(soup):
    """
    Prüft die Verfügbarkeit auf card-corner.de
    
    Verfügbare Produkte:
    - Grünes Rechteck mit "BESTSELLER" oder "AUF LAGER"
    - Grüner "Verfügbar"-Text
    - Gelber runder Button mit Warenkorb-Symbol
    
    Nicht verfügbare Produkte:
    - Rotes Rechteck mit "AUSVERKAUFT"
    - Roter "Momentan nicht verfügbar"-Text
    - Gelber Button mit "Zum Artikel" statt Warenkorb-Symbol
    """
    # Prüfe auf "AUSVERKAUFT"-Status
    sold_out_badge = soup.find(string=re.compile("AUSVERKAUFT", re.IGNORECASE))
    if sold_out_badge:
        price = extract_price(soup, ['.price', '.product-price', '.product__price'])
        return False, price, "❌ Ausverkauft (AUSVERKAUFT-Badge)"
    
    # Prüfe auf "Momentan nicht verfügbar"-Text
    unavailable_text = soup.find(string=re.compile("Momentan nicht verfügbar", re.IGNORECASE))
    if unavailable_text:
        price = extract_price(soup, ['.price', '.product-price', '.product__price'])
        return False, price, "❌ Ausverkauft (Momentan nicht verfügbar)"
    
    # Prüfe auf "AUF LAGER"-Status
    in_stock_badge = soup.find(string=re.compile("AUF LAGER", re.IGNORECASE))
    if in_stock_badge:
        price = extract_price(soup, ['.price', '.product-price', '.product__price'])
        return True, price, "✅ Verfügbar (AUF LAGER-Badge)"
    
    # Prüfe auf "BESTSELLER"-Status (typisch für verfügbare Produkte)
    bestseller_badge = soup.find(string=re.compile("BESTSELLER", re.IGNORECASE))
    if bestseller_badge:
        price = extract_price(soup, ['.price', '.product-price', '.product__price'])
        return True, price, "✅ Verfügbar (BESTSELLER-Badge)"
    
    # Prüfe auf "Verfügbar"-Text
    available_text = soup.find(string=re.compile("Verfügbar", re.IGNORECASE))
    if available_text:
        price = extract_price(soup, ['.price', '.product-price', '.product__price'])
        return True, price, "✅ Verfügbar (Verfügbar-Text)"
    
    # Prüfe auf Warenkorb-Button
    cart_button = soup.select_one('.cart-btn, .add-to-cart, button[title*="Warenkorb"]')
    if cart_button:
        price = extract_price(soup, ['.price', '.product-price', '.product__price'])
        return True, price, "✅ Verfügbar (Warenkorb-Button)"
    
    # Prüfe auf "Zum Artikel"-Button (typisch für nicht verfügbare Produkte)
    article_button = soup.find('a', string=re.compile("Zum Artikel", re.IGNORECASE))
    if article_button:
        price = extract_price(soup, ['.price', '.product-price', '.product__price'])
        return False, price, "❌ Ausverkauft (Zum Artikel-Button)"
    
    # Wenn keine der bekannten Muster zutrifft, generische Methode
    return check_generic(soup)

def check_sapphire_cards(soup):
    """
    Prüft die Verfügbarkeit auf sapphire-cards.de
    
    Verfügbare Produkte:
    - Blauer "In den Warenkorb"-Button
    - Grüner Rahmen um die Sprachflagge
    
    Nicht verfügbare Produkte:
    - Roter "In den Warenkorb"-Button
    """
    # Prüfe auf roten "In den Warenkorb"-Button (nicht verfügbar)
    red_cart_button = soup.select_one('button.btn-danger, button.btn-outline-danger, .btn-cart.unavailable')
    if red_cart_button:
        price = extract_price(soup, ['.price', '.product-price', '.product__price'])
        return False, price, "❌ Ausverkauft (Roter Warenkorb-Button)"
    
    # Prüfe auf blauen "In den Warenkorb"-Button (verfügbar)
    blue_cart_button = soup.select_one('button.btn-primary, button.btn-outline-primary, .btn-cart:not(.unavailable)')
    if blue_cart_button:
        price = extract_price(soup, ['.price', '.product-price', '.product__price'])
        return True, price, "✅ Verfügbar (Blauer Warenkorb-Button)"
    
    # Prüfe auf aktive Sprachauswahl mit grünem Rahmen
    lang_selection = soup.select_one('.lang-selection.active, .flag-container.selected')
    if lang_selection:
        price = extract_price(soup, ['.price', '.product-price', '.product__price'])
        return True, price, "✅ Verfügbar (Aktive Sprachauswahl)"
    
    # Wenn keine der bekannten Muster zutrifft, generische Methode
    return check_generic(soup)

def check_mighty_cards(soup):
    """
    Prüft die Verfügbarkeit auf mighty-cards.de
    
    Verfügbare Produkte:
    - Statusindikator: NEW, SALE oder EXCLUSIVE
    - Roter "In den Warenkorb"-Button
    
    Nicht verfügbare Produkte:
    - Roter Button mit "AUSVERKAUFT"
    - Kein "In den Warenkorb"-Button
    """
    # Prüfe auf "AUSVERKAUFT"-Text
    sold_out_text = soup.find(string=re.compile("AUSVERKAUFT", re.IGNORECASE))
    if sold_out_text:
        price = extract_price(soup, ['.price', '.product-price', '.current-price'])
        return False, price, "❌ Ausverkauft (AUSVERKAUFT-Text)"
    
    # Prüfe auf "In den Warenkorb"-Button
    cart_button = soup.find('button', string=re.compile("In den Warenkorb", re.IGNORECASE))
    if cart_button:
        price = extract_price(soup, ['.price', '.product-price', '.current-price'])
        return True, price, "✅ Verfügbar (Warenkorb-Button)"
    
    # Prüfe auf spezielle Statusanzeigen, die auf Verfügbarkeit hindeuten
    special_status = soup.find(string=re.compile("NEW|SALE|EXCLUSIVE", re.IGNORECASE))
    if special_status:
        price = extract_price(soup, ['.price', '.product-price', '.current-price'])
        return True, price, f"✅ Verfügbar ({special_status.strip()})"
    
    # Wenn keine der bekannten Muster zutrifft, generische Methode
    return check_generic(soup)

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
    # Prüfe auf "Momentan nicht verfügbar"-Text
    unavailable_text = soup.find(string=re.compile("Momentan nicht verfügbar", re.IGNORECASE))
    if unavailable_text:
        price = extract_price(soup, ['.price', '.product-price', '.current-price'])
        return False, price, "❌ Ausverkauft (Momentan nicht verfügbar)"
    
    # Prüfe auf "Benachrichtigung anfordern"-Button
    notify_button = soup.find('button', string=re.compile("Benachrichtigung anfordern", re.IGNORECASE))
    if notify_button:
        price = extract_price(soup, ['.price', '.product-price', '.current-price'])
        return False, price, "❌ Ausverkauft (Benachrichtigungsbutton)"
    
    # Prüfe auf "AUF LAGER"-Status
    in_stock_badge = soup.find(string=re.compile("AUF LAGER", re.IGNORECASE))
    if in_stock_badge:
        price = extract_price(soup, ['.price', '.product-price', '.current-price'])
        return True, price, "✅ Verfügbar (AUF LAGER-Badge)"
    
    # Prüfe auf "Sofort verfügbar"-Text
    available_text = soup.find(string=re.compile("Sofort verfügbar", re.IGNORECASE))
    if available_text:
        price = extract_price(soup, ['.price', '.product-price', '.current-price'])
        return True, price, "✅ Verfügbar (Sofort verfügbar)"
    
    # Prüfe auf "In den Warenkorb"-Button
    cart_button = soup.find('button', string=re.compile("In den Warenkorb", re.IGNORECASE))
    if cart_button:
        price = extract_price(soup, ['.price', '.product-price', '.current-price'])
        return True, price, "✅ Verfügbar (Warenkorb-Button)"
    
    # Wenn keine der bekannten Muster zutrifft, generische Methode
    return check_generic(soup)

def check_gameware(soup):
    """
    Prüft die Verfügbarkeit auf gameware.at
    
    Verfügbare Produkte:
    - Grüner Punkt mit "lagernd, in 1-3 Werktagen bei dir"
    - Grüner "IN DEN WARENKORB"-Button
    
    Nicht verfügbare Produkte:
    - Orangefarbener Punkt mit "Bestellung momentan nicht möglich"
    - Grauer Button mit grüner rechter Seite
    """
    # Prüfe auf "Bestellung momentan nicht möglich"-Text
    unavailable_text = soup.find(string=re.compile("Bestellung momentan nicht möglich", re.IGNORECASE))
    if unavailable_text:
        price = extract_price(soup, ['.price', '.product-price', '.price-box'])
        return False, price, "❌ Ausverkauft (Bestellung nicht möglich)"
    
    # Prüfe auf orangefarbenen Statusindikator
    orange_status = soup.select_one('.stock-state.warning, .stock-state.unavailable')
    if orange_status:
        price = extract_price(soup, ['.price', '.product-price', '.price-box'])
        return False, price, "❌ Ausverkauft (Orangefarbener Status)"
    
    # Prüfe auf grünen Statusindikator oder "lagernd"-Text
    green_status = soup.select_one('.stock-state.success, .stock-state.available')
    in_stock_text = soup.find(string=re.compile("lagernd", re.IGNORECASE))
    if green_status or in_stock_text:
        price = extract_price(soup, ['.price', '.product-price', '.price-box'])
        return True, price, "✅ Verfügbar (Grüner Status / Lagernd)"
    
    # Prüfe auf "IN DEN WARENKORB"-Button
    cart_button = soup.find('button', string=re.compile("IN DEN WARENKORB", re.IGNORECASE))
    if cart_button and 'disabled' not in cart_button.attrs:
        price = extract_price(soup, ['.price', '.product-price', '.price-box'])
        return True, price, "✅ Verfügbar (Warenkorb-Button aktiv)"
    
    # Wenn keine der bekannten Muster zutrifft, generische Methode
    return check_generic(soup)

def check_generic(soup):
    """
    Generische Methode zur Verfügbarkeitsprüfung, die auf verschiedenen Websites funktioniert
    
    Diese Methode verwendet allgemeine Muster, die auf vielen E-Commerce-Seiten zu finden sind.
    """
    page_text = soup.get_text().lower()
    
    # Extraiere den Preis
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
    
    # Prüfe auf "Vorbestellbar" oder "Pre-order" als Form der Verfügbarkeit
    preorder_patterns = ['vorbestellbar', 'vorbestellung', 'pre-order', 'preorder']
    is_preorder = any(pattern in page_text for pattern in preorder_patterns)
    
    # Prüfe auf Verfügbarkeitshinweise
    available_patterns = ['auf lager', 'verfügbar', 'available', 'in stock', 'lieferbar']
    has_available_text = any(pattern in page_text for pattern in available_patterns)
    
    # Entscheidungslogik
    if has_add_button and not any(pattern in page_text for pattern in unavailable_patterns):
        return True, price, "✅ Verfügbar (Warenkorb-Button vorhanden)"
    elif is_preorder:
        return True, price, "🔜 Vorbestellbar"
    elif has_available_text:
        return True, price, "✅ Verfügbar (Verfügbarkeitstext)"
    else:
        return False, price, "❓ Status unbekannt"