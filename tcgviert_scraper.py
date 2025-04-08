import requests
import json
import time
import datetime
import os
import re
from telegram import send_telegram_message

# Dateien laden
def load_file(filename):
    with open(filename, "r", encoding="utf-8") as f:
        return [line.strip() for line in f.readlines() if line.strip()]

def load_json(filename):
    with open(filename, "r", encoding="utf-8") as f:
        return json.load(f)

# Text vereinfachen für flexibles Matching
def clean_text(text):
    return re.sub(r"[^a-z0-9äöüß ]", "", text.lower())

# Flexibles Wort-Matching mit Logausgabe
def is_flexible_match(keywords, text):
    match_count = 0
    for word in keywords:
        if word in text:
            match_count += 1
    ratio = match_count / len(keywords)
    print(f"🟡 LOG: Keywords = {keywords}")
    print(f"🟡 LOG: Gefundene Wörter = {[w for w in keywords if w in text]} → Trefferquote = {ratio:.2f}")
    return ratio >= 0.5

# Hauptfunktion
def run_tcgviert_scraper():
    print("🟢 Master-Scraper gestartet")
    print("🌐 JSON-API von tcgviert.com wird verwendet")

    products_of_interest = load_file("products.txt")
    urls = load_file("urls.txt")
    telegram_config = load_json("telegram_config.json")
    seen = set(load_file("seen.txt")) if os.path.exists("seen.txt") else set()

    api_url = "https://tcgviert.com/products.json"
    response = requests.get(api_url)
    all_products = response.json().get("products", [])

    found_anything = False

    for product in all_products:
        title = clean_text(product.get("title", ""))
        handle = product.get("handle", "")
        url = f"https://tcgviert.com/products/{handle}"
        price = product["variants"][0]["price"] if product["variants"] else "?"

        for entry in products_of_interest:
            keywords = clean_text(entry).split()
            if is_flexible_match(keywords, title):
                if title not in seen:
                    message = f"✅ TREFFER: {product['title']} – {price} € – {url}"
                    print(message)
                    send_telegram_message(message, telegram_config)
                    seen.add(title)
                    found_anything = True

    if found_anything:
        with open("seen.txt", "w", encoding="utf-8") as f:
            for item in seen:
                f.write(item + "\n")

if __name__ == "__main__":
    run_tcgviert_scraper()
