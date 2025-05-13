"""
Selenium Manager Modul für zentralisierte Browser-Steuerung

Dieses Modul bietet eine zentrale Steuerung für Selenium-Browser und
abstrahiert die komplexe Verwaltung von Browser-Instanzen, Konfigurationen
und Fehlerbehandlung. Es unterstützt automatische Wiederversuche, Headless-Modus
und verbesserte Chrome-Binary-Erkennung.
"""

import os
import re
import time
import random
import logging
import threading
import queue
from pathlib import Path
from threading import Lock

# Selenium Imports
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager

# Logger konfigurieren
logger = logging.getLogger(__name__)

# Standardeinstellungen
SELENIUM_TIMEOUT = 15  # Sekunden
SELENIUM_HEADLESS = os.environ.get('SELENIUM_HEADLESS', 'true').lower() == 'true'
BROWSER_POOL_SIZE = int(os.environ.get('BROWSER_POOL_SIZE', '3'))
BROWSER_MAX_USES = int(os.environ.get('BROWSER_MAX_USES', '10'))
MAX_RETRY_ATTEMPTS = 3

# Browser-Pool und synchronisierte Zugriffsmechanismen
browser_pool = queue.Queue()
browser_use_count = {}
browser_pool_lock = Lock()
browser_semaphore = threading.Semaphore(BROWSER_POOL_SIZE)

def detect_chrome_binary():
    """
    Erkennt den Pfad zum Chrome-Binary auf verschiedenen Betriebssystemen
    mit verbesserter Fehlertoleranz und Unterstützung für Docker/CI-Umgebungen.
    
    :return: Pfad zum Chrome-Binary oder None, wenn nicht gefunden
    """
    # Zuerst aus Umgebungsvariable holen (höchste Priorität)
    chrome_binary = os.environ.get('SELENIUM_BROWSER_BINARY')
    if chrome_binary and os.path.exists(chrome_binary):
        logger.info(f"🔍 Chrome-Binary aus Umgebungsvariable gefunden: {chrome_binary}")
        return chrome_binary
    
    # Liste möglicher Chrome-Binaries nach Betriebssystem
    potential_paths = []
    
    # Linux-Pfade
    if os.name == 'posix' and not os.path.exists('/proc/sys/kernel/osrelease') or \
       os.path.exists('/proc/sys/kernel/osrelease') and 'microsoft' not in open('/proc/sys/kernel/osrelease').read().lower():
        # Standard Linux-Pfade (nicht WSL)
        potential_paths.extend([
            "/usr/bin/google-chrome-stable",
            "/usr/bin/google-chrome",
            "/usr/bin/chromium-browser",
            "/usr/bin/chromium",
            # Container-spezifische Pfade
            "/usr/local/bin/chrome",
            "/usr/local/bin/google-chrome",
            # Zusätzliche Pfade für verschiedene Distributionen
            "/snap/bin/chromium",
            "/var/lib/snapd/snap/bin/chromium"
        ])
    
    # MacOS-Pfade
    elif os.name == 'posix' and os.path.exists('/Applications'):
        potential_paths.extend([
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium"
        ])
    
    # Windows-Pfade
    elif os.name == 'nt':
        potential_paths.extend([
            "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
            "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
            # Weitere typische Windows-Installationspfade
            os.path.expandvars("%LOCALAPPDATA%\\Google\\Chrome\\Application\\chrome.exe"),
            os.path.expanduser("~\\AppData\\Local\\Google\\Chrome\\Application\\chrome.exe")
        ])
    
    # Prüfen Sie jeden Pfad
    for path in potential_paths:
        if os.path.exists(path):
            logger.info(f"🔍 Chrome-Binary gefunden unter: {path}")
            return path
    
    # Wenn kein expliziter Pfad gefunden wurde, versuche Chrome über Systembefehle zu finden
    try:
        if os.name == 'posix':
            # Unter Linux/Mac versuchen wir, den Pfad mit 'which' zu finden
            import subprocess
            chrome_path = subprocess.check_output(['which', 'google-chrome'], 
                                                 stderr=subprocess.STDOUT).decode().strip()
            if chrome_path and os.path.exists(chrome_path):
                logger.info(f"🔍 Chrome-Binary mit 'which' gefunden: {chrome_path}")
                return chrome_path
                
            # Versuche es mit chromium
            try:
                chromium_path = subprocess.check_output(['which', 'chromium-browser'], 
                                                      stderr=subprocess.STDOUT).decode().strip()
                if chromium_path and os.path.exists(chromium_path):
                    logger.info(f"🔍 Chromium-Binary mit 'which' gefunden: {chromium_path}")
                    return chromium_path
            except subprocess.CalledProcessError:
                pass
    except Exception as e:
        logger.debug(f"⚠️ Fehler bei der Suche nach Chrome über Systembefehle: {e}")
    
    # Fallback auf den Docker-Chrome-Pfad in der Render-Umgebung
    if os.environ.get('RENDER_ENVIRONMENT') == 'true':
        render_chrome_path = "/usr/bin/google-chrome-stable"
        logger.info(f"🔍 Render-Umgebung erkannt, verwende Standard-Pfad: {render_chrome_path}")
        return render_chrome_path
    
    logger.warning("⚠️ Kein Chrome-Binary gefunden. Selenium könnte nicht funktionieren.")
    return None

