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
            r'\bbooster\s+box\b(?!\s+trainer)',  # Booster Box ohne "Trainer"
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
            r'\bbooster\s+pack\b(?!\s+display)',  # Booster Pack ohne Display
            r'\beinzelbooster\b'
        ],
        "tin": [
            r'\btin\b(?!\s+display)', 
            r'\bmetal\s+box\b',
            r'\bpokeball\s+tin\b'
        ],
        "premium": [
            r'\bpremium\s+collection\b', 
            r'\bcollector\s+box\b',
            r'\bspecial\s+collection\b'
        ]
    }
    
    # Prüfe zuerst auf eindeutige Kombinationen
    if re.search(r'\bdisplay\b.*\b36\b|\b36\b.*\bdisplay\b', text):
        return "display"
    
    if re.search(r'\belite\b.*\btrainer\b.*\bbox\b', text):
        return "etb"
    
    if re.search(r'\btop\b.*\btrainer\b.*\bbox\b', text):
        return "ttb"
    
    # Dann prüfe einzelne Muster
    for product_type, patterns in product_patterns.items():
        for pattern in patterns:
            if re.search(pattern, text):
                # Zusätzliche Validierung für bestimmte Typen
                if product_type == "display" and re.search(r'\btrainer\s+box\b', text):
                    continue  # Trainer Box ist kein Display
                    
                if product_type == "single_booster" and re.search(r'\b(display|36er)\b', text):
                    continue  # Wenn Display erwähnt wird, ist es kein Single Booster
                    
                return product_type
    
    return "unknown"

def is_keyword_in_text(keywords, text, log_level='DEBUG'):
    """
    Verbesserte Prüfung auf exakte Übereinstimmung des Suchbegriffs im Text
    
    :param keywords: Liste mit einzelnen Wörtern des Suchbegriffs
    :param text: Zu prüfender Text
    :param log_level: Loglevel für Ausgaben (DEBUG, INFO, ERROR, None für keine Ausgabe)
    :return: True, wenn die Keywords gefunden wurden, sonst False
    """
    if not text or len(text) < 3:
        return False
        
    original_keywords = " ".join(keywords)
    clean_title = clean_text(text)
    
    # Extrahiere den Produkttyp aus dem Suchbegriff
    search_term = " ".join(keywords)
    search_product_type = extract_product_type_from_text(search_term)
    
    # Extrahiere den Produkttyp aus dem zu durchsuchenden Text
    text_product_type = extract_product_type_from_text(text)
    
    # Strikte Produkttyp-Prüfung
    if search_product_type != "unknown" and text_product_type != "unknown":
        if search_product_type != text_product_type:
            if log_level and log_level != 'None':
                logger.debug(f"⚠️ Produkttyp-Konflikt: Suche '{search_product_type}', gefunden '{text_product_type}'")
            return False
    
    # Laden der Ausschlusslisten
    exclusion_sets = load_exclusion_sets()
    
    # Prüfe auf Ausschluss-Sets
    for exclusion in exclusion_sets:
        if exclusion in text.lower():
            # Prüfe ob der Ausschlussbegriff Teil des Suchbegriffs ist
            if exclusion not in search_term.lower():
                if log_level and log_level != 'None':
                    logger.debug(f"⚠️ Text enthält ausgeschlossenes Set '{exclusion}'")
                return False
    
    # Strengere Keyword-Überprüfung
    important_keywords = extract_important_keywords(keywords)
    
    if not important_keywords:
        return False
    
    # Erstelle Wortlisten für exakte Überprüfung
    text_words = set(clean_title.split())
    
    # ALLE wichtigen Keywords müssen exakt gefunden werden
    matched_count = 0
    for keyword in important_keywords:
        # Exakte Wortübereinstimmung erforderlich
        if keyword in text_words:
            matched_count += 1
        else:
            # Prüfe auf Teilübereinstimmungen (mit strengeren Regeln)
            if not check_partial_match(keyword, text_words):
                if log_level and log_level != 'None':
                    logger.debug(f"❌ Keyword '{keyword}' nicht gefunden in '{clean_title}'")
                return False
    
    # Erfolg nur wenn ALLE Keywords gefunden wurden
    if matched_count == len(important_keywords):
        if log_level == 'INFO':
            logger.info(f"✅ Treffer für '{original_keywords}' in '{text}'")
        return True
    
    return False

def check_partial_match(keyword, text_words):
    """
    Prüft auf teilweise Übereinstimmung mit strengeren Regeln
    
    :param keyword: Einzelnes Keyword zum Prüfen
    :param text_words: Set von Wörtern im Text
    :return: True wenn teilweise Übereinstimmung gefunden
    """
    # Mindestlänge für Teilübereinstimmungen
    if len(keyword) < 4:
        return False
    
    # Prüfe ob Keyword als Teil eines längeren Wortes vorkommt
    for word in text_words:
        if len(word) >= len(keyword) and keyword in word:
            # Verhindere falsche Teilübereinstimmungen
            # z.B. "reis" sollte nicht in "preise" matchen
            if word.startswith(keyword) or word.endswith(keyword):
                return True
    
    return False

