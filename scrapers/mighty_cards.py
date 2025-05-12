"""
Spezieller Scraper für mighty-cards.de mit Sitemap-Integration und zweistufigem Ansatz:
1. BeautifulSoup für schnelle URL-Filterung
2. Selenium für präzise Preis-/Verfügbarkeitserkennung der gefundenen Treffer

Diese kombinierte Lösung bietet hohe Performance und Genauigkeit.
"""

import requests
import hashlib
import re
import json
import time
import random
import logging
import os
import threading
import queue
from pathlib import Path
from threading import Lock
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote_plus

# Selenium Imports
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager

# Projekt-spezifische Importe
from utils.matcher import is_keyword_in_text, extract_product_type_from_text, clean_text
from utils.stock import update_product_status
from utils.availability import detect_availability

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
browser_pool_lock = Lock()

# Cache-Datei
CACHE_FILE = "data/mighty_cards_cache.json"

# Selenium-Konfiguration
SELENIUM_TIMEOUT = 15  # Sekunden
SELENIUM_HEADLESS = True
BROWSER_POOL_SIZE = 3  # Anzahl der Browser im Pool
BROWSER_MAX_USES = 10  # Maximale Nutzung eines Browsers bevor er neugestartet wird

# Browser-Pool und Zähler
browser_pool = queue.Queue()
browser_use_count = {}

# Semaphore zum Begrenzen der gleichzeitigen Selenium-Anfragen
browser_semaphore = threading.Semaphore(BROWSER_POOL_SIZE)

def initialize_browser_pool():
    """Initialisiert den Browser-Pool für Selenium"""
    logger.info(f"🔄 Initialisiere Browser-Pool mit {BROWSER_POOL_SIZE} Browsern")
    for _ in range(BROWSER_POOL_SIZE):
        try:
            browser = create_browser()
            browser_id = id(browser)
            browser_use_count[browser_id] = 0
            browser_pool.put(browser)
        except Exception as e:
            logger.error(f"❌ Fehler beim Erstellen eines Browsers: {e}")

