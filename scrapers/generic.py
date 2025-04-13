import requests
import hashlib
import os
import json
import time
from pathlib import Path
from bs4 import BeautifulSoup
import re
from utils.matcher import clean_text, is_keyword_in_text, normalize_product_name, extract_product_type_from_text
from utils.telegram import send_telegram_message, escape_markdown
from utils.stock import get_status_text, update_product_status
# Importiere das Modul für webseitenspezifische Verfügbarkeitsprüfung
from utils.availability import detect_availability, extract_price
# Import der Filter-Funktionen
from utils.filters import should_skip_url, filter_links, log_filter_stats

def load_product_cache(cache_file="data/product_cache.json"):
    """Lädt das Cache-Dictionary mit bekannten Produkten und ihren URLs"""
    try:
        if os.path.exists(cache_file):
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}
    except Exception as e:
        print(f"⚠️ Fehler beim Laden des Produkt-Caches: {e}", flush=True)
        return {}

def save_product_cache(cache, cache_file="data/product_cache.json"):
    """Speichert das Cache-Dictionary mit bekannten Produkten"""
    try:
        # Stelle sicher, dass das Verzeichnis existiert
        Path(cache_file).parent.mkdir(parents=True, exist_ok=True)
        
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ Fehler beim Speichern des Produkt-Caches: {e}", flush=True)

def create_fingerprint(html_content):
    """Erstellt einen Fingerprint vom HTML-Inhalt, um Änderungen zu erkennen"""
    # Wir verwenden einen Hash des Inhalts als Fingerprint
    return hashlib.md5(html_content.encode('utf-8')).hexdigest()

def extract_product_type_from_search_term(search_term):
    """Extrahiert den Produkttyp direkt aus einem Suchbegriff"""
    return extract_product_type_from_text(search_term)

