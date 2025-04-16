"""
Zentrale Konfigurationsverwaltung für den Pokémon TCG Scraper

Dieses Modul stellt Funktionen zur vereinfachten Verwaltung aller Konfigurationseinstellungen 
des Scrapers bereit, einschließlich Laden, Validieren und Speichern von Konfigurationsdateien.
"""

import os
import json
import logging
import time
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

# Cache für geladene Konfigurationen (verhindert wiederholtes Laden derselben Daten)
_config_cache = {}
_cache_timestamps = {}
# Wie lange der Cache gültig ist (in Sekunden)
CACHE_TTL = 300  # 5 Minuten

# Erstellen der Verzeichnisse, falls sie nicht existieren
def ensure_directories():
    """Stellt sicher, dass alle erforderlichen Verzeichnisse existieren"""
    for path in DEFAULT_CONFIG_PATHS.values():
        directory = os.path.dirname(path)
        if directory:
            Path(directory).mkdir(parents=True, exist_ok=True)

# Laden und Validieren von JSON-Konfigurationsdateien
def load_json_config(config_type, default_value=None, force_reload=False):
    """
    Lädt eine JSON-Konfigurationsdatei mit Cache-Unterstützung
    
    :param config_type: Typ der Konfiguration (schedule, telegram, synonyms, etc.)
    :param default_value: Standardwert, falls die Datei nicht existiert
    :param force_reload: Erzwingt das Neuladen der Datei, auch wenn sie im Cache ist
    :return: Geladene Konfiguration oder Standardwert
    """
    if config_type not in DEFAULT_CONFIG_PATHS:
        logger.error(f"⚠️ Unbekannter Konfigurationstyp: {config_type}")
        return default_value or {}
    
    file_path = DEFAULT_CONFIG_PATHS[config_type]
    current_time = time.time()
    
    # Prüfe, ob Datei im Cache ist und noch gültig
    if (not force_reload and 
        config_type in _config_cache and 
        current_time - _cache_timestamps.get(config_type, 0) < CACHE_TTL):
        return _config_cache[config_type]
    
    try:
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                config_data = json.load(f)
                
                # Speichere im Cache
                _config_cache[config_type] = config_data
                _cache_timestamps[config_type] = current_time
                
                return config_data
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
    Speichert eine JSON-Konfigurationsdatei und aktualisiert den Cache
    
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
        
        # Cache aktualisieren
        _config_cache[config_type] = config_data
        _cache_timestamps[config_type] = time.time()
        
        return True
    except Exception as e:
        logger.error(f"⚠️ Fehler beim Speichern der Konfigurationsdatei {file_path}: {e}")
        return False

# Laden von Textdateien
def load_text_list(config_type, force_reload=False):
    """
    Lädt eine Liste aus einer Textdatei mit Cache-Unterstützung
    
    :param config_type: Typ der Konfiguration (products, urls, etc.)
    :param force_reload: Erzwingt das Neuladen der Datei, auch wenn sie im Cache ist
    :return: Liste von Zeilen aus der Datei
    """
    if config_type not in DEFAULT_CONFIG_PATHS:
        logger.error(f"⚠️ Unbekannter Konfigurationstyp: {config_type}")
        return []
    
    file_path = DEFAULT_CONFIG_PATHS[config_type]
    current_time = time.time()
    
    # Prüfe, ob Datei im Cache ist und noch gültig
    if (not force_reload and 
        config_type in _config_cache and 
        current_time - _cache_timestamps.get(config_type, 0) < CACHE_TTL):
        return _config_cache[config_type]
    
    try:
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f if line.strip()]
                
                # Speichere im Cache
                _config_cache[config_type] = lines
                _cache_timestamps[config_type] = current_time
                
                return lines
        else:
            logger.warning(f"⚠️ Textdatei {file_path} nicht gefunden. Verwende leere Liste.")
            return []
    except Exception as e:
        logger.error(f"⚠️ Fehler beim Laden der Textdatei {file_path}: {e}")
        return []

