"""
Zentrale Konfigurationsverwaltung für den Pokémon TCG Scraper

Dieses Modul stellt Funktionen zur vereinfachten Verwaltung aller Konfigurationseinstellungen 
des Scrapers bereit, einschließlich Laden, Validieren und Speichern von Konfigurationsdateien.
"""

import os
import json
import logging
from pathlib import Path
from datetime import datetime, date

# Logger konfigurieren
logger = logging.getLogger(__name__)

# Standard-Konfigurationspfade
DEFAULT_CONFIG_PATHS = {
    "schedule": "config/schedule.json",
    "telegram": "config/telegram_config.json",
    "synonyms": "config/synonyms.json",
    "products": "data/products.txt",
    "urls": "data/urls.txt",
    "seen": "data/seen.txt",
    "out_of_stock": "data/out_of_stock.txt",
    "product_cache": "data/product_cache.json"
}

# Erstellen der Verzeichnisse, falls sie nicht existieren
def ensure_directories():
    """Stellt sicher, dass alle erforderlichen Verzeichnisse existieren"""
    for path in DEFAULT_CONFIG_PATHS.values():
        directory = os.path.dirname(path)
        if directory:
            Path(directory).mkdir(parents=True, exist_ok=True)

# Laden und Validieren von JSON-Konfigurationsdateien
def load_json_config(config_type, default_value=None):
    """
    Lädt eine JSON-Konfigurationsdatei
    
    :param config_type: Typ der Konfiguration (schedule, telegram, synonyms, etc.)
    :param default_value: Standardwert, falls die Datei nicht existiert
    :return: Geladene Konfiguration oder Standardwert
    """
    if config_type not in DEFAULT_CONFIG_PATHS:
        logger.error(f"⚠️ Unbekannter Konfigurationstyp: {config_type}")
        return default_value or {}
    
    file_path = DEFAULT_CONFIG_PATHS[config_type]
    
    try:
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        else:
            logger.warning(f"⚠️ Konfigurationsdatei {file_path} nicht gefunden. Verwende Standardwert.")
            return default_value or {}
    except json.JSONDecodeError as e:
        logger.error(f"⚠️ Fehler beim Parsen der JSON-Datei {file_path}: {e}")
        return default_value or {}
    except Exception as e:
        logger.error(f"⚠️ Fehler beim Laden der Konfigurationsdatei {file_path}: {e}")
        return default_value or {}

# Speichern von JSON-Konfigurationsdateien
def save_json_config(config_data, config_type):
    """
    Speichert eine JSON-Konfigurationsdatei
    
    :param config_data: Zu speichernde Konfigurationsdaten
    :param config_type: Typ der Konfiguration (schedule, telegram, synonyms, etc.)
    :return: True bei Erfolg, False bei Fehler
    """
    if config_type not in DEFAULT_CONFIG_PATHS:
        logger.error(f"⚠️ Unbekannter Konfigurationstyp: {config_type}")
        return False
    
    file_path = DEFAULT_CONFIG_PATHS[config_type]
    
    try:
        # Sicherstellen, dass das Verzeichnis existiert
        directory = os.path.dirname(file_path)
        if directory:
            Path(directory).mkdir(parents=True, exist_ok=True)
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, ensure_ascii=False, indent=2)
        
        return True
    except Exception as e:
        logger.error(f"⚠️ Fehler beim Speichern der Konfigurationsdatei {file_path}: {e}")
        return False

# Laden von Textdateien
def load_text_list(config_type):
    """
    Lädt eine Liste aus einer Textdatei
    
    :param config_type: Typ der Konfiguration (products, urls, etc.)
    :return: Liste von Zeilen aus der Datei
    """
    if config_type not in DEFAULT_CONFIG_PATHS:
        logger.error(f"⚠️ Unbekannter Konfigurationstyp: {config_type}")
        return []
    
    file_path = DEFAULT_CONFIG_PATHS[config_type]
    
    try:
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                return [line.strip() for line in f if line.strip()]
        else:
            logger.warning(f"⚠️ Textdatei {file_path} nicht gefunden. Verwende leere Liste.")
            return []
    except Exception as e:
        logger.error(f"⚠️ Fehler beim Laden der Textdatei {file_path}: {e}")
        return []