def scrape_generic(url, keywords_map, seen, out_of_stock, check_availability=True, only_available=False):
    """
    Optimierte generische Scraper-Funktion mit Cache-Unterstützung und verbesserter Produkttyp-Prüfung
    
    :param url: URL der zu scrapenden Website
    :param keywords_map: Dictionary mit Suchbegriffen und ihren Tokens
    :param seen: Set mit bereits gesehenen Produkttiteln
    :param out_of_stock: Set mit ausverkauften Produkten
    :param check_availability: Ob Produktdetailseiten für Verfügbarkeitsprüfung besucht werden sollen
    :param only_available: Ob nur verfügbare Produkte gemeldet werden sollen
    :return: Liste der neuen Treffer
    """
    print(f"🌐 Starte generischen Scraper für {url}", flush=True)
    new_matches = []
    
    # Cache laden oder neu erstellen
    product_cache = load_product_cache()
    site_id = url.split('//')[1].split('/')[0].replace('www.', '')
    
    # Prüfe, ob wir neue Keywords haben, die nicht im Cache sind
    cache_key = f"{site_id}_keywords"
    cached_keywords = product_cache.get(cache_key, [])
    current_keywords = list(keywords_map.keys())
    
    new_keywords = [k for k in current_keywords if k not in cached_keywords]
    if new_keywords:
        print(f"🔍 Neue Suchbegriffe gefunden: {new_keywords}", flush=True)
        # Wir werden die Seite vollständig scannen, da wir neue Keywords haben
        full_scan_needed = True
    else:
        # Keine neuen Keywords, wir können den Cache nutzen
        full_scan_needed = False
    
    try:
        # User-Agent setzen, um Blockierung zu vermeiden
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        
        # Prüfen, ob wir gecachte Produktpfade für diese Domain haben
        domain_paths = product_cache.get(site_id, {})
        
        if domain_paths and not full_scan_needed:
            print(f"🔍 Nutze {len(domain_paths)} gecachte Produktpfade für {site_id}", flush=True)
            
            # Nur die bereits bekannten Produktseiten prüfen
            for product_id, product_info in list(domain_paths.items()):  # list() erstellen um während Iteration zu löschen
                product_url = product_info.get("url", "")
                matched_term = product_info.get("term", "")
                last_checked = product_info.get("last_checked", 0)
                
                # Nur Produkte prüfen, die für unsere aktuellen Suchbegriffe relevant sind
                if matched_term not in keywords_map:
                    continue
                
                # Prüfen, ob die Seite vor kurzem überprüft wurde (z.B. in den letzten 12 Stunden)
                if time.time() - last_checked < 43200:  # 12 Stunden in Sekunden
                    print(f"⏱️ Überspringe kürzlich geprüftes Produkt: {product_url}", flush=True)
                    continue
                
                # Produktseite direkt besuchen
                try:
                    response = requests.get(product_url, headers=headers, timeout=10)
                    if response.status_code != 200:
                        print(f"⚠️ Fehler beim Abrufen von {product_url}: Status {response.status_code}", flush=True)
                        
                        # Wenn Seite nicht mehr erreichbar, aus Cache entfernen
                        if response.status_code in (404, 410):
                            print(f"🗑️ Entferne nicht mehr verfügbaren Produktpfad: {product_url}", flush=True)
                            domain_paths.pop(product_id, None)
                        continue
                    
                    # Fingerprint des aktuellen Inhalts erstellen
                    current_fingerprint = create_fingerprint(response.text)
                    stored_fingerprint = product_info.get("fingerprint", "")
                    
                    # HTML parsen
                    soup = BeautifulSoup(response.text, "html.parser")
                    
                    # Titel extrahieren
                    title_elem = soup.find('title')
                    link_text = title_elem.text.strip() if title_elem else ""
                    
                    # VERBESSERT: Strikte Prüfung auf exakte Übereinstimmung mit dem Suchbegriff
                    tokens = keywords_map.get(matched_term, [])
                    
                    # Extrahiere Produkttyp aus Suchbegriff und Titel
                    search_term_type = extract_product_type_from_text(matched_term)
                    title_product_type = extract_product_type(link_text)
                    
                    # Wenn nach einem Display gesucht wird, aber der Titel etwas anderes enthält, überspringen
                    if search_term_type == "display" and title_product_type and title_product_type != "display":
                        print(f"⚠️ Produkttyp-Diskrepanz: Suche nach 'display', aber Produkt ist '{title_product_type}': {link_text}", flush=True)
                        continue
                    
                    # Strengere Keyword-Prüfung mit Berücksichtigung des Produkttyps
                    if not is_keyword_in_text(tokens, link_text):
                        print(f"⚠️ Produkt entspricht nicht mehr dem Suchbegriff '{matched_term}': {link_text}", flush=True)
                        continue
                    
                    # Aktualisiere die letzte Prüfzeit
                    domain_paths[product_id]["last_checked"] = time.time()
                    
                    # Wenn der Fingerprint sich geändert hat oder wir keinen haben, führe vollständige Verfügbarkeitsprüfung durch
                    if current_fingerprint != stored_fingerprint or not stored_fingerprint:
                        print(f"🔄 Änderung erkannt oder erste Prüfung: {product_url}", flush=True)
                        domain_paths[product_id]["fingerprint"] = current_fingerprint
                        
                        # Prüfe Verfügbarkeit und sende Benachrichtigung
                        soup, is_available, price, status_text = check_product_availability(product_url, headers)
                        
                        # Aktualisiere Cache-Eintrag
                        domain_paths[product_id]["is_available"] = is_available
                        domain_paths[product_id]["price"] = price
                        
                        # Bei "nur verfügbare" Option, nicht-verfügbare Produkte überspringen
                        if only_available and not is_available:
                            continue
                        
                        # Aktualisiere Produkt-Status und prüfe, ob Benachrichtigung gesendet werden soll
                        should_notify, is_back_in_stock = update_product_status(
                            product_id, is_available, seen, out_of_stock
                        )
                        
                        if should_notify:
                            # Nachricht senden
                            if not status_text:
                                status_text = get_status_text(is_available, is_back_in_stock)
                            
                            # Escape special characters for Markdown
                            safe_link_text = escape_markdown(link_text)
                            safe_price = escape_markdown(price)
                            safe_status_text = escape_markdown(status_text)
                            safe_matched_term = escape_markdown(matched_term)
                            
                            # Füge Produkttyp-Information hinzu
                            product_type_info = f" [{title_product_type.upper()}]" if title_product_type != "unknown" else ""
                            
                            # URLs müssen nicht escaped werden, da sie in Klammern stehen
                            msg = (
                                f"🎯 *{safe_link_text}*{product_type_info}\n"
                                f"💶 {safe_price}\n"
                                f"📊 {safe_status_text}\n"
                                f"🔎 Treffer für: '{safe_matched_term}'\n"
                                f"🔗 [Zum Produkt]({product_url})"
                            )
                            
                            if send_telegram_message(msg):
                                if is_available:
                                    seen.add(f"{product_id}_status_available")
                                else:
                                    seen.add(f"{product_id}_status_unavailable")
                                
                                new_matches.append(product_id)
                                print(f"✅ Cache-Treffer gemeldet: {link_text} - {status_text}", flush=True)
                    else:
                        print(f"✓ Keine Änderung für {product_url}", flush=True)
                        
                except Exception as e:
                    print(f"⚠️ Fehler bei der Verarbeitung von {product_url}: {e}", flush=True)
            
            # Cache mit den aktualisierten Zeitstempeln speichern
            product_cache[site_id] = domain_paths
            save_product_cache(product_cache)
        
        # Wenn neue Keywords oder ein vollständiger Scan erforderlich ist
        if full_scan_needed or not domain_paths:
            print(f"🔍 Durchführung eines vollständigen Scans für {url}", flush=True)
            
            # Hier kommt der Code aus der ursprünglichen Funktion, aber optimiert
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code != 200:
                print(f"⚠️ Fehler beim Abrufen von {url}: Status {response.status_code}", flush=True)
                return new_matches
            
            # HTML parsen
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Titel der Seite extrahieren
            page_title = soup.title.text.strip() if soup.title else url
            
            # Extrahiere den ersten Suchbegriff für die Produkttypbestimmung
            first_search_term = next(iter(keywords_map.keys())) if keywords_map else None
            search_product_type = extract_product_type_from_text(first_search_term) if first_search_term else None
            
            # Gefilterte Links abrufen
            filtered_links = filter_links(soup, url, search_product_type)
            
            print(f"🔍 {len(filtered_links)} potenzielle Produktlinks nach Filterung gefunden auf {url}", flush=True)
            
            # Rest der Funktion bleibt ähnlich, aber wir verwenden die gefilterten Links
            for href, link_text in filtered_links:
                # Eindeutige ID für diesen Fund erstellen
                product_id = create_product_id(link_text, site_id=site_id)
                
                # Prüfe jeden Suchbegriff gegen den Linktext
                matched_term = None
                for search_term, tokens in keywords_map.items():
                    # Extrahiere Produkttyp aus Suchbegriff und dem Link-Text
                    search_term_type = extract_product_type_from_text(search_term)
                    link_product_type = extract_product_type(link_text)
                    
                    # VERBESSERT: Wenn nach einem Display gesucht wird, aber der Link keins ist, überspringen
                    if search_term_type == "display" and link_product_type != "display":
                        print(f"❌ Produkttyp-Konflikt: Suche nach Display, aber Link ist '{link_product_type}': {link_text}", flush=True)
                        continue
                    
                    # VERBESSERT: Strenge Prüfung mit der neuen Funktion
                    match_result = is_keyword_in_text(tokens, link_text)
                    
                    if match_result:
                        matched_term = search_term
                        print(f"🔍 Treffer für '{search_term}' im Link: {link_text}", flush=True)
                        
                        # WICHTIG: Zusätzliche Prüfung für den genauen Produkttyp
                        print(f"🔍 Produkttyp-Prüfung für '{site_id}': Link-Text='{link_product_type}', Suchbegriff='{search_term_type}'", flush=True)
                        
                        # Wenn der Suchbegriff einen spezifischen Produkttyp enthält, muss exakt dieser Typ übereinstimmen
                        if search_term_type != "unknown":
                            # Nur exakte Produkttyp-Übereinstimmungen zulassen
                            if link_product_type != search_term_type:
                                print(f"❌ Produkttyp-Diskrepanz bei {site_id}: Suchtyp '{search_term_type}' stimmt nicht mit Produkttyp '{link_product_type}' überein", flush=True)
                                matched_term = None
                                continue
                        
                        # VERBESSERT: Wenn nach "display" gesucht wird, alle anderen Produkttypen ausschließen
                        if "display" in search_term.lower() and link_product_type != "display":
                            print(f"❌ Abgelehnt: Nach Display gesucht, aber Produkt ist '{link_product_type}'", flush=True)
                            matched_term = None
                            continue
                        
                        break
                
                if not matched_term:
                    continue
                
                # Prüfe Verfügbarkeit
                is_available = True  # Standard
                price = "Preis nicht verfügbar"
                status_text = ""
                detail_soup = None
                
                if check_availability:
                    try:
                        detail_soup, is_available, price, status_text = check_product_availability(href, headers)
                        
                        # VERBESSERT: Nochmals prüfen, ob der Produktdetailseiten-Titel dem Suchbegriff entspricht
                        if detail_soup:
                            detail_title = detail_soup.find('title')
                            if detail_title:
                                detail_title_text = detail_title.text.strip()
                                tokens = keywords_map.get(matched_term, [])
                                
                                # Extrahiere Produkttyp aus dem Detailtitel
                                detail_product_type = extract_product_type(detail_title_text)
                                search_term_type = extract_product_type_from_text(matched_term)
                                
                                # Wenn nach Display gesucht wird, muss der Detailtitel auch Display sein
                                if search_term_type == "display" and detail_product_type != "display":
                                    print(f"❌ Detailseite ist kein Display, obwohl nach Display gesucht wurde: {detail_title_text}", flush=True)
                                    continue
                                
                                # Generelle Keyword-Übereinstimmungsprüfung
                                if not is_keyword_in_text(tokens, detail_title_text):
                                    print(f"❌ Detailseite passt nicht zum Suchbegriff '{matched_term}': {detail_title_text}", flush=True)
                                    continue
                        
                        # Für den Cache: Speichere die URL und den erkannten Term
                        if site_id not in product_cache:
                            product_cache[site_id] = {}
                        
                        if product_id not in product_cache[site_id]:
                            product_cache[site_id][product_id] = {}
                        
                        # Speichere Produktinfos im Cache
                        fingerprint = ""
                        if detail_soup:
                            html_content = str(detail_soup)
                            fingerprint = create_fingerprint(html_content)
                            
                        product_cache[site_id][product_id].update({
                            "url": href,
                            "term": matched_term,
                            "is_available": is_available,
                            "price": price,
                            "last_checked": time.time(),
                            "fingerprint": fingerprint,
                            "product_type": extract_product_type(link_text)  # Speichere auch den Produkttyp
                        })
                        
                    except Exception as e:
                        print(f"⚠️ Fehler beim Prüfen der Verfügbarkeit für {href}: {e}", flush=True)
                
                # Bei "nur verfügbare" Option, nicht-verfügbare Produkte überspringen
                if only_available and not is_available:
                    continue
                
                # Benachrichtigungslogik
                should_notify, is_back_in_stock = update_product_status(
                    product_id, is_available, seen, out_of_stock
                )
                
                if should_notify:
                    # Status-Text erstellen oder den bereits generierten verwenden
                    if not status_text:
                        status_text = get_status_text(is_available, is_back_in_stock)
                    
                    # Escape special characters for Markdown
                    safe_link_text = escape_markdown(link_text)
                    safe_price = escape_markdown(price)
                    safe_status_text = escape_markdown(status_text)
                    safe_matched_term = escape_markdown(matched_term)
                    
                    # Füge Produkttyp-Information hinzu
                    product_type = extract_product_type(link_text)
                    product_type_info = f" [{product_type.upper()}]" if product_type != "unknown" else ""
                    
                    # Nachricht zusammenstellen
                    msg = (
                        f"🎯 *{safe_link_text}*{product_type_info}\n"
                        f"💶 {safe_price}\n"
                        f"📊 {safe_status_text}\n"
                        f"🔎 Treffer für: '{safe_matched_term}'\n"
                        f"🔗 [Zum Produkt]({href})"
                    )
                    
                    # Telegram-Nachricht senden
                    if send_telegram_message(msg):
                        # Je nach Verfügbarkeit unterschiedliche IDs speichern
                        if is_available:
                            seen.add(f"{product_id}_status_available")
                        else:
                            seen.add(f"{product_id}_status_unavailable")
                        
                        new_matches.append(product_id)
                        print(f"✅ Neuer Treffer gemeldet: {link_text} - {status_text}", flush=True)
            
            # Aktualisiere die Liste der bekannten Keywords im Cache
            product_cache[cache_key] = current_keywords
            
            # Speichere den aktualisierten Cache
            save_product_cache(product_cache)
    
    except Exception as e:
        print(f"❌ Fehler beim generischen Scraping von {url}: {e}", flush=True)
    
    return new_matches

