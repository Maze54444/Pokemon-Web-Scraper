def load_out_of_stock(path="data/out_of_stock.txt"):
    """Lädt die ausverkauften Produkte als Set"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    except FileNotFoundError:
        print(f"ℹ️ Hinweis: Datei {path} nicht gefunden. Neues Set wird erstellt.", flush=True)
        return set()

def save_out_of_stock(out_of_stock, path="data/out_of_stock.txt"):
    """Speichert das Set der ausverkauften Produkte"""
    with open(path, "w", encoding="utf-8") as f:
        for item in out_of_stock:
            f.write(f"{item}\n")

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
    base_product_id = product_id.split("_status_")[0]
    
    # Vollständige Produkt-IDs mit Status
    available_id = f"{base_product_id}_status_available"
    unavailable_id = f"{base_product_id}_status_unavailable"
    
    # Prüfen, ob das Produkt wieder verfügbar ist
    is_back_in_stock = False
    if not is_available:
        # Produkt ist nicht verfügbar, zu ausverkauften hinzufügen
        if unavailable_id not in seen:
            out_of_stock.add(base_product_id)
            return True, False  # Benachrichtigen, aber nicht als "wieder verfügbar"
        return False, False  # Bereits als ausverkauft gemeldet
    else:
        # Produkt ist verfügbar
        # Prüfen, ob es zuvor als ausverkauft gemerkt wurde
        if base_product_id in out_of_stock:
            out_of_stock.remove(base_product_id)
            is_back_in_stock = True  # Produkt ist wieder verfügbar
        
        if available_id not in seen:
            return True, is_back_in_stock  # Benachrichtigen und eventuell als "wieder verfügbar" markieren
        return False, False  # Bereits als verfügbar gemeldet

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