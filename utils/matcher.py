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
            r'\bbox\s+display\b',
            r'\b36\s+(pack|packs)\b',
            r'\bbooster\s+box\b',
            r'\b18er\s+booster\s+display\b',
            r'\b36er\s+display\b'
        ],
        "etb": [
            r'\belite\s+trainer\s+box\b', 
            r'\betb\b', 
            r'\belite-trainer-box\b',
            r'\belitetrainerbox\b'
        ],
        "ttb": [
            r'\btop\s+trainer\s+box\b',
            r'\bttb\b',
            r'\btop-trainer-box\b',
            r'\btoptrainerbox\b'
        ],
        "build_battle": [
            r'\bbuild\s*[&]?\s*battle\b', 
            r'\bprerelease\b'
        ],
        "blister": [
            r'\bblister\b', 
            r'\b3er\s+booster\b',
            r'\b3\s*er\b',
            r'\b3-pack\b', 
            r'\bchecklane\b', 
            r'\bsleeve(d)?\s+booster\b',
            r'\b3\s*pack\b',
            r'\bpremium\s*checklane\b'
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
    
    # Stark hervorheben: Wenn "display" und "36" oder "18" im Text vorkommen, ist es definitiv ein Display 
    # - höchste Priorität, wird immer zuerst geprüft
    if (re.search(r'\bdisplay\b', text) and 
        (re.search(r'\b36\b|\b36er\b|\b18\b|\b18er\b', text) or re.search(r'\bbooster\s+box\b', text))):
        return "display"
        
    # Spezifische Codes-Muster, die üblicherweise mit bestimmten Produkttypen verbunden sind
    # SVXX/KPXX + (36er/18er oder Display)
    if (re.search(r'\b(sv\d+|kp\d+)\b', text) and 
        (re.search(r'\b36er\b|\b18er\b|\bdisplay\b|\bbooster box\b', text))):
        return "display"
        
    # Explizit nach "booster pack" oder "pack" suchen, um single booster von displays zu unterscheiden
    has_booster_pack_pattern = r'\bbooster\s+pack\b|\bpack\b|\beinzelpack\b|\bsingle\s*pack\b'
    has_booster_pack = re.search(has_booster_pack_pattern, text) is not None
    
    # Explizit nach "3er", "3-pack", etc. suchen, um blister zu identifizieren
    blister_pattern = r'\b3er\b|\b3-pack\b|\b3\s+pack\b|\bblister\b|\b3\s*er\b|\bchecklane\b'
    has_3pack_or_blister = re.search(blister_pattern, text) is not None
    
    # Jedes Muster prüfen und den ersten Treffer zurückgeben
    for product_type, patterns in product_patterns.items():
        for pattern in patterns:
            if re.search(pattern, text):
                # Vermeidung von Fehlklassifikationen:
                
                # Wenn wir "display" gefunden haben, prüfen wir ob auch "3er"/"blister" vorhanden ist
                if product_type == "display" and has_3pack_or_blister:
                    # In diesem Fall handelt es sich wahrscheinlich um ein Blister-Produkt
                    logger.debug(f"Produkt enthält 'display', aber auch blister/3er: '{text}' → als blister klassifiziert")
                    return "blister"
                
                # Wenn wir "display" gefunden haben und einzelne Booster-Muster definitiv im Titel stehen, 
                # dann ist es kein Display, sondern einzelne Booster
                if product_type == "display" and has_booster_pack:
                    # Check für spezielle Display-Kennzeichen, die stärker sind als Booster-Pack
                    if re.search(r'\b36er\b|\b36\s+booster\b|\b18er\b|\b18\s+booster\b', text):
                        # Bei expliziter Anzahl von Boostern (36/18) ist es ein Display trotz "Pack" im Namen
                        return "display"
                    logger.debug(f"Produkt enthält 'display', aber auch 'booster pack': '{text}' → als single_booster klassifiziert")
                    return "single_booster"
                
                # Wenn "booster" und "Preis unter 10€" gefunden wird, ist es sehr wahrscheinlich ein einzelner Booster
                if product_type == "display" and re.search(r'\b\d[,\.]\d{2}\s*[€$]', text):
                    # Extrahiere Preis und prüfe, ob er unter 10€ liegt
                    price_match = re.search(r'(\d+[,\.]\d{2})\s*[€$]', text)
                    if price_match:
                        price_str = price_match.group(1).replace(',', '.')
                        try:
                            price = float(price_str)
                            if price < 10.0:
                                logger.debug(f"Produkt enthält 'display', aber Preis unter 10€ ({price}€): '{text}' → als single_booster klassifiziert")
                                return "single_booster"
                        except ValueError:
                            pass
                
                return product_type
    
    # Spezialfall für einzelne Booster erkennen (ohne "display" im Text)
    if has_booster_pack or (re.search(r'\bbooster\b', text) and not re.search(r'display|36er|box', text)):
        # Wenn "Booster" alleine steht, ohne "display" oder "36er", dann ist es ein einzelner Booster
        return "single_booster"
    
    # Wenn wir hier sind, haben wir keinen eindeutigen Produkttyp erkannt
    # Nochmal spezifische Muster für Display-Produkte prüfen
    if re.search(r'36\s*(x|\*)', text) or re.search(r'booster\s*box', text, re.IGNORECASE):
        return "display"
        
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
    if search_product_type in ["display", "etb", "ttb"]:
        if text_product_type != search_product_type:
            if log_level and log_level != 'None':
                logger.debug(f"⚠️ Produkttyp-Konflikt: Suche nach '{search_product_type}', Text enthält '{text_product_type}': {original_text}")
            return False
    
    # Versuche, eine Konfigurationsdatei mit Ausschlusssets zu laden
    exclusion_sets = load_exclusion_sets()
    
    # Produktspezifische Keywords aus dem Suchbegriff extrahieren (ohne Produkttyp)
    product_keywords = extract_product_keywords(search_term)
    
    # Prüfe, ob Text Ausschlusssets enthält, die nicht dem gesuchten Produkt entsprechen
    for exclusion in exclusion_sets:
        if exclusion in text.lower() and not any(keyword in exclusion for keyword in product_keywords):
            if log_level and log_level != 'None':
                logger.debug(f"⚠️ Text enthält ausgeschlossenes Set '{exclusion}': '{original_text}'")
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
                         if len(k) > 3 and k not in ignore_words and k not in ["display", "booster", "pack", "box", "etb", "ttb", "blister"]]
    
    # Wenn es keine wichtigen Keywords gibt, verwende alle
    if not important_keywords:
        important_keywords = [k for k in standardized_keywords if k not in ignore_words]
    
    # Zähle, wie viele wichtige Keywords gefunden wurden
    found_count = sum(1 for key_term in important_keywords if key_term in standardized_text)
    
    # Bei Suche nach "display", muss "display" oder "36er" oder "box" im Text vorkommen
    if search_product_type == "display" and not any(term in standardized_text for term in ["display", "36er", "box", "36"]):
        if log_level and log_level != 'None':
            logger.debug(f"⚠️ 'display' im Suchbegriff, aber kein Display-Begriff im Text gefunden: '{original_keywords}' in '{original_text}'")
        return False
    
    # Bei Suche nach "etb", muss "etb" oder "elite trainer box" im Text vorkommen
    if search_product_type == "etb" and not any(term in standardized_text for term in ["etb", "elite trainer", "trainer box"]):
        if log_level and log_level != 'None':
            logger.debug(f"⚠️ 'etb' im Suchbegriff, aber kein ETB-Begriff im Text gefunden: '{original_keywords}' in '{original_text}'")
        return False
    
    # Bei Suche nach "ttb", muss "ttb" oder "top trainer box" im Text vorkommen
    if search_product_type == "ttb" and not any(term in standardized_text for term in ["ttb", "top trainer", "trainer box"]):
        if log_level and log_level != 'None':
            logger.debug(f"⚠️ 'ttb' im Suchbegriff, aber kein TTB-Begriff im Text gefunden: '{original_keywords}' in '{original_text}'")
        return False
    
    # Mindestens 80% der wichtigen Keywords müssen gefunden werden
    threshold = 0.8
    required_matches = max(1, int(len(important_keywords) * threshold))
    
    if found_count < required_matches:
        if log_level and log_level != 'None' and important_keywords:
            logger.debug(f"⚠️ Nicht genug wichtige Begriffe gefunden ({found_count}/{len(important_keywords)}): '{original_keywords}' in '{original_text}'")
        return False
    
    if log_level and log_level == 'INFO':
        logger.info(f"✅ Treffer für Suchbegriff: '{original_keywords}' in '{original_text}'")
        
    return True