def check_product_availability(url, headers):
    """
    Besucht die Produktdetailseite und prüft die Verfügbarkeit
    
    :param url: Produkt-URL
    :param headers: HTTP-Headers für die Anfrage
    :return: Tuple (BeautifulSoup-Objekt, Verfügbarkeitsstatus, Preis, Status-Text)
    """
    print(f"🔍 Prüfe Produktdetails für {url}", flush=True)
    
    response = requests.get(url, headers=headers, timeout=15)
    if response.status_code != 200:
        return None, False, "Preis nicht verfügbar", "❌ Ausverkauft (Fehler beim Laden)"
    
    soup = BeautifulSoup(response.text, "html.parser")
    
    # Verwende das Availability-Modul für webseitenspezifische Erkennung
    is_available, price, status_text = detect_availability(soup, url)
    
    print(f"  - Verfügbarkeit für {url}: {status_text}", flush=True)
    print(f"  - Preis: {price}", flush=True)
    
    return soup, is_available, price, status_text

def extract_product_type(text):
    """
    Extrahiert den Produkttyp aus einem Text mit strengeren Regeln
    
    :param text: Text, aus dem der Produkttyp extrahiert werden soll
    :return: Produkttyp als String
    """
    text = text.lower()
    
    # Display erkennen - höchste Priorität und strenge Prüfung
    if re.search(r'\bdisplay\b|\b36er\b|\b36\s+booster\b|\bbooster\s+display\b', text):
        # Zusätzliche Prüfung: Wenn andere Produkttypen erwähnt werden, ist es möglicherweise kein Display
        if re.search(r'\bblister\b|\bpack\b|\bbuilder\b|\bbuild\s?[&]?\s?battle\b|\betb\b|\belite trainer box\b', text):
            # Prüfe, ob "display" tatsächlich prominenter ist als andere Erwähnungen
            if text.find('display') < text.find('blister') and text.find('display') < text.find('pack'):
                return "display"
            print(f"  [DEBUG] Produkt enthält 'display', aber auch andere Produkttypen: '{text}'", flush=True)
            return "mixed_or_unclear"
        return "display"
    
    # Blister erkennen - klare Abgrenzung
    elif re.search(r'\bblister\b|\b3er\s+blister\b|\b3-pack\b|\bsleeve(d)?\s+booster\b|\bcheck\s?lane\b', text):
        return "blister"
    
    # Elite Trainer Box eindeutig erkennen
    elif re.search(r'\belite trainer box\b|\betb\b|\btrainer box\b', text):
        return "etb"
    
    # Build & Battle Box eindeutig erkennen
    elif re.search(r'\bbuild\s?[&]?\s?battle\b|\bprerelease\b', text):
        return "build_battle"
    
    # Premium Collectionen oder Special Produkte
    elif re.search(r'\bpremium\b|\bcollector\b|\bcollection\b|\bspecial\b', text):
        return "premium"

    # Einzelne Booster erkennen - aber nur wenn "display" definitiv nicht erwähnt wird
    elif re.search(r'\bbooster\b|\bpack\b', text) and not re.search(r'display', text):
        return "single_booster"
    
    # Wenn nichts erkannt wurde
    return "unknown"

