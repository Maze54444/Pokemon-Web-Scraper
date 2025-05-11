"""
Spezieller Scraper für mighty-cards.de, der die Sitemap verwendet
um Produkte zu finden und zu verarbeiten.
Optimiert mit Multithreading und Selenium-Integration für dynamische Inhalte.
"""

import requests
import logging
import re
import json
import hashlib
import time
import concurrent.futures
import os
import random
from threading import Lock, Thread, Semaphore
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote_plus
from pathlib import Path
from utils.matcher import is_keyword_in_text, extract_product_type_from_text, clean_text
from utils.stock import update_product_status
from utils.availability import detect_availability

# Selenium-Imports
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException

# Logger konfigurieren
logger = logging.getLogger(__name__)

# Blacklist für Produkttitel und URLs, die nicht relevant sind
PRODUCT_BLACKLIST = [
    # Trading Card Games
    "yu-gi-oh", "yugioh", "yu gi oh", "yu-gi", 
    "union arena", "flesh and blood", "star wars", "disney lorcana", "lorcana",
    "magic the gathering", "mtg", "digimon", "one piece", "dragon ball",
    "final fantasy", "star wars unlimited", "trading card game",
    "jcc", "jumpstart", "grundstein", "himmelsleuchten", "captain",
    "metazoo", "dbscg", "weiss schwarz", "weiss", "schwarz",
    
    # Spezifische Sets/Namen anderer TCGs
    "op01", "op02", "op03", "op04", "op05", "op06", "op07", "op08", "op09", "op10",
    "bt01", "bt02", "bt03", "bt04", "bt05", "bt06", "bt07", "bt08", "bt09", "bt10",
    "ex01", "ex02", "ex03", "b01", "b02", "b03", "b04", "b05", "b06", "b07", "b08",
    "b09", "b10", "b11", "b12", "b13", "b14", "b15", "b16", "b17", "b18", "b19", "b20",
    "rb01", "eb01", "prb01", "jumpstart", "altered", "vicious", "dawn of", "royal blood",
    "romance dawn", "paramount war", "pillars of strength", "kingdom of intrigue", 
    "awakening of", "wings of", "two legends", "500 years", "memorial collection",
    "premium the best", "ursulas", "das erste kapitel", "draconic roar", "rising wind",
    "classic collection", "power absorbed", "fighters ambition", "malicious", "colossal",
    "ultimate advent", "battle evolution", "supreme rivalry", "vermilion", "ultimate squad",
    "rise of", "beyond generations", "trial by frost", "beyond the gates"
]

# Produkt-Typ Mapping (verschiedene Schreibweisen für die gleichen Produkttypen)
PRODUCT_TYPE_VARIANTS = {
    "display": [
        "display", "36er display", "36-er display", "36 booster", "36er booster",
        "booster display", "booster box", "36er box", "box", "booster-box", "18er display",
        "18er booster", "18-er display"
    ],
    "etb": [
        "etb", "elite trainer box", "elite-trainer-box", "elite trainer", "trainer box"
    ],
    "ttb": [
        "ttb", "top trainer box", "top-trainer-box", "top trainer", "trainer box"
    ],
    "blister": [
        "blister", "3pack", "3-pack", "3er pack", "3er blister", "sleeved booster",
        "sleeve booster", "check lane", "checklane"
    ]
}

# Umlaut-Mapping für die URL-Suche
UMLAUT_MAPPING = {
    'ä': 'a',
    'ö': 'o',
    'ü': 'u',
    'ß': 'ss',
    'Ä': 'A',
    'Ö': 'O',
    'Ü': 'U'
}

# Locks für Thread-sichere Operationen
url_lock = Lock()
data_lock = Lock()
cache_lock = Lock()

# Cache-Datei
CACHE_FILE = "data/mighty_cards_cache.json"

# Selenium-Browser-Pool-Konfiguration
BROWSER_POOL_SIZE = 3  # Anzahl gleichzeitig offener Browser
browser_pool = []
browser_semaphore = Semaphore(BROWSER_POOL_SIZE)
browser_pool_lock = Lock()

# Selenium-Konfiguration
SELENIUM_TIMEOUT = 10  # Timeout in Sekunden
HEADLESS = True  # Browser im Hintergrund ausführen
MAX_BROWSER_REUSE = 10  # Maximale Anzahl Wiederverwendungen pro Browser-Instanz

def setup_browser():
    """
    Erstellt und konfiguriert eine neue Selenium-WebDriver-Instanz
    
    :return: WebDriver-Instanz
    """
    options = Options()
    if HEADLESS:
        options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-extensions")
    
    # Wichtig für Bot-Detektion-Vermeidung
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    
    # Zufälligen User-Agent verwenden
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.4 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.45 Safari/537.36"
    ]
    options.add_argument(f"--user-agent={random.choice(user_agents)}")
    
    try:
        driver = webdriver.Chrome(options=options)
        
        # Webdriver-Erkennungs-Bypass
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        # Timeout für alle Operationen setzen
        driver.set_page_load_timeout(SELENIUM_TIMEOUT)
        driver.implicitly_wait(SELENIUM_TIMEOUT)
        
        return driver
    except Exception as e:
        logger.error(f"❌ Fehler beim Erstellen des WebDrivers: {e}")
        return None

