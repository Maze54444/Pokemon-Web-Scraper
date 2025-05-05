"""
Zentrale Anfrage-Behandlung mit erweiterter Fehlertoleranz

Dieses Modul stellt robust implementierte Funktionen für HTTP-Anfragen
bereit, mit Unterstützung für SSL-Zertifikat-Fehler, Timeouts und
anderen Netzwerkproblemen.
"""

import requests
import logging
import time
import random
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from requests.packages.urllib3.exceptions import InsecureRequestWarning
from urllib3.exceptions import SSLError, ConnectTimeoutError
from urllib.parse import urlparse  # Import hinzugefügt, um den Fehler zu beheben

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

# Liste von Domains mit bekannten Timeout-Problemen, die längere Timeouts benötigen
SLOW_DOMAINS = [
    "games-island.eu",
    "www.games-island.eu"
]

def get_random_user_agent():
    """
    Gibt einen zufälligen User-Agent zurück
    
    :return: Ein zufälliger User-Agent String
    """
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.4 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.159 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36 Edg/90.0.818.66",
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

def create_session_with_retries(retries=MAX_RETRIES, backoff_factor=BACKOFF_FACTOR, 
                                status_forcelist=(500, 502, 503, 504)):
    """
    Erstellt eine Session mit Retry-Mechanismus
    
    :param retries: Anzahl der Wiederholungsversuche
    :param backoff_factor: Faktor für exponentielles Backoff
    :param status_forcelist: Liste von HTTP-Statuscodes, die wiederholt werden sollen
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
    
    return session

def fetch_url(url, headers=None, timeout=DEFAULT_TIMEOUT, max_retries=MAX_RETRIES, 
              verify_ssl=True, allow_redirects=True):
    """
    Robuste Funktion zum Abrufen einer URL mit erweiterter Fehlerbehandlung
    
    :param url: Die abzurufende URL
    :param headers: Optional - HTTP-Headers für die Anfrage
    :param timeout: Timeout in Sekunden
    :param max_retries: Maximale Anzahl von Wiederholungsversuchen
    :param verify_ssl: SSL-Zertifikate überprüfen (True/False)
    :param allow_redirects: Weiterleitungen folgen (True/False)
    :return: Tuple (response, error_message)
    """
    if headers is None:
        headers = get_default_headers()
    
    # Extrahiere Domain aus URL
    domain = extract_domain(url)
    
    # Prüfe, ob die Domain in der Liste der problematischen SSL-Domains ist
    if domain in SSL_PROBLEMATIC_DOMAINS:
        verify_ssl = False
        # Unterdrücke die InsecureRequestWarning für bekannte problematische Domains
        requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
    
    # Prüfe, ob die Domain in der Liste der langsamen Domains ist
    if domain in SLOW_DOMAINS:
        # Erhöhe Timeout für langsame Domains
        timeout = timeout * 1.5
    
    # Füge einen Referer-Header hinzu, wenn nicht vorhanden
    if "Referer" not in headers:
        base_url = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
        headers["Referer"] = base_url
    
    # Retry-Counter initialisieren
    retry_count = 0
    
    # Verschiedene Fehlertypen für besseres Logging
    ssl_error = False
    timeout_error = False
    connection_error = False
    
    while retry_count <= max_retries:
        try:
            # Verwende Session für bessere Performance und Retry-Mechanismus
            session = create_session_with_retries(retries=max_retries)
            
            # Führe die Anfrage aus
            response = session.get(
                url, 
                headers=headers, 
                timeout=timeout,
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
            timeout = timeout * 1.5
            
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
            # Exponentielles Backoff zwischen Wiederholungsversuchen
            wait_time = BACKOFF_FACTOR * (2 ** (retry_count - 1))
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

def get_page_content(url, headers=None, timeout=DEFAULT_TIMEOUT, max_retries=MAX_RETRIES, 
                     verify_ssl=True, parser="html.parser"):
    """
    Kombinierte Funktion zum Abrufen und Parsen einer Webseite
    
    :param url: Die abzurufende URL
    :param headers: Optional - HTTP-Headers für die Anfrage
    :param timeout: Timeout in Sekunden
    :param max_retries: Maximale Anzahl von Wiederholungsversuchen
    :param verify_ssl: SSL-Zertifikate überprüfen (True/False)
    :param parser: HTML-Parser für BeautifulSoup
    :return: Tuple (success, soup, status_code, error_message)
    """
    # Setze Header, falls nicht übergeben
    if headers is None:
        headers = get_default_headers()
    
    # URL abrufen mit robuster Fehlerbehandlung
    response, error = fetch_url(
        url, 
        headers=headers, 
        timeout=timeout, 
        max_retries=max_retries, 
        verify_ssl=verify_ssl
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