# Speichern von Textdateien
def save_text_list(text_list, config_type):
    """
    Speichert eine Liste in eine Textdatei und aktualisiert den Cache
    
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
        
        # Cache aktualisieren
        _config_cache[config_type] = text_list
        _cache_timestamps[config_type] = time.time()
        
        return True
    except Exception as e:
        logger.error(f"⚠️ Fehler beim Speichern der Textdatei {file_path}: {e}")
        return False

# Laden von Sets (für seen, out_of_stock, etc.)
def load_set(config_type, force_reload=False):
    """
    Lädt ein Set aus einer Textdatei mit Cache-Unterstützung
    
    :param config_type: Typ der Konfiguration (seen, out_of_stock, etc.)
    :param force_reload: Erzwingt das Neuladen der Datei, auch wenn sie im Cache ist
    :return: Set mit Elementen aus der Datei
    """
    if config_type.startswith("_set_") and not force_reload:
        # Spezielle Caching-Logik für Sets, um Tippfehler zu vermeiden
        cache_key = config_type
        if cache_key in _config_cache and time.time() - _cache_timestamps.get(cache_key, 0) < CACHE_TTL:
            return _config_cache[cache_key]
    
    items = load_text_list(config_type, force_reload)
    result_set = set(items)
    
    # Speichere das Set im Cache unter einem speziellen Schlüssel
    _config_cache[f"_set_{config_type}"] = result_set
    _cache_timestamps[f"_set_{config_type}"] = time.time()
    
    return result_set

# Speichern von Sets
def save_set(data_set, config_type):
    """
    Speichert ein Set in eine Textdatei und aktualisiert den Cache
    
    :param data_set: Zu speicherndes Set
    :param config_type: Typ der Konfiguration (seen, out_of_stock, etc.)
    :return: True bei Erfolg, False bei Fehler
    """
    # Aktualisiere auch den speziellen Set-Cache
    _config_cache[f"_set_{config_type}"] = data_set
    _cache_timestamps[f"_set_{config_type}"] = time.time()
    
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

# Cache leeren (für Tests oder bei Speicherplatzproblemen)
def clear_cache():
    """Leert den internen Konfigurationscache vollständig"""
    global _config_cache, _cache_timestamps
    _config_cache = {}
    _cache_timestamps = {}
    logger.info("🧹 Konfigurationscache geleert")

# Einzelne Einträge aus dem Cache entfernen
def invalidate_cache_entry(config_type):
    """
    Entfernt einen bestimmten Eintrag aus dem Cache
    
    :param config_type: Typ der Konfiguration, die gelöscht werden soll
    :return: True wenn Eintrag gefunden und gelöscht, False sonst
    """
    if config_type in _config_cache:
        del _config_cache[config_type]
        if config_type in _cache_timestamps:
            del _cache_timestamps[config_type]
        return True
    return False

# Convenience-Funktionen für häufig benötigte Konfigurationen

def load_products(force_reload=False):
    """Lädt die Produktliste"""
    return load_text_list("products", force_reload)

def load_urls(force_reload=False):
    """Lädt die URL-Liste"""
    return load_text_list("urls", force_reload)

def load_seen(force_reload=False):
    """Lädt die gesehenen Produkte"""
    return load_set("seen", force_reload)

def save_seen(seen_set):
    """Speichert die gesehenen Produkte"""
    return save_set(seen_set, "seen")

def load_out_of_stock(force_reload=False):
    """Lädt die ausverkauften Produkte"""
    return load_set("out_of_stock", force_reload)

def save_out_of_stock(out_of_stock_set):
    """Speichert die ausverkauften Produkte"""
    return save_set(out_of_stock_set, "out_of_stock")

def load_product_cache(force_reload=False):
    """Lädt den Produkt-Cache"""
    return load_json_config("product_cache", {}, force_reload)

def save_product_cache(cache):
    """Speichert den Produkt-Cache"""
    return save_json_config(cache, "product_cache")

# Dateigröße überprüfen
def get_file_size(config_type):
    """
    Gibt die Größe einer Konfigurationsdatei in Bytes zurück
    
    :param config_type: Typ der Konfiguration
    :return: Dateigröße in Bytes oder 0, falls Datei nicht existiert
    """
    if config_type not in DEFAULT_CONFIG_PATHS:
        return 0
    
    file_path = DEFAULT_CONFIG_PATHS[config_type]
    if os.path.exists(file_path):
        return os.path.getsize(file_path)
    return 0

# Cache-Statistiken
def get_cache_stats():
    """
    Gibt Statistiken zum aktuellen Cache-Status zurück
    
    :return: Dictionary mit Cache-Statistiken
    """
    current_time = time.time()
    stats = {
        "entries": len(_config_cache),
        "valid_entries": sum(1 for k, t in _cache_timestamps.items() if current_time - t < CACHE_TTL),
        "expired_entries": sum(1 for k, t in _cache_timestamps.items() if current_time - t >= CACHE_TTL),
        "entries_by_type": {k: type(_config_cache[k]).__name__ for k in _config_cache},
        "cache_ages": {k: int(current_time - t) for k, t in _cache_timestamps.items()}
    }
    return stats

# Initialisierung
ensure_directories()