def create_browser():
    """Erstellt einen neuen Selenium-Browser mit optimierten Einstellungen"""
    options = Options()
    
    if SELENIUM_HEADLESS:
        options.add_argument("--headless=new")
    
    # Performance-Optimierungen
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")
    
    # Verhindert Bot-Erkennung
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    
    # Zufälliger User-Agent für natürlicheres Verhalten
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
    ]
    options.add_argument(f"--user-agent={random.choice(user_agents)}")
    
    # Verwende webdriver_manager für automatische Updates des ChromeDrivers
    try:
        service = Service(ChromeDriverManager().install())
        browser = webdriver.Chrome(service=service, options=options)
        
        # Anti-Bot-Detection: Execute CDP commands
        browser.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            """
        })
        
        # Setze angemessene Timeouts
        browser.set_page_load_timeout(SELENIUM_TIMEOUT)
        browser.implicitly_wait(5)
        
        return browser
    except Exception as e:
        logger.error(f"❌ Fehler beim Erstellen des Browsers: {e}")
        raise

def get_browser_from_pool():
    """Holt einen Browser aus dem Pool oder erstellt einen neuen bei Bedarf"""
    with browser_pool_lock:
        if browser_pool.empty():
            logger.info("🔄 Browser-Pool leer, erstelle neuen Browser")
            browser = create_browser()
            browser_id = id(browser)
            browser_use_count[browser_id] = 0
            return browser
        
        browser = browser_pool.get()
        browser_id = id(browser)
        
        # Prüfe, ob Browser zu oft verwendet wurde und erstelle ggf. einen neuen
        if browser_use_count.get(browser_id, 0) >= BROWSER_MAX_USES:
            logger.info(f"🔄 Browser hat Nutzungslimit erreicht ({BROWSER_MAX_USES}), erstelle neuen Browser")
            try:
                browser.quit()
            except:
                pass
            
            browser = create_browser()
            browser_id = id(browser)
            browser_use_count[browser_id] = 0
        
        return browser

def return_browser_to_pool(browser):
    """Gibt einen Browser zurück in den Pool"""
    with browser_pool_lock:
        browser_id = id(browser)
        
        # Erhöhe Nutzungszähler
        if browser_id in browser_use_count:
            browser_use_count[browser_id] += 1
        else:
            browser_use_count[browser_id] = 1
        
        # Zurück in den Pool
        browser_pool.put(browser)

def shutdown_browser_pool():
    """Schließt alle Browser im Pool"""
    logger.info("🔄 Schließe Browser-Pool")
    with browser_pool_lock:
        while not browser_pool.empty():
            browser = browser_pool.get()
            try:
                browser.quit()
            except:
                pass

def extract_product_info_with_selenium(product_url, timeout=SELENIUM_TIMEOUT):
    """
    Extrahiert präzise Preis- und Verfügbarkeitsinformationen mit Selenium
    
    :param product_url: URL der Produktseite
    :param timeout: Timeout in Sekunden
    :return: Dictionary mit Produktdetails (title, price, is_available, status_text)
    """
    browser = None
    result = {
        "title": None,
        "price": "Preis nicht verfügbar",
        "is_available": False,
        "status_text": "[?] Status unbekannt"
    }
    
    with browser_semaphore:
        try:
            browser = get_browser_from_pool()
            logger.info(f"🌐 Lade Produktseite mit Selenium: {product_url}")
            
            # Zufällige Verzögerung für natürlicheres Verhalten
            time.sleep(random.uniform(1, 2))
            
            # Seite laden
            browser.get(product_url)
            
            # Warte auf das Laden der Seite
            WebDriverWait(browser, timeout).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            # Titel extrahieren
            try:
                title_element = WebDriverWait(browser, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".product-details__product-title, h1.title, h1"))
                )
                result["title"] = title_element.text.strip()
            except (TimeoutException, NoSuchElementException):
                logger.warning(f"⚠️ Titel konnte nicht gefunden werden für {product_url}")
            
            # Preis extrahieren mit verschiedenen Selektoren
            price_selectors = [
                ".details-product-price__value",
                ".product-details__product-price",
                ".price"
            ]
            
            for selector in price_selectors:
                try:
                    price_element = WebDriverWait(browser, 3).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                    )
                    result["price"] = price_element.text.strip()
                    logger.info(f"💰 Preis gefunden: {result['price']}")
                    break
                except (TimeoutException, NoSuchElementException):
                    continue
            
            # Verfügbarkeit prüfen (erst negative, dann positive Indikatoren)
            
            # 1. Negative Indikatoren (nicht verfügbar)
            not_available_indicators = [
                # Text-basierte Indikatoren
                ("text", "Ausverkauft"),
                ("text", "nicht verfügbar"),
                ("text", "nicht auf Lager"),
                ("text", "vergriffen"),
                
                # Element-basierte Indikatoren
                ("selector", ".badge.badge-danger"),
                ("selector", ".not-available"),
                ("selector", ".sold-out"),
                ("selector", "button.disabled"),
                ("selector", "[disabled]")
            ]
            
            for indicator_type, indicator in not_available_indicators:
                try:
                    if indicator_type == "text":
                        # Suche nach Text in der Seite
                        page_text = browser.find_element(By.TAG_NAME, "body").text
                        if indicator in page_text:
                            result["is_available"] = False
                            result["status_text"] = f"[X] Ausverkauft ({indicator} gefunden)"
                            logger.info(f"❌ Produkt nicht verfügbar: {indicator} im Text gefunden")
                            return result
                    else:
                        # Suche nach Element mit Selektor
                        if browser.find_elements(By.CSS_SELECTOR, indicator):
                            result["is_available"] = False
                            result["status_text"] = f"[X] Ausverkauft (Element {indicator} gefunden)"
                            logger.info(f"❌ Produkt nicht verfügbar: Element {indicator} gefunden")
                            return result
                except Exception:
                    pass
            
            # 2. Prüfung auf Vorbestellung
            preorder_indicators = [
                ("text", "Vorbestellung"),
                ("text", "vorbestellen"),
                ("text", "Pre-Order"),
                ("text", "Preorder"),
                ("selector", ".preorder"),
                ("selector", ".pre-order")
            ]
            
            for indicator_type, indicator in preorder_indicators:
                try:
                    if indicator_type == "text":
                        page_text = browser.find_element(By.TAG_NAME, "body").text
                        if indicator in page_text:
                            result["is_available"] = True
                            result["status_text"] = f"[V] Vorbestellbar ({indicator} gefunden)"
                            logger.info(f"✅ Produkt vorbestellbar: {indicator} im Text gefunden")
                            return result
                    else:
                        if browser.find_elements(By.CSS_SELECTOR, indicator):
                            result["is_available"] = True
                            result["status_text"] = f"[V] Vorbestellbar (Element {indicator} gefunden)"
                            logger.info(f"✅ Produkt vorbestellbar: Element {indicator} gefunden")
                            return result
                except Exception:
                    pass
            
            # 3. Positive Indikatoren (verfügbar)
            available_indicators = [
                # Warenkorb-Button
                ("selector", "button:not([disabled]).add-to-cart, button:not([disabled]) .form-control__button-text"),
                
                # Text-basierte Indikatoren
                ("text", "In den Warenkorb"),
                ("text", "Auf Lager"),
                ("text", "Lieferbar"),
                ("text", "Verfügbar"),
                
                # Element-basierte Indikatoren
                ("selector", ".available"),
                ("selector", ".in-stock"),
                ("selector", ".badge-success")
            ]
            
            for indicator_type, indicator in available_indicators:
                try:
                    if indicator_type == "text":
                        # Prüfen, ob der Text im Kontext eines nicht-deaktivierten Buttons vorkommt
                        if indicator == "In den Warenkorb":
                            # Spezialfall für den Warenkorb-Button
                            cart_buttons = browser.find_elements(By.XPATH, 
                                f"//button[contains(text(), '{indicator}') and not(@disabled)]")
                            
                            if not cart_buttons:
                                # Suche nach Span-Element innerhalb eines Buttons
                                cart_buttons = browser.find_elements(By.XPATH, 
                                    f"//button[not(@disabled)]//span[contains(text(), '{indicator}')]")
                            
                            if cart_buttons:
                                result["is_available"] = True
                                result["status_text"] = f"[V] Verfügbar (Warenkorb-Button aktiv)"
                                logger.info(f"✅ Produkt verfügbar: Warenkorb-Button aktiv")
                                return result
                        else:
                            # Andere Text-Indikatoren
                            page_text = browser.find_element(By.TAG_NAME, "body").text
                            if indicator in page_text:
                                result["is_available"] = True
                                result["status_text"] = f"[V] Verfügbar ({indicator} gefunden)"
                                logger.info(f"✅ Produkt verfügbar: {indicator} im Text gefunden")
                                return result
                    else:
                        # Suche nach Element mit Selektor
                        if browser.find_elements(By.CSS_SELECTOR, indicator):
                            result["is_available"] = True
                            result["status_text"] = f"[V] Verfügbar (Element {indicator} gefunden)"
                            logger.info(f"✅ Produkt verfügbar: Element {indicator} gefunden")
                            return result
                except Exception:
                    pass
            
            # Fallback wenn keine eindeutigen Indikatoren gefunden wurden
            # Prüfe, ob der Warenkorb-Button existiert und nicht deaktiviert ist
            try:
                add_to_cart = browser.find_element(By.XPATH, "//button[contains(., 'In den Warenkorb')]")
                if "disabled" not in add_to_cart.get_attribute("class") and not add_to_cart.get_attribute("disabled"):
                    result["is_available"] = True
                    result["status_text"] = "[V] Wahrscheinlich verfügbar (Warenkorb-Button vorhanden)"
                else:
                    result["is_available"] = False
                    result["status_text"] = "[X] Wahrscheinlich nicht verfügbar (Warenkorb-Button deaktiviert)"
            except NoSuchElementException:
                # Default wenn nichts erkannt wurde
                result["status_text"] = "[?] Status unbekannt (als nicht verfügbar behandelt)"
            
            logger.info(f"🔍 Selenium-Extraktion abgeschlossen für {product_url}: {result['status_text']}")
            return result
            
        except Exception as e:
            logger.error(f"❌ Fehler bei der Selenium-Extraktion für {product_url}: {e}")
            result["status_text"] = f"[?] Fehler bei der Verfügbarkeitsprüfung: {str(e)}"
            return result
        finally:
            # Browser zurück in den Pool
            if browser:
                try:
                    # Cookies löschen für sauberen nächsten Besuch
                    browser.delete_all_cookies()
                    return_browser_to_pool(browser)
                except Exception as e:
                    logger.warning(f"⚠️ Fehler beim Zurückgeben des Browsers in den Pool: {e}")

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

def check_product_availability(soup):
    """
    Verbesserte Verfügbarkeitsprüfung für mighty-cards.de mit BeautifulSoup
    (Wird als erster Schritt vor Selenium verwendet)
    
    :param soup: BeautifulSoup-Objekt der Produktseite
    :return: Tuple (is_available, price, status_text)
    """
    # 1. Preisinformation extrahieren mit verbessertem Selektor
    price_elem = soup.find('span', {'class': 'details-product-price__value'})
    if price_elem:
        price = price_elem.text.strip()
    else:
        # Fallback für andere Preisformate
        price_elem = soup.select_one('.product-details__product-price, .price')
        price = price_elem.text.strip() if price_elem else "Preis nicht verfügbar"
    
    # 2. Prüfe auf Vorbestellung
    is_preorder = False
    preorder_text = soup.find(string=re.compile("Vorbestellung", re.IGNORECASE))
    if preorder_text:
        is_preorder = True
        return True, price, "[V] Vorbestellbar"
    
    # 3. Positivprüfung: Suche nach "In den Warenkorb"-Button
    cart_button = None
    
    # Suche nach dem Button-Element mit dem Text "In den Warenkorb"
    for elem in soup.find_all(['button', 'span']):
        if elem.text and "In den Warenkorb" in elem.text:
            cart_button = elem
            # Prüfe, ob das Elternelement ein Button ist
            parent = elem.parent
            while parent and parent.name != 'button' and parent.name != 'form':
                parent = parent.parent
            
            if parent and parent.name == 'button':
                # Prüfe, ob der Button deaktiviert ist
                if parent.has_attr('disabled'):
                    cart_button = None  # Button ist deaktiviert
                else:
                    cart_button = parent
            break
    
    if cart_button:
        return True, price, "[V] Verfügbar (Warenkorb-Button aktiv)"
    
    # 4. Negativprüfung: Suche nach beiden möglichen "Ausverkauft"-Elementen
    # a) Als div mit class="label__text"
    sold_out_label = soup.find('div', {'class': 'label__text'}, text="Ausverkauft")
    
    # b) Als span innerhalb eines div
    sold_out_span = soup.find('span', text="Ausverkauft")
    
    if sold_out_label or sold_out_span:
        return False, price, "[X] Ausverkauft"
    
    # 5. Wenn nichts eindeutiges gefunden wurde, versuche eine heuristische Annäherung
    # Da wir wissen, dass BeautifulSoup bei JavaScript-generierten Inhalten unzuverlässig ist,
    # markieren wir den Status als unbekannt - Selenium wird später genauer prüfen
    return None, price, "[?] Status unbekannt"

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

def search_mighty_cards_products(search_term, headers):
    """
    Sucht Produkte mit dem gegebenen Suchbegriff auf mighty-cards.de
    
    :param search_term: Suchbegriff
    :param headers: HTTP-Headers für die Anfragen
    :return: Liste mit gefundenen Produkt-URLs
    """
    product_urls = []
    
    try:
        # Verwende Original-Suchbegriff
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
                # Prüfe, ob der Link relevante Pokemon-Produkte enthält
                href_lower = href.lower()
                
                # Nur Pokemon-Links und keine Blacklist-Begriffe
                if "pokemon" in href_lower and not contains_blacklist_terms(href_lower):
                    # Vollständige URL erstellen
                    product_url = href if href.startswith('http') else urljoin("https://www.mighty-cards.de", href)
                    if product_url not in product_urls:
                        product_urls.append(product_url)
        
        # Versuche Variante ohne Umlaute, wenn es keine Ergebnisse gab
        if not product_urls and any(umlaut in search_term for umlaut in UMLAUT_MAPPING.keys()):
            no_umlaut_term = replace_umlauts(search_term)
            logger.info(f"🔍 Versuche auch Suche ohne Umlaute: {no_umlaut_term}")
            
            encoded_term = quote_plus(no_umlaut_term)
            search_url = f"https://www.mighty-cards.de/shop/search?keyword={encoded_term}&limit=20"
            
            try:
                response = requests.get(search_url, headers=headers, timeout=15)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.content, "html.parser")
                    
                    for link in soup.find_all("a", href=True):
                        href = link.get('href', '')
                        if '/shop/' in href and 'p' in href.split('/')[-1]:
                            href_lower = href.lower()
                            
                            if "pokemon" in href_lower and not contains_blacklist_terms(href_lower):
                                product_url = href if href.startswith('http') else urljoin("https://www.mighty-cards.de", href)
                                if product_url not in product_urls:
                                    product_urls.append(product_url)
            except Exception as e:
                logger.warning(f"⚠️ Fehler bei der Suche ohne Umlaute nach {no_umlaut_term}: {e}")
        
        logger.info(f"🔍 {len(product_urls)} Produkte gefunden für Suchbegriff '{search_term}'")
        
    except Exception as e:
        logger.warning(f"⚠️ Fehler bei der Suche nach {search_term}: {e}")
    
    return product_urls

def fetch_filtered_products_from_sitemap_with_retry(headers, product_info, max_retries=4, timeout=15):
    """
    Lädt und filtert Produkt-URLs aus der Sitemap mit verbessertem Retry-Mechanismus
    
    :param headers: HTTP-Headers für die Anfragen
    :param product_info: Liste mit extrahierten Produktinformationen
    :param max_retries: Maximale Anzahl von Wiederholungsversuchen (3-4)
    :param timeout: Timeout pro Versuch in Sekunden
    :return: Liste mit vorgefilterterten Produkt-URLs
    """
    sitemap_url = "https://www.mighty-cards.de/wp-sitemap-ecstore-1.xml"
    
    # Mehrere Versuche, die Sitemap zu laden
    for retry in range(max_retries):
        try:
            logger.info(f"🔍 Lade Sitemap von {sitemap_url} (Versuch {retry+1}/{max_retries})")
            response = requests.get(sitemap_url, headers=headers, timeout=timeout)
            
            if response.status_code == 200:
                # Sitemap erfolgreich geladen
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
                        continue  # Zum nächsten Versuch
                
                # Alle URLs aus der Sitemap extrahieren
                all_product_urls = []
                for url_tag in soup.find_all("url"):
                    loc_tag = url_tag.find("loc")
                    if loc_tag and loc_tag.text:
                        url = loc_tag.text.strip()
                        # Nur Shop-URLs hinzufügen
                        if "/shop/" in url:
                            all_product_urls.append(url)
                
                if all_product_urls:
                    logger.info(f"🔍 {len(all_product_urls)} Produkt-URLs aus Sitemap extrahiert")
                    
                    # Filtern der URLs wie zuvor
                    return filter_sitemap_products(all_product_urls, product_info)
                else:
                    logger.warning(f"⚠️ Keine Produkt-URLs in der Sitemap gefunden (Versuch {retry+1}/{max_retries})")
            else:
                logger.warning(f"⚠️ Fehler beim Laden der Sitemap: Status {response.status_code} (Versuch {retry+1}/{max_retries})")
        
        except requests.exceptions.Timeout:
            logger.warning(f"⚠️ Timeout beim Laden der Sitemap (Versuch {retry+1}/{max_retries})")
        except Exception as e:
            logger.warning(f"⚠️ Fehler beim Laden der Sitemap: {e} (Versuch {retry+1}/{max_retries})")
        
        # Warte exponentiell länger vor dem nächsten Versuch, wenn nicht der letzte Versuch
        if retry < max_retries - 1:
            wait_time = 2 ** retry  # 1, 2, 4, 8 Sekunden...
            logger.info(f"🕒 Warte {wait_time} Sekunden vor dem nächsten Versuch...")
            time.sleep(wait_time)
    
    # Wenn alle Versuche fehlschlagen, leere Liste zurückgeben
    logger.error(f"❌ Alle {max_retries} Versuche zum Laden der Sitemap sind fehlgeschlagen")
    return []

def filter_sitemap_products(all_product_urls, product_info):
    """
    Filtert Produkt-URLs aus der Sitemap basierend auf den Produktinformationen
    
    :param all_product_urls: Liste aller Produkt-URLs aus der Sitemap
    :param product_info: Liste mit extrahierten Produktinformationen
    :return: Liste mit gefilterten Produkt-URLs
    """
    # Sammle alle relevanten Keyword-Varianten für die Filterung
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
    
    logger.info(f"🔍 Filterung mit {len(relevant_keywords)} Namen-Varianten und {len(product_codes)} Produktcodes")
    
    # Vorfilterung der URLs direkt nach dem Laden
    filtered_urls = []
    direct_matches = []  # Für besonders relevante URLs (direkte Treffer)
    
    for url in all_product_urls:
        url_lower = url.lower()
        
        # 1. Muss "pokemon" im URL enthalten
        if "pokemon" not in url_lower:
            continue
            
        # 2. Darf keine Blacklist-Begriffe enthalten
        if contains_blacklist_terms(url_lower):
            continue
        
        # Prüfe auf direkte Übereinstimmung mit Produktcode oder Setnamen
        # z.B. "kp09" oder "reisegefahrten" im URL
        is_direct_match = False
        
        # Prüfe zuerst auf Produktcodes (höchste Priorität)
        for code in product_codes:
            if code and code.lower() in url_lower:
                is_direct_match = True
                direct_matches.append(url)
                break
        
        if is_direct_match:
            continue  # Wurde bereits zu direct_matches hinzugefügt
        
        # Prüfe auf alle Namen-Varianten (inkl. ohne Umlaute)
        relevant_match = False
        for kw in relevant_keywords:
            if kw and kw.lower() in url_lower:
                relevant_match = True
                break
        
        # URLs mit relevantem Keyword hinzufügen
        if relevant_match:
            filtered_urls.append(url)
        # URLs, die allgemein relevante Begriffe enthalten, als Fallback
        elif any(term in url_lower for term in ["karmesin", "purpur", "scarlet", "violet", "kp09", "sv09"]):
            filtered_urls.append(url)
    
    # Direkte Matches haben höchste Priorität
    # (Diese sollten definitiv Ergebnisse liefern)
    logger.info(f"🔍 {len(direct_matches)} direkte Treffer und {len(filtered_urls)} potentielle Treffer gefunden")
    
    # Direkte Matches zuerst, dann andere gefilterte URLs
    result = direct_matches + [url for url in filtered_urls if url not in direct_matches]
    return result

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

def process_product_matches_with_selenium(positive_matches):
    """
    Verarbeitet die positiven Treffer mit Selenium für präzise Verfügbarkeits- und Preisinformationen
    
    :param positive_matches: Liste der positiven Treffer aus dem BeautifulSoup-Scanning
    :return: Liste der aktualisierten Produktinformationen
    """
    if not positive_matches:
        return []
    
    logger.info(f"🔄 Starte Selenium-Verarbeitung für {len(positive_matches)} positive Treffer")
    
    # Initialisiere den Browser-Pool
    try:
        initialize_browser_pool()
    except Exception as e:
        logger.error(f"❌ Fehler bei der Initialisierung des Browser-Pools: {e}")
        return positive_matches  # Fallback auf die ursprünglichen Matches
    
    # Liste für aktualisierte Produkt-Daten
    updated_matches = []
    
    try:
        # Verarbeite jedes positive Match
        for product in positive_matches:
            url = product.get("url")
            if not url:
                updated_matches.append(product)
                continue
            
            logger.info(f"🔄 Verarbeite positiven Treffer mit Selenium: {product.get('title')}")
            
            # Extrahiere Produktdaten mit Selenium
            selenium_data = extract_product_info_with_selenium(url)
            
            # Aktualisiere die Produktdaten
            if selenium_data:
                # Behalte Originaltitel, falls Selenium keinen findet
                if not selenium_data["title"]:
                    selenium_data["title"] = product.get("title")
                
                # Aktualisiere die Produktdaten
                updated_product = product.copy()
                updated_product["price"] = selenium_data["price"]
                updated_product["is_available"] = selenium_data["is_available"]
                updated_product["status_text"] = selenium_data["status_text"]
                
                # Füge zu den aktualisierten Matches hinzu
                updated_matches.append(updated_product)
                logger.info(f"✅ Aktualisiertes Produkt: {updated_product['title']} - {updated_product['status_text']}")
            else:
                # Fallback auf die ursprünglichen Daten
                updated_matches.append(product)
                logger.warning(f"⚠️ Selenium-Extraktion fehlgeschlagen für {url}, verwende ursprüngliche Daten")
    
    except Exception as e:
        logger.error(f"❌ Fehler bei der Selenium-Verarbeitung: {e}")
        # Fallback auf die ursprünglichen Matches
        return positive_matches
    
    finally:
        # Schließe den Browser-Pool
        try:
            shutdown_browser_pool()
        except Exception as e:
            logger.warning(f"⚠️ Fehler beim Schließen des Browser-Pools: {e}")
    
    return updated_matches

def send_batch_notifications(all_products):
    """Sendet Benachrichtigungen in Batches"""
    from utils.telegram import send_batch_notification
    
    if all_products:
        logger.info(f"📤 Sende Batch {1}/{1} mit {len(all_products)} Produkten")
        send_batch_notification(all_products)
    else:
        logger.info("ℹ️ Keine Produkte für Benachrichtigung gefunden")

def process_cached_product(product_url, product_data, product_info, seen, out_of_stock, only_available,
                         headers, all_products, new_matches, found_product_ids, cached_products):
    """
    Verarbeitet ein bereits im Cache gespeichertes Produkt
    
    :return: (success, error_404) - Erfolg und ob ein 404-Fehler aufgetreten ist
    """
    search_term = product_data.get("search_term")
    
    try:
        # Produkt-Detailseite abrufen
        try:
            response = requests.get(product_url, headers=headers, timeout=15)
            
            # Wenn 404 zurückgegeben wird, müssen wir die Sitemap neu scannen
            if response.status_code == 404:
                return False, True
                
            if response.status_code != 200:
                logger.warning(f"⚠️ Fehler beim Abrufen von {product_url}: Status {response.status_code}")
                return False, False
        except requests.exceptions.RequestException as e:
            logger.warning(f"⚠️ Fehler beim Abrufen von {product_url}: {e}")
            return False, False
        
        soup = BeautifulSoup(response.content, "html.parser")
        
        # Titel extrahieren und validieren
        title_elem = soup.find('h1', {'class': 'product-details__product-title'})
        if not title_elem:
            title_elem = soup.find('h1')
        
        if not title_elem:
            # Wenn kein Titel gefunden wird, verwende den zwischengespeicherten
            title = product_data.get("title", "Pokemon Produkt")
        else:
            title = title_elem.text.strip()
        
        # VERBESSERT: Verwende die neue Verfügbarkeitsprüfung
        is_available, price, status_text = check_product_availability(soup)
        
        # Eindeutige ID für das Produkt erstellen
        product_id = product_data.get("product_id") or create_product_id(title)
        
        # Thread-sichere Prüfung auf Duplikate
        with url_lock:
            if product_id in found_product_ids:
                return True, False
        
        # Status aktualisieren
        should_notify, is_back_in_stock = update_product_status(
            product_id, is_available, seen, out_of_stock
        )
        
        # Bei "nur verfügbare" Option, nicht verfügbare Produkte überspringen
        if only_available and not is_available:
            # Aktualisiere Verfügbarkeitsstatus im Cache
            with cache_lock:
                if product_id in cached_products:
                    cached_products[product_id]["is_available"] = is_available
                    cached_products[product_id]["price"] = price
                    cached_products[product_id]["last_checked"] = int(time.time())
            return True, False
        
        if should_notify:
            # Status anpassen wenn wieder verfügbar
            if is_back_in_stock:
                status_text = "🎉 Wieder verfügbar!"
            
            # Extrahiere Produkttyp
            detected_product_type = extract_product_type_from_text(title)
            
            # VERBESSERT: Überprüfe, ob der Produkttyp dem ursprünglichen Suchbegriff entspricht
            search_term_product_type = None
            for item in product_info:
                if item["original_term"] == search_term:
                    search_term_product_type = item["product_type"]
                    break
            
            # Wenn der erkannte Produkttyp nicht mit dem gesuchten übereinstimmt, überspringen
            if (search_term_product_type and search_term_product_type != "unknown" and 
                detected_product_type != "unknown" and search_term_product_type != detected_product_type):
                logger.debug(f"⚠️ Produkttyp-Diskrepanz: Gesucht {search_term_product_type}, gefunden {detected_product_type}: {title}")
                return True, False
            
            # Produkt-Daten sammeln
            product_data = {
                "title": title,
                "url": product_url,
                "price": price,
                "status_text": status_text,
                "is_available": is_available,
                "matched_term": search_term,
                "product_type": detected_product_type,
                "shop": "mighty-cards.de"
            }
            
            # Thread-sicher zu Ergebnissen hinzufügen
            with data_lock:
                all_products.append(product_data)
                new_matches.append(product_id)
                found_product_ids.add(product_id)
                
            logger.info(f"✅ Gecachtes Produkt aktualisiert: {title} - {status_text}")
        
        # Aktualisiere Produkt im Cache
        with cache_lock:
            cached_products[product_id] = {
                "product_id": product_id,
                "title": title,
                "url": product_url,
                "search_term": search_term,
                "is_available": is_available,
                "price": price,
                "last_checked": int(time.time())
            }
        
        return True, False
    
    except Exception as e:
        logger.error(f"❌ Fehler bei der Verarbeitung von gecachtem Produkt {product_url}: {e}")
        return False, False

def process_mighty_cards_product(product_url, product_info, seen, out_of_stock, only_available, 
                               headers, all_products, new_matches, found_product_ids, cached_products=None):
    """
    Verarbeitet ein einzelnes Produkt von mighty-cards.de (Thread-sicher) mit verbesserter
    Produkttyp- und Produktnamen-Validierung.
    
    :param product_url: URL des Produkts
    :param product_info: Liste mit extrahierten Produktinformationen
    :param seen: Set mit bereits gesehenen Produkten
    :param out_of_stock: Set mit ausverkauften Produkten
    :param only_available: Ob nur verfügbare Produkte angezeigt werden sollen
    :param headers: HTTP-Headers für die Anfragen
    :param all_products: Liste für gefundene Produkte (wird aktualisiert)
    :param new_matches: Liste für neue Treffer (wird aktualisiert)
    :param found_product_ids: Set für Deduplizierung (wird aktualisiert)
    :param cached_products: Optional - Cache-Dictionary für gefundene Produkte
    :return: True bei Erfolg, False bei Fehler
    """
    try:
        # DEBUG: Zeige URL für Debugging-Zwecke
        logger.debug(f"Prüfe URL: {product_url}")
        
        # Extra URL-Validierung mit strengeren Bedingungen
        url_lower = product_url.lower()
        
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
        
        # Titel extrahieren und validieren
        title_elem = soup.find('h1', {'class': 'product-details__product-title'})
        if not title_elem:
            title_elem = soup.find('h1')
        
        if not title_elem:
            # Wenn kein Titel gefunden wird, versuche aus URL zu generieren
            title = extract_title_from_url(product_url)
            logger.debug(f"⚠️ Kein Titel für {product_url} gefunden, generiere aus URL: {title}")
        else:
            title = title_elem.text.strip()
        
        # DEBUG: Zeige Titel für Debugging-Zwecke
        logger.debug(f"Titel: {title}")
        
        # VERBESSERT: Verwende die neue Verfügbarkeitsprüfung
        is_available, price, status_text = check_product_availability(soup)
        
        # URL-Segmente für zuverlässigere Erkennung aufteilen
        url_segments = product_url.split('/')
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
                        "url": product_url,
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
                "url": product_url,
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
                        "url": product_url,
                        "search_term": matched_product["original_term"],
                        "is_available": is_available,
                        "price": price,
                        "last_checked": int(time.time())
                    }
            
            return True
    
    except Exception as e:
        logger.error(f"❌ Fehler bei der Verarbeitung von {product_url}: {e}")
    
    return False

def scrape_mighty_cards(keywords_map, seen, out_of_stock, only_available=False):
    """
    Hauptfunktion: Zweistufiger Scaper mit BeautifulSoup zur schnellen URL-Filterung
    und Selenium für die präzise Preis-/Verfügbarkeitserkennung bei positiven Treffern
    
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param seen: Set mit bereits gesehenen Produkten
    :param out_of_stock: Set mit ausverkauften Produkten
    :param only_available: Ob nur verfügbare Produkte gemeldet werden sollen
    :return: Liste der neuen Treffer
    """
    start_time = time.time()
    logger.info("🌐 Starte speziellen Scraper für mighty-cards.de mit Sitemap-Integration und Multithreading")
    
    # Thread-sichere Kollektionen
    new_matches = []
    all_products = []  # Liste für alle gefundenen Produkte
    found_product_ids = set()  # Set für Deduplizierung von gefundenen Produkten
    
    # Sammle Produkt-Information aus keywords_map
    product_info = extract_product_name_type_info(keywords_map)
    logger.info(f"🔍 Extrahierte Produktinformationen: {len(product_info)} Einträge")
    
    # Standardheader erstellen
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7"
    }
    
    # Cache laden
    cache_data = load_cache()
    cached_products = cache_data.get("products", {})
    last_update = cache_data.get("last_update", 0)
    current_time = int(time.time())
    
    # Cache-Kriterien
    cache_valid = len(cached_products) > 0
    force_refresh = current_time - last_update > 86400  # Alle 24 Stunden Cache aktualisieren
    
    # Prüfen, ob wir den Cache verwenden können
    found_all_products = True
    
    # Prüfen, ob alle gesuchten Produkte im Cache sind
    for item in product_info:
        original_term = item["original_term"]
        if not any(original_term == cached["search_term"] for cached in cached_products.values()):
            found_all_products = False
            break
    
    # Entscheiden, ob wir den Cache verwenden oder neu scannen
    if cache_valid and found_all_products and not force_refresh:
        logger.info(f"✅ Verwende Cache mit {len(cached_products)} Produkten")
        
        # Überprüfe jedes zwischengespeicherte Produkt erneut
        valid_product_urls = []
        cached_items_to_remove = []
        
        for product_id, product_data in cached_products.items():
            product_url = product_data.get("url")
            if not product_url:
                cached_items_to_remove.append(product_id)
                continue
                
            valid_product_urls.append((product_url, product_data))
        
        # Entferne ungültige Einträge aus dem Cache
        for item_id in cached_items_to_remove:
            del cached_products[item_id]
        
        # Wenn wir gültige Produkt-URLs haben, verarbeite sie direkt
        if valid_product_urls:
            logger.info(f"🔄 Überprüfe {len(valid_product_urls)} zwischengespeicherte Produkte")
            
            # Parallelisierte Verarbeitung der gecachten Produkt-URLs
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(valid_product_urls), 10)) as executor:
                futures = []
                
                for product_url, product_data in valid_product_urls:
                    future = executor.submit(
                        process_cached_product,
                        product_url, product_data, product_info, seen, out_of_stock, only_available,
                        headers, all_products, new_matches, found_product_ids, cached_products
                    )
                    futures.append((future, product_url))
                
                # Sammle Ergebnisse und prüfe auf 404-Fehler
                need_rescan = False
                completed = 0
                
                for future, url in futures:
                    try:
                        result, error_404 = future.result()
                        completed += 1
                        
                        # Wenn einer der URLs 404 zurückgibt, müssen wir neu scannen
                        if error_404:
                            need_rescan = True
                            logger.warning(f"⚠️ Gecachte URL nicht mehr erreichbar: {url}")
                            
                            # Entferne URL aus dem Cache
                            for pid, pdata in list(cached_products.items()):
                                if pdata.get("url") == url:
                                    del cached_products[pid]
                    except Exception as e:
                        logger.error(f"❌ Fehler bei der Verarbeitung von {url}: {e}")
                        completed += 1
                
                # Zeige Fortschritt
                if len(futures) > 0:
                    logger.info(f"✅ {completed}/{len(futures)} cache URLs verarbeitet")
            
            # Wenn wir einen 404-Fehler hatten oder nicht alle Produkte gefunden haben, scannen wir neu
            if need_rescan or not new_matches:
                logger.info("🔄 Einige gecachte URLs lieferten 404 oder keine Treffer - führe vollständigen Scan durch")
                # Führe einen vollständigen Scan mit Sitemap durch (siehe unten)
            else:
                # Produkte für die zweite Stufe (Selenium) sammeln
                if all_products:
                    # Verarbeite die positiven Treffer mit Selenium für präzise Daten
                    updated_products = process_product_matches_with_selenium(all_products)
                    
                    # Sende Benachrichtigungen für die aktualisierten Produkte
                    if updated_products:
                        # Überschreibe die vorherigen Ergebnisse
                        all_products = updated_products
                        send_batch_notifications(all_products)
                
                # Cache aktualisieren
                cache_data["products"] = cached_products
                cache_data["last_update"] = current_time
                save_cache(cache_data)
                
                # Messung der Gesamtlaufzeit
                elapsed_time = time.time() - start_time
                logger.info(f"✅ Cache-basiertes Scraping abgeschlossen in {elapsed_time:.2f} Sekunden, {len(new_matches)} Treffer gefunden")
                
                return new_matches
    
    # Vollständiger Scan erforderlich
    logger.info("🔍 Führe vollständigen Scan mit Sitemap durch")
    
    # 1. Zugriff über die Sitemap mit Vorfilterung
    logger.info("🔍 Lade und filtere Produkte aus der Sitemap")
    sitemap_products = fetch_filtered_products_from_sitemap_with_retry(headers, product_info)
    
    if sitemap_products:
        logger.info(f"🔍 Nach Vorfilterung verbleiben {len(sitemap_products)} relevante URLs")
        
        # 2. Parallelisierte Verarbeitung der gefilterten Produkt-URLs
        logger.info(f"🔄 Starte parallele Verarbeitung von {len(sitemap_products)} URLs")
        
        # Bestimme optimale Worker-Anzahl basierend auf CPU-Kernen und URL-Anzahl
        max_workers = min(20, len(sitemap_products))  # Max 20 Worker
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Dictionary zum Speichern der Future-Objekte mit ihren URLs
            future_to_url = {
                executor.submit(
                    process_mighty_cards_product, 
                    url, product_info, seen, out_of_stock, only_available, 
                    headers, all_products, new_matches, found_product_ids, cached_products
                ): url for url in sitemap_products
            }
            
            # Sammle die Ergebnisse ein, während sie fertig werden
            completed = 0
            total = len(future_to_url)
            
            for future in concurrent.futures.as_completed(future_to_url):
                url = future_to_url[future]
                completed += 1
                
                # Gib alle 10% einen Fortschrittsindikator aus
                if completed % max(1, total // 10) == 0 or completed == total:
                    percent = (completed / total) * 100
                    logger.info(f"⏳ Fortschritt: {completed}/{total} URLs verarbeitet ({percent:.1f}%)")
                
                try:
                    # Das Ergebnis wird bereits in den übergebenen Listen gespeichert
                    future.result()
                except Exception as e:
                    logger.error(f"❌ Fehler bei der Verarbeitung von {url}: {e}")
    
    # 3. Fallback: Direkte Suche nach Produkten, wenn nichts gefunden wurde
    if len(all_products) < 2:
        logger.info("🔍 Nicht genug Produkte über Sitemap gefunden, versuche direkte Suche")
        
        # Verwende unterschiedliche Suchbegriffe für die direkte Suche
        search_terms = []
        for product_item in product_info:
            for name_variant in product_item["name_variants"]:
                if name_variant not in search_terms:
                    search_terms.append(name_variant)
                    if len(search_terms) >= 5:  # Begrenze auf max. 5 Suchbegriffe
                        break
        
        # Füge auch immer die Produktcodes hinzu
        for product_item in product_info:
            if product_item["product_code"] and product_item["product_code"] not in search_terms:
                search_terms.append(product_item["product_code"])
        
        # Direktsuche mit den generierten Suchbegriffen
        for search_term in search_terms:
            # Verwende Original-Term und Ersetzungsversion (ohne Umlaute)
            search_products = search_mighty_cards_products(search_term, headers)
            
            # Verarbeite gefundene Produkte sequentiell (meist weniger)
            for product_url in search_products:
                with url_lock:  # Thread-sicher prüfen, ob URL bereits verarbeitet wurde
                    if product_url in sitemap_products:
                        continue  # Vermeidet Duplikate
                
                process_mighty_cards_product(product_url, product_info, seen, out_of_stock, only_available, 
                                            headers, all_products, new_matches, found_product_ids, cached_products)
    
    # Cache aktualisieren
    if cached_products:
        cache_data["products"] = cached_products
        cache_data["last_update"] = current_time
        save_cache(cache_data)
    
    # 4. Zweite Stufe: Verarbeite positive Treffer mit Selenium für präzise Daten
    if all_products:
        updated_products = process_product_matches_with_selenium(all_products)
        
        # Sende Benachrichtigungen für die aktualisierten Produkte
        if updated_products:
            # Überschreibe die vorherigen Ergebnisse
            all_products = updated_products
            send_batch_notifications(all_products)
    else:
        logger.info("ℹ️ Keine Produkte für Selenium-Verarbeitung gefunden")
    
    # Messung der Gesamtlaufzeit
    elapsed_time = time.time() - start_time
    logger.info(f"✅ Scraping abgeschlossen in {elapsed_time:.2f} Sekunden, {len(new_matches)} neue Treffer gefunden")
    
    return new_matches