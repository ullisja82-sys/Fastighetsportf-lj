"""Kundundersökningen (AktivBo): serviceindex och produktindex per fastighet, för HFAB och för riket.

Mappen Kundundersökning läses vid start:
- AktivBo Analytics-exporter (aktivbo_analytics_result_export_….xlsx). Bladet Results har en rad per index och
  enhet; året tas från Survey Name ("CSC Bostad 2026") och värdet från Positive Results (andel nöjda i procent).
  AktivBo anger fastigheten med namn ("Adjunkten 1"), inte nummer, och delar ibland upp en fastighet i flera
  enheter ("Hjässan 2 Höghus"). Namnen paras ihop med fastigheterna i underlaget; en fastighet med flera enheter
  får medelvärdet av enheterna, vägt med antal svar. HFAB totalt räknas på samma sätt ur alla enheter.
  En export utan fastighetskolumn är undersökningens totalsiffror och läses som HFAB som helhet.
- Kundundersökning.csv för det som exporten inte innehåller, t.ex. HFAB totalt och riket. Semikolonavgränsad med
  rubrikraden  ar;niva;kod;serviceindex;produktindex  där niva är fastighet, hfab eller riket.
"""
import csv
import hashlib
import os
import re

from openpyxl import load_workbook

FILNAMN = "Kundundersökning.csv"
MATT = [("serviceindex", "Serviceindex"), ("produktindex", "Produktindex")]
INDEXNAMN = {"serviceindex": "serviceindex", "produktindex": "produktindex"}


