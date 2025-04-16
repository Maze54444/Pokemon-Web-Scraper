"""
Filter-Utility-Modul zur Filterung von URLs und Text-Inhalten basierend auf den Konfigurationsregeln
"""

import re
from urllib.parse import urlparse
from utils.filter_config import URL_FILTERS, TEXT_FILTERS, PRODUCT_TYPE_EXCLUSIONS, CATEGORY_WHITELIST

def get_domain(url):
    """
    Extrahiert die Domain aus einer URL
    
    :param url: Die zu analysierende URL
    :return: Normalisierte Domain ohne www. Präfix
    """
    try:
        parsed_url = urlparse(url)
        domain = parsed_url.netloc
        
        # Entferne www. Präfix, falls vorhanden
        if domain.startswith('www.'):
            domain = domain[4:]
            
        return domain.lower()
    except Exception as e:
        print(f"⚠️ Fehler beim Extrahieren der Domain aus {url}: {e}", flush=True)
        return url.lower()

def should_filter_url(url, link_text=None, search_product_type=None, site_id=None):
    """
    Prüft, ob eine URL basierend auf den Filterregeln gefiltert werden soll
    
    :param url: Die zu prüfende URL
    :param link_text: Optionaler Text des Links
    :param search_product_type: Produkttyp, nach dem gesucht wird (display, etb, etc.)
    :param site_id: Optionale Website-ID für spezifischere Filterung
    :return: True wenn URL gefiltert werden soll, False wenn erlaubt
    """
    if not url:
        return True  # Leere URLs immer filtern
    
    # Normalisiere URL und Link-Text
    normalized_url = url.lower()
    normalized_text = link_text.lower() if link_text else ""
    
    # Extrahiere Domain
    domain = site_id or get_domain(url)
    
    # 1. Prüfe globale URL-Filter
    for filter_term in URL_FILTERS.get("global", []):
        if filter_term in normalized_url:
            print(f"   [Filter] URL enthält globalen Filter-Term: '{filter_term}'", flush=True)
            return True
    
    # 2. Prüfe website-spezifische URL-Filter
    for site, filters in URL_FILTERS.items():
        if site != "global" and site in domain:
            for filter_term in filters:
                if filter_term in normalized_url:
                    print(f"   [Filter] URL enthält website-spezifischen Filter-Term: '{filter_term}'", flush=True)
                    return True
    
    # Wenn Link-Text vorhanden ist, auch diesen prüfen
    if normalized_text:
        # 3. Prüfe globale Text-Filter
        for filter_term in TEXT_FILTERS.get("global", []):
            if filter_term in normalized_text:
                print(f"   [Filter] Link-Text enthält globalen Filter-Term: '{filter_term}'", flush=True)
                return True
        
        # 4. Prüfe website-spezifische Text-Filter
        for site, filters in TEXT_FILTERS.items():
            if site != "global" and site in domain:
                for filter_term in filters:
                    if filter_term in normalized_text:
                        print(f"   [Filter] Link-Text enthält website-spezifischen Filter-Term: '{filter_term}'", flush=True)
                        return True
        
        # 5. Prüfe Produkt-Typ-Kompatibilität
        if search_product_type and search_product_type == "display":
            # Wenn wir nach Display suchen, prüfe auf Schlüsselwörter, die nicht-Display-Produkte anzeigen
            exclude_terms = PRODUCT_TYPE_EXCLUSIONS.get("global", [])
            for term in exclude_terms:
                if term in normalized_text:
                    print(f"   [Filter] Link-Text enthält Nicht-Display-Term: '{term}'", flush=True)
                    return True
                    
    # Whitelist-Ansatz für Kategorien, wenn aktiviert
    if is_category_link(normalized_url) and CATEGORY_WHITELIST:
        # Prüfe, ob der Link-Text relevante Kategorien enthält
        if not should_process_category(normalized_text, domain):
            print(f"   [Filter] Kategorie nicht in Whitelist: '{normalized_text}'", flush=True)
            return True
    
    # Die URL hat alle Filter bestanden
    return False

def should_process_category(category_text, domain):
    """
    Prüft, ob eine Kategorie basierend auf der Whitelist verarbeitet werden soll
    
    :param category_text: Text der Kategorie
    :param domain: Domain der Website
    :return: True wenn Kategorie in Whitelist, False sonst
    """
    if not category_text or not CATEGORY_WHITELIST:
        return True  # Ohne Text oder Whitelist alles erlauben
    
    category_text = category_text.lower()
    
    # Globale Whitelist prüfen
    for allowed_term in CATEGORY_WHITELIST.get("global", []):
        if allowed_term.lower() in category_text:
            return True
    
    # Domain-spezifische Whitelist prüfen
    for site, allowed_terms in CATEGORY_WHITELIST.items():
        if site != "global" and site in domain:
            for allowed_term in allowed_terms:
                if allowed_term.lower() in category_text:
                    return True
    
    # Wenn nicht in Whitelist
    return False

