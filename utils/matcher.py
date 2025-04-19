import re
import json
import logging

# Logger konfigurieren
logger = logging.getLogger(__name__)

def clean_text(text):
    """
    Entfernt Sonderzeichen, wandelt zu Kleinbuchstaben & entfernt doppelte Leerzeichen
    """
    text = str(text).lower()
    text = re.sub(r"[^a-zA-Z0-9äöüß ]", " ", text)
    text = re.sub(r"\s+", " ", text)  # Mehrere Leerzeichen zu einem reduzieren
    return text.strip()

def extract_product_type_from_text(text):
    """
    Extrahiert den Produkttyp aus einem Text für strengere Filterung
    
    :param text: Text, aus dem der Produkttyp extrahiert werden soll
    :return: Produkttyp als String oder "unknown" wenn nicht eindeutig
    """
    if not text:
        return "unknown"
        
    text = text.lower()
    
    # Definiere klare Muster für verschiedene Produkttypen
    product_patterns = {
        "display": [
            r'\bdisplay\b', 
            r'\b36er\b', 
            r'\b36\s+booster\b', 
            r'\bbooster\s+display\b', 
            r'\bbooster\s+box\b',
            r'\bbox\s+display\b'
        ],
        "etb": [
            r'\belite\s+trainer\s+box\b', 
            r'\betb\b', 
            r'\btrainer\s+box\b', 
            r'\btop\s+trainer\s+box\b'
        ],
        "build_battle": [
            r'\bbuild\s*[&]?\s*battle\b', 
            r'\bprerelease\b'
        ],
        "blister": [
            r'\bblister\b', 
            r'\b3er\s+blister\b',
            r'\b3\s*er\b',
            r'\b3-pack\b', 
            r'\bchecklane\b', 
            r'\bsleeve(d)?\s+booster\b',
            r'\b3\s*pack\b'
        ],
        "single_booster": [
            r'\bsingle\s+booster\b', 
            r'\bbooster\s+pack\b'
        ],
        "tin": [
            r'\btin\b', 
            r'\bmetal\s+box\b'
        ],
        "premium": [
            r'\bpremium\b', 
            r'\bcollection\b', 
            r'\bcollector\b'
        ]
    }
    
    # Explizit nach "booster pack" oder "pack" suchen, um single booster von displays zu unterscheiden
    has_booster_pack = re.search(r'\bbooster\s+pack\b|\bpack\b|\bbooster(?!\s+display|\s+box|\s+36|\s*36er)\b', text) is not None
    
    # Explizit nach "3er", "3-pack", etc. suchen, um blister zu identifizieren
    has_3pack_or_blister = re.search(r'\b3er\b|\b3-pack\b|\b3\s+pack\b|\bblister\b|\b3\s*er\b', text) is not None
    
    # Jedes Muster prüfen und den ersten Treffer zurückgeben
    for product_type, patterns in product_patterns.items():
        for pattern in patterns:
            if re.search(pattern, text):
                # Vermeidung von Fehlklassifikationen:
                # Wenn wir "display" gefunden haben, prüfen wir ob auch "3er"/"blister" vorhanden ist
                if product_type == "display" and has_3pack_or_blister:
                    return "blister"  # Priorität für blister bei Mehrdeutigkeit
                
                # Wenn wir "display" gefunden haben und "booster pack" steht definitiv im Titel, 
                # dann ist es kein Display, sondern einzelne Booster
                if product_type == "display" and has_booster_pack:
                    return "single_booster"
                
                return product_type
    
    # Spezialfall für einzelne Booster erkennen (ohne "display" im Text)
    if has_booster_pack or (re.search(r'\bbooster\b', text) and not re.search(r'display|36er|box', text)):
        return "single_booster"
    
    return "unknown"  # Default: Wenn kein klarer Produkttyp erkannt wurde

def is_product_type_match(search_type, text_type):
    """
    Prüft, ob der Produkttyp im Text mit dem gesuchten Produkttyp übereinstimmt
    
    :param search_type: Gesuchter Produkttyp
    :param text_type: Im Text gefundener Produkttyp
    :return: True wenn übereinstimmend, False sonst
    """
    # Wenn kein bestimmter Produkttyp gesucht wird, gilt das als Übereinstimmung
    if not search_type or search_type == "unknown":
        return True
    
    # Wenn im Text kein Produkttyp erkannt wurde ("unknown"), aber einer gesucht wird
    if search_type and text_type == "unknown":
        # Bei "display" sind wir strenger - nur bei expliziter Erwähnung
        if search_type == "display":
            return False
        # Bei anderen Typen sind wir toleranter
        return True
    
    # Exakte Übereinstimmung erforderlich
    return search_type == text_type

