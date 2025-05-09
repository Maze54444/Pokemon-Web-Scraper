"""
Zentrale Anfrage-Behandlung mit erweiterter Fehlertoleranz und Anti-Blocking-Funktionen

Dieses Modul stellt robust implementierte Funktionen für HTTP-Anfragen bereit, mit:
- Unterstützung für SSL-Zertifikat-Fehler
- Zeitlimits und Wiederholungsversuchen
- Umgehung von Bot-Erkennungssystemen wie Cloudflare 
- Optionale Proxy-Unterstützung
"""

import requests
import logging
import time
import random
import json
import os
from pathlib import Path
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from requests.packages.urllib3.exceptions import InsecureRequestWarning
from urllib3.exceptions import SSLError, ConnectTimeoutError
from urllib.parse import urlparse

# Logger konfigurieren
logger = logging.getLogger(__name__)

# Standardeinstellungen
DEFAULT_TIMEOUT = 15  # Sekunden
MAX_RETRIES = 3
BACKOFF_FACTOR = 1.5

# Liste problematischer Domains, die SSL-Fehler verursachen und mit verify=False behandelt werden sollten
SSL_PROBLEMATIC_DOMAINS = [
    "www.gameware.at",
    "gameware.at"
]

# Liste von Domains mit bekannten Timeout-Problemen oder Anti-Bot-Systemen
PROBLEMATIC_DOMAINS = [
    "games-island.eu",
    "www.games-island.eu",
    "sapphire-cards.de",
    "www.sapphire-cards.de"
]

# Spezielle Timeouts für problematische Seiten
DOMAIN_TIMEOUTS = {
    "games-island.eu": 40,  # Erhöht auf 40 Sekunden
    "www.games-island.eu": 40,
    "sapphire-cards.de": 20,
    "www.sapphire-cards.de": 20
}

# Maximale Retry-Versuche für problematische Domains
DOMAIN_MAX_RETRIES = {
    "games-island.eu": 3,  # Reduziert, aber mit besserer Strategie
    "www.games-island.eu": 3
}

# Liste von URLs, die komplett übersprungen werden sollen
SKIP_URLS = [
    "https://games-island.eu/",
    "https://www.games-island.eu/"
]

# Proxy-Konfiguration (optional)
USE_PROXIES = False  # Auf True setzen, wenn Proxies verfügbar sind
PROXIES = [
    # Format: "http://user:pass@ip:port" oder "http://ip:port"
]

# Proxy-Konfigurationsdatei
PROXY_CONFIG_FILE = "config/proxies.json"

# Cache für HTTP-Responses, um wiederholte Anfragen zu vermeiden
RESPONSE_CACHE = {}
CACHE_EXPIRY = 15 * 60  # 15 Minuten in Sekunden

def init_proxy_config():
    """
    Initialisiert die Proxy-Konfiguration aus einer Datei
    """
    global USE_PROXIES, PROXIES
    
    try:
        if os.path.exists(PROXY_CONFIG_FILE):
            with open(PROXY_CONFIG_FILE, "r", encoding="utf-8") as f:
                proxy_config = json.load(f)
                USE_PROXIES = proxy_config.get("use_proxies", False)
                PROXIES = proxy_config.get("proxies", [])
                
                if USE_PROXIES and PROXIES:
                    logger.info(f"🔄 Proxy-Konfiguration geladen: {len(PROXIES)} Proxies verfügbar")
                elif USE_PROXIES and not PROXIES:
                    logger.warning("⚠️ Proxy-Nutzung aktiviert, aber keine Proxies konfiguriert")
                    USE_PROXIES = False
    except Exception as e:
        logger.warning(f"⚠️ Fehler beim Laden der Proxy-Konfiguration: {e}")
        USE_PROXIES = False
        PROXIES = []

# Proxy-Konfiguration initialisieren
init_proxy_config()

def get_random_user_agent():
    """
    Gibt einen zufälligen User-Agent zurück
    
    :return: Ein zufälliger User-Agent String
    """
    user_agents = [
        # Desktop Browser
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.45 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.93 Safari/537.36 Edg/96.0.1054.43",
        
        # Neuere Mobile User-Agents für mehr Vielfalt
        "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (iPad; CPU OS 15_0_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1"
    ]
    return random.choice(user_agents)

