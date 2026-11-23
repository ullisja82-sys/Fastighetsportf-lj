"""Fastigheternas läge på kartan. Adressen tas ur fastighetens namn i underlaget och slås upp hos OpenStreetMap
(Nominatim). Resultatet sparas i appens databas, så varje adress slås bara upp en gång."""
import json
import re
import time
import urllib.parse
import urllib.request

NOMINATIM = "https://nominatim.openstreetmap.org/search"
# Halmstads kommun med marginal: väst, norr, öst, syd
RUTA = (12.55, 56.95, 13.45, 56.45)
ORTER = ["Oskarström", "Getinge", "Harplinge", "Kvibille", "Gullbrandstorp", "Trönninge", "Eldsberga", "Simlångsdalen", "Åled", "Sennan",
         "Slättåkra", "Steninge", "Haverdal", "Holm", "Fyllinge", "Frösakull", "Tylösand", "Söndrum", "Vallås", "Andersberg"]
FORKORTNINGAR = [("pl", "platsen"), ("g", "gatan"), ("v", "vägen")]
HELA = ("väg", "vägen", "gatan", "gata", "stig", "stigen", "ring", "ringen", "torg", "torget", "plats", "platsen", "gång", "gången", "gränd",
        "allén", "vång", "vången", "strand", "berg", "borg", "lycken", "fästet", "vallen", "centrum")
EGNA = {"a-ringen": "Andersbergsringen"}


def _hel(ordet: str) -> str:
    """Skriver ut förkortade gatunamn: Arkitektg -> Arkitektgatan, Fågelv -> Fågelvägen, Frescopl -> Frescoplatsen."""
    o = ordet.rstrip(".")
    if o.lower() in EGNA:
        return EGNA[o.lower()]
    if len(o) > 4 and not o.lower().endswith(HELA):
        for kort, hel in FORKORTNINGAR:
            if o.endswith(kort):
                return o[:-len(kort)] + hel
    return o


def adress_ur_namn(namn: str) -> str:
    """ "340 Adjunkten 1. Arkitektg 1-3, Hylteg 2-4" -> "Arkitektgatan 1". Tom sträng om namnet saknar gatuadress."""
    # Gatan står efter beteckningen ("Adjunkten 1", "Bäckagård 1:156"), skild med punkt eller komma
    delar = re.split(r"\.\s+|,\s+(?=[A-ZÅÄÖ])", namn, maxsplit=1)
    if len(delar) < 2:
        delar = re.split(r"(?<=\d)\s+(?=[A-ZÅÄÖ][a-zåäö]+\S*\s+\d)", namn, maxsplit=1)
    if len(delar) < 2 or re.search(r"nyproduktion|kommun", delar[1], re.I):
        return ""
    m = re.match(r"\s*((?:[A-Za-zÅÄÖåäöé\-]+\.?\s+){0,3}?[A-Za-zÅÄÖåäöé\-]+\.?)\s*(\d+)", delar[1])
    if m:
        ordlista = m.group(1).split()
        return f"{' '.join(ordlista[:-1] + [_hel(ordlista[-1])])} {m.group(2)}"
    m = re.match(r"\s*((?:[A-ZÅÄÖ][a-zåäöé]+\s)?[A-ZÅÄÖ][a-zåäöé]+(?:gatan|vägen|gången|gränd|stigen|platsen))", delar[1])
    return m.group(1) if m else ""   # gata utan nummer


def ort_ur_namn(namn: str) -> str:
    return next((o for o in ORTER[:13] if o.lower() in namn.lower()), "Halmstad")


def koordinater(text: str) -> tuple[float, float] | None:
    """ "56.66400, 12.76200" (som Google Maps kopierar dem) -> (lat, lon). None om texten inte är två koordinater i Sverige."""
    m = re.fullmatch(r"\s*(\d{2}\.\d+)\s*[,; ]\s*(\d{1,2}\.\d+)\s*", text or "")
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    return (lat, lon) if 55 <= lat <= 70 and 10 <= lon <= 25 else None


def sla_upp(adress: str, ort: str = "Halmstad") -> tuple[float, float] | None:
    """En fråga till Nominatim. Anroparen ansvarar för högst en fråga per sekund. Koordinater används som de är."""
    if koordinater(adress):
        return koordinater(adress)
    fraga = urllib.parse.urlencode({"q": f"{adress}, {ort}" if ort else adress, "format": "jsonv2", "limit": 1, "countrycodes": "se",
                                    "viewbox": ",".join(map(str, RUTA)), "bounded": 1})
    req = urllib.request.Request(f"{NOMINATIM}?{fraga}", headers={"User-Agent": "fastighetsportfolj-karta/1.0"})
    with urllib.request.urlopen(req, timeout=20) as svar:
        traffar = json.load(svar)
    return (float(traffar[0]["lat"]), float(traffar[0]["lon"])) if traffar else None


def sla_upp_fastighet(namn: str, adress: str = "") -> tuple[str, tuple[float, float] | None]:
    """Slår upp en egen adress, annars adressen ur namnet; provar även gatan utan nummer. Returnerar (adress som söktes, läge)."""
    if adress:
        forsok = [(adress, "" if "," in adress else "Halmstad")]
    else:
        adress = adress_ur_namn(namn)
        gata = re.sub(r"\s+\d+$", "", adress)
        forsok = [(adress, ort_ur_namn(namn))] + ([(gata, ort_ur_namn(namn))] if gata != adress else []) if adress else []
    for i, (a, ort) in enumerate(forsok):
        if i:
            time.sleep(1.1)
        lage = sla_upp(a, ort)
        if lage:
            return a, lage
    return adress, None