def extract_important_keywords(keywords):
    """
    Extrahiert wichtige Keywords (ohne Füllwörter und Produkttypen)
    Mit strengerer Filterung
    """
    ignore_words = [
        # Produkttypen
        "display", "displays", "booster", "boosters", "pack", "packs", 
        "box", "boxes", "etb", "ttb", "tin", "tins", "blister", "blisters",
        
        # Pokémon-spezifische Wörter
        "pokemon", "pokémon", "tcg", "trading", "card", "cards", "game",
        
        # Füllwörter
        "und", "the", "and", "for", "mit", "von", "pro", "per", 
        "der", "die", "das", "ein", "eine", "einem", "einen", "einer",
        
        # Zahlen und Einheiten
        "36er", "36", "18er", "18", "3er", "3"
    ]
    
    important = []
    for keyword in keywords:
        keyword_lower = keyword.lower()
        # Strengere Kriterien: Mindestens 3 Zeichen und nicht in Ignorierliste
        if len(keyword) >= 3 and keyword_lower not in ignore_words:
            important.append(keyword_lower)
    
    # Mindestens ein wichtiges Keyword muss vorhanden sein
    if not important and keywords:
        # Fallback: Nimm das längste Keyword das nicht ignoriert wird
        candidates = [k for k in keywords if k.lower() not in ignore_words]
        if candidates:
            important.append(max(candidates, key=len).lower())
    
    return important

def validate_specific_keywords(product_type, text):
    """
    Validiert spezifische Keywords basierend auf dem Produkttyp
    """
    if product_type == "display":
        # Muss Display- oder 36er-Begriff enthalten
        if not re.search(r'\b(display|36er|36\s|booster\s+box)\b', text):
            return False
    
    elif product_type == "etb":
        # Muss ETB- oder Elite Trainer-Begriff enthalten
        if not re.search(r'\b(etb|elite\s+trainer|trainer\s+box)\b', text):
            return False
    
    elif product_type == "ttb":
        # Muss TTB- oder Top Trainer-Begriff enthalten
        if not re.search(r'\b(ttb|top\s+trainer|trainer\s+box)\b', text):
            return False
    
    return True

def extract_product_keywords(search_term):
    """
    Extrahiert produktspezifische Keywords aus einem Suchbegriff (ohne Produkttyp)
    
    :param search_term: Suchbegriff
    :return: Liste mit produktspezifischen Keywords
    """
    search_term = search_term.lower()
    
    # Entferne Produkttyp-Wörter
    product_type_words = [
        "display", "etb", "ttb", "elite trainer box", "top trainer box", 
        "elite-trainer-box", "top-trainer-box", "box", "tin", "blister",
        "booster", "pack", "36er", "18er", "3er"
    ]
    
    clean_term = search_term
    for word in product_type_words:
        clean_term = re.sub(rf'\b{re.escape(word)}\b', '', clean_term)
    
    # Bereinige und teile in Wörter
    clean_term = clean_text(clean_term)
    keywords = [word for word in clean_term.split() if len(word) > 2]
    
    # Entferne häufige Füllwörter
    ignore_words = ["und", "the", "and", "for", "mit", "von", "pro", "per", "der", "die", "das", "set"]
    keywords = [word for word in keywords if word not in ignore_words]
    
    return keywords

