"""
Filter-Utility-Modul zur Filterung von URLs und Text-Inhalten basierend auf den Konfigurationsregeln
"""

import re
import json
import logging
import os
from urllib.parse import urlparse
from utils.filter_config import URL_FILTERS, TEXT_FILTERS, PRODUCT_TYPE_EXCLUSIONS, CATEGORY_WHITELIST
from utils.matcher import extract_product_type_from_text, extract_product_keywords

# Logger konfigurieren
logger = logging.getLogger(__name__)

# Cache für verarbeitete Domains und Filterentscheidungen
_domain_cache = {}
_filter_decision_cache = {}
# Maximale Größe der Caches, um Speicherverbrauch zu begrenzen
MAX_CACHE_ENTRIES = 1000

def get_domain(url):
    """
    Extrahiert die Domain aus einer URL
    
    :param url: Die zu analysierende URL
    :return: Normalisierte Domain ohne www. Präfix
    """
    # Prüfe, ob die Domain bereits im Cache ist
    if url in _domain_cache:
        return _domain_cache[url]
        
    try:
        parsed_url = urlparse(url)
        domain = parsed_url.netloc
        
        # Entferne www. Präfix, falls vorhanden
        if domain.startswith('www.'):
            domain = domain[4:]
            
        result = domain.lower()
        
        # Speichere im Cache
        if len(_domain_cache) < MAX_CACHE_ENTRIES:
            _domain_cache[url] = result
            
        return result
    except Exception as e:
        logger.debug(f"Fehler beim Extrahieren der Domain aus {url}: {e}")
        return url.lower()

