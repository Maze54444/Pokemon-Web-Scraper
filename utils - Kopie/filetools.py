def load_list(path):
    """Lädt eine Textdatei als Liste von Zeilen"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        print(f"⚠️ Warnung: Datei {path} nicht gefunden. Leere Liste wird zurückgegeben.", flush=True)
        return []

def load_seen(path="data/seen.txt"):
    """Lädt die bereits gesehenen Produkte als Set"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    except FileNotFoundError:
        print(f"ℹ️ Hinweis: Datei {path} nicht gefunden. Neues Set wird erstellt.", flush=True)
        return set()

def save_seen(seen, path="data/seen.txt"):
    """Speichert das Set der gesehenen Produkte"""
    with open(path, "w", encoding="utf-8") as f:
        for item in seen:
            f.write(f"{item}\n")