def _tal(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    try:
        return float(str(v).replace("%", "").replace("\u00a0", "").replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def _ord(namn: str) -> list[str]:
    """Namnet som ord i gemener; skiljetecken bort men beteckningar som 1:156 och 17-18 hålls ihop."""
    s = re.sub(r"(?<=[a-zåäöé])-(?=[a-zåäöé])", " ", str(namn).lower())
    return [o.strip(".") for o in re.split(r"[,\s]+", s) if o.strip(".")]


def _finns_i(sok: list[str], ord_: list[str]) -> bool:
    return any(ord_[i:i + len(sok)] == sok for i in range(len(ord_) - len(sok) + 1))


def para_ihop(enheter: list[str], fastigheter: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """AktivBo-enhetens namn -> fastighetsnummer. Returnerar (träffar, enheter utan säker träff)."""
    ordlistor = {kod: _ord(namn) for kod, namn in fastigheter.items()}
    # Fastighetens beteckning är texten före adressen: "340 Adjunkten 1" i "340 Adjunkten 1. Arkitektg 1-3"
    beteckning = {kod: _ord(re.split(r"\.\s|,\s(?=[A-ZÅÄÖ])", namn)[0]) for kod, namn in fastigheter.items()}

    def en(traffar, o=None):
        if len(traffar) > 1 and o:  # flera möjliga: den vars beteckning slutar med just det sökta
            traffar = [k for k in traffar if beteckning[k][-len(o):] == o]
        return traffar[0] if len(traffar) == 1 else None

    def sok(o):
        # 1. Hela namnet står i fastighetens namn: "Adjunkten 1" i "340 Adjunkten 1. Arkitektg 1-3"
        kod = en([k for k, x in ordlistor.items() if _finns_i(o, x)], o)
        if kod or len(o) < 2:
            return kod
        # 2. Fastigheten samlar flera beteckningar: "Koljan 10" i "Koljan 1, 10", "Breared 2:88:3" i "Breared 2:88"
        def samlad(x):
            if o[0] not in x:
                return False
            efter = x[x.index(o[0]) + 1:x.index(o[0]) + 5]
            return any(o[1] == e or o[1].startswith(e + ":") for e in efter)
        return en([k for k, x in ordlistor.items() if samlad(x)])

    traffar, utan = {}, []
    for namn in enheter:
        o = _ord(namn)
        kod = None
        # 3. Del av en fastighet: "Karl XI 6 Servicelägenheter" -> "Karl XI 6"; sist bara namnet om det är entydigt
        for n in range(len(o), 0, -1):
            kod = sok(o[:n]) if n > 1 else (None if o[1:2] and o[1][0].isdigit() else en([k for k, x in ordlistor.items() if o[0] in x]))
            if kod:
                break
        if kod:
            traffar[namn] = kod
        else:
            utan.append(namn)
    return traffar, utan


def _las_export(sokvag: str) -> dict:
    """{(år, enhetsnamn): {"serviceindex": …, "produktindex": …, "svar": …}} ur en AktivBo-export.

    svar = antal svar i enheten, hämtat från indexet Profil (exporten saknar antal för service- och produktindex).
    Används som vikt när enheter slås ihop."""
    wb = load_workbook(sokvag, read_only=True, data_only=True)
    if "Results" not in wb.sheetnames:
        raise ValueError("Bladet Results saknas")
    rader = wb["Results"].iter_rows(values_only=True)
    rubriker = [str(c or "").strip() for c in next(rader)]
    kol = {n: rubriker.index(n) for n in ("Survey Name", "Index Name", "Result Type", "Positive Results") if n in rubriker}
    svarskol = rubriker.index("Total option answers") if "Total option answers" in rubriker else None
    enhet = next((i for i, r in enumerate(rubriker) if r not in kol and i > kol.get("Index Name", 0) and i < kol.get("Result Type", 99)
                  and r not in ("Sub-index Name", "QuestionID", "Question Name")), None)
    if len(kol) < 4:
        raise ValueError("Kolumnerna Survey Name, Index Name, Result Type eller Positive Results saknas")
    # Utan enhetskolumn är exporten undersökningens totalsiffror, dvs. HFAB som helhet (enhetsnamn None)
    ut = {}
    for rad in rader:
        index = str(rad[kol["Index Name"]] or "").strip().lower()
        falt = INDEXNAMN.get(index)
        ar = re.search(r"(20\d\d)", str(rad[kol["Survey Name"]] or ""))
        if not ar or rad[kol["Result Type"]] != "index" or (enhet is not None and not rad[enhet]):
            continue
        post = ut.setdefault((int(ar.group(1)), " ".join(str(rad[enhet]).split()) if enhet is not None else None), {})
        if index == "profil" and svarskol is not None and _tal(rad[svarskol]):
            post["svar"] = _tal(rad[svarskol])
        if falt and _tal(rad[kol["Positive Results"]]) is not None:
            post[falt] = _tal(rad[kol["Positive Results"]])
    return ut


def _las_csv(sokvag: str) -> dict:
    ut = {}
    with open(sokvag, encoding="utf-8-sig", newline="") as f:
        for rad in csv.DictReader(f, delimiter=";"):
            rad = {(k or "").strip().lower(): (v or "").strip() for k, v in rad.items()}
            niva = rad.get("niva", "").lower()
            if not rad.get("ar", "").isdigit() or niva not in ("fastighet", "hfab", "riket"):
                continue
            ut[(int(rad["ar"]), niva, rad.get("kod", "") if niva == "fastighet" else "")] = {m: _tal(rad.get(m, "")) for m, _ in MATT}
    return ut


def _vagt(poster: list[dict], falt: str) -> float | None:
    """Medelvärde vägt med antal svar; enheter utan uppgift om antal svar väger som en svarande."""
    med = [(v[falt], v.get("svar") or 1) for v in poster if v.get(falt) is not None]
    return sum(x * w for x, w in med) / sum(w for _, w in med) if med else None


class Kund(dict):
    """{(år, nivå, kod): {"serviceindex", "produktindex", "enheter"}} plus uppgifter om inläsningen."""

    def __init__(self):
        super().__init__()
        self.filer, self.fel, self.utan_traff, self.enheter, self.manuella = [], [], [], {}, {}   # enheter: namn -> kod


def las_kund(mapp: str, fastigheter: dict[str, str], manuella: dict[str, str] | None = None) -> Kund:
    """fastigheter: nummer -> namn i underlaget; manuella: enhet -> nummer, kopplat för hand. Tom Kund om mappen saknas eller är tom."""
    k = Kund()
    if not os.path.isdir(mapp):
        return k
    export = {}
    for filnamn in sorted(os.listdir(mapp)):
        sokvag = os.path.join(mapp, filnamn)
        if filnamn.startswith("~$"):
            continue
        try:
            if filnamn.lower().endswith(".xlsx"):
                export.update(_las_export(sokvag))   # senare filnamn gäller för samma år och enhet
                k.filer.append(filnamn)
            elif filnamn == FILNAMN:
                k.update(_las_csv(sokvag))
                k.filer.append(filnamn)
        except Exception as e:  # en trasig fil ska inte stoppa appen
            k.fel.append((filnamn, str(e)))
    # Totalexporten (utan enhetskolumn) är AktivBos egen siffra för HFAB och går före den beräknade
    for (ar, namn) in [n for n in export if n[1] is None]:
        k.setdefault((ar, "hfab", ""), {falt: export[(ar, namn)].get(falt) for falt, _ in MATT})
        del export[(ar, namn)]
    alla = sorted({namn for _, namn in export})
    k.manuella = {e: kod for e, kod in (manuella or {}).items() if e in alla and kod in fastigheter}
    k.enheter, k.utan_traff = para_ihop([e for e in alla if e not in k.manuella], fastigheter)
    k.enheter.update(k.manuella)
    per_fastighet = {}
    for (ar, namn), v in export.items():
        if namn in k.enheter:
            per_fastighet.setdefault((ar, k.enheter[namn]), []).append((namn, v))
    for (ar, kod), enheter in per_fastighet.items():
        post = {"enheter": sorted(enheter, key=lambda e: e[0])}
        for falt, _ in MATT:
            post[falt] = _vagt([v for _, v in enheter], falt)
        k.setdefault((ar, "fastighet", kod), post)   # en rad i csv-filen går före
    # HFAB totalt finns inte som egen rad i exporten: räknas ur alla enheter, vägt med antal svar
    for ar in sorted({a for a, _ in export}):
        alla_ar = [v for (a, _), v in export.items() if a == ar]
        k.setdefault((ar, "hfab", ""), {**{falt: _vagt(alla_ar, falt) for falt, _ in MATT}, "beraknad": len(alla_ar)})
    return k


def jamforelse(data: dict, kod: str, ar: int) -> list[dict]:
    """Ett diagram per mått: fastigheten, HFAB och riket, valt år och året före. Tom lista om fastigheten saknar mätning."""
    ut = []
    for falt, namn in MATT:
        rader = []
        for niva, etikett, nyckel in (("fastighet", "Fastigheten", kod), ("hfab", "HFAB", ""), ("riket", "Riket", "")):
            nu = data.get((ar, niva, nyckel), {}).get(falt)
            fore = data.get((ar - 1, niva, nyckel), {}).get(falt)
            rader.append({"niva": niva, "etikett": etikett, "nu": nu, "fore": fore,
                          "andring": nu - fore if nu is not None and fore is not None else None})
        if rader[0]["nu"] is not None or rader[0]["fore"] is not None:
            hfab = rader[1]["nu"]
            ut.append({"falt": falt, "namn": namn, "rader": [x for x in rader if x["nu"] is not None or x["fore"] is not None],
                       "nu": rader[0]["nu"], "andring": rader[0]["andring"],
                       "mot_hfab": rader[0]["nu"] - hfab if rader[0]["nu"] is not None and hfab is not None else None,
                       "saknas": [x["etikett"] for x in rader if x["nu"] is None and x["fore"] is None]
                                 + ([str(ar - 1)] if all(x["fore"] is None for x in rader) else [])})
    return ut


def fiktiv(koder: list[str], aren: list[int]) -> dict:
    """PÅHITTADE värden i samma form som las_kund, för att visa diagrammet innan riktiga uppgifter finns.

    Används bara när Kundundersökning.csv saknas och ska alltid visas med tydlig märkning. Värdena är
    slumpade ur fastighetsnumret (samma varje gång) och säger ingenting om fastigheten.
    """
    def varde(nyckel: str, lag: float, hog: float) -> float:
        andel = int(hashlib.sha256(nyckel.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        return round(lag + andel * (hog - lag), 1)

    ut = {}
    for ar in sorted({a for x in aren for a in (x - 1, x)}):
        ut[(ar, "hfab", "")] = {"serviceindex": varde(f"hfab-s-{ar}", 81, 84), "produktindex": varde(f"hfab-p-{ar}", 78, 81)}
        ut[(ar, "riket", "")] = {"serviceindex": varde(f"riket-s-{ar}", 82, 85), "produktindex": varde(f"riket-p-{ar}", 79, 82)}
        for kod in koder:
            ut[(ar, "fastighet", kod)] = {"serviceindex": varde(f"{kod}-s-{ar}", 70, 93), "produktindex": varde(f"{kod}-p-{ar}", 66, 90)}
    return ut
