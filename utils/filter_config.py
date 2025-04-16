"""
Konfigurationsdatei für website-spezifische Filterregeln.
Diese Datei enthält Filterregeln für verschiedene Webshops, um unnötige Kategorien 
und Inhalte zu filtern und die Scraping-Effizienz zu verbessern.
"""

# Dictionary mit website-spezifischen URL-Filtern
URL_FILTERS = {
    # Allgemeine Filter für alle Webseiten
    "global": [
        # Trading Card Games und Konkurrenzprodukte
        "one-piece", "onepiece", "one piece",
        "disney-lorcana", "disney lorcana", "lorcana",
        "final-fantasy", "final fantasy",
        "yu-gi-oh", "yugioh", "yu gi oh",
        "union-arena", "union arena",
        "star-wars", "star wars",
        "mtg", "magic the gathering", "magic-the-gathering",
        "flesh-and-blood", "flesh and blood",
        "digimon", "metazoo", "grand archive", "sorcery",
        
        # Shop-Funktionalitäten
        "/login", "/account", "/cart", "/checkout", "/wishlist", "/warenkorb", 
        "/kontakt", "/contact", "/agb", "/impressum", "/datenschutz", 
        "/widerruf", "/hilfe", "/help", "/faq", "/versand", "/shipping",
        "/my-account", "/merkliste", "/newsletter", "/registrieren", 
        "passwort", "anmelden", "registrieren", "warenkorb", "merkliste",
        
        # Social Media und externe Links
        "youtube.com", "instagram.com", "facebook.com", "twitter.com",
        "twitch.tv", "discord", "whatsapp", "discord.gg",
        
        # Merchandise und Sammlerstücke
        "/figuren", "/plüsch", "/plush", "/funko-pop", "/funko", 
        "/merchandise", "/sammelkoffer", "schlüsselanhänger", "tassen",
        "/capsule", "fan-artikel", "binder", "playmat", "sleeves",
        
        # Andere Medien
        "/manga", "/comic", "/videospiele", "nintendo-switch",
        
        # Leere Links oder JavaScript-Links
        "javascript:", "#", "tel:", "mailto:",
    ],
    
    # tcgviert.com spezifische Filter basierend auf Log-Analyse
    "tcgviert.com": [
        # Gefunden in Logs
        "plusch-figuren", "zubehor-fur-deine-schatze", "structure-decks",
        "japanische-sleeves", "jobs",
        
        # Zusätzliche spezifische Filter
        "battle-deck", "build-battle", "sammelkoffer", "tin", "spielmatte", "toploader",
    ],
    
    # card-corner.de spezifische Filter basierend auf Log-Analyse
    "card-corner.de": [
        # Gefunden in Logs
        "einzelkarten", "seltenes", "kartenlisten", "erweiterungen", 
        "neu-im-shop", "blog", "promos", "decks", "jtl-shop",
        "wunschzettel", "artikelnummer", "erscheinungsdatum", "gtin",
        "bestseller", "bewertungen", "neueste", 
    ],
    
    # comicplanet.de spezifische Filter basierend auf Log-Analyse
    "comicplanet.de": [
        # Gefunden in Logs
        "details", "kontaktformular", "defektes-produkt", "ruckgabe",
        "aktuelles", "handler", "shopware", "codeenterprise",
        "persönliches-profil", "adressen", "zahlungsarten", "bestellungen",
        "gutscheine", "store-events",
    ],
    
    # gameware.at spezifische Filter basierend auf Log-Analyse
    "gameware.at": [
        # Gefunden in Logs
        "abenteuerspiele", "actionspiele", "beat-em-ups",
        "rennspiele", "rollenspiele", "shooterspiele", "sportspiele",
        "zombies", "endzeit", "blood", "gore", "coop", "vr", "4x",
        "ps5", "ps4", "xbox", "switch", "controller", "headset",
        "tastatur", "maus", "konsole", "consoles", "joystick",
        "englische", "mediabooks", "steelbooks",
        "statuen", "geldbörsen", "fußmatten", "pyramido", "uncut",
        "pegi", "psn-karten", "xbox-live", "warenkorb", "merkliste",
        "jtl-shop", "collectors", "premium-edition", "mediabooks",
        "/gutscheine", "/boni", "/bonus", "collector", "deliverance",
        "yasha", "terminator", "ninja-turtles", "indiana-jones",
        "donkey-kong", "clair-obscur", "mario-kart", "lunar",
        "dead-island", "skull-and-bones", "doom", "saints-row",
        "horizon", "at-pegi", "directx", "gore", 
    ],
    
    # kofuku.de spezifische Filter basierend auf Log-Analyse
    "kofuku.de": [
        # Gefunden in Logs
        "ultra-pro", "binder", "pocket", "gallery",
        "schlüsselanhänger", "tassen", "capsule-toys",
        "altraverse", "mangacult", "egmont", "tokyopop", "crunchyroll",
        "carlsen", "/alte-shop", "/old-shop", "/startseite", "/löschen",
    ],
    
    # mighty-cards.de spezifische Filter basierend auf Log-Analyse
    "mighty-cards.de": [
        # Gefunden in Logs
        "figuren-plüsch", "funko-pop", "dragon-ball", "naruto",
        "boruto", "sleeves-kartenhüllen", "toploader", "playmat",
        "deck-boxen", "van-gogh", "altered",
    ],
    
    # games-island.eu spezifische Filter (basierend auf allgemeinen Filtern)
    "games-island.eu": [
        "brettspiele", "gesellschaftsspiele", "trading-cards",
        "tabletop", "warhammer", "puzzles", "spiel-des-jahres",
    ],
    
    # sapphire-cards.de spezifische Filter (basierend auf allgemeinen Filtern)
    "sapphire-cards.de": [
        "einzelkarten", "singles", "sleeves",
        "deckboxen", "binder", "dice", "würfel", "playmats",
    ]
}