def is_category_link(url):
    """
    Erkennt, ob eine URL wahrscheinlich eine Kategorie-Seite ist
    
    :param url: Die zu prüfende URL
    :return: True wenn wahrscheinlich eine Kategorie-Seite, False sonst
    """
    category_patterns = [
        r'/category/', r'/categories/', r'/kat/', r'/kategorie/', 
        r'/collection/', r'/collections/', r'/c/', r'/cat/',
        r'/produkt-kategorie/', r'/product-category/',
    ]
    
    for pattern in category_patterns:
        if re.search(pattern, url, re.IGNORECASE):
            return True
    
    return False

def filter_links(all_links, base_url, search_product_type=None):
    """
    Filtert Links basierend auf den Filterregeln
    
    :param all_links: Liste mit Link-Tuples (href, text)
    :param base_url: Basis-URL für Domainextraktion
    :param search_product_type: Produkttyp, nach dem gesucht wird
    :return: Gefilterte Liste mit Link-Tuples
    """
    if not all_links:
        return []
    
    domain = get_domain(base_url)
    filtered_links = []
    total_links = len(all_links)
    filtered_count = 0
    
    print(f"🔍 Filtern von {total_links} Links für {domain}...", flush=True)
    
    for href, text in all_links:
        if not should_filter_url(href, text, search_product_type, domain):
            filtered_links.append((href, text))
        else:
            filtered_count += 1
    
    # Erfolgsrate berechnen
    success_rate = ((total_links - filtered_count) / total_links) * 100 if total_links > 0 else 0
    print(f"✅ {len(filtered_links)} von {total_links} Links nach Filterung übrig ({filtered_count} gefiltert, {success_rate:.1f}% Erfolgsrate)", flush=True)
    
    return filtered_links

def extract_product_links_from_soup(soup, base_url, search_product_type=None):
    """
    Extrahiert und filtert Produkt-Links aus einer BeautifulSoup-Instanz
    
    :param soup: BeautifulSoup-Objekt
    :param base_url: Basis-URL für relative Links
    :param search_product_type: Produkttyp, nach dem gesucht wird
    :return: Liste gefilterter Link-Tuples (href, text)
    """
    if not soup:
        return []
    
    domain = get_domain(base_url)
    all_links = []
    
    # Finde alle Links
    for a_tag in soup.find_all('a', href=True):
        href = a_tag.get('href', '').strip()
        
        # Überspringe leere oder JS-Links
        if not href or href.startswith(('#', 'javascript:', 'tel:', 'mailto:')):
            continue
        
        # Vollständige URL erstellen
        if not href.startswith(('http://', 'https://')):
            if href.startswith('/'):
                href = f"{base_url.rstrip('/')}{href}"
            else:
                href = f"{base_url.rstrip('/')}/{href}"
        
        # Link-Text extrahieren und bereinigen
        link_text = a_tag.get_text().strip()
        
        all_links.append((href, link_text))
    
    # Anschließend filtern
    return filter_links(all_links, base_url, search_product_type)

def filter_product_type(product_title, search_product_type):
    """
    Prüft, ob ein Produkttitel dem gesuchten Produkttyp entspricht
    
    :param product_title: Titel des Produkts
    :param search_product_type: Gesuchter Produkttyp (z.B. 'display')
    :return: True wenn Produkt dem Typ entspricht, False sonst
    """
    if not search_product_type or not product_title:
        return True  # Ohne Suchtyp oder Titel alles erlauben
    
    product_title = product_title.lower()
    
    # Wenn Display gesucht wird, nach relevanten Schlagwörtern suchen
    if search_product_type == "display":
        display_indicators = [
            r'\bdisplay\b', r'36er', r'36\s+booster', r'\bbooster\s+display\b',
            r'\bbox\s+display\b', r'booster\s+box', r'\b36\s+packs?\b'
        ]
        
        for pattern in display_indicators:
            if re.search(pattern, product_title, re.IGNORECASE):
                return True
        
        # Negative Indikatoren prüfen
        non_display_indicators = [
            r'\bblister\b', r'\betb\b', r'\belite\s+trainer\s+box\b',
            r'\bbuild\s*[&]?\s*battle\b', r'\btin\b', r'\bpack\b'
        ]
        
        for pattern in non_display_indicators:
            if re.search(pattern, product_title, re.IGNORECASE):
                return False
    
    # Weitere Produkttypen können hier hinzugefügt werden
    
    # Im Zweifelsfall Produkt zulassen
    return True

def log_filter_stats(site_id, filtered_links, total_links):
    """
    Gibt Statistiken zur Filterung aus
    
    :param site_id: ID der Website
    :param filtered_links: Anzahl der übrig gebliebenen Links
    :param total_links: Gesamtzahl der Links vor Filterung
    """
    if total_links == 0:
        rate = 100
    else:
        rate = (filtered_links / total_links) * 100
    
    print(f"📊 Filter-Statistik für {site_id}:", flush=True)
    print(f"  - Ursprüngliche Links: {total_links}", flush=True)
    print(f"  - Verbleibende Links: {filtered_links}", flush=True)
    print(f"  - Erfolgsrate: {rate:.1f}%", flush=True)