README

# Pokémon TCG Web-Scraper

Ein Python-basierter Web-Scraper, der die Verfügbarkeit von Trading Card Game Produkten (insbesondere Pokémon) auf verschiedenen Websites überwacht und Telegram-Benachrichtigungen sendet, wenn Produkte gefunden werden, die mit vordefinierten Suchbegriffen übereinstimmen.

## Funktionsübersicht

- Überwacht tcgviert.com (spezialisierter Scraper) und andere Websites (generischer Scraper)
- Erkennt neue Produkte basierend auf Suchbegriffen und Synonymen
- Sendet Telegram-Benachrichtigungen bei Produktfunden
- Unterstützt intelligente Duplikaterkennung durch strukturierte Produkt-IDs
- Speichert bereits gemeldete Produkte, um Doppelbenachrichtigungen zu vermeiden
- Bietet konfigurierbare Abrufintervalle basierend auf Zeitperioden
- Robuste Fehlerbehandlung mit automatischen Neustarts

## Ordnerstruktur

```
Pokemon-Web-Scraper/
├── main.py                    # Hauptprogramm und Steuerlogik
├── render.yaml                # Konfiguration für Hosting auf Render.com
├── requirements.txt           # Benötigte Python-Pakete
├── scrapers/
│   ├── __init__.py            # Python-Paket-Initialisierung
│   ├── tcgviert.py            # Spezieller Scraper für tcgviert.com
│   └── generic.py             # Generischer Scraper für andere Websites
├── utils/
│   ├── __init__.py            # Python-Paket-Initialisierung
│   ├── filetools.py           # Funktionen zum Laden/Speichern von Dateien
│   ├── matcher.py             # Suchbegriff-Matching-Logik
│   ├── scheduler.py           # Zeitplanung für Scraping-Intervalle
│   └── telegram.py            # Telegram-Benachrichtigungsfunktionen
├── data/
│   ├── products.txt           # Suchbegriffe für Produkte
│   ├── seen.txt               # Liste bereits gefundener Produkte
│   └── urls.txt               # URLs für den generischen Scraper
└── config/
    ├── schedule.json          # Zeitplan für Scraping-Intervalle
    ├── synonyms.json          # Synonyme für Suchbegriffe
    └── telegram_config.json   # Telegram-Bot-Token und Chat-ID
```

## Hauptmodule und ihre Funktionen

### main.py
Enthält die Hauptsteuerlogik und bietet verschiedene Ausführungsmodi:
- **run_once()**: Führt einen einzelnen Scan-Durchlauf aus
- **run_loop()**: Startet den Scraper im Dauerbetrieb
- **test_telegram()**: Testet die Telegram-Benachrichtigung
- **test_matching()**: Testet die Suchbegriff-Matching-Logik

### scrapers/tcgviert.py
Spezialisierter Scraper für tcgviert.com mit folgenden Funktionen:
- **scrape_tcgviert()**: Hauptfunktion für tcgviert.com
- **discover_collection_urls()**: Findet automatisch gültige Collection-URLs
- **scrape_tcgviert_json()**: Scraper für die JSON-API von tcgviert.com
- **scrape_tcgviert_html()**: HTML-Scraper für tcgviert.com als Fallback
- **extract_product_info()**: Extrahiert strukturierte Produktinformationen aus dem Titel
- **create_product_id()**: Erstellt eine eindeutige, strukturierte Produkt-ID
- **generic_scrape_product()**: Generische Funktion zur Verarbeitung von Produkten für beliebige Websites

### scrapers/generic.py
Flexibler Scraper für beliebige Websites:
- **scrape_generic()**: Hauptfunktion für das Scrapen von URLs aus urls.txt

### utils/matcher.py
Enthält die Logik für das Matching von Suchbegriffen:
- **clean_text()**: Bereinigt Text für besseres Matching
- **is_keyword_in_text()**: Prüft, ob alle Suchbegriffe im Text vorkommen
- **prepare_keywords()**: Bereitet Suchbegriffe aus products.txt vor und fügt Synonyme hinzu

### utils/filetools.py
Funktionen zum Laden und Speichern von Dateien:
- **load_list()**: Lädt Textdateien als Listen
- **load_seen()**: Lädt bereits gesehene Produkte
- **save_seen()**: Speichert gesehene Produkte