def get_browser():
    """
    Holt einen Browser aus dem Pool oder erstellt einen neuen
    
    :return: WebDriver-Instanz
    """
    browser_semaphore.acquire()
    
    with browser_pool_lock:
        if browser_pool:
            browser, usage_count = browser_pool.pop(0)
            if usage_count >= MAX_BROWSER_REUSE:
                # Browser wurde zu oft verwendet, schließen und neu erstellen
                try:
                    browser.quit()
                except:
                    pass
                browser = setup_browser()
                usage_count = 0
            return browser, usage_count
    
    # Kein Browser im Pool, neuen erstellen
    return setup_browser(), 0

def release_browser(browser, usage_count):
    """
    Gibt einen Browser zurück in den Pool
    
    :param browser: WebDriver-Instanz
    :param usage_count: Anzahl der bisherigen Verwendungen
    """
    with browser_pool_lock:
        if browser is not None:
            browser_pool.append((browser, usage_count + 1))
    
    browser_semaphore.release()

def cleanup_browsers():
    """
    Schließt alle Browser im Pool
    """
    with browser_pool_lock:
        for browser, _ in browser_pool:
            try:
                browser.quit()
            except:
                pass
        browser_pool.clear()

def load_cache():
    """Lädt den Cache mit gefundenen Produkten"""
    try:
        # Stelle sicher, dass das Verzeichnis existiert
        Path(CACHE_FILE).parent.mkdir(parents=True, exist_ok=True)
        
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"products": {}, "last_update": int(time.time())}
    except Exception as e:
        logger.error(f"❌ Fehler beim Laden des Caches: {e}")
        return {"products": {}, "last_update": int(time.time())}

def save_cache(cache_data):
    """Speichert den Cache mit gefundenen Produkten"""
    try:
        # Stelle sicher, dass das Verzeichnis existiert
        Path(CACHE_FILE).parent.mkdir(parents=True, exist_ok=True)
        
        with cache_lock:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"❌ Fehler beim Speichern des Caches: {e}")
        return False

def check_product_availability_selenium(url):
    """
    Prüft die Verfügbarkeit eines Produkts mit Selenium, um dynamische Inhalte zu laden
    
    :param url: URL der Produktseite
    :return: Tuple (is_available, price, status_text, title)
    """
    browser, usage_count = None, 0
    title = "Unbekanntes Produkt"
    
    try:
        browser, usage_count = get_browser()
        if browser is None:
            logger.error("❌ Konnte keinen WebDriver erstellen")
            return False, "Preis nicht verfügbar", "[X] Fehler bei der Verfügbarkeitsprüfung", title
        
        # Lade Seite
        browser.get(url)
        
        # Warte kurz, um JavaScript-Ausführung zu ermöglichen
        time.sleep(2)
        
        # Extrahiere Titel
        try:
            title_elem = WebDriverWait(browser, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'h1.product-details__product-title, h1'))
            )
            title = title_elem.text.strip()
        except (TimeoutException, NoSuchElementException):
            logger.debug(f"⚠️ Konnte Titel für {url} nicht finden")
            title = extract_title_from_url(url)
        
        # 1. Prüfe auf "Ausverkauft"-Text
        try:
            sold_out_elements = browser.find_elements(By.XPATH, "//*[contains(text(), 'Ausverkauft')]")
            if sold_out_elements:
                return False, extract_price_selenium(browser), "[X] Ausverkauft (Text gefunden)", title
        except:
            pass
        
        # 2. Prüfe auf "In den Warenkorb"-Button
        try:
            cart_button = browser.find_elements(By.XPATH, "//button[contains(., 'In den Warenkorb')]")
            if cart_button:
                # Prüfe, ob der Button aktiv ist
                is_disabled = 'disabled' in cart_button[0].get_attribute('class') or cart_button[0].get_attribute('disabled')
                if not is_disabled:
                    return True, extract_price_selenium(browser), "[V] Verfügbar (Warenkorb-Button aktiv)", title
        except:
            pass
        
        # 3. Prüfe Verfügbarkeitstext
        try:
            delivery_text = browser.find_element(By.CSS_SELECTOR, '.product-detail--delivery .delivery--text').text
            if "nicht verfügbar" in delivery_text.lower() or "ausverkauft" in delivery_text.lower():
                return False, extract_price_selenium(browser), f"[X] Ausverkauft ({delivery_text})", title
            elif "verfügbar" in delivery_text.lower() or "lieferbar" in delivery_text.lower():
                return True, extract_price_selenium(browser), f"[V] Verfügbar ({delivery_text})", title
        except:
            pass
        
        # 4. Wenn JavaScript-Variablen zugänglich sind, direkt aus dem Shopware-Datenlayer extrahieren
        try:
            is_available = browser.execute_script("return document.querySelector('meta[itemprop=\"availability\"]').content.includes('InStock')")
            if is_available is not None:
                return is_available, extract_price_selenium(browser), "[V] Verfügbar (JSON-LD: InStock)" if is_available else "[X] Ausverkauft (OutOfStock)", title
        except:
            pass
        
        # 5. Fallback: Page Source nach relevanten Texten durchsuchen
        page_text = browser.page_source.lower()
        if "ausverkauft" in page_text:
            return False, extract_price_selenium(browser), "[X] Ausverkauft (Text in Seite)", title
        elif "in den warenkorb" in page_text:
            return True, extract_price_selenium(browser), "[V] Wahrscheinlich verfügbar (Warenkorb-Text)", title
        
        # Wenn keine klare Entscheidung getroffen werden kann
        return False, extract_price_selenium(browser), "[?] Status unbekannt, als nicht verfügbar interpretiert", title
    
    except WebDriverException as e:
        logger.error(f"❌ Selenium-Fehler bei {url}: {e}")
        return False, "Preis nicht verfügbar", "[X] Fehler bei der Verfügbarkeitsprüfung", title
    except Exception as e:
        logger.error(f"❌ Unerwarteter Fehler bei {url}: {e}")
        return False, "Preis nicht verfügbar", "[X] Fehler bei der Verfügbarkeitsprüfung", title
    finally:
        if browser is not None:
            release_browser(browser, usage_count)

