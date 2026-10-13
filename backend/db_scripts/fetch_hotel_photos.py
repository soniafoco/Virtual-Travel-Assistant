"""Cerca su Wikimedia Commons una foto per ogni hotel del seed e salva i risultati in db_scripts/hotel_photos.json.

Serve internet e va lanciato una volta sola (da backend/):
    python -m db_scripts.fetch_hotel_photos

Gli hotel del seed sono inventati: le foto sono foto indicative di hotel della stessa citta' (stelle simili),
non degli hotel veri. Ogni foto ha una licenza libera: autore e licenza vengono salvati insieme all'indirizzo.
"""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from db_scripts.seed_data import HOTELS

FILE_FOTO = Path(__file__).parent / "hotel_photos.json"
URL_API = "https://commons.wikimedia.org/w/api.php"
INTESTAZIONI = {"User-Agent": "VirtualTravelAssistant/1.0 (student project)"}  # Commons blocca httpx: uso urllib
LARGHEZZA = 900  # larghezza dell'anteprima da mostrare nell'app

# Nome della citta' nei titoli delle foto su Commons (in inglese o nella lingua locale)
NOMI_CITTA = {
    "Madrid": ["Madrid"],
    "Barcellona": ["Barcelona"],
    "Lisbona": ["Lisbon", "Lisboa"],
    "Porto": ["Porto"],
    "Atene": ["Athens", "Athina"],
    "Santorini": ["Santorini", "Oia", "Fira", "Imerovigli", "Thira"],
    "Stoccolma": ["Stockholm"],
    "Oslo": ["Oslo"],
    "Marrakech": ["Marrakech", "Marrakesh"],
    "Berlino": ["Berlin"],
    "Vienna": ["Vienna", "Wien"],
    "Cracovia": ["Krakow", "Kraków", "Cracow"],
}

# Parole che indicano che la foto non mostra un hotel (insegne, mappe, interni di sale, ecc.)
PAROLE_DA_EVITARE = ["sign", "logo", "map", "plan", "poster", "flag", "coat", "lobby", "restaurant", "menu", "room", "bar ", "dorm", "pool", "terrace"]


def ricerche(citta, stelle):
    """Le frasi da cercare per un hotel, dalla piu' adatta alle stelle."""
    nome = NOMI_CITTA[citta][0]
    if stelle >= 5:
        return ["palace hotel " + nome, "grand hotel " + nome, "luxury hotel " + nome, "hotel " + nome]
    if stelle >= 4:
        return ["hotel " + nome, "boutique hotel " + nome]
    return ["hostel " + nome, "hostal " + nome, "guest house " + nome, "hotel " + nome]


def cerca(frase):
    """I risultati di una ricerca su Commons: titolo, indirizzo dell'anteprima, dimensioni, autore e licenza."""
    parametri = {
        "action": "query", "format": "json", "generator": "search", "gsrsearch": frase + " filetype:bitmap",
        "gsrnamespace": 6, "gsrlimit": 30, "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata",
        "iiurlwidth": LARGHEZZA, "iiextmetadatafilter": "LicenseShortName|Artist",
    }
    richiesta = urllib.request.Request(URL_API + "?" + urllib.parse.urlencode(parametri), headers=INTESTAZIONI)

    # Se Commons risponde 429 (troppe richieste) aspetto e riprovo, fino a 6 volte
    for tentativo in range(6):
        try:
            with urllib.request.urlopen(richiesta, timeout=60) as risposta:
                pagine = json.load(risposta).get("query", {}).get("pages", {}).values()
            break
        except urllib.error.HTTPError as errore:
            if errore.code != 429 or tentativo == 5:
                raise
            attesa = int(errore.headers.get("Retry-After", 30)) + 5 * tentativo
            print("   troppe richieste, aspetto", attesa, "secondi...")
            time.sleep(attesa)

    def per_indice(p):
        return p["index"]

    risultati = []
    for pagina in sorted(pagine, key=per_indice):
        info = pagina["imageinfo"][0]
        meta = info.get("extmetadata", {})
        autore = re.sub(r"<[^>]+>", "", meta.get("Artist", {}).get("value", "")).strip()  # l'autore arriva con tag HTML
        risultati.append({
            "titolo": pagina["title"], "url": info["thumburl"], "pagina": info["descriptionurl"],
            "larghezza": info["width"], "altezza": info["height"], "tipo": info["mime"],
            "licenza": meta.get("LicenseShortName", {}).get("value", ""), "autore": autore[:80],
        })
    return risultati


def adatta(foto, citta):
    """True se la foto e' utilizzabile: JPEG orizzontale e grande, licenza libera, citta' giusta, non un'insegna o una mappa."""
    titolo = foto["titolo"].lower()
    if foto["tipo"] != "image/jpeg" or foto["larghezza"] < 1000 or foto["larghezza"] < foto["altezza"] * 1.2:
        return False
    if not (foto["licenza"].startswith("CC") or foto["licenza"].lower().startswith("public domain")):
        return False
    if not any(nome.lower() in titolo for nome in NOMI_CITTA[citta]):
        return False
    return not any(parola in titolo for parola in PAROLE_DA_EVITARE)


def main():
    # Se il file esiste riparto da li': gli hotel gia' trovati non si cercano di nuovo
    foto_hotel = json.loads(FILE_FOTO.read_text(encoding="utf-8")) if FILE_FOTO.exists() else {}
    usate = {foto["pagina"] for foto in foto_hotel.values()}  # una foto non si usa per due hotel

    for citta, hotel_della_citta in HOTELS.items():
        for nome, stelle, prezzo, descrizione in hotel_della_citta:
            if nome in foto_hotel:
                continue
            scelta = None
            for frase in ricerche(citta, stelle):
                time.sleep(3)  # una richiesta ogni 3 secondi: Commons e' un servizio gratuito, non va sovraccaricato
                for foto in cerca(frase):
                    if foto["pagina"] not in usate and adatta(foto, citta):
                        scelta = foto
                        break
                if scelta:
                    break

            if scelta is None:
                print("NESSUNA FOTO:", citta, "-", nome)
                continue
            usate.add(scelta["pagina"])
            credito = (scelta["autore"] + ", " if scelta["autore"] else "") + scelta["licenza"] + " (Wikimedia Commons)"
            foto_hotel[nome] = {"image_url": scelta["url"], "image_credit": credito, "pagina": scelta["pagina"], "file": scelta["titolo"]}
            print(citta.ljust(11), str(stelle) + "*", nome.ljust(26), scelta["titolo"][:60])
            FILE_FOTO.write_text(json.dumps(foto_hotel, ensure_ascii=False, indent=2), encoding="utf-8")  # salvo a ogni hotel

    FILE_FOTO.write_text(json.dumps(foto_hotel, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Salvate", len(foto_hotel), "foto in", FILE_FOTO)


if __name__ == "__main__":
    main()
