import os
import logging
from pathlib import Path

# Logger konfigurieren
logger = logging.getLogger(__name__)

def load_out_of_stock(path="data/out_of_stock.txt"):
    """Lädt die ausverkauften Produkte als Set"""
    try:
        # Stellen Sie sicher, dass das Verzeichnis existiert
        directory = os.path.dirname(path)
        if directory:
            Path(directory).mkdir(parents=True, exist_ok=True)
            
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return set(line.strip() for line in f if line.strip())
        logger.info(f"ℹ️ Datei {path} nicht gefunden. Neues Set wird erstellt.")
        return set()
    except Exception as e:
        logger.error(f"❌ Fehler beim Laden der ausverkauften Produkte: {e}")
        return set()

def save_out_of_stock(out_of_stock, path="data/out_of_stock.txt"):
    """Speichert das Set der ausverkauften Produkte"""
    try:
        # Stellen Sie sicher, dass das Verzeichnis existiert
        directory = os.path.dirname(path)
        if directory:
            Path(directory).mkdir(parents=True, exist_ok=True)
            
        with open(path, "w", encoding="utf-8") as f:
            for item in out_of_stock:
                f.write(f"{item}\n")
        return True
    except Exception as e:
        logger.error(f"❌ Fehler beim Speichern der ausverkauften Produkte: {e}")
        return False

def update_product_status(product_id, is_available, seen, out_of_stock):
    """
    Aktualisiert den Status eines Produkts und entscheidet, ob eine Benachrichtigung gesendet werden sollte
    
    :param product_id: Eindeutige Produkt-ID
    :param is_available: Verfügbarkeitsstatus (True = verfügbar, False = ausverkauft)
    :param seen: Set mit bereits gemeldeten Produkten
    :param out_of_stock: Set mit ausverkauften Produkten
    :return: Tupel (should_notify, is_back_in_stock)
        - should_notify: Bool, ob benachrichtigt werden soll
        - is_back_in_stock: Bool, ob Produkt wieder verfügbar ist
    """
    # Basisversion der Produkt-ID (ohne Verfügbarkeitsstatus-Suffix)
    base_product_id = product_id.split("_status_")[0] if "_status_" in product_id else product_id
    
    # Vollständige Produkt-IDs mit Status
    available_id = f"{base_product_id}_status_available"
    unavailable_id = f"{base_product_id}_status_unavailable"
    
    # Prüfen, ob das Produkt wieder verfügbar ist
    is_back_in_stock = False
    
    # Immer benachrichtigen, unabhängig vom Verfügbarkeitsstatus
    should_notify = True
    
    if not is_available:
        # Produkt ist nicht verfügbar, zu ausverkauften hinzufügen
        if unavailable_id not in seen:
            out_of_stock.add(base_product_id)
            logger.debug(f"Produkt {base_product_id} ist ausverkauft und wurde zu out_of_stock hinzugefügt")
        else:
            logger.debug(f"Produkt {base_product_id} ist bereits als ausverkauft bekannt")
            should_notify = False  # Bereits als ausverkauft gemeldet, keine erneute Benachrichtigung
    else:
        # Produkt ist verfügbar
        # Prüfen, ob es zuvor als ausverkauft gemerkt wurde
        if base_product_id in out_of_stock:
            out_of_stock.remove(base_product_id)
            is_back_in_stock = True  # Produkt ist wieder verfügbar
            logger.info(f"Produkt {base_product_id} ist wieder verfügbar und wurde aus out_of_stock entfernt")
        
        if available_id in seen:
            logger.debug(f"Produkt {base_product_id} ist bereits als verfügbar bekannt")
            should_notify = False  # Bereits als verfügbar gemeldet, keine erneute Benachrichtigung
    
    # Aktualisiere den Status im 'seen' Set
    if should_notify:
        if is_available:
            seen.add(available_id)
            logger.debug(f"Status '{available_id}' zu 'seen' hinzugefügt")
        else:
            seen.add(unavailable_id)
            logger.debug(f"Status '{unavailable_id}' zu 'seen' hinzugefügt")
    
    return should_notify, is_back_in_stock

def get_status_text(is_available, is_back_in_stock=False):
    """
    Erstellt einen formatierten Statustext
    
    :param is_available: Verfügbarkeitsstatus
    :param is_back_in_stock: Ob Produkt wieder verfügbar ist
    :return: Formatierter Statustext
    """
    if is_available:
        if is_back_in_stock:
            return "🎉 Wieder verfügbar!"
        return "✅ Verfügbar"
    return "❌ Ausverkauft"

def should_check_product(product_id, seen, only_available=False):
    """
    Prüft, ob ein Produkt überprüft werden soll oder bereits bekannt ist
    
    :param product_id: Produkt-ID
    :param seen: Set mit bereits gemeldeten Produkten
    :param only_available: Ob nur auf Verfügbarkeit geprüft werden soll
    :return: True wenn Produkt geprüft werden soll, False sonst
    """
    # Basisversion der Produkt-ID (ohne Verfügbarkeitsstatus-Suffix)
    base_product_id = product_id.split("_status_")[0] if "_status_" in product_id else product_id
    
    available_id = f"{base_product_id}_status_available"
    unavailable_id = f"{base_product_id}_status_unavailable"
    
    # Wenn wir nur verfügbare Produkte suchen, überspringen wir bekannte nicht-verfügbare
    if only_available and unavailable_id in seen:
        return False
    
    # Bei normaler Suche prüfen wir alle Produkte
    return True