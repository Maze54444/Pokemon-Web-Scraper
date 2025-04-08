# ... (imports und setup wie gehabt)

def is_flexible_match(keywords, text, threshold=0.75):
    matches = [word for word in keywords if word in text]
    score = len(matches) / len(keywords)
    print(f"🟡 LOG: Keywords = {keywords}", flush=True)
    print(f"🟡 LOG: Text = {text[:100]}...", flush=True)
    print(f"🟡 LOG: Gefundene Wörter: {matches} → Trefferquote: {score:.2f}", flush=True)
    return score >= threshold

def parse_tcgviert(content, keywords, seen):
    soup = BeautifulSoup(content, "html.parser")
    found = []

    products = soup.find_all("a", href=True)
    for product in products:
        title_tag = product.find("p")
        price_tag = product.find_next(string=re.compile(r"\d{1,3}[.,]\d{2} ?€"))

        if title_tag:
            title = title_tag.get_text(strip=True).lower()
            print(f"🟡 LOG: Prüfe Titel: {title}", flush=True)

            if is_flexible_match(keywords, title):
                link = "https://tcgviert.com" + product['href']
                price = price_tag.strip() if price_tag else "Preis nicht gefunden"
                product_id = hashlib.md5((title + link).encode()).hexdigest()

                if product_id not in seen:
                    found.append((title, link, price, product_id))
            else:
                print("🟡 LOG: → NICHT genug Übereinstimmung, wird übersprungen\n", flush=True)
    return found

