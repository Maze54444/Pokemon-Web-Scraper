"""
Spezieller Scraper für mighty-cards.de, der die Sitemap verwendet
um Produkte zu finden und zu verarbeiten.
"""

import requests
import logging
import re
import json
import hashlib
import time
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote_plus
from utils.matcher import is_keyword_in_text, extract_product_type_from_text
from utils.stock import update_product_status
from utils.availability import detect_availability

# Logger konfigurieren
logger = logging.getLogger(__name__)

def scrape_mighty_cards(keywords_map, seen, out_of_stock, only_available=False):
    """
    Spezieller Scraper für mighty-cards.de mit Sitemap-Integration
    
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param seen: Set mit bereits gesehenen Produkttiteln
    :param out_of_stock: Set mit ausverkauften Produkten
    :param only_available: Ob nur verfügbare Produkte gemeldet werden sollen
    :return: Liste der neuen Treffer
    """
    logger.info("🌐 Starte speziellen Scraper für mighty-cards.de mit Sitemap-Integration")
    new_matches = []
    all_products = []  # Liste für alle gefundenen Produkte
    
    # Set für Deduplizierung von gefundenen Produkten
    found_product_ids = set()
    
    # Standardheader setzen
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7"
    }
    
    # 1. Zugriff über die Sitemap
    logger.info("🔍 Versuche Produkte über die Sitemap zu finden")
    sitemap_products = fetch_products_from_sitemap(headers)
    
    # Verarbeite Sitemap-Produkte
    for product_url in sitemap_products:
        process_mighty_cards_product(product_url, keywords_map, seen, out_of_stock, only_available, 
                                    headers, all_products, new_matches, found_product_ids)
    
    # 2. Fallback: Direkte Suche nach Produkten
    if len(all_products) < 2:
        logger.info("🔍 Nicht genug Produkte über Sitemap gefunden, versuche direkte Suche")
        for search_term in keywords_map.keys():
            search_products = search_mighty_cards_products(search_term, headers)
            
            # Verarbeite gefundene Produkte
            for product_url in search_products:
                if product_url not in sitemap_products:  # Vermeidet Duplikate
                    process_mighty_cards_product(product_url, keywords_map, seen, out_of_stock, only_available, 
                                               headers, all_products, new_matches, found_product_ids)
    
    # Sende Benachrichtigungen
    if all_products:
        from utils.telegram import send_batch_notification
        send_batch_notification(all_products)
    
    return new_matches

def fetch_products_from_sitemap(headers):
    """
    Extrahiert Produkt-URLs aus der Sitemap von mighty-cards.de
    
    :param headers: HTTP-Headers für die Anfragen
    :return: Liste mit Produkt-URLs
    """
    product_urls = []
    sitemap_url = "https://www.mighty-cards.de/wp-sitemap-ecstore-1.xml"
    
    try:
        logger.info(f"🔍 Lade Sitemap von {sitemap_url}")
        response = requests.get(sitemap_url, headers=headers, timeout=15)
        
        if response.status_code != 200:
            logger.error(f"❌ Fehler beim Abrufen der Sitemap: Status {response.status_code}")
            return product_urls
            
        # Versuche, die XML mit verschiedenen Parsern zu verarbeiten
        try:
            # Versuche zuerst mit lxml-xml Parser
            soup = BeautifulSoup(response.content, "lxml-xml")
        except Exception:
            try:
                # Fallback zu html.parser
                soup = BeautifulSoup(response.content, "html.parser")
                logger.warning("⚠️ Verwende html.parser statt lxml-xml für XML-Parsing")
            except Exception as e:
                logger.error(f"❌ Fehler beim Parsen der Sitemap: {e}")
                return product_urls
        
        # Alle URLs aus der Sitemap extrahieren
        for url_tag in soup.find_all("url"):
            loc_tag = url_tag.find("loc")
            if loc_tag and loc_tag.text:
                url = loc_tag.text.strip()
                # Nur Shop-URLs hinzufügen
                if "/shop/" in url:
                    product_urls.append(url)
        
        logger.info(f"🔍 {len(product_urls)} Produkt-URLs aus Sitemap extrahiert")
        
    except Exception as e:
        logger.error(f"❌ Fehler beim Laden der Sitemap: {e}")
    
    return product_urls