# Dictionary mit website-spezifischen Text-Filtern
TEXT_FILTERS = {
    # Allgemeine Text-Filter für alle Websites
    "global": [
        # Trading Card Games und Konkurrenzprodukte
        "one piece", "onepiece", 
        "disney lorcana", "lorcana",
        "final fantasy",
        "yu gi oh", "yugioh", "yu-gi-oh",
        "union arena",
        "star wars",
        "magic the gathering", "mtg",
        "flesh and blood",
        "digimon", "metazoo", "grand archive", "sorcery",
        
        # Shop-Funktionalitäten
        "warenkorb", "merkliste", "wunschzettel", "login", "anmelden", 
        "registrieren", "passwort vergessen", "kontakt", "impressum", 
        "datenschutz", "agb", "widerrufsrecht", "hilfe", "versand", 
        "checkout", "konto", "account",
        "kundendaten", "bestellungen", "gutschein", "gutscheine",
        
        # Merchandise und Sammlerstücke
        "figuren", "plüsch", "funko pop", "merchandise", 
        "sammelkoffer", "schlüsselanhänger", "tassen", 
        "binder", "playmat", "sleeves", "kartenhüllen", 
        
        # Andere Medien
        "manga", "comic", "videospiele", "nintendo switch",
    ],
    
    # tcgviert.com spezifische Text-Filter
    "tcgviert.com": [
        # Produkttypen, die nicht Display sind
        "structure deck", "battle deck", "build & battle", "tin", 
        "japanische sleeves", "jobs", "zubehor",
    ],
    
    # card-corner.de spezifische Text-Filter
    "card-corner.de": [
        "sleeved booster", "einzelkarten", "seltenes", "promos", "decks",
        "kartenlisten", "andere tcg", "topps", "dragon ball", "yu gi oh",
        "artikelnummer", "erscheinungsdatum", "gtin",
    ],
    
    # comicplanet.de spezifische Text-Filter
    "comicplanet.de": [
        "passwort",
        "einzelkarten", "manga", "comic", "fan artikel", "merchandise",
        "defektes produkt", "widerrufsrecht", "rückgabe",
    ],
    
    # gameware.at spezifische Text-Filter
    "gameware.at": [
        "abenteuerspiele", "actionspiele", "beat em ups",
        "rennspiele", "rollenspiele", "shooterspiele", "sportspiele",
        "zombies", "endzeit", "blood", "gore", "coop", "vr", "headset",
        "konsole", "controller",
        "mediabooks", "steelbooks", "in den warenkorb", "auf die merkliste",
        "donkey kong", "mario kart", "horizon", "indiana jones", "doom",
    ],
    
    # kofuku.de spezifische Text-Filter
    "kofuku.de": [
        "build & battle", "binder", "pocket",
        "plüsch", "manga", "videospiele", "gallery series",
        "ultra pro", "discord", "instagram", "youtube", "twitch",
    ],
    
    # mighty-cards.de spezifische Text-Filter
    "mighty-cards.de": [
        "figuren", "funko pop", "dragon ball", "naruto", "boruto",
        "sleeves", "kartenhüllen", "toploader", "playmat", "spielmatten",
        "deck boxen", "binder", "van gogh", "widerrufsbelehrung",
    ],
    
    # games-island.eu spezifische Text-Filter
    "games-island.eu": [
        "brettspiele", "gesellschaftsspiele",
        "tabletop", "warhammer", "puzzles",
        "auf lager", "benachrichtigung anfordern",
    ],
    
    # sapphire-cards.de spezifische Text-Filter
    "sapphire-cards.de": [
        "einzelkarten", "singles", "sleeves",
        "deckboxen", "binder", "dice", "würfel", "playmats",
    ]
}

# Spezielle Produkttypen, die nach Webseite gefiltert werden sollten
PRODUCT_TYPE_EXCLUSIONS = {
    # Diese Produkttypen werden ausgeschlossen, wenn nach einem Display gesucht wird
    "global": ["blister", "single_booster", "etb", "build_battle", "premium", "tin", "unknown"],
}

# Kategoriefilter für die Hauptnavigation (für effizienteres Scraping)
# Gibt an, welche Kategorien im Menü gescannt werden sollen (Whitelist-Ansatz)
CATEGORY_WHITELIST = {
    "global": [
        "pokemon", "pokémon", "display", "booster", "karmesin", "purpur", "scarlet", "violet",
        "reisegefährten", "journey together", "sv09", "kp09", "vorbestellung", "preorder",
    ],
    
    "tcgviert.com": [
        "pokemon", "vorbestellungen", "displays", "boosterboxen",
    ],
    
    "card-corner.de": [
        "pokemon", "displays", "display", "booster", "vorbestellungen",
    ],
    
    "comicplanet.de": [
        "pokemon", "sammelkartenspiel", "display", "booster box",
    ],
    
    "gameware.at": [
        "pokemon", "kartenspiele", "displays", "booster",
    ],
    
    "kofuku.de": [
        "pokemon", "display", "booster", "tcg",
    ],
    
    "mighty-cards.de": [
        "pokemon", "display", "booster", "displays",
    ],
    
    "games-island.eu": [
        "pokemon", "display", "booster", "booster-displays",
    ],
    
    "sapphire-cards.de": [
        "pokemon", "displays", "booster boxes", "vorbestellungen",
    ]
}