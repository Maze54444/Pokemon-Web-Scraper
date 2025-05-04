import requests
import hashlib
import re
import time
import random
import logging
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote_plus
from utils.telegram import send_telegram_message, escape_markdown, send_product_notification, send_batch_notification
from utils.matcher import is_keyword_in_text, extract_product_type_from_text, load_exclusion_sets
from utils.stock import get_status_text, update_product_status
from utils.availability import detect_availability

# Logger-Konfiguration
logger = logging.getLogger(__name__)

def scrape_sapphire_cards(keywords_map, seen, out_of_stock, only_available=False, max_retries=0):
    """
    Spezieller Scraper für sapphire-cards.de mit maximaler Robustheit und Fehlertoleranz
    
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param seen: Set mit bereits gesehenen Produkttiteln
    :param out_of_stock: Set mit ausverkauften Produkten
    :param only_available: Ob nur verfügbare Produkte gemeldet werden sollen
    :param max_retries: Maximale Anzahl von Wiederholungsversuchen (Standard: 0)
    :return: Liste der neuen Treffer
    """
    logger.info("🌐 Starte speziellen Scraper für sapphire-cards.de")
    new_matches = []
    all_products = []  # Liste für alle gefundene Produkte (für sortierte Benachrichtigung)
    
    # Verwende ein Set, um bereits verarbeitete URLs zu speichern und Duplikate zu vermeiden
    processed_urls = set()
    
    # Extrahiere den Produkttyp aus dem ersten Suchbegriff (meistens "display")
    search_product_type = None
    if keywords_map:
        sample_search_term = list(keywords_map.keys())[0]
        search_product_type = extract_product_type_from_text(sample_search_term)
        logger.debug(f"🔍 Suche nach Produkttyp: '{search_product_type}'")
    
    # User-Agent-Rotation zur Vermeidung von Bot-Erkennung
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.4 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0"
    ]
    
    headers = {
        "User-Agent": random.choice(user_agents),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://sapphire-cards.de/",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1"
    }
    
    # Cache für fehlgeschlagene URLs mit Timestamps
    failed_urls_cache = {}
    
    # 1. Versuche zuerst die Hauptseite und Kategorien zu durchsuchen
    logger.info("🔍 Durchsuche Hauptseite und Kategorien...")
    
    # Hauptseite Pokemon-Kategorie
    main_url = "https://sapphire-cards.de/produkt-kategorie/pokemon/"
    
    try:
        response = requests.get(main_url, headers=headers, timeout=15)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Sammle Produkt-Links
            product_links = []
            for link in soup.find_all("a", href=True):
                href = link.get("href", "")
                link_text = link.get_text().lower()
                
                # Nur Produkt-URLs
                if "/produkt/" in href and href not in product_links:
                    # Prüfe ob relevante Keywords im Link-Text
                    is_relevant = False
                    for search_term, tokens in keywords_map.items():
                        if any(token.lower() in link_text for token in tokens):
                            is_relevant = True
                            break
                    
                    if is_relevant:
                        product_links.append(href)
            
            logger.info(f"🔍 {len(product_links)} relevante Produktlinks gefunden")
            
            # Verarbeite gefundene Produkt-Links
            for product_url in product_links:
                if product_url in processed_urls:
                    continue
                    
                processed_urls.add(product_url)
                
                # Einmaliger Versuch ohne Wiederholungen
                product_data = process_product_url(product_url, keywords_map, seen, out_of_stock, only_available, headers, new_matches, max_retries=0)
                
                if product_data and isinstance(product_data, dict):
                    all_products.append(product_data)
            
    except Exception as e:
        logger.error(f"❌ Fehler beim Durchsuchen der Pokemon-Kategorie: {e}")
    
    # 2. Wenn keine Produkte gefunden wurden, verwende die Suche
    if not all_products:
        logger.info("🔍 Keine Produkte auf der Kategorieseite gefunden, verwende die Suche...")
        
        for search_term in keywords_map.keys():
            # Bereinige Suchbegriff
            clean_term = re.sub(r'\s+(display|box|tin|etb)$', '', search_term.lower())
            
            # URL-Encoding für die Suche
            encoded_term = quote_plus(clean_term)
            search_url = f"https://sapphire-cards.de/?s={encoded_term}&post_type=product"
            
            try:
                response = requests.get(search_url, headers=headers, timeout=15)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, "html.parser")
                    
                    # Sammle Produkt-Links aus den Suchergebnissen
                    for link in soup.find_all("a", href=True):
                        href = link.get("href", "")
                        if "/produkt/" in href and href not in processed_urls:
                            processed_urls.add(href)
                            
                            product_data = process_product_url(href, keywords_map, seen, out_of_stock, only_available, headers, new_matches, max_retries=0)
                            
                            if product_data and isinstance(product_data, dict):
                                all_products.append(product_data)
                
            except Exception as e:
                logger.error(f"❌ Fehler bei der Suche nach '{search_term}': {e}")
    
    # Sende Benachrichtigungen
    if all_products:
        from utils.telegram import send_batch_notification
        send_batch_notification(all_products)
    
    return new_matches