def create_browser(proxy=None, user_agent=None):
    """
    Erstellt einen neuen Selenium-Browser mit optimierten Einstellungen
    und erweiterter Fehlerbehandlung.
    
    :param proxy: Optional - Proxy-Server für den Browser
    :param user_agent: Optional - Benutzerdefinierter User-Agent
    :return: Selenium WebDriver Instanz oder None bei Fehler
    """
    try:
        options = Options()
        
        # Chrome Binary Pfad konfigurieren - mit verbesserter Erkennung
        chrome_binary = detect_chrome_binary()
        if chrome_binary:
            options.binary_location = chrome_binary
        
        # Headless-Modus basierend auf Konfiguration
        if SELENIUM_HEADLESS:
            options.add_argument("--headless=new")
        
        # Performance-Optimierungen
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-sandbox")  # Wichtig für Container/CI-Umgebungen
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-infobars")
        options.add_argument("--disable-notifications")
        options.add_argument("--disable-popup-blocking")
        
        # Verhindert Bot-Erkennung
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        
        # Bei Server-Umgebungen ohne Display
        if os.environ.get('RENDER_ENVIRONMENT') == 'true' or os.environ.get('CI') == 'true':
            logger.info("🖥️ Server-Umgebung erkannt, konfiguriere für Headless-Betrieb")
            options.add_argument("--headless=new")
            options.add_argument("--no-sandbox")
            options.add_argument("--window-size=1920,1080")
        
        # Proxy konfigurieren, falls angegeben
        if proxy:
            options.add_argument(f'--proxy-server={proxy}')
        
        # Zufälliger User-Agent für natürlicheres Verhalten
        if not user_agent:
            user_agents = [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
            ]
            user_agent = random.choice(user_agents)
        
        options.add_argument(f"--user-agent={user_agent}")
        
        # Verwende webdriver_manager für automatische Updates des ChromeDrivers
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
        # Erweiterte Fehlerinformationen ausgeben
        if 'cannot find Chrome binary' in str(e):
            logger.error("💡 Chrome wurde nicht gefunden. Stellen Sie sicher, dass Chrome installiert ist.")
            logger.error(f"💡 Umgebungsvariable SELENIUM_BROWSER_BINARY ist: {os.environ.get('SELENIUM_BROWSER_BINARY', 'nicht gesetzt')}")
            
            # Versuche, verfügbare Browser aufzulisten
            try:
                if os.name == 'posix':
                    import subprocess
                    logger.info("🔍 Suche nach installierten Browsern...")
                    subprocess.call(["which", "google-chrome"], stderr=subprocess.STDOUT)
                    subprocess.call(["which", "chromium-browser"], stderr=subprocess.STDOUT)
                    subprocess.call(["ls", "-l", "/usr/bin/google-chrome*"], stderr=subprocess.STDOUT)
            except Exception:
                pass
        return None