def extract_price_selenium(browser):
    """
    Extrahiert den Preis mit verschiedenen Selektoren aus der Produktseite
    
    :param browser: WebDriver-Instanz
    :return: Preis als String
    """
    # Prioritätsreihenfolge der Selektoren
    price_selectors = [
        '.details-product-price__value',
        '.product-details__product-price',
        '.product-detail--price .price--content',
        '.price',
        '.product-price',
        '.current-price',
        '[itemprop="price"]'
    ]
    
    for selector in price_selectors:
        try:
            price_elem = browser.find_element(By.CSS_SELECTOR, selector)
            price_text = price_elem.text.strip()
            if price_text:
                # Bereinige den Preis
                price_text = re.sub(r'\s+', ' ', price_text)
                return price_text
        except:
            continue
    
    # Versuche es über JavaScript
    try:
        price = browser.execute_script("return document.querySelector('meta[itemprop=\"price\"]').content")
        if price:
            return f"{price}€"
    except:
        pass
    
    # Wenn kein Preis gefunden wurde, mit Regex im Seiteninhalt suchen
    try:
        page_text = browser.page_source
        price_pattern = r'(\d+[,.]\d+)\s*[€$£]'
        price_match = re.search(price_pattern, page_text)
        if price_match:
            return f"{price_match.group(1)}€"
    except:
        pass
    
    # Fallback-Standardpreis basierend auf Titel-Produkttyp
    try:
        title = browser.find_element(By.CSS_SELECTOR, 'h1.product-details__product-title, h1').text
        product_type = extract_product_type_from_text(title)
        standard_prices = {
            "display": "159,99 €",
            "etb": "49,99 €",
            "box": "49,99 €",
            "tin": "24,99 €",
            "blister": "14,99 €"
        }
        return standard_prices.get(product_type, "Preis nicht verfügbar")
    except:
        pass
    
    return "Preis nicht verfügbar"