def is_keyword_in_text(keywords, text, log_level='DEBUG'):
    """
    Strengere Prüfung auf exakte Übereinstimmung des Suchbegriffs im Text
    mit besonderer Berücksichtigung der Produkttypen
    
    :param keywords: Liste mit einzelnen Wörtern des Suchbegriffs
    :param text: Zu prüfender Text
    :param log_level: Loglevel für Ausgaben (DEBUG, INFO, ERROR, None für keine Ausgabe)
    :return: True, wenn die Phrase gefunden wurde und Produkttypen übereinstimmen, sonst False
    """
    # Kurze Texte sofort ablehnen
    if not text or len(text) < 3:
        return False
        
    original_keywords = " ".join(keywords)  # für Debug-Ausgaben
    original_text = text  # Originaltext für Debug-Ausgaben speichern
    text = clean_text(text)
    
    # Extrahiere den Produkttyp aus dem Suchbegriff
    search_term = " ".join(keywords)
    search_product_type = extract_product_type_from_text(search_term)
    
    # Extrahiere den Produkttyp aus dem zu durchsuchenden Text
    text_product_type = extract_product_type_from_text(text)
    
    # Wenn nach einem bestimmten Produkttyp gesucht wird, muss dieser im Text übereinstimmen
    # Besonders stringente Prüfung für Displays
    if search_product_type == "display":
        if text_product_type != "display":
            if log_level and log_level != 'None':
                logger.debug(f"Produkttyp-Konflikt: Suche nach 'display', Text enthält '{text_product_type}': {original_text}")
            return False
    
    # Prüfe auf falsche Kartensets und veraltete Produkte
    exclusion_sets = [
        "stürmische funken", "sturmi", "paradox rift", "paradox", "prismat", "stellar", "battle partners",
        "nebel der sagen", "zeit", "paldea", "obsidian", "151", "astral", "brilliant", "fusion", 
        "kp01", "kp02", "kp03", "kp04", "kp05", "kp06", "kp07", "kp08", "sv01", "sv02", "sv03", "sv04", 
        "sv05", "sv06", "sv07", "sv08", "sv10", "sv11", "sv12", "sv13"
    ]
    
    # Prüfe spezifische Produkte - wenn wir nach "Journey Together" oder "Reisegefährten" suchen
    has_journey_together = "journey together" in search_term.lower() or "sv09" in search_term.lower()
    has_reisegefaehrten = "reisegefährten" in search_term.lower() or "kp09" in search_term.lower()
    
    # Wenn wir nach einem spezifischen Produkt suchen
    if has_journey_together or has_reisegefaehrten:
        # Prüfen wir auf falsche Sets/Editionen, um andere Produkte auszuschließen
        for exclusion in exclusion_sets:
            if exclusion in text.lower():
                if log_level and log_level != 'None':
                    logger.debug(f"Text enthält ausgeschlossenes Set '{exclusion}': '{original_text}'")
                return False
    
    # Standardisiere Singular/Plural
    standardized_keywords = []
    for word in keywords:
        if word in ["display", "displays"]:
            standardized_keywords.append("display")
        elif word in ["booster", "boosters"]:
            standardized_keywords.append("booster")
        elif word in ["pack", "packs"]:
            standardized_keywords.append("pack")
        elif word in ["box", "boxes"]:
            standardized_keywords.append("box")
        else:
            standardized_keywords.append(word)
    
    # Standardisiere auch im Text
    standardized_text = text
    for singular, plural in [("display", "displays"), ("booster", "boosters"), 
                            ("pack", "packs"), ("box", "boxes")]:
        standardized_text = standardized_text.replace(plural, singular)
    
    # Überprüfe die Übereinstimmung von Schlüsselwörtern
    # Ignoriere kurze Wörter (< 3 Zeichen) und häufige Füllwörter
    ignore_words = ["und", "the", "and", "for", "mit", "von", "pro", "per", "der", "die", "das"]
    
    # Wichtige Schlüsselwörter identifizieren, die unterscheiden zwischen Displays und anderen Produkten
    important_keywords = []
    
    # Sammle wichtige Keywords (> 3 Zeichen) und nicht in ignore_words,
    # aber nicht die Produkttyp-Wörter (die werden separat geprüft)
    important_keywords = [k for k in standardized_keywords 
                         if len(k) > 3 and k not in ignore_words and k not in ["display", "booster", "pack", "box", "etb", "blister"]]
    
    # Wenn es keine wichtigen Keywords gibt, verwende alle
    if not important_keywords:
        important_keywords = [k for k in standardized_keywords if k not in ignore_words]
    
    # Zähle, wie viele wichtige Keywords gefunden wurden
    found_count = sum(1 for key_term in important_keywords if key_term in standardized_text)
    
    # Bei Suche nach "display", muss "display" oder "36er" oder "box" im Text vorkommen
    if search_product_type == "display" and not any(term in standardized_text for term in ["display", "36er", "box", "36"]):
        if log_level and log_level != 'None':
            logger.debug(f"'display' im Suchbegriff, aber kein Display-Begriff im Text gefunden: '{original_keywords}' in '{original_text}'")
        return False
    
    # Mindestens 80% der wichtigen Keywords müssen gefunden werden
    threshold = 0.8
    required_matches = max(1, int(len(important_keywords) * threshold))
    
    if found_count < required_matches:
        if log_level and log_level != 'None' and important_keywords:
            logger.debug(f"Nicht genug wichtige Begriffe gefunden ({found_count}/{len(important_keywords)}): '{original_keywords}' in '{original_text}'")
        return False
    
    if log_level and log_level == 'INFO':
        logger.info(f"Treffer für Suchbegriff: '{original_keywords}' in '{original_text}'")
        
    return True

