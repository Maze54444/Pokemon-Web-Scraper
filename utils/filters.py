"""
Modul 'utils/filters.py' für die Filterlogik
"""

import re
from urllib.parse import urlparse
from utils.filter_config import URL_FILTERS, TEXT_FILTERS, PRODUCT_TYPE_EXCLUSIONS

def get_domain(url):
    """Extrahiert die Domain aus einer URL"""
    try:
        parsed_url = urlparse(url)
        domain = parsed_url.netloc
        
        # Entferne www. Präfix, falls vorhanden
        if domain.startswith('www.'):
            domain = domain[4:]
            
        return domain
    except:
        # Falls ein Fehler auftritt, gib die URL zurück
        return url

def should_skip_url(url, link_text=None, search_product_type=None):
    """
    Prüft, ob eine URL oder ein Link basierend auf den konfigurierten Filterregeln übersprungen werden soll.
    
    :param url: Die zu prüfende URL
    :param link_text: Der Text des Links (optional)
    :param search_product_type: Der gesuchte Produkttyp (optional, für spezielle Produkttypfilterung)
    :return: True wenn URL übersprungen werden soll, False sonst
    """
    if not url:
        return True
        
    # Normalisiere URL und Link-Text
    normalized_url = url.lower()
    normalized_text = link_text.lower() if link_text else ""
    
    # Extrahiere Domain für website-spezifische Filter
    domain = get_domain(url)
    
    # 1. Prüfe globale URL-Filter
    for filter_term in URL_FILTERS["global"]:
        if filter_term in normalized_url:
            return True
    
    # 2. Prüfe globale Text-Filter
    if normalized_text:
        for filter_term in TEXT_FILTERS["global"]:
            if filter_term in normalized_text:
                return True
    
    # 3. Prüfe website-spezifische Filter
    for site, filters in URL_FILTERS.items():
        if site != "global" and site in domain:
            for filter_term in filters:
                if filter_term in normalized_url:
                    return True
                    
    # 4. Prüfe website-spezifische Text-Filter
    if normalized_text:
        for site, filters in TEXT_FILTERS.items():
            if site != "global" and site in domain:
                for filter_term in filters:
                    if filter_term in normalized_text:
                        return True
    
    # 5. Prüfe auf ausgeschlossene Produkttypen, wenn ein Suchprodukttyp angegeben ist
    if search_product_type and search_product_type == "display":
        # Prüfe auf typische Nicht-Display-Schlüsselwörter
        non_display_keywords = [
            "blister", "booster pack", "einzelpack", "single pack", "promo",
            "tin", "figur", "elite trainer box", "etb", "build & battle", 
            "sammelordner", "sleeves", "deck", "binder", "top trainer"
        ]
        
        for keyword in non_display_keywords:
            if keyword in normalized_text:
                return True
    
    # Die URL sollte nicht übersprungen werden
    return False

def filter_links(soup, base_url, search_product_type=None):
    """
    Filtert Links aus einer BeautifulSoup-Instanz basierend auf den konfigurierten Filterregeln.
    
    :param soup: BeautifulSoup-Objekt mit den zu filternden Links
    :param base_url: Basis-URL für die Vervollständigung relativer URLs
    :param search_product_type: Der gesuchte Produkttyp (optional)
    :return: Liste mit gefilterten Link-Tuples (href, text)
    """
    if not soup:
        return []
        
    # Extrahiere alle Links
    all_links = soup.find_all('a', href=True)
    
    # Erstelle Liste für gefilterte Links (href, text)
    filtered_links = []
    
    domain = get_domain(base_url)
    
    # Zähler für Statistiken
    total_links = len(all_links)
    filtered_out = 0
    
    for a_tag in all_links:
        href = a_tag.get('href', '')
        
        # Überspringe leere Links oder JavaScript-Links
        if not href or href.startswith('#') or href.startswith('javascript:'):
            filtered_out += 1
            continue
        
        # Vollständige URL erstellen, falls notwendig
        if not href.startswith(('http://', 'https://')):
            if href.startswith('/'):
                href = f"{base_url.rstrip('/')}{href}"
            else:
                href = f"{base_url.rstrip('/')}/{href}"
        
        # Link-Text extrahieren und bereinigen
        link_text = a_tag.get_text().strip()
        
        # Prüfen, ob der Link gefiltert werden soll
        if should_skip_url(href, link_text, search_product_type):
            filtered_out += 1
            continue
        
        # Diesen Link zur gefilterten Liste hinzufügen
        filtered_links.append((href, link_text))
    
    # Log-Ausgabe mit Statistiken
    print(f"🔍 Filterstatistik für {domain}: {len(filtered_links)}/{total_links} Links übrig nach Filterung ({filtered_out} gefiltert)", flush=True)
    
    return filtered_links

def log_filter_stats(site_id, filtered_count, total_count, reason_stats=None):
    """
    Gibt Statistiken über die Filterung aus
    
    :param site_id: ID der Website
    :param filtered_count: Anzahl der gefilterten Links
    :param total_count: Gesamtanzahl der Links
    :param reason_stats: Dictionary mit Filtergründen und deren Häufigkeit
    """
    percentage = 0 if total_count == 0 else (filtered_count / total_count) * 100
    print(f"📊 Filter-Statistik für {site_id}: {filtered_count}/{total_count} Links gefiltert ({percentage:.1f}%)", flush=True)
    
    if reason_stats:
        print("📋 Filtergründe:", flush=True)
        for reason, count in sorted(reason_stats.items(), key=lambda x: x[1], reverse=True):
            if count > 0:
                print(f"  - {reason}: {count}x", flush=True)