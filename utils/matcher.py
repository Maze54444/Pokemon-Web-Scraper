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
    Prüft auf exakte Übereinstimmung des Suchbegriffs im Text
    
    Diese verbesserte Version sucht nach der exakten Phrase, nicht nur nach den einzelnen Wörtern.
    Keywords werden als zusammenhängende Phrase behandelt.
    
    :param keywords: Liste mit einzelnen Wörtern des Suchbegriffs
    :param text: Zu prüfender Text
    :return: True, wenn die exakte Phrase gefunden wurde, sonst False
    """
    text = clean_text(text)
    
    # Konstruiere eine exakte Phrase aus den Keywords
    phrase = " ".join(keywords)
    
    # Prüfe, ob die exakte Phrase im Text vorkommt
    match = phrase in text
    
    # Debug-Ausgabe für besseres Verständnis
    if match:
        print(f"    ✅ Treffer für exakte Phrase: '{phrase}' in '{text}'", flush=True)
    else:
        print(f"    ❌ Keine exakte Übereinstimmung für: '{phrase}' in '{text}'", flush=True)
    
    return match

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