def initialize_browser_pool():
    """
    Initialisiert den Browser-Pool mit der konfigurierten Anzahl von Browsern.
    Bei Fehlern wird ein fallback-Mechanismus aktiviert, der später
    bei Bedarf browserlose Funktionalität ermöglicht.
    
    :return: True wenn erfolgreich, False bei kritischen Fehlern
    """
    global browser_pool
    
    logger.info(f"🔄 Initialisiere Browser-Pool mit {BROWSER_POOL_SIZE} Browsern")
    
    # Zähle erfolgreiche Browser-Initialisierungen
    success_count = 0
    
    for _ in range(BROWSER_POOL_SIZE):
        try:
            browser = create_browser()
            if browser:
                browser_id = id(browser)
                browser_use_count[browser_id] = 0
                browser_pool.put(browser)
                success_count += 1
            else:
                logger.warning("⚠️ Browser konnte nicht erstellt werden, überspringe...")
        except Exception as e:
            logger.error(f"❌ Fehler beim Erstellen eines Browsers: {e}")
    
    # Prüfe, ob mindestens ein Browser erstellt werden konnte
    if success_count > 0:
        logger.info(f"✅ Browser-Pool initialisiert mit {success_count} Browsern")
        return True
    else:
        logger.error("❌ Keine Browser konnten erstellt werden. Gehe in den Fallback-Modus über.")
        return False

def get_browser_from_pool():
    """
    Holt einen Browser aus dem Pool oder erstellt einen neuen bei Bedarf.
    Bei Fehlern wird ein retry-Mechanismus verwendet.
    
    :return: Browser-Instanz oder None bei kritischen Fehlern
    """
    with browser_semaphore:
        with browser_pool_lock:
            if browser_pool.empty():
                logger.info("🔄 Browser-Pool leer, erstelle neuen Browser")
                for attempt in range(MAX_RETRY_ATTEMPTS):
                    try:
                        browser = create_browser()
                        if browser:
                            browser_id = id(browser)
                            browser_use_count[browser_id] = 0
                            return browser
                        else:
                            logger.warning(f"⚠️ Browser konnte nicht erstellt werden (Versuch {attempt+1}/{MAX_RETRY_ATTEMPTS})")
                            time.sleep(1)  # Kurze Pause zwischen Versuchen
                    except Exception as e:
                        logger.error(f"❌ Fehler beim Erstellen eines Browsers (Versuch {attempt+1}/{MAX_RETRY_ATTEMPTS}): {e}")
                        time.sleep(1)
                
                logger.error("❌ Alle Versuche, einen Browser zu erstellen, sind fehlgeschlagen")
                return None
            
            browser = browser_pool.get()
            browser_id = id(browser)
            
            # Prüfe, ob Browser zu oft verwendet wurde und erstelle ggf. einen neuen
            if browser_use_count.get(browser_id, 0) >= BROWSER_MAX_USES:
                logger.info(f"🔄 Browser hat Nutzungslimit erreicht ({BROWSER_MAX_USES}), erstelle neuen Browser")
                try:
                    browser.quit()
                except:
                    pass
                
                # Neuen Browser erstellen
                for attempt in range(MAX_RETRY_ATTEMPTS):
                    try:
                        browser = create_browser()
                        if browser:
                            browser_id = id(browser)
                            browser_use_count[browser_id] = 0
                            return browser
                    except Exception as e:
                        logger.error(f"❌ Fehler beim Erstellen eines Ersatz-Browsers: {e}")
                
                # Wenn alle Versuche fehlschlagen
                logger.error("❌ Konnte keinen Ersatz-Browser erstellen")
                return None
            
            return browser

