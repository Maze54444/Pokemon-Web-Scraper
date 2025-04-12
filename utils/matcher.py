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

def extract_product_type_from_text(text):
    """
    Extrahiert den Produkttyp aus einem Text für strengere Filterung
    
    :param text: Text, aus dem der Produkttyp extrahiert werden soll
    :return: Produkttyp als String oder None wenn nicht eindeutig
    """
    text = text.lower()
    
    # Definiere klare Muster für verschiedene Produkttypen
    product_patterns = {
        "display": [r'\bdisplay\b', r'36er', r'36\s+booster', r'booster\s+display'],
        "etb": [r'\belite\s+trainer\s+box\b', r'\betb\b', r'\btrainer\s+box\b', r'\btop\s+trainer\s+box\b'],
        "build_battle": [r'\bbuild\s*[&]?\s*battle\b', r'\bprerelease\b'],
        "blister": [r'\bblister\b', r'\b3er\s+blister\b', r'\b3-pack\b', r'\bchecklane\b', r'\bsleeve(d)?\s+booster\b'],
        "booster": [r'\bbooster\b', r'\bbooster\s+pack\b', r'\bpack\b'],
        "tin": [r'\btin\b', r'\bmetal\s+box\b'],
        "premium": [r'\bpremium\b', r'\bcollection\b', r'\bcollector\b']
    }
    
    for product_type, patterns in product_patterns.items():
        for pattern in patterns:
            if re.search(pattern, text):
                return product_type
    
    return None  # Wenn kein klarer Produkttyp erkannt wurde

def is_product_type_match(search_type, text_type):
    """
    Prüft, ob der Produkttyp im Text mit dem gesuchten Produkttyp übereinstimmt
    
    :param search_type: Gesuchter Produkttyp
    :param text_type: Im Text gefundener Produkttyp
    :return: True wenn übereinstimmend, False sonst
    """
    # Wenn kein bestimmter Produkttyp gesucht wird, gilt das als Übereinstimmung
    if not search_type:
        return True
    
    # Wenn im Text kein Produkttyp erkannt wurde, aber einer gesucht wird, keine Übereinstimmung
    if search_type and not text_type:
        return False
    
    # Exakte Übereinstimmung erforderlich
    return search_type == text_type

def is_keyword_in_text(keywords, text):
    """
    Strengere Prüfung auf exakte Übereinstimmung des Suchbegriffs im Text
    mit besonderer Berücksichtigung der Produkttypen
    
    :param keywords: Liste mit einzelnen Wörtern des Suchbegriffs
    :param text: Zu prüfender Text
    :return: True, wenn die Phrase gefunden wurde und Produkttypen übereinstimmen, sonst False
    """
    original_keywords = " ".join(keywords)  # für Debug-Ausgaben
    text = clean_text(text)
    
    # Extrahiere den Produkttyp aus dem Suchbegriff
    search_term = " ".join(keywords)
    search_product_type = extract_product_type_from_text(search_term)
    
    # Extrahiere den Produkttyp aus dem zu durchsuchenden Text
    text_product_type = extract_product_type_from_text(text)
    
    # Wenn nach einem bestimmten Produkttyp gesucht wird, muss dieser im Text übereinstimmen
    if search_product_type and text_product_type:
        if search_product_type != text_product_type:
            print(f"    ❌ Produkttyp-Konflikt: Suche nach '{search_product_type}', Text enthält '{text_product_type}'", flush=True)
            return False
    
    # Wenn nach "display" gesucht wird, darf der Text KEINEN anderen Produkttyp enthalten
    if search_product_type == "display" and text_product_type and text_product_type != "display":
        print(f"    ❌ Nach Display gesucht, aber Produkt ist '{text_product_type}'", flush=True)
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
    
    # Konstruiere eine exakte Phrase aus den standardisierten Keywords
    phrase = " ".join(standardized_keywords)
    
    # Die Phrase muss als eigenständiges Wort oder Teilphrase vorkommen
    words = standardized_text.split()
    text_length = len(words)
    phrase_words = phrase.split()
    phrase_length = len(phrase_words)
    
    # Überprüfe die Übereinstimmung von Schlüsselwörtern
    key_terms_found = True
    
    # Überprüfe, ob alle wichtigen Begriffe enthalten sind (z.B. "journey together", "reisegefährten")
    non_product_keywords = [k for k in standardized_keywords if k not in ["display", "booster", "pack", "box", "etb", "blister"]]
    for key_term in non_product_keywords:
        if key_term not in standardized_text:
            key_terms_found = False
            break
    
    if not key_terms_found:
        print(f"    ❌ Wichtige Begriffe nicht gefunden: '{original_keywords}' in '{text}'", flush=True)
        return False
    
    # Suche nach der exakten Phrase im Text
    exact_match = False
    for i in range(text_length - phrase_length + 1):
        if " ".join(words[i:i+phrase_length]) == phrase:
            exact_match = True
            break
    
    # Wenn eine exakte Übereinstimmung erforderlich ist und fehlt
    if phrase_length <= 3 and not exact_match:
        print(f"    ❌ Keine exakte Übereinstimmung für kurze Phrase: '{original_keywords}' in '{text}'", flush=True)
        return False
    
    # Spezielle Logik für Produkte mit "display" im Suchbegriff
    if "display" in standardized_keywords:
        if "display" not in standardized_text:
            print(f"    ❌ 'display' im Suchbegriff, aber nicht im Text gefunden: '{original_keywords}' in '{text}'", flush=True)
            return False
    
    print(f"    ✅ Treffer für Suchbegriff: '{original_keywords}' in '{text}'", flush=True)
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
                print(f"ℹ️ Synonyme aus {file_path} geladen", flush=True)
                break  # Wenn erfolgreich geladen, breche die Schleife ab
                
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"ℹ️ Synonyme aus {file_path} konnten nicht geladen werden: {e}", flush=True)
    
    if not synonyms_loaded:
        print("ℹ️ Keine Synonyme geladen. Nur direkte Suchbegriffe werden verwendet.", flush=True)
    
    # Debug-Ausgabe der geladenen Suchbegriffe
    print(f"ℹ️ Geladene Suchbegriffe: {list(keywords_map.keys())}", flush=True)
    
    return keywords_map