def scrape_mighty_cards(keywords_map, seen, out_of_stock, only_available=False):
    """
    Spezieller Scraper für mighty-cards.de mit Sitemap-Integration, Multithreading
    und Selenium für dynamische Inhalte
    
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param seen: Set mit bereits gesehenen Produkttiteln
    :param out_of_stock: Set mit ausverkauften Produkten
    :param only_available: Ob nur verfügbare Produkte gemeldet werden sollen
    :return: Liste der neuen Treffer
    """
    start_time = time.time()
    logger.info("🌐 Starte speziellen Scraper für mighty-cards.de mit Sitemap-Integration und Selenium")
    
    try:
        # Thread-sichere Kollektionen
        new_matches = []
        all_products = []  # Liste für alle gefundenen Produkte
        found_product_ids = set()  # Set für Deduplizierung von gefundenen Produkten
        
        # Sammle Produkt-Information aus keywords_map
        product_info = extract_product_name_type_info(keywords_map)
        logger.info(f"🔍 {len(product_info)} Produktkombinationen aus Keywords extrahiert")
        
        # Optimierte/reduzierte Liste von Suchbegriffen
        search_terms = get_optimized_search_terms(product_info)
        logger.info(f"🔍 Verwende {len(search_terms)} optimierte Suchbegriffe")
        
        # Versuche zuerst vorbereitete Produkt-URLs
        product_list = load_cached_product_urls()
        if not product_list:
            # Wenn kein Cache, versuche mit optimierten URLs
            logger.info("🔄 Kein Produkt-Cache gefunden, verwende Kategorie-Navigation")
            product_list = fetch_products_from_categories()
        
        logger.info(f"🔍 {len(product_list)} bekannte Produkt-URLs zum Scannen")
        
        # Falls keine relevanten Produkte direkt gefunden wurden
        if len(product_list) < 2:
            logger.info("🔍 Nicht genug URLs gefunden, führe direktere Suche durch")
            sitemap_products = fetch_filtered_products_from_sitemap_with_retry(get_default_headers(), product_info)
            if sitemap_products:
                for url in sitemap_products:
                    if url not in [p['url'] for p in product_list]:
                        product_list.append({'url': url, 'title': ''})
        
        # Zufällige Reihenfolge und erhöhte Pausen, um Bot-Erkennung zu reduzieren
        random.shuffle(product_list)
        
        # Bestimme optimale Worker-Anzahl basierend auf Browser-Pool-Größe
        max_workers = min(BROWSER_POOL_SIZE, len(product_list))
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            
            for product_data in product_list:
                url = product_data.get('url')
                if not url:
                    continue
                
                future = executor.submit(
                    process_mighty_cards_product_selenium,
                    url, product_info, seen, out_of_stock, only_available,
                    all_products, new_matches, found_product_ids
                )
                futures.append((future, url))
            
            # Sammle die Ergebnisse ein
            completed = 0
            total = len(futures)
            
            for future, url in futures:
                completed += 1
                
                # Gib alle 10% einen Fortschrittsindikator aus
                if completed % max(1, total // 10) == 0 or completed == total:
                    percent = (completed / total) * 100
                    logger.info(f"⏳ Fortschritt: {completed}/{total} URLs verarbeitet ({percent:.1f}%)")
                
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"❌ Fehler bei der Verarbeitung von {url}: {e}")
        
        # Sende Benachrichtigungen für gefundene Produkte
        if all_products:
            send_batch_notifications(all_products)
        
        # Messung der Gesamtlaufzeit
        elapsed_time = time.time() - start_time
        logger.info(f"✅ Scraping abgeschlossen in {elapsed_time:.2f} Sekunden, {len(new_matches)} neue Treffer gefunden")
        
        return new_matches
    
    finally:
        # Stellen sicher, dass alle Browser geschlossen werden
        cleanup_browsers()

def send_batch_notifications(all_products):
    """Sendet Benachrichtigungen in Batches"""
    from utils.telegram import send_batch_notification
    
    # Gruppiere Produkte in kleinere Batches (max. 20 pro Batch)
    batch_size = 20
    product_batches = [all_products[i:i+batch_size] for i in range(0, len(all_products), batch_size)]
    
    for i, batch in enumerate(product_batches):
        logger.info(f"📤 Sende Batch {i+1}/{len(product_batches)} mit {len(batch)} Produkten")
        send_batch_notification(batch)
        # Kurze Pause zwischen Batches
        if i < len(product_batches) - 1:
            time.sleep(1)