def normalize_product_name(text):
    """
    Normalisiert einen Produktnamen für konsistenten Vergleich.
    
    :param text: Zu normalisierender Text
    :return: Normalisierter Text
    """
    text = clean_text(text)
    # Singular/Plural für häufige Produkttypen standardisieren
    text = text.replace("displays", "display")
    text = text.replace("boosters", "booster")
    text = text.replace("packs", "pack")
    text = text.replace("boxes", "box")
    text = text.replace("tins", "tin")
    text = text.replace("blisters", "blister")
    return text

def prepare_keywords(products):
    """
    Zerlegt die products.txt Zeilen in Keyword-Listen und
    fügt ggf. Synonyme aus synonyms.json hinzu
    """
    keywords_map = {}
    
    # Normale Keywords aus products.txt
    for line in products:
        # Entferne führende/nachfolgende Leerzeichen
        clean_line = line.strip()
        if clean_line:  # Überspringe leere Zeilen
            keywords_map[clean_line] = clean_text(clean_line).split()
    
    # Versuche zuerst config/synonyms.json
    synonyms_file_paths = ["config/synonyms.json", "data/synonyms.json"]
    synonyms_loaded = False
    
    for file_path in synonyms_file_paths:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                synonyms = json.load(f)
                
                # Füge jeden Synonym-Eintrag als separaten Suchbegriff hinzu
                for key, synonym_list in synonyms.items():
                    # Prüfe, ob der Key selbst ein Suchbegriff ist
                    if key in keywords_map:
                        # Füge nur die Synonyme zum Map hinzu
                        for synonym in synonym_list:
                            if synonym not in keywords_map:  # Vermeide Duplikate
                                keywords_map[synonym] = clean_text(synonym).split()
                    # Wenn der Key kein Suchbegriff ist, ignorieren
                    # Dies stellt sicher, dass nur Synonyme für tatsächliche Suchbegriffe verwendet werden
                                
                synonyms_loaded = True
                logger.info(f"ℹ️ Synonyme aus {file_path} geladen")
                break  # Wenn erfolgreich geladen, breche die Schleife ab
                
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.debug(f"ℹ️ Synonyme aus {file_path} konnten nicht geladen werden: {e}")
    
    if not synonyms_loaded:
        logger.info("ℹ️ Keine Synonyme geladen. Nur direkte Suchbegriffe werden verwendet.")
    
    # Debug-Ausgabe der geladenen Suchbegriffe
    logger.info(f"ℹ️ Geladene Suchbegriffe: {list(keywords_map.keys())}")
    
    return keywords_map