def return_browser_to_pool(browser):
    """
    Gibt einen Browser zurück in den Pool und aktualisiert die Nutzungsstatistik.
    
    :param browser: Browser-Instanz
    """
    if not browser:
        return
        
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
    """
    Schließt alle Browser im Pool sicher und gibt Ressourcen frei.
    
    :return: Anzahl der geschlossenen Browser
    """
    closed_count = 0
    
    logger.info("🔄 Schließe Browser-Pool")
    with browser_pool_lock:
        while not browser_pool.empty():
            browser = browser_pool.get()
            try:
                browser.quit()
                closed_count += 1
            except Exception as e:
                logger.warning(f"⚠️ Fehler beim Schließen eines Browsers: {e}")
    
    # Statistiken ausgeben
    logger.info(f"✅ {closed_count} Browser wurden geschlossen")
    return closed_count

def extract_data_with_selenium(url, extraction_function=None, timeout=SELENIUM_TIMEOUT, max_retries=2):
    """
    Extrahiert Daten von einer URL mit Selenium. Dies ist die Hauptfunktion,
    die von externen Modulen aufgerufen werden sollte.
    
    :param url: Die zu besuchende URL
    :param extraction_function: Funktion zur Datenextraktion, die den Browser als Parameter erhält
    :param timeout: Timeout in Sekunden
    :param max_retries: Maximale Anzahl an Wiederholungsversuchen
    :return: Extrahierte Daten oder None bei Fehler
    """
    browser = None
    result = None
    
    # Standardwerte für das Ergebnis
    default_result = {
        "title": None,
        "price": "Preis nicht verfügbar",
        "is_available": False,
        "status_text": "[?] Status unbekannt"
    }
    
    with browser_semaphore:
        try:
            # Browser aus dem Pool holen
            browser = get_browser_from_pool()
            if not browser:
                logger.warning("⚠️ Kein Browser verfügbar für die Datenextraktion")
                return default_result
            
            # Zufällige Verzögerung für natürlicheres Verhalten
            time.sleep(random.uniform(1, 2))
            
            # Versuche, die URL zu laden
            retry_count = 0
            while retry_count <= max_retries:
                try:
                    logger.info(f"🌐 Lade Seite mit Selenium: {url}")
                    browser.get(url)
                    
                    # Warte auf das Laden der Seite
                    WebDriverWait(browser, timeout).until(
                        EC.presence_of_element_located((By.TAG_NAME, "body"))
                    )
                    
                    # Wenn eine benutzerdefinierte Extraktionsfunktion bereitgestellt wurde, verwenden wir diese
                    if extraction_function and callable(extraction_function):
                        result = extraction_function(browser)
                    else:
                        # Standard-Extraktionsfunktion
                        result = extract_product_details(browser, url)
                    
                    break  # Erfolgreicher Versuch, Schleife beenden
                    
                except TimeoutException:
                    retry_count += 1
                    logger.warning(f"⚠️ Timeout beim Laden von {url} (Versuch {retry_count}/{max_retries})")
                    if retry_count <= max_retries:
                        # Exponentielles Backoff
                        wait_time = 2 ** retry_count
                        logger.info(f"🕒 Warte {wait_time} Sekunden vor dem nächsten Versuch...")
                        time.sleep(wait_time)
                except WebDriverException as e:
                    retry_count += 1
                    logger.warning(f"⚠️ WebDriver-Fehler: {e} (Versuch {retry_count}/{max_retries})")
                    if retry_count <= max_retries:
                        time.sleep(2 ** retry_count)
                except Exception as e:
                    retry_count += 1
                    logger.warning(f"⚠️ Unerwarteter Fehler: {e} (Versuch {retry_count}/{max_retries})")
                    if retry_count <= max_retries:
                        time.sleep(2 ** retry_count)
            
            # Wenn alle Versuche fehlgeschlagen sind
            if retry_count > max_retries:
                logger.error(f"❌ Alle {max_retries} Versuche, {url} zu laden, sind fehlgeschlagen")
                return default_result
            
            return result or default_result
            
        except Exception as e:
            logger.error(f"❌ Kritischer Fehler bei der Selenium-Extraktion: {e}")
            return default_result
        finally:
            # Browser zurück in den Pool oder aufräumen
            if browser:
                try:
                    # Cookies löschen für sauberen nächsten Besuch
                    browser.delete_all_cookies()
                    return_browser_to_pool(browser)
                except Exception as e:
                    logger.warning(f"⚠️ Fehler beim Aufräumen des Browsers: {e}")