def get_default_headers():
    """
    Erstellt Standard-HTTP-Headers mit zufälligem User-Agent
    
    :return: Dictionary mit HTTP-Headers
    """
    return {
        "User-Agent": get_random_user_agent(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1"
    }

def get_cloudflare_friendly_headers(url=None):
    """
    Erstellt umfangreichere Cloudflare-freundliche HTTP-Headers
    
    :param url: Optional - URL für domain-spezifische Anpassungen
    :return: Dictionary mit HTTP-Headers
    """
    user_agent = get_random_user_agent()
    
    # Zufällige Referer von bekannten Webseiten
    referers = [
        "https://www.google.de/",
        "https://www.google.com/",
        "https://www.bing.com/",
        "https://duckduckgo.com/",
        "https://www.pokemon.com/de/",
        "https://www.pokemoncenter.com/"
    ]
    
    # Wenn URL übergeben wurde, füge die Basis-URL zu den Referers hinzu
    if url:
        domain = extract_domain(url)
        try:
            parsed_url = urlparse(url)
            base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
            referers.append(base_url)
        except:
            pass
    
    # Länderspezifische Akzeptanz-Header für DE
    accept_language = "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7"
    
    # Chrome-Browser Kennung (für Cloudflare wichtig)
    chrome_version = f"{random.randint(90, 108)}.0.{random.randint(1000, 9999)}.{random.randint(10, 999)}"
    
    return {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": accept_language,
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": random.choice(referers),
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
        "sec-ch-ua": f'"Chromium";v="{chrome_version}", "Google Chrome";v="{chrome_version}", "Not=A?Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"'
    }

def create_session_with_retries(retries=MAX_RETRIES, backoff_factor=BACKOFF_FACTOR, 
                                status_forcelist=(500, 502, 503, 504), timeout=DEFAULT_TIMEOUT):
    """
    Erstellt eine Session mit Retry-Mechanismus
    
    :param retries: Anzahl der Wiederholungsversuche
    :param backoff_factor: Faktor für exponentielles Backoff
    :param status_forcelist: Liste von HTTP-Statuscodes, die wiederholt werden sollen
    :param timeout: Timeout für die Session
    :return: Konfigurierte requests.Session
    """
    session = requests.Session()
    
    retry_strategy = Retry(
        total=retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
        allowed_methods=["GET", "POST"]
    )
    
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    # Fehler behoben: Die originale request-Methode speichern und dann überschreiben
    original_request = session.request
    session.request = lambda method, url, **kwargs: original_request(
        method=method, url=url, timeout=kwargs.pop('timeout', timeout), **kwargs
    )
    
    return session

def extract_domain(url):
    """
    Extrahiert die Domain aus einer URL
    
    :param url: Die zu analysierende URL
    :return: Domain ohne Protokoll und Pfad
    """
    try:
        parsed_url = urlparse(url)
        domain = parsed_url.netloc
        
        # Entferne www. Präfix, falls vorhanden
        if domain.startswith('www.'):
            domain = domain[4:]
            
        return domain.lower()
    except Exception as e:
        logger.debug(f"Fehler beim Extrahieren der Domain aus {url}: {e}")
        return None

def get_random_proxy():
    """
    Wählt einen zufälligen Proxy aus der Liste
    
    :return: Dictionary mit Proxy-Konfiguration oder None
    """
    if not USE_PROXIES or not PROXIES:
        return None
        
    proxy = random.choice(PROXIES)
    return {
        "http": proxy,
        "https": proxy
    }

def fetch_url(url, headers=None, timeout=None, max_retries=None, 
              verify_ssl=True, allow_redirects=True, use_cache=True, 
              use_cloudflare_bypass=None, use_proxy=None):
    """
    Robuste Funktion zum Abrufen einer URL mit erweiterter Fehlerbehandlung
    
    :param url: Die abzurufende URL
    :param headers: Optional - HTTP-Headers für die Anfrage
    :param timeout: Timeout in Sekunden (Domain-spezifische Werte haben Vorrang)
    :param max_retries: Maximale Anzahl von Wiederholungsversuchen (Domain-spezifische Werte haben Vorrang)
    :param verify_ssl: SSL-Zertifikate überprüfen (True/False)
    :param allow_redirects: Weiterleitungen folgen (True/False)
    :param use_cache: Verwende Cache für diese Anfrage
    :param use_cloudflare_bypass: Ob Cloudflare-freundliche Header verwendet werden sollen
    :param use_proxy: Ob ein Proxy verwendet werden soll
    :return: Tuple (response, error_message)
    """
    # Generiere einen Cache-Schlüssel
    cache_key = f"{url}_{verify_ssl}_{allow_redirects}"
    
    # Prüfe, ob die Anfrage im Cache ist
    if use_cache and cache_key in RESPONSE_CACHE:
        cached_data = RESPONSE_CACHE[cache_key]
        cache_time = cached_data.get("timestamp", 0)
        
        # Wenn Cache noch gültig ist
        if time.time() - cache_time < CACHE_EXPIRY:
            logger.debug(f"🔄 Verwende gecachte Antwort für {url}")
            return cached_data.get("response"), None
    
    if headers is None:
        headers = get_default_headers()
    
    # Prüfe, ob die URL übersprungen werden soll
    if url in SKIP_URLS:
        logger.info(f"⚠️ Überspringe bekannte problematische URL: {url}")
        return None, "URL wurde übersprungen, da bekannt ist, dass sie Timeouts verursacht"
    
    # Extrahiere Domain aus URL
    domain = extract_domain(url)
    
    # Spezialfall: games-island.eu mit strengeren Anti-Bot-Maßnahmen
    is_problematic_domain = domain in PROBLEMATIC_DOMAINS
    
    # Automatische Cloudflare-Umgehung für problematische Domains aktivieren
    if use_cloudflare_bypass is None:
        use_cloudflare_bypass = is_problematic_domain
    
    # Wenn Cloudflare-Umgehung aktiviert ist, verwende spezielle Header
    if use_cloudflare_bypass:
        headers = get_cloudflare_friendly_headers(url)
    
    # Domain-spezifische Einstellungen
    if domain in DOMAIN_TIMEOUTS:
        domain_timeout = DOMAIN_TIMEOUTS[domain]
        # Verwende den Domain-spezifischen Timeout, wenn keiner explizit angegeben wurde
        if timeout is None or timeout > domain_timeout:
            timeout = domain_timeout
            logger.debug(f"Verwende Domain-spezifischen Timeout für {domain}: {timeout}s")
    else:
        # Standard-Timeout, wenn nichts anderes angegeben wurde
        if timeout is None:
            timeout = DEFAULT_TIMEOUT
    
    # Domain-spezifische Wiederholungsversuche
    if domain in DOMAIN_MAX_RETRIES:
        domain_max_retries = DOMAIN_MAX_RETRIES[domain]
        # Verwende die Domain-spezifische Anzahl, wenn keine explizit angegeben wurde
        if max_retries is None or max_retries < domain_max_retries:
            max_retries = domain_max_retries
            logger.debug(f"Verwende Domain-spezifische Wiederholungsversuche für {domain}: {max_retries}")
    else:
        # Standard-Wiederholungsversuche, wenn nichts anderes angegeben wurde
        if max_retries is None:
            max_retries = MAX_RETRIES
    
    # Prüfe, ob die Domain in der Liste der problematischen SSL-Domains ist
    if domain in SSL_PROBLEMATIC_DOMAINS:
        verify_ssl = False
        # Unterdrücke die InsecureRequestWarning für bekannte problematische Domains
        requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
    
    # Verwende Proxy wenn gewünscht oder automatisch für problematische Domains
    if use_proxy is None:
        use_proxy = USE_PROXIES and is_problematic_domain
    
    proxies = get_random_proxy() if use_proxy else None
    
    # Sicherheitsmechanismus für problematische Domains, die häufig Timeouts verursachen
    if domain in PROBLEMATIC_DOMAINS and domain not in ["games-island.eu", "www.games-island.eu"]:
        # Für problematische Domains außer games-island.eu normale Strategie verwenden
        return fetch_with_retry(url, headers, timeout, max_retries, verify_ssl, 
                              allow_redirects, proxies, use_cloudflare_bypass)
    
    # Spezialfall für games-island.eu
    if domain in ["games-island.eu", "www.games-island.eu"]:
        logger.info(f"🔄 Verwende spezielle Behandlung für {domain}")
        
        # Maximale Anzahl von Versuchen für games-island.eu
        retry_attempts = 0
        while retry_attempts <= max_retries:
            try:
                # Jitter für Timing und abwechselnde Verzögerungen
                jitter = random.uniform(0.8, 1.2)
                
                # Bei Wiederholungen: Mehr Zufälligkeit und neue Header
                if retry_attempts > 0:
                    headers = get_cloudflare_friendly_headers(url)
                    
                    # Für eine natürliche Verzögerung (wie menschliches Verhalten)
                    wait_time = 2 * jitter * retry_attempts + random.uniform(2, 5)
                    logger.info(f"🔄 Wiederholungsversuch {retry_attempts}/{max_retries} für {url} in {wait_time:.1f} Sekunden")
                    time.sleep(wait_time)
                    
                    # Ggf. Proxy rotieren
                    if use_proxy and USE_PROXIES and PROXIES:
                        proxies = get_random_proxy()
                
                # Verwende Session für bessere Performance und Cookie-Handling
                session = requests.Session()
                if proxies:
                    session.proxies.update(proxies)
                
                # Füge einen Referer-Header hinzu, wenn nicht vorhanden
                if "Referer" not in headers:
                    headers["Referer"] = random.choice([
                        "https://www.google.com/search?q=games+island+pokemon",
                        "https://www.bing.com/search?q=pokemon+karmesin+purpur+reisegefährten",
                        "https://www.pokemon.com/de/"
                    ])
                
                session.headers.update(headers)
                
                # Führe die Anfrage aus
                response = session.get(
                    url, 
                    timeout=timeout,
                    verify=verify_ssl,
                    allow_redirects=allow_redirects
                )
                
                # Bei erfolgreicher Antwort im Cache speichern
                if use_cache and response.status_code == 200:
                    RESPONSE_CACHE[cache_key] = {
                        "response": response,
                        "timestamp": time.time()
                    }
                
                return response, None
                
            except requests.exceptions.Timeout:
                retry_attempts += 1
                logger.warning(f"⚠️ Timeout bei der Anfrage an {url} (Versuch {retry_attempts})")
            except requests.exceptions.RequestException as e:
                retry_attempts += 1
                logger.warning(f"⚠️ Fehler bei der Anfrage an {url}: {e} (Versuch {retry_attempts})")
            except Exception as e:
                retry_attempts += 1
                logger.warning(f"⚠️ Unerwarteter Fehler: {e} (Versuch {retry_attempts})")
                
        # Alle Versuche fehlgeschlagen
        error_message = f"Alle {max_retries} Versuche für {url} fehlgeschlagen"
        logger.error(f"❌ {error_message}")
        return None, error_message
    
    # Für alle anderen Domains: Standard-Strategie verwenden
    return fetch_with_retry(url, headers, timeout, max_retries, verify_ssl, 
                          allow_redirects, proxies, use_cloudflare_bypass)

def fetch_with_retry(url, headers, timeout, max_retries, verify_ssl, 
                    allow_redirects, proxies=None, use_cloudflare_bypass=False):
    """
    Hilfs-Funktion für fetch_url mit einheitlicher Retry-Strategie
    
    :return: Tuple (response, error_message)
    """
    # Retry-Counter initialisieren
    retry_count = 0
    
    # Verschiedene Fehlertypen für besseres Logging
    ssl_error = False
    timeout_error = False
    connection_error = False
    
    while retry_count <= max_retries:
        try:
            # Bei Wiederholungen: Neue Headers und ggf. Proxy
            if retry_count > 0:
                if use_cloudflare_bypass:
                    headers = get_cloudflare_friendly_headers(url)
                else:
                    headers["User-Agent"] = get_random_user_agent()
                
                if USE_PROXIES and PROXIES:
                    proxies = get_random_proxy()
            
            # Verwende Session für bessere Performance und Retry-Mechanismus
            session = create_session_with_retries(retries=1, timeout=timeout)  # Weniger interne Retries
            
            # Proxy verwenden, falls vorhanden
            if proxies:
                session.proxies.update(proxies)
            
            # Headers setzen
            session.headers.update(headers)
            
            # Führe die Anfrage aus
            response = session.get(
                url, 
                verify=verify_ssl,
                allow_redirects=allow_redirects
            )
            
            # Bei erfolgreicher Antwort zurückgeben
            return response, None
            
        except requests.exceptions.SSLError as e:
            ssl_error = True
            error_message = f"SSL-Fehler: {str(e)}"
            logger.warning(f"⚠️ SSL-Fehler beim Abrufen von {url}: {e}")
            
            # Wenn SSL-Fehler und wir SSL bisher verifiziert haben, versuche ohne Verifizierung
            if verify_ssl:
                logger.info(f"🔄 Versuche erneut ohne SSL-Verifizierung für: {url}")
                verify_ssl = False
                requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
                # Direkt erneut versuchen ohne Retry-Zähler zu erhöhen
                continue
            
        except (requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout) as e:
            timeout_error = True
            error_message = f"Timeout-Fehler: {str(e)}"
            logger.warning(f"⚠️ Timeout beim Abrufen von {url}: {e}")
            
            # Bei Timeout erhöhen wir den Timeout-Wert für den nächsten Versuch
            timeout = min(timeout * 1.5, 60)  # Erhöhe Timeout, max. 60 Sekunden
            
        except requests.exceptions.ConnectionError as e:
            connection_error = True
            error_message = f"Verbindungsfehler: {str(e)}"
            logger.warning(f"⚠️ Verbindungsfehler beim Abrufen von {url}: {e}")
            
        except Exception as e:
            error_message = f"Unerwarteter Fehler: {str(e)}"
            logger.warning(f"⚠️ Unerwarteter Fehler beim Abrufen von {url}: {e}")
        
        # Erhöhe Retry-Counter
        retry_count += 1
        
        if retry_count <= max_retries:
            # Exponentielles Backoff zwischen Wiederholungsversuchen mit Jitter
            jitter = random.uniform(0.8, 1.2)
            wait_time = BACKOFF_FACTOR * (2 ** (retry_count - 1)) * jitter
            logger.info(f"🔄 Wiederholungsversuch {retry_count}/{max_retries} für {url} in {wait_time:.1f} Sekunden")
            time.sleep(wait_time)
        else:
            # Maximale Anzahl von Wiederholungen erreicht
            if ssl_error:
                logger.error(f"❌ SSL-Fehler konnte nicht behoben werden für {url}")
            elif timeout_error:
                logger.error(f"❌ Timeout konnte nicht behoben werden für {url}")
            elif connection_error:
                logger.error(f"❌ Verbindungsfehler konnte nicht behoben werden für {url}")
            else:
                logger.error(f"❌ Fehler konnte nicht behoben werden für {url}")
    
    # Alle Wiederholungsversuche fehlgeschlagen
    return None, error_message

def parse_html(html_content, parser="html.parser"):
    """
    Parsed HTML-Inhalt zu einem BeautifulSoup-Objekt
    
    :param html_content: HTML-Inhalt als String oder Response-Objekt
    :param parser: HTML-Parser (Standard: html.parser, Alternative: lxml)
    :return: BeautifulSoup-Objekt
    """
    from bs4 import BeautifulSoup
    
    # Wenn html_content ein Response-Objekt ist, extrahiere den Text
    if hasattr(html_content, 'text'):
        html_content = html_content.text
    
    try:
        # Versuche zuerst mit lxml-Parser (schneller), fallback auf html.parser
        if parser == "lxml":
            try:
                return BeautifulSoup(html_content, "lxml")
            except ImportError:
                logger.warning("lxml-Parser nicht verfügbar, verwende html.parser")
                return BeautifulSoup(html_content, "html.parser")
        else:
            return BeautifulSoup(html_content, parser)
    except Exception as e:
        logger.error(f"❌ Fehler beim Parsen des HTML-Inhalts: {e}")
        # Leeres BeautifulSoup-Objekt als Fallback
        return BeautifulSoup("", "html.parser")

def get_page_content(url, headers=None, timeout=None, max_retries=None, 
                     verify_ssl=True, parser="html.parser", use_cache=True,
                     use_cloudflare_bypass=None, use_proxy=None):
    """
    Kombinierte Funktion zum Abrufen und Parsen einer Webseite
    
    :param url: Die abzurufende URL
    :param headers: Optional - HTTP-Headers für die Anfrage
    :param timeout: Timeout in Sekunden (Domain-spezifische Werte haben Vorrang)
    :param max_retries: Maximale Anzahl von Wiederholungsversuchen (Domain-spezifische Werte haben Vorrang)
    :param verify_ssl: SSL-Zertifikate überprüfen (True/False)
    :param parser: HTML-Parser für BeautifulSoup
    :param use_cache: Verwende Cache für diese Anfrage
    :param use_cloudflare_bypass: Ob Cloudflare-freundliche Header verwendet werden sollen
    :param use_proxy: Ob ein Proxy verwendet werden soll
    :return: Tuple (success, soup, status_code, error_message)
    """
    # Prüfe, ob die URL übersprungen werden soll
    if url in SKIP_URLS:
        logger.info(f"⚠️ Überspringe bekannte problematische URL: {url}")
        return False, None, None, "URL wurde übersprungen, da bekannt ist, dass sie Timeouts verursacht"
    
    # Setze Header, falls nicht übergeben
    if headers is None:
        headers = get_default_headers()
    
    # Extrahiere Domain für spezifische Einstellungen
    domain = extract_domain(url)
    
    # Spezielle Behandlung für bekannte problematische Domains
    is_problematic_domain = domain in PROBLEMATIC_DOMAINS
    
    # Automatische Cloudflare-Umgehung für problematische Domains aktivieren
    if use_cloudflare_bypass is None:
        use_cloudflare_bypass = is_problematic_domain
    
    # URL abrufen mit robuster Fehlerbehandlung
    response, error = fetch_url(
        url, 
        headers=headers, 
        timeout=timeout, 
        max_retries=max_retries, 
        verify_ssl=verify_ssl,
        use_cache=use_cache,
        use_cloudflare_bypass=use_cloudflare_bypass,
        use_proxy=use_proxy
    )
    
    # Wenn ein Fehler aufgetreten ist
    if error:
        return False, None, None, error
    
    # Wenn die Antwort erfolgreich war
    if response and response.status_code == 200:
        # Parse HTML
        soup = parse_html(response.content, parser)
        return True, soup, response.status_code, None
    elif response:
        # Fehlerstatuscode
        return False, None, response.status_code, f"HTTP-Fehlercode: {response.status_code}"
    else:
        # Sollte nicht passieren, aber zur Sicherheit
        return False, None, None, "Unbekannter Fehler: Keine Antwort und kein Fehler"

def clear_response_cache():
    """
    Löscht den Response-Cache
    
    :return: Anzahl der gelöschten Cache-Einträge
    """
    global RESPONSE_CACHE
    
    cache_size = len(RESPONSE_CACHE)
    RESPONSE_CACHE = {}
    
    logger.info(f"🧹 Response-Cache gelöscht ({cache_size} Einträge)")
    return cache_size

def invalidate_cache_for_domain(domain):
    """
    Löscht Cache-Einträge für eine bestimmte Domain
    
    :param domain: Domain, deren Cache-Einträge gelöscht werden sollen
    :return: Anzahl der gelöschten Cache-Einträge
    """
    global RESPONSE_CACHE
    
    removed_count = 0
    keys_to_remove = []
    
    for key in RESPONSE_CACHE.keys():
        if domain in key:
            keys_to_remove.append(key)
    
    for key in keys_to_remove:
        del RESPONSE_CACHE[key]
        removed_count += 1
    
    if removed_count > 0:
        logger.info(f"🧹 {removed_count} Cache-Einträge für Domain {domain} gelöscht")
        
    return removed_count

def check_domain_accessibility(domain, test_url=None, use_cloudflare_bypass=True):
    """
    Prüft, ob eine Domain aktuell erreichbar ist
    
    :param domain: Zu prüfende Domain (ohne Protokoll)
    :param test_url: Optional - Spezifische URL zum Testen
    :param use_cloudflare_bypass: Ob Cloudflare-freundliche Header verwendet werden sollen
    :return: Tuple (is_accessible, status_code, response_time)
    """
    # Standardmäßig die Hauptseite testen
    if not test_url:
        test_url = f"https://{domain}"
    
    start_time = time.time()
    
    try:
        # Headers für Cloudflare-Umgehung
        headers = get_cloudflare_friendly_headers(test_url) if use_cloudflare_bypass else get_default_headers()
        
        # Verwende Proxy, wenn verfügbar und aktiviert
        proxies = get_random_proxy() if USE_PROXIES and PROXIES else None
        
        # Verwende Session für bessere Performance
        session = requests.Session()
        if proxies:
            session.proxies.update(proxies)
        
        session.headers.update(headers)
        
        # Kurzer Timeout (wir wollen nur prüfen, ob die Domain antwortet)
        response = session.get(test_url, timeout=10, allow_redirects=True)
        
        # Zeitmessung
        response_time = time.time() - start_time
        
        return True, response.status_code, response_time
    
    except Exception as e:
        # Fehlgeschlagen, Domain möglicherweise nicht erreichbar
        response_time = time.time() - start_time
        logger.warning(f"⚠️ Domain {domain} nicht erreichbar: {e}")
        
        return False, None, response_time

def check_cloudflare_detection(domain, test_url=None):
    """
    Prüft, ob eine Domain durch Cloudflare geschützt ist und ob wir blockiert werden
    
    :param domain: Zu prüfende Domain (ohne Protokoll)
    :param test_url: Optional - Spezifische URL zum Testen
    :return: Tuple (has_cloudflare, is_blocked, challenge_type)
    """
    # Standardmäßig die Hauptseite testen
    if not test_url:
        test_url = f"https://{domain}"
    
    # Standard-Header verwenden (ohne Cloudflare-Umgehung)
    headers = get_default_headers()
    
    try:
        # Keine Proxies und keine erweiterten Header für diese Prüfung
        response = requests.get(test_url, headers=headers, timeout=10, allow_redirects=True)
        
        # Cloudflare-spezifische Erkennungsmerkmale prüfen
        has_cloudflare = False
        is_blocked = False
        challenge_type = None
        
        # Prüfe auf Cloudflare-Header
        server_header = response.headers.get("Server", "").lower()
        if "cloudflare" in server_header:
            has_cloudflare = True
        
        # Prüfe auf Cloudflare-Challenge (Captcha oder JavaScript-Challenge)
        if response.status_code == 403 or response.status_code == 503:
            content = response.text.lower()
            
            if "cloudflare" in content and ("captcha" in content or "challenge" in content):
                is_blocked = True
                
                if "captcha" in content:
                    challenge_type = "captcha"
                else:
                    challenge_type = "js_challenge"
        
        return has_cloudflare, is_blocked, challenge_type
    
    except Exception as e:
        logger.warning(f"⚠️ Fehler bei der Cloudflare-Prüfung für {domain}: {e}")
        # Bei Fehler nehmen wir an, dass Cloudflare aktiv sein könnte
        return True, True, "connection_error"

def generate_proxy_config_template(output_file=PROXY_CONFIG_FILE):
    """
    Erstellt eine Vorlage für die Proxy-Konfigurationsdatei
    
    :param output_file: Pfad zur Ausgabedatei
    :return: True bei Erfolg, False bei Fehler
    """
    try:
        # Stelle sicher, dass das Verzeichnis existiert
        Path(os.path.dirname(output_file)).mkdir(parents=True, exist_ok=True)
        
        config = {
            "use_proxies": False,
            "rotation_policy": "round_robin",  # oder "random"
            "proxies": [
                "http://user:pass@proxy1.example.com:8080",
                "http://user:pass@proxy2.example.com:8080",
                # Weitere Proxies hier hinzufügen
            ]
        }
        
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        
        logger.info(f"✅ Proxy-Konfigurationsvorlage erstellt: {output_file}")
        return True
    except Exception as e:
        logger.error(f"❌ Fehler beim Erstellen der Proxy-Konfigurationsvorlage: {e}")
        return False

def get_cache_stats():
    """
    Gibt Statistiken zum Response-Cache zurück
    
    :return: Dictionary mit Cache-Statistiken
    """
    current_time = time.time()
    valid_entries = 0
    expired_entries = 0
    
    # Zähle gültige und abgelaufene Einträge
    for key, entry in RESPONSE_CACHE.items():
        cache_time = entry.get("timestamp", 0)
        if current_time - cache_time < CACHE_EXPIRY:
            valid_entries += 1
        else:
            expired_entries += 1
    
    # Erstelle strukturierte Statistiken
    stats = {
        "total_entries": len(RESPONSE_CACHE),
        "valid_entries": valid_entries,
        "expired_entries": expired_entries,
        "cache_expiry_seconds": CACHE_EXPIRY,
        "domains": {}
    }
    
    # Zähle Einträge pro Domain
    for key in RESPONSE_CACHE.keys():
        try:
            url_part = key.split('_')[0]
            domain = extract_domain(url_part)
            if domain:
                if domain not in stats["domains"]:
                    stats["domains"][domain] = 0
                stats["domains"][domain] += 1
        except:
            pass
    
    return stats