def process_product_url(product_url, keywords_map, seen, out_of_stock, only_available, headers, new_matches, max_retries=0):
    """
    Verarbeitet eine einzelne Produkt-URL mit maximaler Fehlertoleranz
    
    :param product_url: URL der Produktseite
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param seen: Set mit bereits gesehenen Produkttiteln
    :param out_of_stock: Set mit ausverkauften Produkten
    :param only_available: Ob nur verfügbare Produkte gemeldet werden sollen
    :param headers: HTTP-Headers für die Anfrage
    :param new_matches: Liste der neuen Treffer
    :param max_retries: Maximale Anzahl an Wiederholungsversuchen (Standard: 0)
    :return: Product data dict if successful, False otherwise
    """
    try:
        logger.info(f"🔍 Prüfe Produktlink: {product_url}")
        
        # Versuche die Seite abzurufen (ohne Wiederholungen)
        try:
            response = requests.get(product_url, headers=headers, timeout=15)
            if response.status_code == 404:
                logger.debug(f"⚠️ Produkt nicht gefunden (404): {product_url}")
                return False
            elif response.status_code != 200:
                logger.warning(f"⚠️ HTTP-Fehler {response.status_code}: {product_url}")
                return False
        except requests.exceptions.RequestException as e:
            logger.debug(f"⚠️ Netzwerkfehler: {e}")
            return False
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Extrahiere Titel
        title_elem = soup.find('h1', class_='product_title') or soup.find('h1')
        if not title_elem:
            return False
            
        title = title_elem.text.strip()
        logger.info(f"📝 Gefundener Produkttitel: '{title}'")
        
        # Prüfe gegen Suchbegriffe
        matched_term = None
        for search_term, tokens in keywords_map.items():
            if is_keyword_in_text(tokens, title, log_level='None'):
                matched_term = search_term
                break
        
        if not matched_term:
            logger.debug(f"❌ Kein passender Suchbegriff für {title}")
            return False
        
        # Verfügbarkeitsprüfung
        is_available, price, status_text = detect_availability(soup, product_url)
        
        # Produkt-ID erstellen
        product_id = create_product_id(product_url, title)
        
        # Status aktualisieren
        should_notify, is_back_in_stock = update_product_status(
            product_id, is_available, seen, out_of_stock
        )
        
        # Bei "nur verfügbare" Option überspringen, wenn nicht verfügbar
        if only_available and not is_available:
            return True  # Erfolgreich verarbeitet aber nicht gemeldet
        
        if should_notify:
            if is_back_in_stock:
                status_text = "🎉 Wieder verfügbar!"
            
            # Produkt-Informationen für die Batch-Benachrichtigung
            product_data = {
                "title": title,
                "url": product_url,
                "price": price,
                "status_text": status_text,
                "is_available": is_available,
                "matched_term": matched_term,
                "product_type": extract_product_type_from_text(title),
                "shop": "sapphire-cards.de"
            }
            
            new_matches.append(product_id)
            logger.info(f"✅ Neuer Treffer bei sapphire-cards.de: {title} - {status_text}")
            
            return product_data
        
        return True  # Erfolgreich, aber keine Benachrichtigung notwendig
    
    except Exception as e:
        logger.error(f"❌ Fehler beim Prüfen des Produkts {product_url}: {e}")
        return False

def create_product_id(product_url, title):
    """Erzeugt eine eindeutige, stabile Produkt-ID"""
    url_hash = hashlib.md5(product_url.encode()).hexdigest()[:10]
    
    # Extrahiere Produkttyp aus dem Titel
    product_type = extract_product_type_from_text(title)
    
    # Normalisiere Titel für einen Identifizierer (entferne produktspezifische Begriffe)
    normalized_title = re.sub(r'\s+(display|box|tin|etb)$', '', title.lower())
    normalized_title = re.sub(r'\s+', '-', normalized_title)
    normalized_title = re.sub(r'[^a-z0-9\-]', '', normalized_title)
    
    return f"sapphirecards_{normalized_title}_{product_type}_{url_hash}"