### utils/telegram.py
Funktionen für Telegram-Benachrichtigungen:
- **load_telegram_config()**: Lädt die Telegram-Konfiguration
- **send_telegram_message()**: Sendet Benachrichtigungen über Telegram

### utils/scheduler.py
Funktionen für zeitbasierte Steuerung:
- **get_current_interval()**: Bestimmt das Abrufintervall basierend auf dem aktuellen Datum

## Konfigurationsdateien

### data/products.txt
Enthält Suchbegriffe für Produkte, z.B.:
```
Reisegefährten
Journey Together
Piece Royal Blood
```

### config/synonyms.json
Definiert alternative Begriffe für die Suche:
```json
{ 
  "sv09": ["reisegefährten", "reisegefährten 36er display"] 
}
```

### config/schedule.json
Definiert verschiedene Abrufintervalle für bestimmte Zeiträume:
```json
[
  { "start": "07.04.2025", "end": "31.12.2025", "interval": 300 }
]
```

### config/telegram_config.json
Enthält Bot-Token und Chat-ID für Telegram-Benachrichtigungen:
```json
{
  "bot_token": "YOUR_BOT_TOKEN",
  "chat_id": "YOUR_CHAT_ID"
}
```

### data/seen.txt
Speichert bereits gemeldete Produkt-IDs, um Duplikate zu vermeiden.

### data/urls.txt
Enthält URLs für den generischen Scraper, z.B.:
```
https://tcgviert.com/collections/vorbestellungen
```

## Zuletzt verbesserte Funktionen

### Intelligente Produktunterscheidung
Die neueste Verbesserung ist die intelligente Produktunterscheidung in tcgviert.py, die folgende Funktionen bietet:

1. **Strukturierte Produkt-IDs**: Erstellt einzigartige IDs basierend auf:
   - Serien-Code (z.B. SV09, KP09)
   - Produkttyp (Display, Booster, Box, Blister)
   - Sprache (DE, EN, JP)
   - Zusätzliche Attribute (premium, elite, top)

2. **Regex-basierte Informationsextraktion**:
   - Erkennt verschiedene Schreibweisen und Formate in Produkttiteln
   - Unterstützt Variationen wie "36er Display", "Display", "sv09", "sv 09", etc.
   - Identifiziert Sprachen basierend auf Text und Kontext

3. **Generische Produktverarbeitung**:
   - Die Funktion `generic_scrape_product()` ermöglicht eine konsistente Verarbeitung von Produkten über verschiedene Websites hinweg
   - Kann für neue Websites wiederverwendet werden

### Beispiel für Produkt-IDs
Diese strukturierten IDs ermöglichen die präzise Unterscheidung ähnlicher Produkte:

- `tcgviert_kp09_display_DE` - "Pokémon TCG: Reisegefährten (KP09) - 36er Display (DE)"
- `tcgviert_kp09_box_DE_top` - "Pokémon TCG: Reisegefährten (KP09) - Top Trainer Box (DE)"
- `tcgviert_sv09_display_EN` - "Pokémon TCG: Journey Together (SV09) - 36er Display (EN)"
- `tcgviert_sv09_box_EN_elite` - "Pokémon TCG: Journey Together (SV09) - Elite Trainer Box (EN)"

## Startoptionen

Der Scraper kann mit verschiedenen Modi gestartet werden:

- `python main.py --mode once`: Einzelner Durchlauf
- `python main.py --mode loop`: Kontinuierlicher Betrieb (Standard)
- `python main.py --mode test`: Testet Telegram-Benachrichtigungen
- `python main.py --mode match_test`: Testet die Suchlogik

## Deployment

Der Scraper kann sowohl lokal als auch auf Render.com als Worker-Service betrieben werden. Die `render.yaml` enthält alle nötigen Konfigurationen für das Hosting auf Render.com.

## Erweiterung für neue Websites

Um den Scraper für eine neue Website zu erweitern:

1. Füge die Website-URL zu `data/urls.txt` hinzu
2. Für einfache Websites verwendet der Scraper automatisch den generischen Scraper
3. Für komplexere Websites kann ein spezialisierter Scraper nach dem Vorbild von `tcgviert.py` erstellt werden, der die Funktion `generic_scrape_product()` verwendet

## Abhängigkeiten

- Python 3.6+
- requests
- beautifulsoup4

Die vollständige Liste der Abhängigkeiten befindet sich in `requirements.txt`.