def process_mighty_cards_product_selenium(url, product_info, seen, out_of_stock, only_available, 
                                        all_products, new_matches, found_product_ids, cached_products=None):
    """
    Verarbeitet ein einzelnes Produkt von mighty-cards.de mit Selenium
    
    :param url: URL des Produkts
    :param product_info: Liste mit extrahierten Produktinformationen
    :param seen: Set mit bereits gesehenen Produkten
    :param out_of_stock: Set mit ausverkauften Produkten
    :param only_available: Ob nur verfügbare Produkte angezeigt werden sollen
    :param all_products: Liste für gefundene Produkte (wird aktualisiert)
    :param new_matches: Liste für neue Treffer (wird aktualisiert)
    :param found_product_ids: Set für Deduplizierung (wird aktualisiert)
    :param cached_products: Optional - Cache-Dictionary für gefundene Produkte
    :return: True bei Erfolg, False bei Fehler
    """
    try:
        # DEBUG: Zeige URL für Debugging-Zwecke
        logger.debug(f"Prüfe URL: {url}")
        
        # Extra URL-Validierung mit strengeren Bedingungen
        url_lower = url.lower()
        
        # 1. Prüfe, ob die URL schon verarbeitet wurde (Thread-sicher)
        with url_lock:
            if any(product_url in pid for pid in found_product_ids):
                return False
        
        # 2. Muss "pokemon" als relevanten Kontext haben
        if "pokemon" not in url_lower:
            return False
            
        # 3. Darf keine Blacklist-Begriffe enthalten
        if contains_blacklist_terms(url_lower):
            return False
        
        # Verwende Selenium für dynamisch geladene Inhalte
        is_available, price, status_text, title = check_product_availability_selenium(url)
        
        # URL-Segmente für zuverlässigere Erkennung aufteilen
        url_segments = url.split('/')
        url_filename = url_segments[-1].lower() if url_segments else ""
        
        # Produktcode aus URL extrahieren (z.B. KP09, SV09)
        url_code_match = re.search(r'(kp\d+|sv\d+)', url_filename, re.IGNORECASE)
        url_product_code = url_code_match.group(0).lower() if url_code_match else None
        
        # Produkttyp aus dem Titel extrahieren
        detected_product_type = extract_product_type_from_text(title)
        
        # Bereinigter Titel für besseres Matching (ohne Sonderzeichen)
        clean_title_lower = clean_text(title).lower()
        
        # 3. Verbesserte URL-basierte Prüfung: Wenn KP09/SV09 in der URL ist, direkt annehmen
        direct_url_match = False
        matched_product = None
        matching_score = 0
        
        # Spezialfall: URL enthält KP09/SV09 und Display/Booster - sofort akzeptieren
        if url_product_code and any(term in url_filename for term in ["display", "booster", "36er", "18er"]):
            logger.debug(f"✅ Direkter Treffer in URL: {url_product_code} + Display/Booster")
            
            # Finde das passende Produkt aus unserer Liste
            for product in product_info:
                if product["product_code"] and product["product_code"].lower() == url_product_code:
                    matched_product = product
                    matching_score = 15  # Sehr hoher Score für direkten Code-Match
                    direct_url_match = True
                    break
                    
                # Prüfe auf Produktnamen-Match in URL
                for name_variant in product["name_variants"]:
                    # Sowohl mit als auch ohne Umlaute prüfen
                    name_match = name_variant and name_variant.lower() in url_filename
                    umlaut_match = name_variant and replace_umlauts(name_variant).lower() in url_filename
                    
                    if name_match or umlaut_match:
                        # Auch auf Produkttyp in URL prüfen
                        for type_variant in product["type_variants"]:
                            if type_variant and type_variant.lower() in url_filename:
                                matched_product = product
                                matching_score = 12  # Hoher Score für Name+Typ in URL
                                direct_url_match = True
                                break
                        
                        if direct_url_match:
                            break
            
        # Wenn kein direkter URL-Match, dann Titel-basierte Prüfung
        if not direct_url_match:
            for product in product_info:
                current_score = 0
                name_match = False
                type_match = False
                
                # 3.1 Prüfe Produktcode-Match (höchste Priorität)
                if product["product_code"] and product["product_code"].lower() in clean_title_lower:
                    current_score += 10
                    name_match = True  # Wenn Produktcode stimmt, gilt der Name als übereinstimmend
                
                # 3.2 Prüfe Produktnamen-Match in verschiedenen Varianten
                if not name_match:
                    for name_variant in product["name_variants"]:
                        if name_variant and name_variant.lower() in clean_title_lower:
                            name_match = True
                            current_score += 5
                            break
                
                # Wenn kein Name-Match, keine weitere Prüfung
                if not name_match:
                    continue
                    
                # 3.3 Prüfe Produkttyp-Match in verschiedenen Varianten
                for type_variant in product["type_variants"]:
                    # Prüfe, ob der Variantentyp im Titel vorkommt
                    if type_variant and type_variant.lower() in clean_title_lower:
                        type_match = True
                        current_score += 5
                        break
                    
                # Alternative: Prüfe, ob der erkannte Produkttyp mit dem gesuchten übereinstimmt
                if not type_match and product["product_type"] == detected_product_type:
                    type_match = True
                    current_score += 3
                
                # VERBESSERT: Striktere Typprüfung - wenn gesuchter Typ und erkannter Typ bekannt
                # sind und nicht übereinstimmen, reduziere den Score
                if product["product_type"] != "unknown" and detected_product_type != "unknown":
                    if product["product_type"] != detected_product_type:
                        # Bei Display besonders streng sein
                        if product["product_type"] == "display" and detected_product_type != "display":
                            current_score -= 20  # Stark reduzieren, wenn wir Display suchen aber etwas anderes finden
                        else:
                            current_score -= 5  # Weniger stark reduzieren für andere Typen
                
                # 3.4 Wähle das Produkt mit dem höchsten Score
                if current_score > matching_score:
                    matched_product = product
                    matching_score = current_score
        
        # Wenn kein passendes Produkt gefunden oder Score zu niedrig
        # (Ein Match braucht mindestens einen Namen-Match -> mind. Score 5)
        if not matched_product or matching_score < 5:
            # Eine letzte Chance: Wenn wir eine KP09/SV09 URL haben, nehmen wir das Produkt mit diesem Code
            if url_product_code:
                for product in product_info:
                    if product["product_code"] and product["product_code"].lower() == url_product_code:
                        matched_product = product
                        matching_score = 10  # Hoher Score für Code-Match in URL
                        logger.info(f"🔍 KP09/SV09-basierter Treffer: {url_product_code} -> {product['original_term']}")
                        break
            
            # Wenn immer noch kein Match, dann ablehnen
            if not matched_product or matching_score < 5:
                logger.debug(f"❌ Produkt passt nicht zu Suchbegriffen (Score {matching_score}): {title}")
                return False
        
        # VERBESSERT: Bei Blister/ETB Produkten, wenn wir eigentlich Display suchen, ablehnen
        if matched_product["product_type"] == "display" and detected_product_type != "unknown" and detected_product_type != "display":
            logger.debug(f"❌ Produkttyp stimmt nicht überein: Gesucht '{matched_product['product_type']}', gefunden '{detected_product_type}': {title}")
            return False
        
        # Eindeutige ID für das Produkt erstellen
        product_id = create_product_id(title)
        
        # Thread-sichere Prüfung auf Duplikate
        with url_lock:
            if product_id in found_product_ids:
                return False
        
        # Status aktualisieren
        should_notify, is_back_in_stock = update_product_status(
            product_id, is_available, seen, out_of_stock
        )
        
        # Bei "nur verfügbare" Option, nicht verfügbare Produkte überspringen
        if only_available and not is_available:
            # Allerdings zum Cache hinzufügen, wenn möglich
            if cached_products is not None:
                with cache_lock:
                    cached_products[product_id] = {
                        "product_id": product_id,
                        "title": title,
                        "url": url,
                        "search_term": matched_product["original_term"],
                        "is_available": is_available,
                        "price": price,
                        "last_checked": int(time.time())
                    }
            return False
        
        if should_notify:
            # Status anpassen wenn wieder verfügbar
            if is_back_in_stock:
                status_text = "🎉 Wieder verfügbar!"
            
            # Produkt-Daten sammeln
            product_data = {
                "title": title,
                "url": url,
                "price": price,
                "status_text": status_text,
                "is_available": is_available,
                "matched_term": matched_product["original_term"],
                "product_type": detected_product_type,
                "shop": "mighty-cards.de"
            }
            
            # Thread-sicher zu Ergebnissen hinzufügen
            with data_lock:
                all_products.append(product_data)
                new_matches.append(product_id)
                found_product_ids.add(product_id)
                
            logger.info(f"✅ Neuer Treffer gefunden: {title} - {status_text}")
            
            # Zum Cache hinzufügen, wenn möglich
            if cached_products is not None:
                with cache_lock:
                    cached_products[product_id] = {
                        "product_id": product_id,
                        "title": title,
                        "url": url,
                        "search_term": matched_product["original_term"],
                        "is_available": is_available,
                        "price": price,
                        "last_checked": int(time.time())
                    }
            
            return True
    
    except Exception as e:
        logger.error(f"❌ Fehler bei der Verarbeitung von {url}: {e}")
    
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
        
        # Stelle sicher, dass "Pokemon" im Titel vorkommt (am Ende, wie typisch für mighty-cards)
        if "pokemon" not in title.lower():
            title = title + " Pokemon"
        
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
    
    # Produktcode (sv09, kp09, etc.)
    code_match = re.search(r'(kp\d+|sv\d+)', title_lower)
    product_code = code_match.group(0) if code_match else "unknown"
    
    # Normalisiere Titel für einen Identifizierer
    normalized_title = re.sub(r'\s+(display|box|tin|etb)$', '', title_lower)
    normalized_title = re.sub(r'\s+', '-', normalized_title)
    normalized_title = re.sub(r'[^a-z0-9\-]', '', normalized_title)
    
    # Begrenze die Länge
    if len(normalized_title) > 50:
        normalized_title = normalized_title[:50]
    
    # Erstelle eine strukturierte ID
    product_id = f"{base_id}_{product_code}_{product_type}_{language}_{normalized_title}"
    
    # Zusatzinformationen
    if "18er" in title_lower:
        product_id += "_18er"
    elif "36er" in title_lower:
        product_id += "_36er"
    
    return product_id