def try_search_fallback(keywords_map, processed_urls, headers, max_retries=0):
    """
    Verbesserte Fallback-Methode für die Suche nach Produkten mit minimalen Ressourcen
    
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param processed_urls: Set mit bereits verarbeiteten URLs
    :param headers: HTTP-Headers für die Anfrage
    :param max_retries: Maximale Anzahl an Wiederholungsversuchen
    :return: Liste gefundener Produkt-URLs
    """
    search_terms = []
    
    # Erstelle Suchbegriffe basierend auf den übergebenen Keywords
    for search_term in keywords_map.keys():
        # Entferne produktspezifische Begriffe wie "display", "box"
        clean_term = re.sub(r'\s+(display|box|tin|etb)$', '', search_term.lower())
        if clean_term not in search_terms:
            search_terms.append(clean_term)
    
    result_urls = []
    
    for term in search_terms:
        try:
            # URL-Encoding für den Suchbegriff
            encoded_term = quote_plus(term)
            search_url = f"https://sapphire-cards.de/?s={encoded_term}&post_type=product&type_aws=true"
            logger.info(f"🔍 Suche nach: {term}")
            
            response = requests.get(search_url, headers=headers, timeout=15)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")
                
                # Sammle Produkt-Links
                for link in soup.find_all("a", href=True):
                    href = link.get("href", "")
                    if "/produkt/" in href and href not in processed_urls:
                        result_urls.append(href)
        
        except Exception as e:
            logger.error(f"❌ Fehler bei der Fallback-Suche für '{term}': {e}")
    
    return list(set(result_urls))

def create_fallback_product(search_term, product_type):
    """
    Erstellt ein Fallback-Produkt basierend auf dem Suchbegriff und Produkttyp
    """
    # Normalisiere den Suchbegriff für die URL
    normalized_term = re.sub(r'\s+(display|box|tin|etb)$', '', search_term.lower())
    url_term = re.sub(r'\s+', '-', normalized_term)
    
    # Titel basierend auf Suchbegriff und Produkttyp
    title_map = {
        "display": f"Pokemon {normalized_term.title()} Booster Box (Display)",
        "etb": f"Pokemon {normalized_term.title()} Elite Trainer Box",
        "box": f"Pokemon {normalized_term.title()} Box",
        "tin": f"Pokemon {normalized_term.title()} Tin",
        "blister": f"Pokemon {normalized_term.title()} Blister"
    }
    
    # URL basierend auf Suchbegriff und Produkttyp
    url_map = {
        "display": f"https://sapphire-cards.de/produkt/{url_term}-booster-box-display/",
        "etb": f"https://sapphire-cards.de/produkt/{url_term}-elite-trainer-box/",
        "box": f"https://sapphire-cards.de/produkt/{url_term}-box/",
        "tin": f"https://sapphire-cards.de/produkt/{url_term}-tin/",
        "blister": f"https://sapphire-cards.de/produkt/{url_term}-blister/"
    }
    
    # Preis basierend auf Produkttyp
    price_map = {
        "display": "159,99 €",
        "etb": "49,99 €",
        "box": "49,99 €",
        "tin": "24,99 €",
        "blister": "14,99 €"
    }
    
    # Erstelle Fallback-Produkt
    fallback_product = {
        "url": url_map.get(product_type),
        "title": title_map.get(product_type),
        "price": price_map.get(product_type),
        "is_available": True,
        "status_text": "✅ Verfügbar (Fallback)",
        "product_type": product_type,
        "shop": "sapphire-cards.de",
        "matched_term": search_term
    }
    
    return fallback_product

def generate_title_from_url(url):
    """
    Generiert einen Titel basierend auf der URL-Struktur
    """
    try:
        # Extrahiere den letzten Pfadteil der URL
        path_parts = url.rstrip('/').split('/')
        last_part = path_parts[-1]
        
        # Entferne Dateiendung falls vorhanden
        if '.' in last_part:
            last_part = last_part.split('.')[0]
        
        # Ersetze Bindestriche durch Leerzeichen und formatiere
        title = last_part.replace('-', ' ').replace('_', ' ').title()
        
        # Ersetze bekannte Abkürzungen
        title = title.replace(' Etb ', ' Elite Trainer Box ')
        
        # Stelle sicher, dass "Pokemon" im Titel vorkommt
        if 'pokemon' not in title.lower():
            title = 'Pokemon ' + title
        
        return title
    except Exception as e:
        logger.warning(f"Fehler bei der Titelgenerierung aus URL {url}: {e}")
        return "Pokemon Produkt"

def extract_product_type(text):
    """
    Extrahiert den Produkttyp aus einem Text mit besonderen Anpassungen für sapphire-cards.de
    """
    if not text:
        return "unknown"
    
    text = text.lower()
    
    # Display erkennen - häufigste Varianten
    if re.search(r'\bdisplay\b|\b36er\b|\b36\s+booster\b|\bbooster\s+display\b|\bbox\s+display\b', text):
        return "display"
    
    # Booster Box als Display erkennen (sapphire-cards.de spezifisch)
    elif re.search(r'booster\s+box', text) and not re.search(r'elite|etb|trainer', text):
        return "display"
    
    # Elite Trainer Box erkennen
    elif re.search(r'\belite trainer box\b|\betb\b|\btrainer box\b', text):
        return "etb"
    
    # Blister/3-Pack erkennen
    elif re.search(r'\bblister\b|\b3er\b|\b3-pack\b|\b3\s+pack\b', text):
        return "blister"
    
    # Wenn nichts erkannt wurde
    return "unknown"