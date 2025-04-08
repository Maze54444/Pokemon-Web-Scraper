import requests
from utils.telegram import send_telegram_message
from utils.matcher import is_keyword_in_text

def scrape_tcgviert(keywords_map, seen):
    """
    Scraper für tcgviert.com
    
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param seen: Set mit bereits gesehenen Produkttiteln
    :return: Liste der neuen Treffer
    """
    print("🌐 Starte JSON-Scraper für tcgviert.com", flush=True)
    
    new_matches = []
    
    try:
        # Versuche zuerst den JSON-Endpunkt
        response = requests.get("https://tcgviert.com/products.json", timeout=10)
        if response.status_code != 200:
            print("⚠️ API antwortet nicht mit Status 200. Versuche HTML-Fallback...", flush=True)
            return scrape_tcgviert_html_fallback(keywords_map, seen)
        
        data = response.json()
        if "products" not in data or not data["products"]:
            print("⚠️ Keine Produkte im JSON gefunden. Versuche HTML-Fallback...", flush=True)
            return scrape_tcgviert_html_fallback(keywords_map, seen)
        
        products = data["products"]
        print(f"🔍 {len(products)} Produkte zum Prüfen gefunden", flush=True)
        
        for product in products:
            title = product["title"]
            handle = product["handle"]
            
            # Prüfe jeden Suchbegriff gegen den Produkttitel
            for search_term, tokens in keywords_map.items():
                if is_keyword_in_text(tokens, title):
                    # Eindeutige ID für dieses Produkt
                    product_id = f"tcgviert_{handle}"
                    
                    if product_id not in seen:
                        # Produkt wurde noch nicht gemeldet
                        url = f"https://tcgviert.com/products/{handle}"
                        
                        # Preis aus der ersten Variante extrahieren, falls vorhanden
                        price = "Preis unbekannt"
                        if product.get("variants") and len(product["variants"]) > 0:
                            price = f"{product['variants'][0].get('price', 'N/A')}€"
                        
                        # Status prüfen (verfügbar/ausverkauft)
                        available = False
                        for variant in product.get("variants", []):
                            if variant.get("available", False):
                                available = True
                                break
                        
                        status = "✅ Verfügbar" if available else "❌ Ausverkauft"
                        
                        # Nachricht zusammenstellen
                        msg = (
                            f"🎯 *{title}*\n"
                            f"💶 {price}\n"
                            f"📊 {status}\n"
                            f"🔎 Treffer für: '{search_term}'\n"
                            f"🔗 [Zum Produkt]({url})"
                        )
                        
                        # Telegram-Nachricht senden
                        if send_telegram_message(msg):
                            seen.add(product_id)
                            new_matches.append(product_id)
                            print(f"✅ Neuer Treffer gefunden: {title}", flush=True)
        
    except Exception as e:
        print(f"❌ Fehler beim TCGViert JSON-Scraping: {e}", flush=True)
        # Versuche HTML-Fallback bei Fehlern
        return scrape_tcgviert_html_fallback(keywords_map, seen)
    
    return new_matches

def scrape_tcgviert_html_fallback(keywords_map, seen):
    """Fallback-Scraper für TCGViert über HTML, falls JSON-API nicht funktioniert"""
    print("🔄 Starte HTML-Fallback für tcgviert.com", flush=True)
    new_matches = []
    
    try:
        # URLs zum Durchsuchen
        urls = [
            "https://tcgviert.com/collections/vorbestellungen",
            "https://tcgviert.com/collections/neu-eingetroffen"
        ]
        
        from bs4 import BeautifulSoup
        
        for url in urls:
            print(f"🔍 Durchsuche {url}", flush=True)
            response = requests.get(url, timeout=15)
            if response.status_code != 200:
                print(f"⚠️ Fehler beim Abrufen von {url}: Status {response.status_code}", flush=True)
                continue
            
            soup = BeautifulSoup(response.text, "html.parser")
            products = soup.select(".product-card")
            
            print(f"🔍 {len(products)} Produkte auf {url} gefunden", flush=True)
            
            for product in products:
                # Extrahiere Titel und Link
                title_elem = product.select_one(".product-card__title")
                if not title_elem:
                    continue
                
                title = title_elem.text.strip()
                
                # Link extrahieren
                link_elem = product.select_one("a.product-card__link")
                if not link_elem:
                    continue
                
                relative_url = link_elem.get("href", "")
                product_url = f"https://tcgviert.com{relative_url}" if relative_url.startswith("/") else relative_url
                
                # Preis extrahieren
                price_elem = product.select_one(".product-card__price")
                price = price_elem.text.strip() if price_elem else "Preis unbekannt"
                
                # Handle aus URL extrahieren für eindeutige ID
                handle = relative_url.split("/")[-1] if relative_url else title.lower().replace(" ", "-")
                product_id = f"tcgviert_{handle}"
                
                # Prüfe jeden Suchbegriff gegen den Produkttitel
                for search_term, tokens in keywords_map.items():
                    if is_keyword_in_text(tokens, title):
                        if product_id not in seen:
                            # Status (Vorbestellung/verfügbar)
                            status = "🔜 Vorbestellung" if "vorbestellungen" in url else "✅ Verfügbar"
                            
                            msg = (
                                f"🎯 *{title}*\n"
                                f"💶 {price}\n"
                                f"📊 {status}\n"
                                f"🔎 Treffer für: '{search_term}'\n"
                                f"🔗 [Zum Produkt]({product_url})"
                            )
                            
                            if send_telegram_message(msg):
                                seen.add(product_id)
                                new_matches.append(product_id)
                                print(f"✅ Neuer Treffer gefunden (HTML): {title}", flush=True)
        
    except Exception as e:
        print(f"❌ Fehler beim TCGViert HTML-Fallback: {e}", flush=True)
    
    return new_matches