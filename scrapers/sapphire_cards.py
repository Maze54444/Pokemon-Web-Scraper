import requests
import hashlib
import re
from bs4 import BeautifulSoup
from utils.telegram import send_telegram_message, escape_markdown
from utils.matcher import is_keyword_in_text
from utils.stock import get_status_text, update_product_status
from utils.availability import detect_availability

def scrape_sapphire_cards(keywords_map, seen, out_of_stock, only_available=False):
    """
    Spezieller Scraper für sapphire-cards.de
    
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param seen: Set mit bereits gesehenen Produkttiteln
    :param out_of_stock: Set mit ausverkauften Produkten
    :param only_available: Ob nur verfügbare Produkte gemeldet werden sollen
    :return: Liste der neuen Treffer
    """
    print("[INFO] Starte speziellen Scraper für sapphire-cards.de", flush=True)
    new_matches = []
    
    # Für jeden Suchbegriff einen direkten Suchaufruf durchführen
    for search_term, tokens in keywords_map.items():
        clean_term = search_term.replace(" ", "+").lower()
        search_url = f"https://sapphire-cards.de/?s={clean_term}&post_type=product"
        
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            
            # Durchführen der Suchanfrage
            response = requests.get(search_url, headers=headers, timeout=15)
            if response.status_code != 200:
                print(f"[WARN] Fehler beim Abrufen von {search_url}: Status {response.status_code}", flush=True)
                continue
            
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Nach Produkten suchen (sapphire-cards.de spezifische Selektoren)
            products = soup.select('.product, .woocommerce-product, .type-product')
            
            if not products:
                # Alternative Selektoren versuchen
                products = soup.select('li.product, div.product, article.product')
            
            print(f"[INFO] {len(products)} Produkte bei der Suche nach '{search_term}' gefunden", flush=True)
            
            # Wenn keine Produkte gefunden wurden, versuche generischen Link-Scan
            if not products:
                all_links = soup.select('a[href*="product"]')
                print(f"[INFO] {len(all_links)} potenzielle Produkt-Links gefunden", flush=True)
                
                for link in all_links:
                    href = link.get('href', '')
                    link_text = link.get_text().strip()
                    
                    # Prüfe, ob der Link-Text mit dem Suchbegriff übereinstimmt
                    if is_keyword_in_text(tokens, link_text):
                        print(f"[INFO] Treffer für '{search_term}' im Link: {link_text}", flush=True)
                        
                        # Prüfe Verfügbarkeit und sende Benachrichtigung
                        product_url = href
                        try:
                            detail_response = requests.get(product_url, headers=headers, timeout=15)
                            if detail_response.status_code == 200:
                                detail_soup = BeautifulSoup(detail_response.text, "html.parser")
                                is_available, price, status_text = detect_availability(detail_soup, product_url)
                                
                                # Produkt-ID aus URL und Link-Text erstellen
                                product_id = f"sapphirecards_{hashlib.md5(product_url.encode()).hexdigest()[:10]}"
                                
                                # Nur verfügbare anzeigen, wenn Option aktiviert
                                if only_available and not is_available:
                                    continue
                                    
                                # Status aktualisieren und ggf. Benachrichtigung senden
                                should_notify, is_back_in_stock = update_product_status(
                                    product_id, is_available, seen, out_of_stock
                                )
                                
                                if should_notify:
                                    # Status anpassen wenn wieder verfügbar
                                    if is_back_in_stock:
                                        status_text = "[GOOD] Wieder verfügbar!"
                                        
                                    # Escape special characters for Markdown
                                    safe_link_text = escape_markdown(link_text)
                                    safe_price = escape_markdown(price)
                                    safe_status_text = escape_markdown(status_text)
                                    safe_search_term = escape_markdown(search_term)
                                    
                                    msg = (
                                        f"[MATCH] *{safe_link_text}*\n"
                                        f"[PRICE] {safe_price}\n"
                                        f"[STATUS] {safe_status_text}\n"
                                        f"[SEARCH] Treffer für: '{safe_search_term}'\n"
                                        f"[LINK] [Zum Produkt]({product_url})"
                                    )
                                    
                                    if send_telegram_message(msg):
                                        if is_available:
                                            seen.add(f"{product_id}_status_available")
                                        else:
                                            seen.add(f"{product_id}_status_unavailable")
                                        
                                        new_matches.append(product_id)
                                        print(f"[SUCCESS] Neuer Treffer bei sapphire-cards.de: {link_text} - {status_text}", flush=True)
                        except Exception as e:
                            print(f"[WARN] Fehler beim Prüfen des Produkts {product_url}: {e}", flush=True)
            
            # Normale Produktliste verarbeiten
            for product in products:
                # Titel und Link extrahieren
                title_elem = product.select_one('.woocommerce-loop-product__title, .product-title, h2, h3')
                title = title_elem.text.strip() if title_elem else "Unbekanntes Produkt"
                
                link_elem = product.select_one('a.woocommerce-loop-product__link, a.product-link, a')
                if not link_elem or not link_elem.get('href'):
                    continue
                
                product_url = link_elem['href']
                
                # Prüfe, ob der Produkttitel mit dem Suchbegriff übereinstimmt
                if is_keyword_in_text(tokens, title):
                    print(f"[INFO] Treffer für '{search_term}' im Produkt: {title}", flush=True)
                    
                    # Prüfe Verfügbarkeit und sende Benachrichtigung
                    try:
                        detail_response = requests.get(product_url, headers=headers, timeout=15)
                        if detail_response.status_code == 200:
                            detail_soup = BeautifulSoup(detail_response.text, "html.parser")
                            is_available, price, status_text = detect_availability(detail_soup, product_url)
                            
                            # Produkt-ID aus URL und Titel erstellen
                            product_id = f"sapphirecards_{hashlib.md5(product_url.encode()).hexdigest()[:10]}"
                            
                            # Nur verfügbare anzeigen, wenn Option aktiviert
                            if only_available and not is_available:
                                continue
                                
                            # Status aktualisieren und ggf. Benachrichtigung senden
                            should_notify, is_back_in_stock = update_product_status(
                                product_id, is_available, seen, out_of_stock
                            )
                            
                            if should_notify:
                                # Status anpassen wenn wieder verfügbar
                                if is_back_in_stock:
                                    status_text = "[GOOD] Wieder verfügbar!"
                                    
                                # Escape special characters for Markdown
                                safe_title = escape_markdown(title)
                                safe_price = escape_markdown(price)
                                safe_status_text = escape_markdown(status_text)
                                safe_search_term = escape_markdown(search_term)
                                
                                msg = (
                                    f"[MATCH] *{safe_title}*\n"
                                    f"[PRICE] {safe_price}\n"
                                    f"[STATUS] {safe_status_text}\n"
                                    f"[SEARCH] Treffer für: '{safe_search_term}'\n"
                                    f"[LINK] [Zum Produkt]({product_url})"
                                )
                                
                                if send_telegram_message(msg):
                                    if is_available:
                                        seen.add(f"{product_id}_status_available")
                                    else:
                                        seen.add(f"{product_id}_status_unavailable")
                                    
                                    new_matches.append(product_id)
                                    print(f"[SUCCESS] Neuer Treffer bei sapphire-cards.de: {title} - {status_text}", flush=True)
                    except Exception as e:
                        print(f"[WARN] Fehler beim Prüfen des Produkts {product_url}: {e}", flush=True)
        
        except Exception as e:
            print(f"[ERROR] Fehler beim Scrapen von sapphire-cards.de für '{search_term}': {e}", flush=True)
    
    return new_matches

# Zur Verwendung als eigenständiges Skript für Tests
if __name__ == "__main__":
    from utils.filetools import load_list
    from utils.matcher import prepare_keywords
    
    products = load_list("data/products.txt")
    keywords_map = prepare_keywords(products)
    
    seen = set()
    out_of_stock = set()
    
    scrape_sapphire_cards(keywords_map, seen, out_of_stock)