"""Läser Fastighetsanalys-filerna (Excel) i Underlag.

Varje fil är ett år (året står i filnamnet, t.ex. "December 2025 Fastighetsanalys ….xlsx"). Bladet har en
rubrikrad (Byggår, TOA, …), en totalrad "Affärsområden", en rad per affärsområde ("Affärsområde Vallås")
följd av dess fastigheter, och eventuellt en rad "Odefinierat". Belopp i tkr, andelar som decimaltal.
"""
import os
import re
from dataclasses import dataclass, field

from openpyxl import load_workbook

# Rubrik i Excel -> fältnamn
KOLUMNER = {
    "Byggår": "byggar",
    "TOA": "toa",
    "BOA": "boa",
    "LOA": "loa",
    "BOA + LOA": "boa_loa",
    "Antal LGH": "lgh",
    "Antal Lokaler": "lokaler",
    "Bokfört värde": "bokfort",
    "Marknadsvärde": "marknad",
    "Resultat EVR": "resultat",
    "Intäkter EVR": "intakter",
    "Avskrivningar EVR": "avskrivningar",
    "Driftsnetto exkl underhåll EVR": "driftsnetto",
    "Vakansgrad": "vakansgrad",
    "Hyresintäkter per kvm": "hyra_kvm",
    "Driftkostnader per kvm": "driftkostnad_kvm",
}
# Uppgifter som beskriver fastigheten och kan hämtas från ett annat år när de saknas
STAMFALT = ["byggar", "toa", "boa", "loa", "boa_loa", "lgh", "lokaler", "bokfort", "marknad"]
ODEFINIERAT = "Odefinierat"


def _tal(v):
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(" ", "").replace(" ", "").replace(",", "."))
    except ValueError:
        return None


@dataclass
class Arsfil:
    ar: int
    filnamn: str
    period: str = ""
    fastigheter: dict = field(default_factory=dict)  # kod -> {namn, ao, rad, fält…}
    ao_rader: dict = field(default_factory=dict)     # ao -> gruppradens värden i Excel
    total: dict = field(default_factory=dict)
    varningar: list = field(default_factory=list)


def las_fil(sokvag: str) -> Arsfil:
    filnamn = os.path.basename(sokvag)
    m = re.search(r"(20\d\d)\s+Fastighetsanalys", filnamn) or re.search(r"(20\d\d)", filnamn)
    if not m:
        raise ValueError("Hittar inget årtal i filnamnet")
    fil = Arsfil(ar=int(m.group(1)), filnamn=filnamn)
    wb = load_workbook(sokvag, read_only=True, data_only=True)
    ws = wb["Fastighetsanalys"] if "Fastighetsanalys" in wb.sheetnames else wb.worksheets[0]
    kol = None
    ao = None
    for nr, rad in enumerate(ws.iter_rows(values_only=True), start=1):
        rad = list(rad)
        forsta = str(rad[0]).strip() if rad and rad[0] is not None else ""
        if kol is None:
            if forsta.lower().startswith("period"):
                fil.period = forsta.split(":", 1)[-1].strip()
            rubriker = {str(c).strip(): i for i, c in enumerate(rad) if c is not None}
            if "Byggår" in rubriker:
                kol = {falt: rubriker[rubrik] for rubrik, falt in KOLUMNER.items() if rubrik in rubriker}
                saknas = [r for r in KOLUMNER if r not in rubriker]
                if saknas:
                    fil.varningar.append("Kolumner saknas: " + ", ".join(saknas))
            continue
        if not forsta:
            continue
        varden = {falt: _tal(rad[i]) if i < len(rad) else None for falt, i in kol.items()}
        if forsta == "Affärsområden":
            fil.total = varden
        elif forsta.startswith("Affärsområde "):
            ao = forsta.removeprefix("Affärsområde ").strip()
            fil.ao_rader[ao] = varden
        elif forsta == ODEFINIERAT:
            # Samlingsrad utan fastigheter – tas med som en egen post så att summorna stämmer med underlaget.
            # Byggåret på en samlingsrad är inte en fastighets byggår.
            fil.ao_rader[ODEFINIERAT] = varden
            fil.fastigheter["ODEF"] = {**varden, "byggar": None, "kod": "ODEF", "namn": "Odefinierat (ej fördelat på fastighet)",
                                       "ao": ODEFINIERAT, "rad": nr, "samlingsrad": True}
        else:
            km = re.match(r"(\d+)\s+(.*)", forsta)
            if not km or ao is None:
                fil.varningar.append(f"Rad {nr} kunde inte tolkas: {forsta[:60]}")
                continue
            kod = km.group(1)
            if kod in fil.fastigheter:
                fil.varningar.append(f"Rad {nr}: fastighetsnummer {kod} förekommer flera gånger")
                continue
            if varden.get("byggar") is not None:
                varden["byggar"] = int(varden["byggar"])
            fil.fastigheter[kod] = {**varden, "kod": kod, "namn": km.group(2).strip(), "ao": ao, "rad": nr, "samlingsrad": False}
    wb.close()
    if kol is None:
        raise ValueError("Hittar ingen rubrikrad med kolumnen Byggår")
    return fil


@dataclass
class Underlag:
    filer: dict = field(default_factory=dict)   # år -> Arsfil
    fel: list = field(default_factory=list)     # [(filnamn, felmeddelande)]

    @property
    def ar(self) -> list[int]:
        return sorted(self.filer)

    def koder(self) -> list[str]:
        sedda = {}
        for ar in self.ar:
            for kod in self.filer[ar].fastigheter:
                sedda.setdefault(kod, None)
        return list(sedda)

    def fastighet(self, kod: str, ar: int) -> dict | None:
        """Fastighetens uppgifter för året. Stamuppgifter som saknas hämtas från närmaste andra år (noteras i 'lanat')."""
        egen = self.filer[ar].fastigheter.get(kod) if ar in self.filer else None
        andra = [self.filer[a].fastigheter[kod] | {"_ar": a} for a in sorted(self.filer, key=lambda a: (abs(a - ar), -a))
                 if a != ar and kod in self.filer[a].fastigheter]
        if egen is None and not andra:
            return None
        if egen is None:
            mall = andra[0]
            bas = {**dict.fromkeys(KOLUMNER.values()), "kod": kod, "namn": mall["namn"], "ao": mall["ao"], "rad": None,
                   "samlingsrad": mall["samlingsrad"], "saknas_i_aret": True}
        else:
            bas = {**egen, "saknas_i_aret": False}
        lanat = {}
        for falt in STAMFALT:
            if bas.get(falt) is None:
                for annan in andra:
                    if annan.get(falt) is not None:
                        bas[falt] = annan[falt]
                        lanat[falt] = annan["_ar"]
                        break
        bas["lanat"] = lanat
        return bas


def las_underlag(katalog: str) -> Underlag:
    u = Underlag()
    if not os.path.isdir(katalog):
        u.fel.append((katalog, "Katalogen finns inte"))
        return u
    for filnamn in sorted(os.listdir(katalog)):
        if not filnamn.lower().endswith(".xlsx") or filnamn.startswith("~$"):
            continue
        try:
            fil = las_fil(os.path.join(katalog, filnamn))
        except Exception as e:  # en trasig fil ska inte stoppa de andra
            u.fel.append((filnamn, str(e)))
            continue
        if fil.ar in u.filer:
            u.fel.append((u.filer[fil.ar].filnamn, f"Ersatt av {filnamn} (samma år, senare filnamn)"))
        u.filer[fil.ar] = fil
    return u