def search_mighty_cards_products(search_term, headers):
    """
    Sucht Produkte mit dem gegebenen Suchbegriff auf mighty-cards.de
    
    :param search_term: Suchbegriff
    :param headers: HTTP-Headers für die Anfragen
    :return: Liste mit gefundenen Produkt-URLs
    """
    product_urls = []
    
    try:
        # URL-Encoding für den Suchbegriff
        encoded_term = quote_plus(search_term)
        search_url = f"https://www.mighty-cards.de/shop/search?keyword={encoded_term}&limit=20"
        
        logger.info(f"🔍 Suche nach Produkten mit Begriff: {search_term}")
        response = requests.get(search_url, headers=headers, timeout=15)
        
        if response.status_code != 200:
            logger.warning(f"⚠️ Fehler bei der Suche nach {search_term}: Status {response.status_code}")
            return product_urls
            
        soup = BeautifulSoup(response.content, "html.parser")
        
        # Suche nach Produktlinks
        for link in soup.find_all("a", href=True):
            href = link.get('href', '')
            if '/shop/' in href and 'p' in href.split('/')[-1]:
                # Vollständige URL erstellen
                product_url = href if href.startswith('http') else urljoin("https://www.mighty-cards.de", href)
                if product_url not in product_urls:
                    product_urls.append(product_url)
        
        logger.info(f"🔍 {len(product_urls)} Produkte gefunden für Suchbegriff '{search_term}'")
        
    except Exception as e:
        logger.warning(f"⚠️ Fehler bei der Suche nach {search_term}: {e}")
    
    return product_urls

def process_mighty_cards_product(product_url, keywords_map, seen, out_of_stock, only_available, 
                               headers, all_products, new_matches, found_product_ids):
    """
    Verarbeitet ein einzelnes Produkt von mighty-cards.de
    
    :param product_url: URL des Produkts
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param seen: Set mit bereits gesehenen Produkten
    :param out_of_stock: Set mit ausverkauften Produkten
    :param only_available: Ob nur verfügbare Produkte angezeigt werden sollen
    :param headers: HTTP-Headers für die Anfragen
    :param all_products: Liste für gefundene Produkte (wird aktualisiert)
    :param new_matches: Liste für neue Treffer (wird aktualisiert)
    :param found_product_ids: Set für Deduplizierung (wird aktualisiert)
    :return: True bei Erfolg, False bei Fehler
    """
    try:
        logger.debug(f"🔍 Verarbeite Produkt: {product_url}")
        
        # Produkt-Detailseite abrufen
        try:
            response = requests.get(product_url, headers=headers, timeout=15)
            if response.status_code != 200:
                logger.warning(f"⚠️ Fehler beim Abrufen von {product_url}: Status {response.status_code}")
                return False
        except requests.exceptions.RequestException as e:
            logger.warning(f"⚠️ Fehler beim Abrufen von {product_url}: {e}")
            return False
        
        soup = BeautifulSoup(response.content, "html.parser")
        
        # Titel extrahieren
        title_elem = soup.find('h1', {'class': 'product-details__product-title'})
        if not title_elem:
            title_elem = soup.find('h1')
        
        if not title_elem:
            # Wenn kein Titel gefunden wird, versuche aus URL zu generieren
            title = extract_title_from_url(product_url)
            logger.debug(f"⚠️ Kein Titel für {product_url} gefunden, generiere aus URL: {title}")
        else:
            title = title_elem.text.strip()
        
        # Produkttyp aus dem Titel extrahieren
        product_type = extract_product_type_from_text(title)
        
        # Prüfe, ob der Titel einem der Suchbegriffe entspricht
        matched_term = None
        for search_term, tokens in keywords_map.items():
            search_term_type = extract_product_type_from_text(search_term)
            
            # Bei Display-Suche: Nur Displays berücksichtigen
            if search_term_type == "display" and product_type != "display":
                continue
                
            if is_keyword_in_text(tokens, title, log_level='None'):
                matched_term = search_term
                break
        
        if not matched_term:
            logger.debug(f"❌ Produkt passt nicht zu Suchbegriffen: {title}")
            return False
        
        # Verwende das Availability-Modul für Verfügbarkeitserkennnung
        is_available, price, status_text = detect_availability(soup, product_url)
        
        # Eindeutige ID für das Produkt erstellen
        product_id = create_product_id(title)
        
        # Deduplizierung
        if product_id in found_product_ids:
            return False
        
        # Status aktualisieren
        should_notify, is_back_in_stock = update_product_status(
            product_id, is_available, seen, out_of_stock
        )
        
        # Bei "nur verfügbare" Option, nicht verfügbare Produkte überspringen
        if only_available and not is_available:
            return False
        
        if should_notify:
            # Status anpassen wenn wieder verfügbar
            if is_back_in_stock:
                status_text = "🎉 Wieder verfügbar!"
            
            # Produkt-Daten sammeln
            product_data = {
                "title": title,
                "url": product_url,
                "price": price,
                "status_text": status_text,
                "is_available": is_available,
                "matched_term": matched_term,
                "product_type": product_type,
                "shop": "mighty-cards.de"
            }
            
            all_products.append(product_data)
            new_matches.append(product_id)
            found_product_ids.add(product_id)
            logger.info(f"✅ Neuer Treffer gefunden: {title} - {status_text}")
            return True
    
    except Exception as e:
        logger.error(f"❌ Fehler bei der Verarbeitung von {product_url}: {e}")
    
    return False

