# utils/matcher.py
import re
import json
import os

def clean_text(text):
    return re.sub(r"[^a-z0-9äöüß ]", "", text.lower())

def is_flexible_match(keywords, text, threshold=0.75):
    match_count = sum(1 for word in keywords if word in text)
    ratio = match_count / len(keywords)
    print(f"🟡 Keywords: {keywords} | Trefferquote: {ratio:.2f}")
    return ratio >= threshold

def load_synonyms(path="config/synonyms.json"):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def prepare_keywords(product_lines):
    synonyms = load_synonyms()
    keyword_map = {}

    for line in product_lines:
        keywords = clean_text(line).split()
        keyword_map[line] = keywords
        for token in keywords:
            if token in synonyms:
                keyword_map[line] += [clean_text(w).strip() for w in synonyms[token]]

    return keyword_map