def contains_blacklist_terms(text):
    """
    Prüft, ob der Text Blacklist-Begriffe enthält
    
    :param text: Zu prüfender Text
    :return: True wenn Blacklist-Begriff gefunden, False sonst
    """
    for term in PRODUCT_BLACKLIST:
        if term in text:
            return True
    return False

def replace_umlauts(text):
    """
    Ersetzt deutsche Umlaute durch ihre ASCII-Entsprechungen
    
    :param text: Text mit möglichen Umlauten
    :return: Text mit ersetzten Umlauten
    """
    if not text:
        return ""
        
    result = text
    for umlaut, replacement in UMLAUT_MAPPING.items():
        result = result.replace(umlaut, replacement)
    return result

def extract_product_name_type_info(keywords_map):
    """
    Extrahiert detaillierte Produkt-Informationen aus dem Keywords-Map.
    Trennt Produktnamen von Produkttypen und erstellt Varianten für verschiedene Schreibweisen.
    
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :return: Liste von Produktinformationen mit Name- und Typ-Varianten
    """
    product_info = []
    
    for search_term in keywords_map.keys():
        search_term_lower = search_term.lower()
        
        # 1. Extrahiere den Produkttyp
        product_type = extract_product_type_from_text(search_term_lower)
        
        # 2. Extrahiere den Produktnamen (ohne Produkttyp)
        product_name = re.sub(r'\s+(display|box|tin|etb|ttb|booster|36er)$', '', search_term_lower).strip()
        
        # 3. Extrahiere Produktcode (kp09, sv09, etc.) falls vorhanden
        product_code = None
        code_match = re.search(r'(kp\d+|sv\d+)', search_term_lower)
        if code_match:
            product_code = code_match.group(0)
        
        # 4. Erstelle Varianten für den Produktnamen (mit/ohne Bindestriche, etc.)
        name_variants = [product_name]
        
        # Mit Bindestrichen
        if ' ' in product_name:
            name_variants.append(product_name.replace(' ', '-'))
        
        # Ohne Leerzeichen
        if ' ' in product_name:
            name_variants.append(product_name.replace(' ', ''))
            
        # Mit Leerzeichen statt Bindestrichen
        if '-' in product_name:
            name_variants.append(product_name.replace('-', ' '))
        
        # Entferne Leerzeichen und Bindestriche für ein reines Keyword
        pure_name = re.sub(r'[\s\-]', '', product_name)
        if pure_name not in name_variants:
            name_variants.append(pure_name)
            
        # WICHTIG: Varianten ohne Umlaute hinzufügen
        umlaut_variants = []
        for variant in name_variants:
            replaced_variant = replace_umlauts(variant)
            if replaced_variant != variant and replaced_variant not in name_variants:
                umlaut_variants.append(replaced_variant)
        
        # Füge die Umlaut-Varianten hinzu
        name_variants.extend(umlaut_variants)
            
        # 5. Erstelle Varianten für den Produkttyp
        type_variants = []
        
        if product_type in PRODUCT_TYPE_VARIANTS:
            type_variants = PRODUCT_TYPE_VARIANTS[product_type]
        else:
            # Wenn der Typ nicht bekannt ist, verwende den erkannten Typ
            if product_type != "unknown":
                type_variants = [product_type]
        
        # 6. Füge das Produktinfo-Dictionary hinzu
        product_info.append({
            "original_term": search_term,
            "product_name": product_name,
            "product_type": product_type,
            "product_code": product_code,
            "name_variants": name_variants,
            "type_variants": type_variants,
            "tokens": keywords_map[search_term]  # Original-Tokens behalten
        })
    
    return product_info

