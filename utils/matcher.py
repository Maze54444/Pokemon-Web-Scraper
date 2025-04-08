
import re, json, os

def clean_text(text):
    return re.sub(r"[^a-z0-9äöüß ]", "", text.lower())

def is_flexible_match(keywords, text, threshold=0.75):
    matches = sum(1 for word in keywords if word in text)
    ratio = matches / len(keywords)
    return ratio >= threshold

def load_synonyms(path="config/synonyms.json"):
    return json.load(open(path, "r", encoding="utf-8")) if os.path.exists(path) else {}

def prepare_keywords(product_lines):
    synonyms = load_synonyms()
    keyword_map = {}
    for line in product_lines:
        words = clean_text(line).split()
        keyword_map[line] = words + [w for word in words for w in synonyms.get(word, [])]
    return keyword_map
