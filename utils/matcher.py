import re
import json

def clean_text(text):
    """
    Entfernt Sonderzeichen, wandelt zu Kleinbuchstaben & entfernt doppelte Leerzeichen
    """
    text = str(text).lower()
    text = re.sub(r"[^a-zA-Z0-9äöüß ]", " ", text)
    text = re.sub(r"\s+", " ", text)  # Mehrere Leerzeichen zu einem reduzieren
    return text.strip()

def is_keyword_in_text(keywords, text):
    """
    Prüft, ob ALLE Wörter im Text vorkommen
    Flexiblere Version, die einzelne Wörter im Text sucht
    """
    text = clean_text(text)
    
    # Debug-Ausgabe für besseres Verständnis
    matches = [word for word in keywords if word in text]
    missing = [word for word in keywords if word not in text]
    
    if missing:
        print(f"    Fehlende Wörter: {missing}", flush=True)
    
    return len(missing) == 0  # Alle Wörter müssen vorkommen

def prepare_keywords(products):
    """
    Zerlegt die products.txt Zeilen in Keyword-Listen und
    fügt ggf. Synonyme aus synonyms.json hinzu
    """
    keywords_map = {}
    
    # Normale Keywords aus products.txt
    for line in products:
        keywords_map[line] = clean_text(line).split()
    
    # Synonyme hinzufügen (falls vorhanden)
    try:
        with open("config/synonyms.json", "r", encoding="utf-8") as f:
            synonyms = json.load(f)
            
        for key, synonym_list in synonyms.items():
            # Füge jeden Synonym-Eintrag als separaten Suchbegriff hinzu
            for synonym in synonym_list:
                keywords_map[synonym] = clean_text(synonym).split()
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"ℹ️ Synonyme konnten nicht geladen werden: {e}", flush=True)
    
    return keywords_map