def get_optimized_search_terms(product_info):
    """
    Erstellt eine optimierte Liste von Suchbegriffen aus den Produktinformationen
    
    :param product_info: Liste mit Produktinformationen
    :return: Liste mit optimierten Suchbegriffen
    """
    search_terms = []
    
    # Höchste Priorität: Produktcodes (wie sv09, kp09)
    product_codes = []
    for product in product_info:
        if product["product_code"] and product["product_code"] not in product_codes:
            product_codes.append(product["product_code"])
    
    # Produktnamen (ohne Duplikate)
    product_names = []
    for product in product_info:
        name = product["product_name"]
        if name and name not in product_names:
            product_names.append(name)
    
    # Kombiniere alle Begriffe (Codes zuerst, dann Namen)
    search_terms = product_codes + product_names
    
    # Beschränke auf maximal 5 Suchbegriffe, um Anfragen zu reduzieren
    return search_terms[:5]

def load_cached_product_urls():
    """
    Lädt die gecachten Produkt-URLs aus dem Cache
    
    :return: Liste mit Produkt-URL-Daten
    """
    cache = load_cache()
    products = cache.get("products", {})
    
    result = []
    for product_id, data in products.items():
        if "url" in data:
            result.append({
                "url": data["url"],
                "title": data.get("title", "")
            })
    
    return result

