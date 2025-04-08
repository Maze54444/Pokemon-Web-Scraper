import re

def clean_text(text):
    """
    Entfernt Sonderzeichen, wandelt zu Kleinbuchstaben & entfernt doppelte Leerzeichen
    """
    return re.sub(r"[^a-zA-Z0-9äöüß ]", " ", text.lower()).replace("  ", " ").strip()

def is_keyword_in_text(keywords, text):
    """
    Prüft, ob ALLE Wörter (z. B. ['reisegefährten', 'display']) im Text vorkommen
    """
    text = clean_text(text)
    return all(word in text for word in keywords)

def prepare_keywords(products):
    """
    Zerlegt die products.txt Zeilen in Keyword-Listen
    """
    return {
        line: clean_text(line).split()
        for line in products
    }