def extract_product_keywords(search_term):
    """
    Extrahiert produktspezifische Keywords aus einem Suchbegriff (ohne Produkttyp)
    
    :param search_term: Suchbegriff
    :return: Liste mit produktspezifischen Keywords
    """
    search_term = search_term.lower()
    
    # Entferne Produkttyp-Wörter
    product_type_words = ["display", "etb", "ttb", "elite trainer box", "top trainer box", 
                          "elite-trainer-box", "top-trainer-box", "box"]
    
    for word in product_type_words:
        search_term = search_term.replace(word, "")
    
    # Bereinige und teile in Wörter
    clean_term = clean_text(search_term)
    keywords = [word for word in clean_term.split() if len(word) > 2]
    
    # Entferne häufige Füllwörter
    ignore_words = ["und", "the", "and", "for", "mit", "von", "pro", "per", "der", "die", "das", "set"]
    keywords = [word for word in keywords if word not in ignore_words]
    
    return keywords

def load_exclusion_sets():
    """
    Lädt die Liste der auszuschließenden Sets aus einer Konfigurationsdatei
    oder verwendet eine Standard-Liste
    
    :return: Liste mit auszuschließenden Sets
    """
    exclusion_sets = []
    try:
        # Versuche, die Ausschlussliste aus einer Konfigurationsdatei zu laden
        exclusion_file_paths = ["config/exclusion_sets.json", "data/exclusion_sets.json"]
        
        for file_path in exclusion_file_paths:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    exclusion_sets = json.load(f)
                    logger.debug(f"Ausschlussliste aus {file_path} geladen: {len(exclusion_sets)} Einträge")
                    return exclusion_sets
            except FileNotFoundError:
                pass
            except json.JSONDecodeError as e:
                logger.warning(f"Fehler beim Parsen der Ausschlussliste {file_path}: {e}")
    except Exception as e:
        logger.warning(f"Fehler beim Laden der Ausschlussliste: {e}")
    
    # Standard-Ausschlussliste, wenn keine Konfigurationsdatei gefunden wurde
    exclusion_sets = [
        "stürmische funken", "sturmi", "paradox rift", "paradox", "prismat", "stellar", "battle partners",
        "nebel der sagen", "zeit", "paldea", "obsidian", "151", "astral", "brilliant", "fusion", 
        "kp01", "kp02", "kp03", "kp04", "kp05", "kp06", "kp07", "kp08", "sv01", "sv02", "sv03", "sv04", 
        "sv05", "sv06", "sv07", "sv08", "sv10", "sv11", "sv12", "sv13", 
        "glory of team rocket"
    ]
    
    return exclusion_sets

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
    
    # Korrigiere bekannte Tippfehler
    text = text.replace("togehter", "together")
    
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