def extract_product_details(browser, url):
    """
    Standard-Extraktionsfunktion für Produktdetails.
    Kann als Basis für produktspezifische Extraktionsfunktionen verwendet werden.
    
    :param browser: Selenium WebDriver Browser-Instanz
    :param url: URL der Produktseite
    :return: Dictionary mit Produktdetails
    """
    result = {
        "title": None,
        "price": "Preis nicht verfügbar",
        "is_available": False,
        "status_text": "[?] Status unbekannt"
    }
    
    try:
        # Titel extrahieren
        try:
            title_element = WebDriverWait(browser, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".product-details__product-title, h1.title, h1"))
            )
            result["title"] = title_element.text.strip()
        except (TimeoutException, NoSuchElementException):
            logger.warning(f"⚠️ Titel konnte nicht gefunden werden für {url}")
        
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
                        return result
                else:
                    # Suche nach Element mit Selektor
                    if browser.find_elements(By.CSS_SELECTOR, indicator):
                        result["is_available"] = False
                        result["status_text"] = f"[X] Ausverkauft (Element {indicator} gefunden)"
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
                        return result
                else:
                    if browser.find_elements(By.CSS_SELECTOR, indicator):
                        result["is_available"] = True
                        result["status_text"] = f"[V] Vorbestellbar (Element {indicator} gefunden)"
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
                            return result
                    else:
                        # Andere Text-Indikatoren
                        page_text = browser.find_element(By.TAG_NAME, "body").text
                        if indicator in page_text:
                            result["is_available"] = True
                            result["status_text"] = f"[V] Verfügbar ({indicator} gefunden)"
                            return result
                else:
                    # Suche nach Element mit Selektor
                    if browser.find_elements(By.CSS_SELECTOR, indicator):
                        result["is_available"] = True
                        result["status_text"] = f"[V] Verfügbar (Element {indicator} gefunden)"
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
        
        return result
        
    except Exception as e:
        logger.error(f"❌ Fehler bei der Produktdetail-Extraktion: {e}")
        return result

# Spezialisierte Funktion für mighty-cards.de
def extract_mighty_cards_product_info(url, timeout=SELENIUM_TIMEOUT):
    """
    Spezialisierte Extraktionsfunktion für mighty-cards.de
    
    :param url: URL der Produktseite
    :param timeout: Timeout in Sekunden
    :return: Dictionary mit Produktdetails
    """
    return extract_data_with_selenium(url, extraction_function=None, timeout=timeout)

def is_selenium_available():
    """
    Prüft, ob Selenium-Funktionalität verfügbar ist.
    
    :return: True wenn Selenium verfügbar ist, False sonst
    """
    try:
        # Versuche, einen Browser für einen schnellen Test zu erstellen
        browser = create_browser()
        if browser:
            browser.quit()
            return True
        return False
    except Exception:
        return False

def get_pool_stats():
    """
    Gibt Statistiken zum Browser-Pool zurück.
    
    :return: Dictionary mit Statistiken
    """
    with browser_pool_lock:
        stats = {
            "pool_size": browser_pool.qsize(),
            "max_pool_size": BROWSER_POOL_SIZE,
            "browsers_in_use": BROWSER_POOL_SIZE - browser_pool.qsize(),
            "browser_usage_counts": dict(browser_use_count),
            "average_browser_usage": sum(browser_use_count.values()) / len(browser_use_count) if browser_use_count else 0,
            "selenium_available": is_selenium_available(),
            "chrome_binary_path": detect_chrome_binary()
        }
        return stats