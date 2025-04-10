README

# Pokémon TCG Web-Scraper: Projektübersicht

## Projektbeschreibung

Dieses Projekt ist ein spezialisierter Web-Scraper, der entwickelt wurde, um Pokémon Trading Card Game (TCG) Produkte auf verschiedenen Online-Shops zu überwachen. Der Scraper durchsucht regelmäßig konfigurierte Webseiten nach bestimmten Produkten, erkennt deren Verfügbarkeitsstatus und sendet Benachrichtigungen über Telegram, wenn neue Produkte gefunden werden oder sich deren Verfügbarkeitsstatus ändert.

## Hauptfunktionen

1. **Multiseitensuche**: Überwacht verschiedene Online-Shops mit einer Mischung aus spezialisierten und generischen Scrapern
2. **Intelligente Verfügbarkeitserkennung**: Webseitenspezifische Erkennung des Produktstatus (verfügbar/ausverkauft)
3. **Suchbegriff-Matching**: Flexible Suche nach konfigurierbaren Keywords und Synonymen
4. **Statusverfolgung**: Speichert den Verfügbarkeitsstatus von Produkten und benachrichtigt bei Änderungen
5. **Telegram-Benachrichtigungen**: Sendet formatierte Nachrichten mit Produktdetails und Links
6. **Zeitplanbasierte Ausführung**: Konfigurierbare Abrufintervalle für verschiedene Zeiträume
7. **Wiederbenachrichtigung bei Wiederverfügbarkeit**: Spezielle Benachrichtigungen, wenn ausverkaufte Produkte wieder verfügbar werden

## Ordnerstruktur

Pokemon-Web-Scraper/
├── main.py                    # Hauptprogramm und Steuerlogik
├── render.yaml                # Konfiguration für Hosting auf Render.com
├── requirements.txt           # Benötigte Python-Pakete
├── scrapers/
│   ├── init.py            # Python-Paket-Initialisierung
│   ├── tcgviert.py            # Spezieller Scraper für tcgviert.com
│   └── generic.py             # Generischer Scraper für andere Websites
├── utils/
│   ├── init.py            # Python-Paket-Initialisierung
│   ├── availability.py        # Webseitenspezifische Verfügbarkeitserkennung (NEUSTE FUNKTION)
│   ├── filetools.py           # Funktionen zum Laden/Speichern von Dateien
│   ├── matcher.py             # Suchbegriff-Matching-Logik
│   ├── scheduler.py           # Zeitplanung für Scraping-Intervalle
│   ├── stock.py               # Funktionen zur Verwaltung des Produktstatus
│   └── telegram.py            # Telegram-Benachrichtigungsfunktionen
├── data/
│   ├── products.txt           # Suchbegriffe für Produkte
│   ├── seen.txt               # Liste bereits gefundener Produkte
│   ├── out_of_stock.txt       # Liste ausverkaufter Produkte zur Überwachung
│   └── urls.txt               # URLs für den generischen Scraper
└── config/
├── schedule.json          # Zeitplan für Scraping-Intervalle
├── synonyms.json          # Synonyme für Suchbegriffe
└── telegram_config.json   # Telegram-Bot-Token und Chat-ID

## Detaillierte Funktionsweise

### 1. Hauptsteuerung (main.py)

Die `main.py` bietet verschiedene Ausführungsmodi:
- **Einmaliger Durchlauf** (`--mode once`): Führt einen einzelnen Scan durch
- **Dauerbetrieb** (`--mode loop`): Führt kontinuierlich Scans durch
- **Testmodi**: Zum Testen einzelner Komponenten (Telegram, Matching, Verfügbarkeit)
- **Filter-Optionen**: `--only-available` zeigt nur verfügbare Produkte an

### 2. Scraper-Module

#### 2.1 Generic Scraper (scrapers/generic.py)

Der generische Scraper kann auf jeder Webseite nach Produkten suchen:
- Findet potenzielle Produktlinks auf der Seite
- Prüft, ob der Linktext mit den Suchbegriffen übereinstimmt
- Besucht bei Übereinstimmung die Produktdetailseite
- Analysiert den Verfügbarkeitsstatus mit dem Availability-Modul
- Sendet bei Bedarf eine Benachrichtigung

#### 2.2 TCGViert Scraper (scrapers/tcgviert.py)

Ein spezialisierter Scraper für tcgviert.com:
- Verwendet sowohl JSON-API als auch HTML-Scraping
- Entdeckt automatisch aktuelle Collection-URLs
- Extrahiert strukturierte Produktinformationen für präzise IDs
- Integriert die webseitenspezifische Verfügbarkeitserkennung

### 3. Utility-Module

#### 3.1 Verfügbarkeitserkennung (utils/availability.py)

**NEUESTE FUNKTION**: Webseitenspezifische Verfügbarkeitserkennung:
- Unterstützt 8 verschiedene Webshops mit individuellen Erkennungsmustern
- Erkennt verschiedene Verfügbarkeitsindikatoren (Buttons, Texte, Badges, Farben)
- Liefert detaillierte Statustexte für Benachrichtigungen
- Extrahiert Preise mit verschiedenen Methoden

Unterstützte Webshops:
- comicplanet.de
- kofuku.de
- tcgviert.com
- card-corner.de
- sapphire-cards.de
- mighty-cards.de
- games-island.eu
- gameware.at

