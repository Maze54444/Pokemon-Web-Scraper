import re
import json
import os

def clean_text(text):
    """
    Entfernt Sonderzeichen, macht Kleinbuchstaben und entfernt doppelte Leerzeichen.
    """
    text = re.sub(r"[^a-z0-9äöüß ]", "", text.lower())
    return re.sub(r"\s+", " ", text.strip())

def is_flexible_match(keywords, text, threshold=0.75):
    """
    Vergleicht Keywords mit Zieltext basierend auf Token-Übereinstimmung.
    Gibt True zurück, wenn die Übereinstimmung ≥ threshold ist.
    """
    matches = sum(1 for word in keywords if word in text)
    ratio = matches / len(keywords) if keywords else 0
    print(f"🟡 Prüfe gegen Produkt: '{text}' mit Keywords {keywords} → Trefferquote: {ratio:.2f}", flush=True)
    return ratio >= threshold

def load_synonyms(path="config/synonyms.json"):
    """
    Lädt optionale Synonyme aus einer JSON-Datei.
    """
    return json.load(open(path, "r", encoding="utf-8")) if os.path.exists(path) else {}

def prepare_keywords(product_lines):
    """
    Zerlegt jede Zeile aus products.txt in Tokens + ergänzt optionale Synonyme.
    Gibt Dictionary zurück: { Originalzeile: [token1, token2, ...] }
    """
    synonyms = load_synonyms()
    keyword_map = {}

    for line in product_lines:
        words = clean_text(line).split()
        extended = words[:]
        for word in words:
            extended += [clean_text(w) for w in synonyms.get(word, [])]
        keyword_map[line] = list(set(extended))  # Duplikate entfernen

    return keyword_map
