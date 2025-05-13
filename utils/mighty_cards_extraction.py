"""
Mighty Cards Extraktion Modul

Dieses Modul bietet spezialisierte Funktionen zur Extraktion von Produktinformationen
von mighty-cards.de - es ist ein Hilfsmodul für den mighty_cards.py Scraper und 
ermöglicht eine bessere Modularisierung durch Trennung der Selenium-spezifischen 
Extraktionsfunktionen vom Hauptscraper.
"""

import logging
import time
import random
import re
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# Importiere die Selenium Manager Funktionen
import selenium_manager

# Logger konfigurieren
logger = logging.getLogger(__name__)

def extract_product_info_with_selenium(product_url, timeout=15):
    """
    Extrahiert Produktinformationen einer mighty-cards.de URL mit Selenium.
    Diese Funktion ist eine Brücke zwischen dem mighty_cards Scraper und dem Selenium Manager.
    
    :param product_url: URL der Produktseite
    :param timeout: Timeout in Sekunden
    :return: Dictionary mit Produktdetails
    """
    logger.info(f"🔍 Extrahiere Produktinfo für: {product_url}")
    
    # Verwende den selenium_manager für die eigentliche Extraktion
    result = selenium_manager.extract_mighty_cards_product_info(product_url, timeout)
    
    logger.info(f"✅ Extraktion abgeschlossen: {result['status_text']}")
    return result

def check_product_availability_with_selenium(product_url):
    """
    Prüft die Verfügbarkeit eines Produkts mit Selenium speziell für mighty-cards.de
    
    :param product_url: URL der Produktseite
    :return: Tuple (is_available, price, status_text)
    """
    product_info = extract_product_info_with_selenium(product_url)
    return (
        product_info.get("is_available", False),
        product_info.get("price", "Preis nicht verfügbar"),
        product_info.get("status_text", "[?] Status unbekannt")
    )

def check_product_availability_with_bs4(soup):
    """
    Prüft die Verfügbarkeit eines Produkts mit BeautifulSoup für mighty-cards.de
    
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

def process_product_matches_with_selenium(positive_matches):
    """
    Verarbeitet die positiven Treffer mit Selenium für präzise Preis- und Verfügbarkeitsinformationen
    
    :param positive_matches: Liste der positiven Treffer aus dem BeautifulSoup-Scanning
    :return: Liste der aktualisierten Produktinformationen
    """
    if not positive_matches:
        return []
    
    logger.info(f"🔄 Starte Selenium-Verarbeitung für {len(positive_matches)} positive Treffer")
    
    # Initialisiere den Browser-Pool
    try:
        selenium_manager.initialize_browser_pool()
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
            selenium_manager.shutdown_browser_pool()
        except Exception as e:
            logger.warning(f"⚠️ Fehler beim Schließen des Browser-Pools: {e}")
    
    return updated_matches

def is_selenium_available():
    """
    Prüft, ob Selenium verfügbar ist und korrekt funktioniert
    
    :return: True wenn Selenium verfügbar ist, False sonst
    """
    return selenium_manager.is_selenium_available()

def get_fallback_availability(product_title, product_url):
    """
    Bietet eine Fallback-Methode zur Verfügbarkeitsprüfung, wenn Selenium nicht funktioniert
    
    :param product_title: Titel des Produkts
    :param product_url: URL des Produkts
    :return: Tuple (is_available, price, status_text)
    """
    # Verwende heuristische Schätzung basierend auf dem Produkt-Titel und der URL
    # Dies ist natürlich weniger genau als die tatsächliche Prüfung
    
    # Standardpreis basierend auf Produkttyp
    price = "Preis nicht verfügbar"
    
    # Versuche, den Produkttyp zu erkennen und einen plausiblen Preis zu schätzen
    if re.search(r'display|36er|booster box', product_title.lower()):
        price = "129,95 €"  # Standardpreis für Displays
    elif re.search(r'etb|elite trainer box', product_title.lower()):
        price = "49,95 €"   # Standardpreis für ETBs
    elif re.search(r'tin', product_title.lower()):
        price = "24,95 €"   # Standardpreis für Tins
    
    # Standardmäßig als nicht verfügbar markieren, da dies der konservativere Ansatz ist
    return False, price, "[?] Status unbekannt (Fallback-Modus)"