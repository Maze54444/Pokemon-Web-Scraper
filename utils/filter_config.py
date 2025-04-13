"""
Konfigurationsdatei für website-spezifische Filterregeln.
Diese Datei wird als 'utils/filter_config.py' erstellt.
"""

# Dictionary mit website-spezifischen URL-Filtern
URL_FILTERS = {
    # Allgemeine Filter für alle Webseiten
    "global": [
        # Shop-Funktionalitäten
        "/login", "/account", "/cart", "/checkout", "/wishlist", "/warenkorb", 
        "/kontakt", "/contact", "/agb", "/impressum", "/datenschutz", 
        "/widerruf", "/hilfe", "/help", "/faq", "/versand", "/shipping",
        "/my-account", "/merkliste", "/newsletter", "/registrieren", 
        
        # Social Media und externe Links
        "youtube.com", "instagram.com", "facebook.com", "twitter.com",
        "twitch.tv", "discord", "whatsapp",
        
        # Leere Links oder JavaScript-Links
        "javascript:", "#",
    ],
    
    # gameware.at spezifische Filter
    "gameware.at": [
        # Andere Kartenspiele
        "magic", "yugioh", "flesh", "lorcana", "metazoo", "digimon",
        "one piece", "star wars", "grand archive", "sorcery",
        
        # Gaming-Kategorien
        "abenteuerspiele", "actionspiele", "beat-em-ups", "kinderspiele",
        "rennspiele", "rollenspiele", "shooterspiele", "sportspiele",
        "zombies", "endzeit", "blood", "gore", "coop", "vr", "4x",
        
        # Konsolen und Hardware
        "ps5", "ps4", "xbox", "switch 2", "controller", "headset",
        "tastatur", "maus", "konsole",
        
        # Shop-Kategorien
        "sale", "aktionen", "bestseller", "neu eingetroffen", 
        "bald erhältlich", "neu im programm", "wieder lieferbar",
        
        # Merchandise
        "figuren", "statuen", "schlüsselanhänger", "geldbörsen", 
        "fußmatten", "mediabooks", "steelbooks", "collectors",
        
        # Brettspiele
        "dungeons", "dragons", "schwarze auge", "cthulhu", "shadowrun", 
        "familienspiele", "prämierte spiele", "englische spiele",
        
        # Unterhaltung und Spiele
        "mediabooks", "gutscheine", "pegi", "uncut", "bis 16 jahre", 
        "bis 12 jahre", "bis 7 jahre", "psn-karten", "xbox live"
    ],
    
    # tcgviert.com spezifische Filter
    "tcgviert.com": [
        # Andere Kartenspiele
        "one-piece", "onepiece", "op04", "op-04", "op05", "op-05",
        "lorcana", "yugioh", "yu-gi-oh", "dragon-ball", "unionarena",
        
        # Produkttypen, die nicht Display sind
        "einzelbooster", "sleeved-booster", "blister", "structure-deck", 
        "battle-deck", "build-battle",
        
        # Merchandise und Zubehör
        "plusch", "plush", "sleeve", "sammelkoffer", "zubehor",
        "japanische", "jobs"
    ],
    
    # comicplanet.de spezifische Filter
    "comicplanet.de": [
        # Produktkategorien
        "einzelkarten", "manga", "anime", "comic", "fan-artikel", 
        "merchandise", "store-events", 
        
        # Servicefunktionen  
        "defektes-produkt", "widerrufsrecht", "ruckgabe", "aktuelles", 
        "handler", "shopware", "codeenterprise"
    ],
    
    # kofuku.de spezifische Filter
    "kofuku.de": [
        # Produkttypen
        "blister", "booster-pack", "build-battle", "binder", "pocket",
        "sammelkoffer", "nur-abholung",
        
        # Andere TCGs
        "dragon-ball", "union-arena",
        
        # Merchandise und Sammlerstücke
        "plush", "figuren", "tassen", "capsule", "merch", "schlüsselanhänger",
        
        # Andere Medien
        "manga", "videospiele", "nintendo-switch"
    ],
    
    # card-corner.de spezifische Filter
    "card-corner.de": [
        # Produkttypen
        "einzelkarten", "sleeved-booster", "seltenes", "promos", "decks",
        
        # Shop-Funktionen
        "wunschzettel", "warenkorb", "passwort", "registrieren",
        
        # Service-Seiten
        "ueber-uns", "kontakt", "zahlungsmoglichkeiten", "widerrufsrecht",
        "jtl-shop",
        
        # Andere TCGs
        "andere-tcg", "topps", "dragon-ball", "yu-gi-oh", "union-arena",
        
        # Zusätzliches
        "kartenlisten", "erweiterungen", "neu-im-shop", "blog"
    ]
}

# Dictionary mit website-spezifischen Text-Filtern
TEXT_FILTERS = {
    # Allgemeine Text-Filter für alle Websites
    "global": [
        "warenkorb", "merkliste", "wunschzettel", "login", "anmelden", 
        "registrieren", "passwort vergessen", "kontakt", "impressum", 
        "datenschutz", "agb", "widerrufsrecht", "hilfe", "versand", 
        "suche", "search", "checkout", "konto", "account",
        "kundendaten", "bestellungen", "gutschein", "gutscheine"
    ],
    
    # gameware.at spezifische Text-Filter
    "gameware.at": [
        "magic", "yugioh", "flesh", "lorcana", "metazoo", "digimon",
        "one piece", "star wars", "grand archive", "sorcery", "headset",
        "konsole", "controller", "zombies", "endzeit", "aktionen"
    ],
    
    # tcgviert.com spezifische Text-Filter
    "tcgviert.com": [
        "einzelbooster", "blister", "sleeve", "build & battle", 
        "booster pack", "epitaff ex", "sammelkoffer", "battle deck"
    ],
    
    # comicplanet.de spezifische Text-Filter
    "comicplanet.de": [
        "blister", "booster blister", "zum artikel", "detail", "passwort",
        "einzelkarten", "manga", "comic", "fan artikel", "merchandise"
    ],
    
    # kofuku.de spezifische Text-Filter
    "kofuku.de": [
        "blister", "booster pack", "build & battle", "binder", "pocket",
        "nur abholung", "plüsch", "manga", "videospiele"
    ],
    
    # card-corner.de spezifische Text-Filter
    "card-corner.de": [
        "sleeved booster", "einzelkarten", "seltenes", "promos", "decks",
        "kartenlisten", "andere tcg", "topps", "dragon ball", "yu gi oh",
        "artikelnummer", "erscheinungsdatum", "gtin"
    ]
}

# Spezielle Produkttypen, die nach Webseite gefiltert werden sollten
PRODUCT_TYPE_EXCLUSIONS = {
    # Diese Produkttypen werden ausgeschlossen, wenn nach einem Display gesucht wird
    "global": ["blister", "single_booster", "etb", "build_battle", "premium", "tin", "unknown"],
    
    # Website-spezifische Ausschlüsse
    "gameware.at": [],  # Keine zusätzlichen Ausschlüsse
    "tcgviert.com": [],  # Keine zusätzlichen Ausschlüsse
    "comicplanet.de": [],  # Keine zusätzlichen Ausschlüsse
    "kofuku.de": [],  # Keine zusätzlichen Ausschlüsse
    "card-corner.de": []  # Keine zusätzlichen Ausschlüsse
}