def fetch_products_from_categories():
    """
    Fetcht Produkte aus den Kategorieseiten
    
    :return: Liste mit Produkt-URLs und Titeln
    """
    # Wichtige Kategorien für Pokemon-Produkte
    category_urls = [
        "https://www.mighty-cards.de/shop/Pokemon",
        "https://www.mighty-cards.de/shop/Vorbestellung-c166467816"
    ]
    
    products = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    for url in category_urls:
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.content, "html.parser")
                
                # Verschiedene Selektoren für Produktkarten
                product_selectors = [
                    ".product-card", ".grid__item", ".product-item", 
                    "article.product, .product-item"
                ]
                
                for selector in product_selectors:
                    items = soup.select(selector)
                    if items:
                        for item in items:
                            link = item.find("a", href=True)
                            if link:
                                title = link.get_text().strip()
                                href = link["href"]
                                
                                # Stelle sicher, dass der Link kein Fragment, JS-Call oder mailto: ist
                                if not href.startswith(("#", "javascript:", "mailto:")):
                                    # Absolute URL erstellen
                                    product_url = href if href.startswith("http") else urljoin(url, href)
                                    
                                    # Nur Pokemon-Produkte hinzufügen
                                    if "pokemon" in product_url.lower() and not contains_blacklist_terms(product_url.lower()):
                                        products.append({
                                            "url": product_url,
                                            "title": title
                                        })
        except Exception as e:
            logger.warning(f"⚠️ Fehler beim Scrapen der Kategorie {url}: {e}")
    
    return products

def fetch_filtered_products_from_sitemap_with_retry(headers, product_info, max_retries=3):
    """
    Versucht, die Sitemap zu laden und daraus relevante Produkte zu extrahieren
    
    :param headers: HTTP-Headers für die Anfrage
    :param product_info: Liste mit extrahierten Produktinformationen
    :param max_retries: Maximale Anzahl von Wiederholungsversuchen
    :return: Liste mit vorgefiltertern Produkt-URLs
    """
    sitemap_url = "https://www.mighty-cards.de/sitemap.xml"
    
    for retry in range(max_retries):
        try:
            response = requests.get(sitemap_url, headers=headers, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.content, "lxml-xml")
                
                # Alle URLs aus der Sitemap extrahieren
                urls = []
                for url_tag in soup.find_all("url"):
                    loc_tag = url_tag.find("loc")
                    if loc_tag:
                        urls.append(loc_tag.text)
                
                # Relevante URLs filtern
                filtered_urls = filter_sitemap_products(urls, product_info)
                logger.info(f"🔍 {len(filtered_urls)} relevante Produkt-URLs aus Sitemap extrahiert")
                return filtered_urls
            else:
                logger.warning(f"⚠️ Fehler beim Laden der Sitemap: Status {response.status_code}")
        except Exception as e:
            logger.warning(f"⚠️ Fehler beim Laden der Sitemap: {e}")
        
        if retry < max_retries - 1:
            wait_time = 2 ** retry  # Exponentielles Backoff
            logger.info(f"🔄 Wiederholungsversuch {retry+1}/{max_retries} in {wait_time} Sekunden...")
            time.sleep(wait_time)
    
    logger.error(f"❌ Alle {max_retries} Versuche zum Laden der Sitemap sind fehlgeschlagen")
    return []

def filter_sitemap_products(all_urls, product_info):
    """
    Filtert URLs aus der Sitemap basierend auf den Produktinformationen
    
    :param all_urls: Liste aller URLs aus der Sitemap
    :param product_info: Liste mit extrahierten Produktinformationen
    :return: Liste mit gefilterten URLs
    """
    filtered_urls = []
    
    # Sammle alle relevanten Schlüsselwörter für die Filterung
    relevant_keywords = []
    product_codes = []
    
    for product in product_info:
        # Produktnamen-Varianten
        for variant in product["name_variants"]:
            if variant and len(variant) > 3 and variant not in relevant_keywords:
                relevant_keywords.append(variant)
        
        # Produktcodes
        if product["product_code"] and product["product_code"] not in product_codes:
            product_codes.append(product["product_code"])
    
    for url in all_urls:
        url_lower = url.lower()
        
        # Muss "pokemon" enthalten
        if "pokemon" not in url_lower:
            continue
            
        # Darf keine Blacklist-Begriffe enthalten
        if contains_blacklist_terms(url_lower):
            continue
        
        # Prüfe auf direkte Übereinstimmung mit Produktcode oder Setnamen
        is_relevant = False
        
        # Prüfe zuerst auf Produktcodes (höchste Priorität)
        for code in product_codes:
            if code and code.lower() in url_lower:
                filtered_urls.append(url)
                is_relevant = True
                break
        
        if is_relevant:
            continue
        
        # Prüfe auf alle Namen-Varianten
        for keyword in relevant_keywords:
            if keyword and keyword.lower() in url_lower:
                filtered_urls.append(url)
                is_relevant = True
                break
        
        if is_relevant:
            continue
            
        # Fallback: URLs, die Display/ETB etc. + Pokemon enthalten
        if "pokemon" in url_lower and any(term in url_lower for term in ["display", "36er", "box", "etb", "elite trainer", "ttb", "top trainer"]):
            filtered_urls.append(url)
    
    return filtered_urls

def get_default_headers():
    """
    Erstellt Standard-HTTP-Headers
    
    :return: Dictionary mit HTTP-Headers
    """
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.4 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0"
    ]
    
    return {
        "User-Agent": random.choice(user_agents),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7"
    }