def load_exclusion_sets():
    """
    Lädt die Liste der auszuschließenden Sets aus einer Konfigurationsdatei
    oder verwendet eine Standard-Liste
    
    :return: Liste mit auszuschließenden Sets
    """
    exclusion_sets = []
    try:
        # Versuche, die Ausschlussliste aus einer Konfigurationsdatei zu laden
        exclusion_file_paths = ["config/exclusion_sets.json", "data/exclusion_sets.json"]
        
        for file_path in exclusion_file_paths:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    exclusion_sets = json.load(f)
                    logger.debug(f"Ausschlussliste aus {file_path} geladen: {len(exclusion_sets)} Einträge")
                    return exclusion_sets
            except FileNotFoundError:
                pass
            except json.JSONDecodeError as e:
                logger.warning(f"Fehler beim Parsen der Ausschlussliste {file_path}: {e}")
    except Exception as e:
        logger.warning(f"Fehler beim Laden der Ausschlussliste: {e}")
    
    # Standard-Ausschlussliste, wenn keine Konfigurationsdatei gefunden wurde
    exclusion_sets = [
        "stürmische funken", "sturmi", "paradox rift", "paradox", "prismat", "stellar", "battle partners",
        "nebel der sagen", "zeit", "paldea", "obsidian", "astral", "brilliant", "fusion", 
        "kp01", "kp02", "kp03", "kp04", "kp05", "kp06", "kp07", "kp08", "sv01", "sv02", "sv03", "sv04", 
        "sv05", "sv06", "sv07", "sv08", "sv10", "sv11", "sv12", "sv13", 
        
    ]
    
    return exclusion_sets

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
    
    # Cache-Schlüssel erstellen
    cache_key = f"{url}::{link_text or ''}::{search_product_type or ''}::{site_id or ''}"
    if cache_key in _filter_decision_cache:
        return _filter_decision_cache[cache_key]
    
    # Normalisiere URL und Link-Text
    normalized_url = url.lower()
    normalized_text = link_text.lower() if link_text else ""
    
    # Schneller Filter für offensichtliche URL-Typen
    if ("/login" in normalized_url or 
        "/account" in normalized_url or 
        "#" in normalized_url or
        "javascript:" in normalized_url or
        "mailto:" in normalized_url or
        "tel:" in normalized_url):
        _store_filter_decision(cache_key, True)
        return True
    
    # Extrahiere Domain
    domain = site_id or get_domain(url)
    
    # 1. Prüfe globale URL-Filter
    for filter_term in URL_FILTERS.get("global", []):
        if filter_term in normalized_url:
            _store_filter_decision(cache_key, True)
            return True
    
    # 2. Prüfe website-spezifische URL-Filter
    for site, filters in URL_FILTERS.items():
        if site != "global" and site in domain:
            for filter_term in filters:
                if filter_term in normalized_url:
                    _store_filter_decision(cache_key, True)
                    return True
    
    # Wenn Link-Text vorhanden ist, auch diesen prüfen
    if normalized_text:
        # 3. Prüfe globale Text-Filter
        for filter_term in TEXT_FILTERS.get("global", []):
            if filter_term in normalized_text:
                _store_filter_decision(cache_key, True)
                return True
        
        # 4. Prüfe website-spezifische Text-Filter
        for site, filters in TEXT_FILTERS.items():
            if site != "global" and site in domain:
                for filter_term in filters:
                    if filter_term in normalized_text:
                        _store_filter_decision(cache_key, True)
                        return True
        
        # 5. Wichtig: Strenge Produkttyp-Überprüfung (insbesondere für Displays)
        if search_product_type:
            # Extrahiere Produkttyp aus dem Text
            text_product_type = extract_product_type_from_text(normalized_text)
            
            # Wenn der Produkttyp erkannt wurde und nicht mit dem gesuchten übereinstimmt, filtern
            if text_product_type != "unknown" and text_product_type != search_product_type:
                _store_filter_decision(cache_key, True)
                return True
            
            # Zusätzliche Prüfung: Wenn der Link Text eindeutige Nicht-Display Begriffe enthält
            if search_product_type == "display":
                non_display_terms = [
                    "3er", "3 er", "3-pack", "blister", "elite trainer", "etb", "top trainer", 
                    "build & battle", "build and battle", "einzelpack", "single pack", "einzelbooster",
                    "premium", "tin", "sleeves", "pin", "mini tin"
                ]
                
                # Genaue Treffer mit Wortgrenzen
                for term in non_display_terms:
                    if re.search(r'\b' + re.escape(term) + r'\b', normalized_text):
                        _store_filter_decision(cache_key, True)
                        return True
            
            # Ähnliche Prüfung für ETB
            elif search_product_type == "etb":
                non_etb_terms = [
                    "display", "36er", "blister", "tin", "booster box", "36",
                    "build & battle", "build and battle", "einzelpack", "single pack"
                ]
                
                for term in non_etb_terms:
                    if re.search(r'\b' + re.escape(term) + r'\b', normalized_text):
                        _store_filter_decision(cache_key, True)
                        return True
            
            # Ähnliche Prüfung für TTB
            elif search_product_type == "ttb":
                non_ttb_terms = [
                    "display", "36er", "blister", "tin", "booster box", "36", "elite trainer",
                    "build & battle", "build and battle", "einzelpack", "single pack"
                ]
                
                for term in non_ttb_terms:
                    if re.search(r'\b' + re.escape(term) + r'\b', normalized_text):
                        _store_filter_decision(cache_key, True)
                        return True
    
    # Prüfe auf ausgeschlossene Sets, falls ein Link-Text vorhanden ist
    if normalized_text:
        # Lade Ausschluss-Sets
        exclusion_sets = load_exclusion_sets()
        
        # Wenn Link-Text einen ausgeschlossenen Set-Namen enthält, filtern
        for exclusion in exclusion_sets:
            if exclusion in normalized_text:
                _store_filter_decision(cache_key, True)
                return True
    
    # Whitelist-Ansatz für Kategorien, wenn aktiviert
    if is_category_link(normalized_url) and CATEGORY_WHITELIST:
        # Prüfe, ob der Link-Text relevante Kategorien enthält
        if not should_process_category(normalized_text, domain):
            _store_filter_decision(cache_key, True)
            return True
    
    # Die URL hat alle Filter bestanden
    _store_filter_decision(cache_key, False)
    return False

def _store_filter_decision(cache_key, decision):
    """Speichert eine Filterentscheidung im Cache"""
    if len(_filter_decision_cache) < MAX_CACHE_ENTRIES:
        _filter_decision_cache[cache_key] = decision

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
    
    # Schnelles Filtern durch Batch-Verarbeitung
    batch_size = 50
    for i in range(0, len(all_links), batch_size):
        batch = all_links[i:i+batch_size]
        
        # Parallele Entscheidungsfindung für den Batch
        for href, text in batch:
            if not should_filter_url(href, text, search_product_type, domain):
                filtered_links.append((href, text))
    
    return filtered_links