# Speichern von Textdateien
def save_text_list(text_list, config_type):
    """
    Speichert eine Liste in eine Textdatei
    
    :param text_list: Zu speichernde Liste
    :param config_type: Typ der Konfiguration (products, urls, etc.)
    :return: True bei Erfolg, False bei Fehler
    """
    if config_type not in DEFAULT_CONFIG_PATHS:
        logger.error(f"⚠️ Unbekannter Konfigurationstyp: {config_type}")
        return False
    
    file_path = DEFAULT_CONFIG_PATHS[config_type]
    
    try:
        # Sicherstellen, dass das Verzeichnis existiert
        directory = os.path.dirname(file_path)
        if directory:
            Path(directory).mkdir(parents=True, exist_ok=True)
        
        with open(file_path, "w", encoding="utf-8") as f:
            for item in text_list:
                f.write(f"{item}\n")
        
        return True
    except Exception as e:
        logger.error(f"⚠️ Fehler beim Speichern der Textdatei {file_path}: {e}")
        return False

# Laden von Sets (für seen, out_of_stock, etc.)
def load_set(config_type):
    """
    Lädt ein Set aus einer Textdatei
    
    :param config_type: Typ der Konfiguration (seen, out_of_stock, etc.)
    :return: Set mit Elementen aus der Datei
    """
    items = load_text_list(config_type)
    return set(items)

# Speichern von Sets
def save_set(data_set, config_type):
    """
    Speichert ein Set in eine Textdatei
    
    :param data_set: Zu speicherndes Set
    :param config_type: Typ der Konfiguration (seen, out_of_stock, etc.)
    :return: True bei Erfolg, False bei Fehler
    """
    return save_text_list(list(data_set), config_type)

# Aktuelles Abrufintervall ermitteln
def get_current_interval():
    """
    Ermittelt das aktuelle Abrufintervall basierend auf der schedule.json
    
    :return: Intervall in Sekunden, Standard: 300 (5 Minuten)
    """
    schedule = load_json_config("schedule", [])
    today = date.today()
    
    for entry in schedule:
        try:
            start_date = datetime.strptime(entry.get("start", "01.01.1970"), "%d.%m.%Y").date()
            end_date = datetime.strptime(entry.get("end", "31.12.2099"), "%d.%m.%Y").date()
            
            if start_date <= today <= end_date:
                return int(entry.get("interval", 300))
        except (ValueError, TypeError) as e:
            logger.error(f"⚠️ Fehler beim Parsen von Datumsangaben in schedule.json: {e}")
            continue
    
    # Standard-Intervall, wenn kein passendes gefunden wurde
    return 300

# Telegram-Konfiguration laden
def get_telegram_config():
    """
    Lädt die Telegram-Konfiguration
    
    :return: Dictionary mit telegram_bot_token und chat_id
    """
    return load_json_config("telegram", {"bot_token": "", "chat_id": ""})

# Convenience-Funktionen für häufig benötigte Konfigurationen

def load_products():
    """Lädt die Produktliste"""
    return load_text_list("products")

def load_urls():
    """Lädt die URL-Liste"""
    return load_text_list("urls")

def load_seen():
    """Lädt die gesehenen Produkte"""
    return load_set("seen")

def save_seen(seen_set):
    """Speichert die gesehenen Produkte"""
    return save_set(seen_set, "seen")

def load_out_of_stock():
    """Lädt die ausverkauften Produkte"""
    return load_set("out_of_stock")

def save_out_of_stock(out_of_stock_set):
    """Speichert die ausverkauften Produkte"""
    return save_set(out_of_stock_set, "out_of_stock")

def load_product_cache():
    """Lädt den Produkt-Cache"""
    return load_json_config("product_cache", {})

def save_product_cache(cache):
    """Speichert den Produkt-Cache"""
    return save_json_config(cache, "product_cache")

# Initialisierung
ensure_directories()