def create_product_id(product_title, site_id="generic"):
    """
    Erstellt eine eindeutige Produkt-ID basierend auf Titel und Website
    
    :param product_title: Produkttitel
    :param site_id: ID der Website (z.B. 'tcgviert', 'kofuku')
    :return: Eindeutige Produkt-ID
    """
    # Extrahiere strukturierte Informationen
    series_code, product_type, language = extract_product_info(product_title)
    
    # Erstelle eine strukturierte ID
    product_id = f"{site_id}_{series_code}_{product_type}_{language}"
    
    # Füge zusätzliche Details für spezielle Produkte hinzu
    if "premium" in product_title.lower():
        product_id += "_premium"
    if "elite" in product_title.lower():
        product_id += "_elite"
    if "top" in product_title.lower() and "trainer" in product_title.lower():
        product_id += "_top"
    
    return product_id

def extract_product_info(title):
    """
    Extrahiert wichtige Produktinformationen aus dem Titel für eine präzise ID-Erstellung
    
    :param title: Produkttitel
    :return: Tupel mit (series_code, product_type, language)
    """
    # Extrahiere Sprache (DE/EN/JP)
    if "(DE)" in title or "pro Person" in title or "deutsch" in title.lower():
        language = "DE"
    elif "(EN)" in title or "per person" in title or "english" in title.lower():
        language = "EN"
    elif "(JP)" in title or "japan" in title.lower():
        language = "JP"
    else:
        language = "UNK"
    
    # Extrahiere Produkttyp mit der verbesserten Funktion
    detected_type = extract_product_type(title)
    if detected_type != "unknown":
        product_type = detected_type
    else:
        # Fallback zur alten Methode
        if re.search(r'display|36er', title.lower()):
            product_type = "display"
        elif re.search(r'booster|pack|sleeve', title.lower()):
            product_type = "booster"
        elif re.search(r'trainer box|elite trainer|box|tin', title.lower()):
            product_type = "box"
        elif re.search(r'blister|check\s?lane', title.lower()):
            product_type = "blister"
        else:
            product_type = "unknown"
    
    # Extrahiere Serien-/Set-Code
    series_code = "unknown"
    # Suche nach Standard-Codes wie SV09, KP09, etc.
    code_match = re.search(r'(?:sv|kp|op)(?:\s|-)?\d+', title.lower())
    if code_match:
        series_code = code_match.group(0).replace(" ", "").replace("-", "")
    # Spezifische Serien-Namen
    elif "journey together" in title.lower():
        series_code = "sv09"
    elif "reisegefährten" in title.lower():
        series_code = "kp09"
    elif "royal blood" in title.lower():
        series_code = "op10"
    
    return (series_code, product_type, language)