def extract_product_links_from_soup(soup, base_url, search_product_type=None, max_links=50):
    """
    Extrahiert und filtert Produkt-Links aus einer BeautifulSoup-Instanz
    
    :param soup: BeautifulSoup-Objekt
    :param base_url: Basis-URL für relative Links
    :param search_product_type: Produkttyp, nach dem gesucht wird
    :param max_links: Maximale Anzahl zu extrahierender Links
    :return: Liste gefilterter Link-Tuples (href, text)
    """
    if not soup:
        return []
    
    domain = get_domain(base_url)
    
    # Finde alle Links
    all_links = []
    counter = 0
    
    # Prioritäts-Selektoren für Produktlinks
    priority_selectors = [
        'a.product-title', 'a.product-name', '.product a', 
        '.product-card a', '.product-item a', '.grid-product a',
        '.grid__item a', '[data-product-card] a'
    ]
    
    # Zuerst Prioritäts-Selektoren prüfen
    for selector in priority_selectors:
        if len(all_links) >= max_links:
            break
            
        for a_tag in soup.select(selector):
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
            counter += 1
            
            if counter >= max_links:
                break
    
    # Wenn nicht genug Prioritäts-Links gefunden, nach regulären Links suchen
    if len(all_links) < max_links:
        remaining_links = max_links - len(all_links)
        
        for a_tag in soup.find_all('a', href=True):
            href = a_tag.get('href', '').strip()
            
            # Überspringe leere oder JS-Links
            if not href or href.startswith(('#', 'javascript:', 'tel:', 'mailto:')):
                continue
                
            # Schnelle Filterung offensichtlich irrelevanter Links
            if ('/login' in href or '/account' in href or '/checkout' in href or 
                '/cart' in href or '/wishlist' in href):
                continue
            
            # Produktlinks bevorzugen
            if ('/product/' not in href and '/products/' not in href and 
                '/produkt/' not in href and 'detail' not in href):
                
                # Spezielle Pfad-Muster für bestimmte Shops prüfen
                shop_specific_patterns = {
                    'mighty-cards.de': ['/shop/', '/p'],
                    'fantasiacards.de': ['/collections/']
                }
                
                match_found = False
                for shop, patterns in shop_specific_patterns.items():
                    if shop in base_url:
                        for pattern in patterns:
                            if pattern in href:
                                match_found = True
                                break
                
                if not match_found:
                    continue
            
            # Vollständige URL erstellen
            if not href.startswith(('http://', 'https://')):
                if href.startswith('/'):
                    href = f"{base_url.rstrip('/')}{href}"
                else:
                    href = f"{base_url.rstrip('/')}/{href}"
            
            # Link-Text extrahieren und bereinigen
            link_text = a_tag.get_text().strip()
            
            # Duplikate vermeiden
            if any(href == h for h, _ in all_links):
                continue
                
            all_links.append((href, link_text))
            counter += 1
            
            if counter >= max_links:
                break
    
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
    
    # Extrahiere Produkttyp aus dem Titel
    text_product_type = extract_product_type_from_text(product_title)
    
    # Wenn ein bestimmter Produkttyp gesucht wird, muss der Titel auch als dieser Typ erkannt werden
    if search_product_type in ["display", "etb", "ttb"]:
        # Sehr strenge Prüfung für bestimmte Produkttypen
        if text_product_type in ("unknown", ""):
            # Bei unbekanntem Typ: Prüfe auf eindeutige Hinweise für den gesuchten Typ
            if search_product_type == "display":
                if re.search(r'\bdisplay\b|\b36er\b|\b36\s+booster\b|\bbooster\s+box\b', product_title):
                    return True
            elif search_product_type == "etb":
                if re.search(r'\betb\b|\belite\s+trainer\s+box\b|\belite-trainer\b', product_title):
                    return True
            elif search_product_type == "ttb":
                if re.search(r'\bttb\b|\btop\s+trainer\s+box\b|\btop-trainer\b', product_title):
                    return True
            return False
        
        return text_product_type == search_product_type
    
    # Bei anderen Produkttypen können wir weniger streng sein
    return True

def reset_caches():
    """
    Setzt die internen Caches zurück (für Testzwecke oder bei Speicherproblemen)
    
    :return: Anzahl der zurückgesetzten Cache-Einträge
    """
    global _domain_cache, _filter_decision_cache
    
    domain_count = len(_domain_cache)
    filter_count = len(_filter_decision_cache)
    
    _domain_cache = {}
    _filter_decision_cache = {}
    
    return domain_count + filter_count

def get_cache_stats():
    """
    Gibt Statistiken zu den aktuellen Caches zurück
    
    :return: Dictionary mit Cache-Statistiken
    """
    return {
        "domain_cache_size": len(_domain_cache),
        "filter_decision_cache_size": len(_filter_decision_cache),
        "total_cache_entries": len(_domain_cache) + len(_filter_decision_cache),
        "max_cache_entries": MAX_CACHE_ENTRIES
    }

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
    
    logger.debug(f"Filter-Statistik für {site_id}:")
    logger.debug(f"  - Ursprüngliche Links: {total_links}")
    logger.debug(f"  - Verbleibende Links: {filtered_links}")
    logger.debug(f"  - Erfolgsrate: {rate:.1f}%")