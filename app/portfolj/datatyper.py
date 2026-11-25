"""Datatyperna som kan läsas in under Datainläsning: kolumner, alternativa rubriknamn och vad som gör en post unik.

En datatyp beskriver det interna formatet. Filimporten (Excel/CSV) och en framtida API-koppling lämnar båda rader i det
här formatet till importmotorn, som validerar och skriver dem på samma sätt. Tabellen i databasen (d_<nyckel>) skapas
ur definitionen; en ny kolumn här läggs till i tabellen vid nästa start.

Kolumntyper: text, tal (svenskt decimaltal), heltal, andel (3,5 % eller 0,035), period (2026, 2026-03, mars 2026, datum),
datum, janej, val (fasta värden med alternativa stavningar) och fastighet (fastighetsnummer eller namn).
Belopp anges i kronor.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Kol:
    falt: str
    rubrik: str
    typ: str = "text"
    kravs: bool = False
    alias: tuple = ()
    val: dict | None = None      # typ "val": värde -> alternativa stavningar
    hjalp: str = ""
    lagras: bool = True          # False = hjälpkolumn som bara används vid tolkningen (t.ex. År och Månad)


FASTIGHET = Kol("fastighet", "Fastighet", "fastighet", True,
                ("fastighetsnummer", "fastighetsnr", "fastighets-id", "fastighetsid", "fastighet nr", "fnr", "k-ställe", "kställe",
                 "fastighetsnamn", "fastighetsbeteckning", "objekt fastighet", "visningsnamn"),
                hjalp="Fastighetsnummer (t.ex. 2232), numret följt av namnet, eller namnet")
PERIOD = Kol("period", "Period", "period", True, ("datum", "månad", "tidpunkt", "avläsningsdatum", "avser period", "år-månad", "period från"),
             hjalp="2026, 2026-03, mars 2026 eller ett datum. Kan också anges i kolumnerna År och Månad")
AR = Kol("_ar", "År", "heltal", alias=("ar", "år", "year", "kalenderår"), hjalp="Används när perioden står i två kolumner", lagras=False)
MANAD = Kol("_manad", "Månad", "manad", alias=("man", "mån", "month", "månadsnr"), hjalp="1–12 eller månadens namn", lagras=False)

MEDIA = {"el": ("el", "elektricitet", "fastighetsel", "elenergi", "elförbrukning"),
         "varme": ("värme", "fjärrvärme", "fjv", "uppvärmning", "värmeenergi"),
         "vatten": ("vatten", "va", "vattenförbrukning"),
         "kallvatten": ("kallvatten", "kv", "kallt vatten"),
         "varmvatten": ("varmvatten", "vv", "tappvarmvatten"),
         "kyla": ("kyla", "fjärrkyla"),
         "gas": ("gas", "naturgas"),
         "ovrigt": ("övrigt", "annat")}
MEDIANAMN = {"el": "El", "varme": "Värme", "vatten": "Vatten", "kallvatten": "Kallvatten", "varmvatten": "Varmvatten", "kyla": "Kyla",
             "gas": "Gas", "ovrigt": "Övrigt"}
ENHET = {"kWh": ("kwh",), "MWh": ("mwh",), "GWh": ("gwh",), "m³": ("m3", "m³", "kbm", "kubikmeter"), "l": ("l", "liter")}
SCENARIO = {"utfall": ("utfall", "u", "actual", "verkligt"), "budget": ("budget", "b"), "prognos": ("prognos", "p", "forecast")}
UHTYP = {"planerat": ("planerat underhåll", "planerat", "underhåll", "normalt planerat underhåll", "pu"),
         "eftersatt": ("eftersatt underhåll", "eftersatt"),
         "investering": ("investering", "inv"),
         "fornyelse": ("förnyelse", "renovering"),
         "energi": ("energieffektivisering", "energi", "energiåtgärd")}
UHTYPNAMN = {"planerat": "Planerat underhåll", "eftersatt": "Eftersatt underhåll", "investering": "Investering", "fornyelse": "Förnyelse",
             "energi": "Energieffektivisering"}

DATATYPER = {
    "energi": {
        "namn": "Energi & media", "flik": "energi",
        "beskrivning": "Förbrukning och kostnad per mätpunkt och period.",
        "kolumner": [
            FASTIGHET,
            Kol("matpunkt", "Mätpunkt", alias=("mätare", "mätar-id", "mätarnummer", "anläggnings-id", "anläggningsid", "mätpunkts-id", "mätpunktsid", "anläggning")),
            PERIOD, AR, MANAD,
            Kol("media", "Media", "val", True, ("energislag", "medietyp", "mediatyp", "typ", "nyttighet", "energislag/media", "mediaslag", "rapportslag"), MEDIA,
                "El, värme, vatten, kallvatten, varmvatten, kyla, gas eller övrigt"),
            Kol("forbrukning", "Förbrukning", "tal", alias=("förbrukning kwh", "förbrukning m3", "mängd", "volym", "kwh", "m3", "användning", "faktisk förbrukning", "värde")),
            Kol("enhet", "Enhet", "val", alias=("måttenhet", "sort"), val=ENHET, hjalp="kWh, MWh, GWh, m³ eller l. Tomt = kWh för energi och m³ för vatten"),
            Kol("kostnad", "Kostnad", "tal", alias=("kostnad kr", "belopp", "kr", "summa kr", "kostnad exkl moms"), hjalp="Kronor"),
            Kol("pris", "Pris/taxa", "tal", alias=("pris", "taxa", "à-pris", "apris", "kr/kwh", "kr/m3", "pris per enhet"), hjalp="Kronor per enhet"),
            Kol("byggnad", "Byggnad", alias=("hus", "byggnadsnummer", "byggnadsnr")),
            Kol("objekt", "Lägenhet/lokal", alias=("lägenhet", "lokal", "objekt", "objektnummer", "lägenhetsnummer")),
            Kol("kvalitet", "Datakvalitet", alias=("kvalitet", "avläsningstyp", "status", "mätvärdesstatus"), hjalp="T.ex. avläst eller uppskattad"),
        ],
        "nyckel": ["matpunkt", "period", "media", "byggnad", "objekt"],
    },
    "ekonomi": {
        "namn": "Ekonomi", "flik": "ekonomi",
        "beskrivning": "Belopp per period, konto eller kategori och scenario (utfall, budget, prognos).",
        "kolumner": [
            FASTIGHET, PERIOD, AR, MANAD,
            Kol("kategori", "Kategori", kravs=True, alias=("kontogrupp", "kostnadsslag", "rad", "benämning", "kontonamn", "post")),
            Kol("konto", "Konto", alias=("kontonummer", "kontonr", "konto nr")),
            Kol("scenario", "Scenario", "val", True, ("typ", "version", "utfall/budget", "scenario/typ"), SCENARIO, "Utfall, budget eller prognos"),
            Kol("belopp", "Belopp", "tal", True, ("belopp kr", "summa", "kr", "värde", "utfall", "saldo"), hjalp="Kronor"),
        ],
        "nyckel": ["period", "kategori", "konto", "scenario"],
    },
    "hyra": {
        "namn": "Hyra", "flik": "hyra",
        "beskrivning": "Hyra per lägenhet eller lokal.",
        "kolumner": [
            FASTIGHET,
            Kol("objekt", "Lägenhet/lokal", kravs=True, alias=("objekt", "objektnummer", "objektnr", "lägenhet", "lokal", "lägenhetsnummer", "lägenhetsnr", "kontraktsobjekt")),
            Kol("typ", "Typ", alias=("objekttyp", "lägenhetstyp", "objektstyp"), hjalp="T.ex. lägenhet, lokal, 2 rok"),
            Kol("area", "Area", "tal", alias=("yta", "kvm", "m2", "boa", "loa", "area kvm")),
            Kol("rum", "Rum", "tal", alias=("antal rum", "rok")),
            Kol("hyra", "Hyra", "tal", alias=("bashyra", "årshyra", "hyra kr/år", "grundhyra", "hyra per år"), hjalp="Kronor per år"),
            Kol("tillagg", "Tillägg", "tal", alias=("hyrestillägg", "tillägg kr"), hjalp="Kronor per år"),
            Kol("rabatt", "Rabatt", "tal", alias=("rabatter", "hyresrabatt"), hjalp="Kronor per år, positivt tal"),
            Kol("kontraktsstatus", "Kontraktsstatus", alias=("status", "kontrakt", "uthyrningsstatus"), hjalp="T.ex. uthyrd, vakant, uppsagd"),
            Kol("giltig_fran", "Giltig från", "datum", alias=("från", "fr o m", "from", "startdatum", "kontrakt från", "giltig fr o m")),
            Kol("giltig_till", "Giltig till", "datum", alias=("till", "t o m", "tom", "slutdatum", "kontrakt till", "giltig t o m")),
            Kol("standard", "Standard", alias=("standardnivå",)),
            Kol("renoveringsar", "Renoveringsår", "heltal", alias=("renoverad", "renoverat år")),
        ],
        "nyckel": ["objekt", "giltig_fran"],
    },
    "drift": {
        "namn": "Drift och felanmälningar", "flik": "drift",
        "beskrivning": "Ett ärende per rad.",
        "kolumner": [
            Kol("arende_id", "Ärende-ID", kravs=True, alias=("ärende", "ärendenummer", "ärendenr", "id", "felanmälan", "arbetsorder", "ordernummer")),
            FASTIGHET,
            Kol("objekt", "Lägenhet/lokal", alias=("lägenhet", "lokal", "objekt", "objektnummer", "lägenhetsnummer")),
            Kol("byggnad", "Byggnad", alias=("hus", "byggnadsnummer")),
            Kol("datum", "Datum", "datum", True, ("öppningsdatum", "anmäld", "anmälningsdatum", "skapad", "registrerad", "inkom")),
            Kol("avslutsdatum", "Avslutsdatum", "datum", alias=("avslutad", "klar", "åtgärdad", "stängd", "klardatum")),
            Kol("kategori", "Kategori", alias=("felkategori", "feltyp", "ärendetyp", "område")),
            Kol("underkategori", "Underkategori", alias=("underkategori", "detalj")),
            Kol("komponent", "Komponent", alias=("teknisk komponent", "byggdel", "installation")),
            Kol("prioritet", "Prioritet", alias=("prio",)),
            Kol("akut", "Akut", "janej", alias=("akut/ej akut", "jour")),
            Kol("status", "Status", alias=("ärendestatus",)),
            Kol("kostnad", "Kostnad", "tal", alias=("reparationskostnad", "belopp", "kostnad kr"), hjalp="Kronor"),
            Kol("leverantor", "Leverantör", alias=("entreprenör", "utförare")),
        ],
        "nyckel": ["arende_id"],
    },
    "underhall": {
        "namn": "Underhåll och åtgärder", "flik": "underhall",
        "beskrivning": "Planerade och genomförda åtgärder per komponent. Investeringsplanen hämtas fortfarande från Styrning.",
        "kolumner": [
            FASTIGHET,
            Kol("atgard", "Åtgärd", kravs=True, alias=("åtgärdsnamn", "benämning", "beskrivning", "aktivitet")),
            Kol("komponent", "Komponent", alias=("byggdel", "teknisk komponent", "system")),
            Kol("byggnad", "Byggnad", alias=("hus", "byggnadsnummer")),
            Kol("typ", "Typ", "val", alias=("åtgärdstyp", "slag", "kategori"), val=UHTYP,
                hjalp="Planerat underhåll, eftersatt underhåll, investering, förnyelse eller energieffektivisering"),
            Kol("planerat_ar", "Planerat år", "heltal", alias=("år", "planår", "planerat", "utförandeår")),
            Kol("planerad_kostnad", "Planerad kostnad", "tal", alias=("kostnad", "budget", "planerat belopp", "kalkyl"), hjalp="Kronor"),
            Kol("genomfort_ar", "Genomfört år", "heltal", alias=("genomfört", "utfört år", "klart år")),
            Kol("faktisk_kostnad", "Faktisk kostnad", "tal", alias=("utfall", "verklig kostnad"), hjalp="Kronor"),
            Kol("status", "Status", alias=("läge",)),
        ],
        "nyckel": ["atgard", "komponent", "byggnad", "planerat_ar"],
    },
    "kund": {
        "namn": "Kund & uthyrning", "flik": "kund",
        "beskrivning": "Kundindex och uthyrningstal per period.",
        "kolumner": [
            FASTIGHET, PERIOD, AR, MANAD,
            Kol("nki", "NKI", "tal", alias=("nöjd kund index", "nöjdkundindex")),
            Kol("serviceindex", "Serviceindex", "tal", alias=("service",)),
            Kol("trygghetsindex", "Trygghetsindex", "tal", alias=("trygghet",)),
            Kol("produktindex", "Produktindex", "tal", alias=("produkt",)),
            Kol("antal_svar", "Antal svar", "heltal", alias=("svar", "svarande")),
            Kol("uthyrningsgrad", "Uthyrningsgrad", "andel", alias=("uthyrningsgrad %",)),
            Kol("vakansgrad", "Vakansgrad", "andel", alias=("vakans", "vakans %", "vakansgrad %")),
            Kol("tomma_lagenheter", "Tomma lägenheter", "heltal", alias=("tomma", "vakanta lägenheter", "lediga lägenheter")),
            Kol("uppsagningar", "Uppsägningar", "heltal", alias=("antal uppsägningar",)),
            Kol("omflyttning", "Omflyttning", "andel", alias=("omflyttningsgrad", "omflyttning %", "omsättning")),
            Kol("soktryck", "Söktryck", "tal", alias=("sökande per lägenhet", "antal sökande")),
            Kol("kotid", "Kötid", "tal", alias=("kötid år", "genomsnittlig kötid"), hjalp="År"),
            Kol("hyresbortfall", "Hyresbortfall", "tal", alias=("hyresbortfall kr",), hjalp="Kronor"),
        ],
        "nyckel": ["period"],
    },
}