def load_exclusion_sets():
    """
    Lädt die Liste der auszuschließenden Sets aus einer Konfigurationsdatei
    
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
        "stürmische funken", "sturmi", "paradox rift", "paradox", "prismat", "stellar", 
        "battle partners", "nebel der sagen", "zeit", "paldea", "obsidian", "151", 
        "astral", "brilliant", "fusion", "kp01", "kp02", "kp03", "kp04", "kp05", 
        "kp06", "kp07", "kp08", "sv01", "sv02", "sv03", "sv04", "sv05", "sv06", 
        "sv07", "sv08", "sv10", "sv11", "sv12", "sv13", "glory of team rocket"
    ]
    
    return exclusion_sets

def normalize_product_name(text):
    """
    Normalisiert einen Produktnamen für konsistenten Vergleich
    
    :param text: Zu normalisierender Text
    :return: Normalisierter Text
    """
    text = clean_text(text)
    
    # Standardisiere Singular/Plural
    text = normalize_text_forms(text)
    
    # Korrigiere bekannte Tippfehler
    corrections = {
        "togehter": "together",
        "journy": "journey", 
        "scarlett": "scarlet",
        "reisegefärten": "reisegefährten"
    }
    
    for wrong, correct in corrections.items():
        text = text.replace(wrong, correct)
    
    return text

def normalize_text_forms(text):
    """Normalisiert Singular/Plural-Formen im Text"""
    replacements = {
        "displays": "display",
        "boosters": "booster",
        "packs": "pack",
        "boxes": "box",
        "tins": "tin",
        "blisters": "blister"
    }
    
    for plural, singular in replacements.items():
        text = text.replace(plural, singular)
    
    return text

def prepare_keywords(products):
    """
    Zerlegt die products.txt Zeilen in Keyword-Listen
    und fügt ggf. Synonyme aus synonyms.json hinzu
    
    :param products: Liste der Produktzeilen aus products.txt
    :return: Dictionary mit Suchbegriffen und ihren Tokens
    """
    keywords_map = {}
    
    # Verarbeite jede Zeile aus products.txt
    for line in products:
        # Entferne führende/nachfolgende Leerzeichen
        clean_line = line.strip()
        if clean_line:  # Überspringe leere Zeilen
            keywords_map[clean_line] = clean_text(clean_line).split()
    
    # Lade Synonyme
    synonyms = load_synonyms()
    
    # Füge Synonyme hinzu, aber nur wenn sie zu einem existierenden Produkt gehören
    for key, synonym_list in synonyms.items():
        if key in keywords_map:
            # Füge nur die Synonyme als separate Suchbegriffe hinzu
            for synonym in synonym_list:
                if synonym not in keywords_map:  # Vermeide Duplikate
                    keywords_map[synonym] = clean_text(synonym).split()
    
    logger.info(f"ℹ️ Geladene Suchbegriffe: {list(keywords_map.keys())}")
    
    return keywords_map

def load_synonyms():
    """Lädt Synonyme aus der Konfigurationsdatei"""
    synonyms = {}
    
    synonyms_file_paths = ["config/synonyms.json", "data/synonyms.json"]
    
    for file_path in synonyms_file_paths:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                synonyms = json.load(f)
                logger.info(f"ℹ️ Synonyme aus {file_path} geladen")
                return synonyms
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.debug(f"ℹ️ Synonyme aus {file_path} konnten nicht geladen werden: {e}")
    
    logger.info("ℹ️ Keine Synonyme gefunden. Nur direkte Suchbegriffe werden verwendet.")
    return synonyms

def is_product_match(search_terms, product_title):
    """
    Hauptfunktion für präzises Produkt-Matching
    
    :param search_terms: String mit Suchbegriff aus products.txt
    :param product_title: Titel des gefundenen Produkts
    :return: True wenn das Produkt dem Suchbegriff entspricht, sonst False
    """
    # Normalisiere beide Texte
    normalized_search = normalize_product_name(search_terms)
    normalized_title = normalize_product_name(product_title)
    
    # Extrahiere Produkttypen
    search_type = extract_product_type_from_text(normalized_search)
    title_type = extract_product_type_from_text(normalized_title)
    
    # Strikte Produkttyp-Validierung
    if search_type != "unknown" and title_type != "unknown":
        if search_type != title_type:
            logger.debug(f"❌ Produkttyp stimmt nicht überein: gesucht '{search_type}', gefunden '{title_type}'")
            return False
    
    # Extrahiere Keywords
    search_keywords = clean_text(normalized_search).split()
    
    # Verwende is_keyword_in_text für konsistente Prüfung
    return is_keyword_in_text(search_keywords, normalized_title, log_level='None')

def is_strict_match(keywords, text, threshold=1.0):
    """
    Führt einen strikten Match durch - eine konfigurierbare Anzahl von Keywords muss übereinstimmen
    
    :param keywords: Liste der Keywords
    :param text: Text zum Durchsuchen
    :param threshold: Anteil der Keywords die gefunden werden müssen (0.0-1.0)
    :return: True wenn genug Keywords gefunden wurden
    """
    if not keywords or not text:
        return False
    
    text_lower = text.lower()
    text_words = set(re.findall(r'\b\w+\b', text_lower))
    
    # Extrahiere wichtige Keywords
    important_keywords = extract_important_keywords(keywords)
    
    if not important_keywords:
        return False
    
    # Zähle gefundene Keywords
    found_count = 0
    for keyword in important_keywords:
        keyword_lower = keyword.lower()
        if keyword_lower in text_words:
            found_count += 1
        else:
            # Prüfe auf Teilübereinstimmungen
            if any(keyword_lower in word for word in text_words):
                found_count += 1
    
    # Berechne ob genug Keywords gefunden wurden
    required_matches = max(1, int(len(important_keywords) * threshold))
    return found_count >= required_matches