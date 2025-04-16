# Pokémon TCG Scraper

## Übersicht
Der Pokémon TCG Scraper ist ein automatisiertes Tool zur Überwachung von Pokémon-Sammelkarten-Displays in Online-Shops. Er benachrichtigt über Telegram, wenn bestimmte Produkte verfügbar oder ausverkauft sind.

## Funktionen
- Überwacht mehrere Online-Shops gleichzeitig
- Sendet Benachrichtigungen über Telegram
- Erkennt spezifische Produkte anhand von Suchbegriffen und Synonymen
- Verfolgt ausverkaufte Produkte und informiert, wenn sie wieder verfügbar sind
- Konfigurierbare Scan-Intervalle mit Zeitplänen
- Spezialisierte Scraper für bestimmte Shops (TCGViert, Sapphire-Cards)
- Generischer Scraper für andere Shops

## Projektstruktur
```
pokemon-tcg-scraper/
├── config/                     # Konfigurationsdateien
│   ├── schedule.json           # Zeitplan für Scan-Intervalle
│   ├── synonyms.json           # Synonyme für Produktnamen
│   └── telegram_config.json    # Telegram-Bot-Konfiguration
├── data/                       # Datendateien
│   ├── out_of_stock.txt        # Liste ausverkaufter Produkte
│   ├── product_cache.json      # Cache für bereits geprüfte Produkte
│   ├── products.txt            # Liste der zu suchenden Produkte
│   ├── seen.txt                # Liste bereits gemeldeter Produkte
│   └── urls.txt                # Liste der zu scannenden URLs
├── utils/                      # Hilfsfunktionen
│   ├── availability.py         # Funktionen zur Verfügbarkeitsprüfung
│   ├── config_manager.py       # Konfigurationsverwaltung
│   ├── filetools.py            # Dateioperationen
│   ├── filter_config.py        # Konfiguration für URL- und Textfilter
│   ├── filters.py              # Filterfunktionen
│   ├── matcher.py              # Funktionen zum Erkennen von Produktnamen
│   ├── stock.py                # Verwaltung von Produktbestand
│   └── telegram.py             # Telegram-Integration
├── scrapers/                   # Scraper-Module
│   ├── generic.py              # Generischer Scraper
│   ├── sapphire_cards.py       # Spezialisierter Scraper für Sapphire-Cards
│   └── tcgviert.py             # Spezialisierter Scraper für TCGViert
├── main.py                     # Hauptprogramm
├── requirements.txt            # Python-Abhängigkeiten
└── render.yaml                 # Konfiguration für Render-Deployment
```

## Installation

### Voraussetzungen
- Python 3.8+
- pip (Python-Paketmanager)

### Setup
1. Repository klonen:
   ```
   git clone https://github.com/yourusername/pokemon-tcg-scraper.git
   cd pokemon-tcg-scraper
   ```

2. Abhängigkeiten installieren:
   ```
   pip install -r requirements.txt
   ```

3. Konfiguration einrichten:
   - Erstelle `config/telegram_config.json` mit folgendem Inhalt:
     ```json
     {
       "bot_token": "DEIN_TELEGRAM_BOT_TOKEN",
       "chat_id": "DEINE_CHAT_ID"
     }
     ```
   - Passe `config/schedule.json` an deine Bedürfnisse an
   - Füge deine gewünschten Produkte in `data/products.txt` ein
   - Füge zu überwachende Shop-URLs in `data/urls.txt` ein

## Konfiguration

### products.txt
Jede Zeile enthält einen Produktnamen, der gesucht werden soll:
```
Journey Together display
Reisegefährten display
```

### urls.txt
Jede Zeile enthält eine URL, die gescannt werden soll:
```
https://tcgviert.com/collections/vorbestellungen
https://www.comicplanet.de/search?search=reisegef%C3%A4hrten
https://kofuku.de/collections/pokemon-karten
```

### synonyms.json
Definiert Synonyme für Produktnamen, um verschiedene Schreibweisen zu erkennen:
```json
{
  "Reisegefährten display": [
    "Reisegefährten Booster Display",
    "Reisegefährten 36er Display",
    "Reisegefährten Display - 36 Booster"
  ],
  "Journey Together display": [
    "Journey Together Booster Display",
    "Journey Together 36 Booster",
    "Journey Together Display - 36 Booster"
  ]
}
```

### schedule.json
Definiert Zeitintervalle für die Scans basierend auf Datumsangaben:
```json
[
  {
    "start": "07.04.2025",
    "end": "31.12.2025",
    "interval": 600
  }
]
```

## Verwendung

### Ausführungsmodi
Der Scraper kann in verschiedenen Modi ausgeführt werden:

1. **Dauerbetrieb** (Standard):
   ```
   python main.py
   ```

2. **Einmaliger Durchlauf**:
   ```
   python main.py --mode once
   ```

3. **Nur verfügbare Produkte**:
   ```
   python main.py --only-available
   ```

4. **Liste gesehener Produkte zurücksetzen**:
   ```
   python main.py --reset
   ```

5. **Telegram-Test**:
   ```
   python main.py --mode test
   ```

6. **Matching-Test**:
   ```
   python main.py --mode match_test
   ```

7. **Verfügbarkeits-Test**:
   ```
   python main.py --mode availability_test
   ```

8. **Sapphire-Cards-Test**:
   ```
   python main.py --mode sapphire_test
   ```

9. **Ausverkaufte Produkte anzeigen**:
   ```
   python main.py --mode show_out_of_stock
   ```

### Log-Level einstellen
```
python main.py --log-level DEBUG|INFO|WARNING|ERROR|CRITICAL
```

## Deployment

Der Scraper kann auf verschiedenen Plattformen bereitgestellt werden:

### Render
Nutze die mitgelieferte `render.yaml`-Datei für eine einfache Bereitstellung auf Render.com.

### Lokaler Server
Für die Ausführung auf einem lokalen Server empfiehlt sich die Verwendung eines Systemdienstes oder Cron-Jobs.

## Fehlerbehebung

### Häufige Probleme

1. **Keine Telegram-Benachrichtigungen**:
   - Überprüfe `telegram_config.json`
   - Stelle sicher, dass dein Bot Zugriff auf den Chat hat
   - Teste mit `python main.py --mode test`

2. **Keine Produkte gefunden**:
   - Überprüfe die Schreibweise der Produkte in `products.txt`
   - Teste das Matching mit `python main.py --mode match_test`

3. **Fehlende Ordnerstruktur**:
   - Der Scraper erstellt fehlende Ordner beim ersten Start
   - Bei manueller Erstellung: stelle sicher, dass alle Ordner aus der Projektstruktur vorhanden sind

### Debug-Modus aktivieren
```
python main.py --log-level DEBUG
```

## Erweiterung und Anpassung

### Neuen Shop hinzufügen
1. Füge die Shop-URL zu `data/urls.txt` hinzu
2. Teste den generischen Scraper mit dieser URL
3. Bei Bedarf: Füge shopspezifische Filter in `filter_config.py` hinzu
4. Bei komplexen Seiten: Erstelle einen spezialisierten Scraper in `scrapers/`

### Neue Produkttypen hinzufügen
Erweitere die Produkttyp-Erkennungsmuster in `matcher.py`, um neue Produktkategorien zu unterstützen.