#### 3.2 Bestandsverwaltung (utils/stock.py)

Verwaltet den Status von Produkten:
- Speichert ausverkaufte Produkte in einer separaten Liste
- Verfolgt Statusänderungen (verfügbar → ausverkauft → wieder verfügbar)
- Ermöglicht spezielles Tracking von ausverkauften Produkten
- Generiert Statustexte für Benachrichtigungen

#### 3.3 Suchbegriff-Matching (utils/matcher.py)

Intelligentes Matching von Suchbegriffen:
- Bereinigt Texte für bessere Vergleichbarkeit
- Unterstützt mehrere Keywords pro Suchbegriff (alle müssen übereinstimmen)
- Lädt und integriert Synonyme aus synonyms.json

#### 3.4 Dateioperationen (utils/filetools.py)

Handhabt das Laden und Speichern von Dateien:
- Lädt Konfigurationsdateien und Suchbegriffe
- Verwaltet die Listen gesehener und ausverkaufter Produkte

#### 3.5 Zeitplanung (utils/scheduler.py)

Bestimmt die Abrufintervalle:
- Lädt Zeitpläne aus schedule.json
- Passt die Abrufhäufigkeit basierend auf dem aktuellen Datum an

#### 3.6 Telegram-Integration (utils/telegram.py)

Sendet Benachrichtigungen über Telegram:
- Lädt Bot-Token und Chat-ID aus telegram_config.json
- Formatiert Nachrichten mit Produktinformationen
- Unterstützt Markdown für bessere Lesbarkeit und klickbare Links

## Zuletzt implementierte Funktion: Webseitenspezifische Verfügbarkeitserkennung

Die neueste Ergänzung zum Projekt ist das Modul `utils/availability.py`, das eine spezialisierte Verfügbarkeitserkennung für verschiedene Webshops implementiert. Diese Erweiterung verbessert signifikant die Zuverlässigkeit des Scrapers, indem sie die spezifischen Merkmale jeder Website bei der Bestimmung des Produktstatus berücksichtigt.

Der Entwickler sollte sich zunächst mit dieser Datei vertraut machen, da sie die Kernlogik für die Verfügbarkeitserkennung enthält. Alle webseitenspezifischen Erkennungsmuster basieren auf einer detaillierten Analyse der Webshop-Strukturen und sind in separaten Funktionen implementiert.

Die Integration dieses Moduls in den generischen Scraper (`generic.py`) und den TCGViert-Scraper (`tcgviert.py`) wurde bereits abgeschlossen. Die nächsten potenziellen Erweiterungen könnten umfassen:
- Caching-Mechanismus zur Reduzierung der HTTP-Anfragen
- Fehlertolerante Verfügbarkeitserkennung mit maschinellem Lernen
- Erweiterung um weitere Webshops mit spezialisierten Erkennungsmustern

## Konfigurationsdateien

### products.txt
Enthält Suchbegriffe für das Produkt-Matching:

Reisegefährten display
Journey Together Display

### synonyms.json
Definiert alternative Begriffe für die Suche:
```json
{ "sv09": ["reisegefährten", "reisegefährten 36er display"] }

schedule.json
Konfiguriert die Abrufintervalle für verschiedene Zeiträume:

[{ "start": "07.04.2025", "end": "31.12.2025", "interval": 600 }]

Besondere Funktionen und Verhaltensweisen

Intelligente Produkt-IDs: Der Scraper erstellt strukturierte IDs basierend auf Website, Serien-Code, Produkttyp und Sprache
Filter für verfügbare Produkte: Mit --only-available werden nur verfügbare Produkte angezeigt, aber ausverkaufte Produkte werden weiterhin im Hintergrund überwacht
"Wieder verfügbar"-Benachrichtigungen: Produkte, die als ausverkauft markiert wurden, lösen eine spezielle Benachrichtigung aus, wenn sie wieder verfügbar werden
Automatische URL-Entdeckung: Der TCGViert-Scraper findet automatisch relevante Collection-URLs
Fehlertolerantes Scraping: Beim Ausfall einer Methode werden alternative Ansätze verwendet (z.B. JSON vs. HTML)

Startanleitung

# Installation der Abhängigkeiten
pip install -r requirements.txt

# Einmalige Ausführung
python main.py --mode once

# Dauerbetrieb (Standard)
python main.py

# Nur verfügbare Produkte anzeigen
python main.py --only-available

# Tests ausführen
python main.py --mode test           # Testet Telegram-Benachrichtigungen
python main.py --mode match_test     # Testet Suchbegriff-Matching
python main.py --mode availability_test  # Testet Verfügbarkeitserkennung

# Anzeige überwachter ausverkaufter Produkte
python main.py --mode show_out_of_stock

Zusammenfassung
Der Pokémon TCG Web-Scraper ist ein leistungsfähiges Tool zur Überwachung von Produktverfügbarkeiten auf verschiedenen Webshops. Die kürzlich implementierte webseitenspezifische Verfügbarkeitserkennung verbessert die Genauigkeit und Zuverlässigkeit erheblich. Die modulare Struktur und die gute Dokumentation machen das Projekt leicht erweiterbar und wartbar.