def extract_title_from_url(url):
    """
    Extrahiert einen Titel aus der URL-Struktur
    
    :param url: URL der Produktseite
    :return: Extrahierter Titel
    """
    try:
        # Extrahiere den letzten Teil des Pfads
        path_parts = url.rstrip('/').split('/')
        last_part = path_parts[-1]
        
        # Entferne produktID am Ende (zB -p12345)
        last_part = re.sub(r'-p\d+$', '', last_part)
        
        # Ersetze Bindestriche durch Leerzeichen und formatiere
        title = last_part.replace('-', ' ').title()
        
        # Stelle sicher, dass "Pokemon" im Titel vorkommt
        if "pokemon" not in title.lower():
            title = "Pokemon " + title
        
        return title
    except Exception as e:
        return "Pokemon Produkt"

def create_product_id(title, base_id="mightycards"):
    """
    Erstellt eine eindeutige Produkt-ID basierend auf dem Titel
    
    :param title: Produkttitel
    :param base_id: Basis-ID (Website-Name)
    :return: Eindeutige Produkt-ID
    """
    # Extrahiere relevante Informationen für die ID
    title_lower = title.lower()
    
    # Sprache (DE/EN)
    if "deutsch" in title_lower:
        language = "DE"
    elif "english" in title_lower or "eng" in title_lower:
        language = "EN"
    else:
        language = "UNK"
    
    # Produkttyp
    product_type = extract_product_type_from_text(title)
    
    # Normalisiere Titel für einen Identifizierer
    normalized_title = re.sub(r'\s+(display|box|tin|etb)$', '', title_lower)
    normalized_title = re.sub(r'\s+', '-', normalized_title)
    normalized_title = re.sub(r'[^a-z0-9\-]', '', normalized_title)
    
    # Erstelle eine strukturierte ID
    product_id = f"{base_id}_{normalized_title}_{product_type}_{language}"
    
    # Zusatzinformationen
    if "18er" in title_lower:
        product_id += "_18er"
    elif "36er" in title_lower:
        product_id += "_36er"
    
    return product_id