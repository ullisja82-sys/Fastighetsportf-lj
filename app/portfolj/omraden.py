"""Nyckeltal och tabeller till fastighetens flikar ur det som lästs in under Datainläsning.

Här räknas bara på inlästa rader; inget sparas. Ett nyckeltal blir None (visas som streck) när underlaget saknas –
aldrig 0. Belopp i filerna är kronor och visas i tkr.

Det som medvetet inte räknas: driftsnetto ur inlästa konton (HFAB:s definition ska fastställas först; raden visas
bara om filen själv har kategorin Driftsnetto).
"""
from datetime import date
from statistics import median

from .datatyper import DATATYPER, MEDIANAMN, UHTYPNAMN
from .importmotor import norm

TILL_KWH = {"kWh": 1, "MWh": 1000, "GWh": 1_000_000}
TILL_M3 = {"m³": 1, "l": 0.001}
VATTEN = ("vatten", "kallvatten")          # varmvatten är en del av kallvattnet och summeras inte en gång till
ENERGIGRUPPER = {"el": ("el",), "varme": ("varme",), "vatten": VATTEN}
EKOKATEGORIER = {
    "hyresintakter": ("hyresintäkter", "hyror", "hyresintäkt", "hyresintäkter bostäder"),
    "ovriga_intakter": ("övriga intäkter", "övriga förvaltningsintäkter"),
    "driftkostnader": ("driftkostnader", "drift", "driftkostnad"),
    "reparationer": ("reparationer", "reparation", "löpande underhåll", "avhjälpande underhåll"),
    "underhall": ("underhåll", "planerat underhåll", "underhållskostnader"),
    "el": ("el", "elkostnad", "fastighetsel"),
    "varme": ("värme", "fjärrvärme", "uppvärmning"),
    "vatten": ("vatten", "va", "vatten och avlopp"),
    "avfall": ("avfall", "sophämtning", "renhållning", "avfallshantering"),
    "fastighetsskatt": ("fastighetsskatt", "fastighetsavgift", "fastighetsskatt/avgift", "fastighetsskatt och avgift"),
    "ovriga_kostnader": ("övriga kostnader", "övrigt"),
    "driftsnetto": ("driftsnetto", "driftnetto"),
}
_EKO = {norm(a): k for k, alias in EKOKATEGORIER.items() for a in alias}


def _summa(varden) -> float | None:
    """Summan av de värden som finns; None om inget finns (saknas är inte noll)."""
    v = [x for x in varden if x is not None]
    return sum(v) if v else None


def _kvot(a, b):
    return a / b if a is not None and b else None


def _tkr(v):
    return v / 1000 if v is not None else None


def _ar(period: str | None) -> int | None:
    return int(period[:4]) if period else None


def _rader(con, datatyp: str, fid: int) -> list[dict]:
    return [dict(r) for r in con.execute(f"SELECT * FROM d_{datatyp} WHERE fastighet_id = ?", (fid,))]


def kallor(con, fid: int) -> dict[str, str]:
    """Datatyp -> "filnamn, inläst datum" för den senaste inläsningen som rört fastigheten."""
    ut = {}
    for nyckel, dt in DATATYPER.items():
        rad = con.execute(f"SELECT i.filnamn, i.importerad FROM d_{nyckel} d JOIN importlogg i ON i.id = d.import_id WHERE d.fastighet_id = ? "
                          "ORDER BY i.id DESC LIMIT 1", (fid,)).fetchone()
        if rad:
            ut[nyckel] = f"{rad['filnamn']}, inläst {rad['importerad'][:10]}"
    return ut


# --- Energi & media ------------------------------------------------------------------------------------
def _mangd(r: dict) -> float | None:
    """Förbrukningen i kWh (energi) eller m³ (vatten). Enhet som inte passar mediet räknas inte med."""
    if r["forbrukning"] is None:
        return None
    vatten = r["media"] in ("vatten", "kallvatten", "varmvatten")
    faktor = (TILL_M3 if vatten else TILL_KWH).get(r["enhet"] or ("m³" if vatten else "kWh"))
    return r["forbrukning"] * faktor if faktor else None


def _energi(rader: list[dict], ar: int, yta) -> dict:
    v = {}
    for grupp, medier in ENERGIGRUPPER.items():
        rr = [r for r in rader if r["media"] in medier and _ar(r["period"]) == ar]
        if not rr:
            continue
        mangd = _summa(_mangd(r) for r in rr)
        enhet = "m3" if grupp == "vatten" else "kwh"
        v[f"{grupp}_{enhet}"] = mangd
        v[f"{grupp}_{enhet}_kvm"] = _kvot(mangd, yta)
        v[f"{grupp}_kostnad"] = _tkr(_summa(r["kostnad"] for r in rr))
    energi = _summa(v.get(k) for k in ("el_kwh", "varme_kwh"))
    v["energi_kwh_kvm"] = _kvot(energi, yta)

    # Kostnadsförändringen mot samma perioder året före, delad i förbrukning och pris
    forbr, pris = [], []
    for medier in ENERGIGRUPPER.values():
        def per(a):
            ut = {}
            for r in rader:
                if r["media"] in medier and _ar(r["period"]) == a and _mangd(r) is not None and r["kostnad"] is not None:
                    q, c = ut.get(r["period"][4:], (0, 0))
                    ut[r["period"][4:]] = (q + _mangd(r), c + r["kostnad"])
            return ut
        nu, fore = per(ar), per(ar - 1)
        gemensamma = nu.keys() & fore.keys()
        q1, c1 = sum(nu[p][0] for p in gemensamma), sum(nu[p][1] for p in gemensamma)
        q0, c0 = sum(fore[p][0] for p in gemensamma), sum(fore[p][1] for p in gemensamma)
        if q0 > 0 and q1 > 0:
            forbr.append((q1 - q0) * c0 / q0)
            pris.append((c1 / q1 - c0 / q0) * q1)
    v["energi_forbrukningseffekt"], v["energi_priseffekt"] = _tkr(_summa(forbr)), _tkr(_summa(pris))
    return v


def _energitabell(rader: list[dict], ar: int, tal) -> dict:
    grupper = {}
    for r in rader:
        if _ar(r["period"]) == ar:
            grupper.setdefault((r["matpunkt"] or "", r["media"], r["byggnad"] or "", r["enhet"] or ""), []).append(r)
    ut = []
    for (matpunkt, media, byggnad, enhet), rr in sorted(grupper.items()):
        mangd, kostnad = _summa(r["forbrukning"] for r in rr), _summa(r["kostnad"] for r in rr)
        pris = _kvot(kostnad, mangd) if kostnad is not None else next((r["pris"] for r in rr if r["pris"] is not None), None)
        perioder = sorted({r["period"] for r in rr})
        ut.append([matpunkt or "–", MEDIANAMN.get(media, media), byggnad or "–", perioder[0] if len(perioder) == 1 else f"{perioder[0]} – {perioder[-1]} ({len(perioder)})",
                   tal(mangd, 0), enhet or ("m³" if media in ("vatten", "kallvatten", "varmvatten") else "kWh"), tal(kostnad, 0), tal(pris, 2),
                   ", ".join(sorted({r["kvalitet"] for r in rr if r["kvalitet"]})) or "–"])
    return {"kolumner": ["Mätpunkt", "Media", "Byggnad", "Period", "Förbrukning", "Enhet", "Kostnad, kr", "Pris, kr/enhet", "Datakvalitet"],
            "num": [4, 6, 7], "rader": ut}


# Jämförelse med liknande fastigheter i beståndet: byggår inom ± JMF_AR år och yta mellan JMF_YTA[0] och JMF_YTA[1] gånger fastighetens
JMF_AR = 10
JMF_YTA = (0.5, 2.0)
JMF_NAMN = {"el": ("El", "kWh"), "varme": ("Värme", "kWh"), "vatten": ("Vatten", "m³")}


def forbrukning_per_fastighet(con, ar: int) -> dict[str, dict[str, float]]:
    """Fastighetsnummer -> {el, varme, vatten: årets inlästa förbrukning i kWh eller m³} för alla fastigheter."""
    ut = {}
    for r in con.execute("SELECT f.kod, d.media, d.enhet, d.forbrukning FROM d_energi d JOIN fastighet f ON f.id = d.fastighet_id "
                         "WHERE d.period LIKE ? AND d.forbrukning IS NOT NULL", (f"{ar}%",)):
        grupp = next((g for g, medier in ENERGIGRUPPER.items() if r["media"] in medier), None)
        mangd = _mangd(dict(r))
        if grupp and mangd is not None:
            per = ut.setdefault(r["kod"], {})
            per[grupp] = per.get(grupp, 0) + mangd
    return ut


def jamforelse(r: dict, alla: list[dict], forbrukning: dict[str, dict[str, float]]) -> list[dict]:
    """Fastighetens förbrukning per kvm mot liknande fastigheter (byggår och yta), en post per media som fastigheten har.
    alla = årets rader för hela beståndet (med byggar och yta)."""
    ut = []
    if not r.get("byggar") or not r.get("yta"):
        return ut
    lika = [x for x in alla if x["kod"] != r["kod"] and not x.get("samlingsrad") and x.get("byggar") and x.get("yta")
            and abs(x["byggar"] - r["byggar"]) <= JMF_AR and JMF_YTA[0] <= x["yta"] / r["yta"] <= JMF_YTA[1]]
    for grupp, (namn, enhet) in JMF_NAMN.items():
        egen = forbrukning.get(r["kod"], {}).get(grupp)
        if egen is None:
            continue
        rader = [{"kod": x["kod"], "namn": x["namn"], "byggar": x["byggar"], "yta": x["yta"], "mangd": forbrukning[x["kod"]][grupp],
                  "per_kvm": forbrukning[x["kod"]][grupp] / x["yta"], "egen": x["kod"] == r["kod"]}
                 for x in [r, *lika] if grupp in forbrukning.get(x["kod"], {})]
        rader.sort(key=lambda x: x["per_kvm"])
        andra = [x["per_kvm"] for x in rader if not x["egen"]]
        egen_kvm = egen / r["yta"]
        med = median(andra) if andra else None
        ut.append({"grupp": grupp, "namn": namn, "enhet": enhet, "rader": rader, "egen": egen_kvm, "median": med, "antal": len(andra),
                   "utan_data": len(lika) - len(andra), "mot_median": egen_kvm / med - 1 if med else None,
                   "plats": next(i for i, x in enumerate(rader, start=1) if x["egen"]), "storst": max(x["per_kvm"] for x in rader)})
    return ut


# --- Ekonomi --------------------------------------------------------------------------------------------
def _ekonomi(rader: list[dict], ar: int) -> dict:
    v = {}
    i_ar = [r for r in rader if _ar(r["period"]) == ar]
    for r in i_ar:
        kat = _EKO.get(norm(r["kategori"]))
        if kat and r["scenario"] == "utfall":
            v[f"eko_{kat}"] = (v.get(f"eko_{kat}") or 0) + r["belopp"] / 1000
        if kat == "driftsnetto" and r["scenario"] in ("budget", "prognos"):
            v[f"eko_{r['scenario']}_dn"] = (v.get(f"eko_{r['scenario']}_dn") or 0) + r["belopp"] / 1000
    if "eko_driftsnetto" in v and "eko_budget_dn" in v:
        v["eko_budgetavvikelse"] = v["eko_driftsnetto"] - v["eko_budget_dn"]
    return v


def _ekonomitabell(rader: list[dict], ar: int, tal) -> dict:
    per = {}
    for r in rader:
        if _ar(r["period"]) == ar:
            rad = per.setdefault((r["konto"] or "", r["kategori"]), {})
            rad[r["scenario"]] = (rad.get(r["scenario"]) or 0) + r["belopp"]
    ut = [[konto or "–", kat, tal(_tkr(x.get("utfall")), 0), tal(_tkr(x.get("budget")), 0), tal(_tkr(x.get("prognos")), 0),
           tal(_tkr(x["utfall"] - x["budget"]) if "utfall" in x and "budget" in x else None, 0)] for (konto, kat), x in sorted(per.items())]
    return {"kolumner": ["Konto", "Kategori", "Utfall, tkr", "Budget, tkr", "Prognos, tkr", "Utfall − budget, tkr"], "num": [2, 3, 4, 5], "rader": ut}


# --- Hyra -----------------------------------------------------------------------------------------------
def _vakant(r: dict) -> bool:
    return any(o in norm(r["kontraktsstatus"]) for o in ("vakant", "tom", "ledig", "outhyrd"))


def _hyresobjekt(rader: list[dict], ar: int) -> list[dict]:
    """Raden som gäller under året för varje lägenhet/lokal (senaste giltig från)."""
    ut = {}
    for r in sorted(rader, key=lambda r: r["giltig_fran"] or ""):
        if (not r["giltig_fran"] or int(r["giltig_fran"][:4]) <= ar) and (not r["giltig_till"] or int(r["giltig_till"][:4]) >= ar):
            ut[r["objekt"]] = r
    return list(ut.values())


def _faktisk(r: dict) -> float | None:
    return r["hyra"] + (r["tillagg"] or 0) - abs(r["rabatt"] or 0) if r["hyra"] is not None else None


def _hyra(rader: list[dict], ar: int) -> dict:
    oo = _hyresobjekt(rader, ar)
    if not oo:
        return {}
    med = [(_faktisk(o), o["area"]) for o in oo if _faktisk(o) is not None and o["area"]]
    per_kvm = [h / a for h, a in med]
    faktisk = _summa(_faktisk(o) for o in oo)
    v = {"hyra_bas": _tkr(_summa(o["hyra"] for o in oo)), "hyra_tillagg": _tkr(_summa(o["tillagg"] for o in oo)),
         "hyra_rabatt": _tkr(_summa(abs(o["rabatt"]) if o["rabatt"] is not None else None for o in oo)),
         "hyra_faktisk": _tkr(faktisk), "hyra_ars": _tkr(faktisk),
         "hyra_kvm_objekt": _kvot(sum(h for h, _ in med), sum(a for _, a in med)) if med else None,
         "hyra_spridning": max(per_kvm) - min(per_kvm) if len(per_kvm) > 1 else None}
    if any(o["kontraktsstatus"] for o in oo):
        v["tomma_objekt"] = sum(1 for o in oo if _vakant(o))
        v["hyresbortfall_objekt"] = _tkr(_summa(_faktisk(o) for o in oo if _vakant(o))) or 0.0
    return v


def _hyrestabell(rader: list[dict], ar: int, tal) -> dict:
    ut = [[o["objekt"], o["typ"] or "–", tal(o["area"], 1), tal(o["rum"], 0), tal(o["hyra"], 0), tal(o["tillagg"], 0), tal(o["rabatt"], 0),
           tal(_kvot(_faktisk(o), o["area"]), 0), " ".join(x for x in (o["kontraktsstatus"], o["giltig_fran"] and f"från {o['giltig_fran']}") if x) or "–"]
          for o in sorted(_hyresobjekt(rader, ar), key=lambda o: o["objekt"])]
    return {"kolumner": ["Objekt", "Typ", "Area, kvm", "Rum", "Hyra, kr/år", "Tillägg", "Rabatt", "Hyra per kvm", "Kontrakt"], "num": [2, 3, 4, 5, 6, 7], "rader": ut}


# --- Drift ----------------------------------------------------------------------------------------------
def _akut(r: dict) -> bool:
    return bool(r["akut"]) or "akut" in norm(r["prioritet"])


def _ledtid(r: dict) -> int | None:
    if r["datum"] and r["avslutsdatum"]:
        return (date.fromisoformat(r["avslutsdatum"]) - date.fromisoformat(r["datum"])).days
    return None


def _medel(varden):
    v = [x for x in varden if x is not None]
    return sum(v) / len(v) if v else None


def _drift(rader: list[dict], ar: int, yta, lgh) -> dict:
    if not rader:
        return {}
    rr = [r for r in rader if _ar(r["datum"]) == ar]
    upprepade = {}
    for r in rr:
        if r["objekt"] and r["kategori"]:
            upprepade[(r["objekt"], r["kategori"])] = upprepade.get((r["objekt"], r["kategori"]), 0) + 1
    kostnad = _summa(r["kostnad"] for r in rr)
    return {"fel_antal": len(rr), "fel_per_1000kvm": _kvot(len(rr) * 1000, yta), "fel_per_lgh": _kvot(len(rr), lgh),
            "fel_akuta": sum(1 for r in rr if _akut(r)) if any(r["akut"] is not None or r["prioritet"] for r in rr) else None,
            "fel_aterkommande": sum(n for n in upprepade.values() if n > 1) if upprepade else None,
            "fel_ledtid": _medel(_ledtid(r) for r in rr), "rep_kostnad": _tkr(kostnad), "rep_kostnad_kvm": _kvot(kostnad, yta)}


def _drifttabell(rader: list[dict], ar: int, tal) -> dict:
    rr = [r for r in rader if _ar(r["datum"]) == ar]
    per = {}
    for r in rr:
        per.setdefault(r["kategori"] or "Utan kategori", []).append(r)
    ut = [[kat, tal(len(x), 0), tal(len(x) * 100 / len(rr), 0) + " %", tal(sum(1 for r in x if _akut(r)), 0), tal(_summa(r["kostnad"] for r in x), 0),
           tal(_medel(_ledtid(r) for r in x), 1)] for kat, x in sorted(per.items(), key=lambda p: -len(p[1]))]
    return {"kolumner": ["Kategori", "Antal", "Andel", "Akuta", "Kostnad, kr", "Ledtid, dagar"], "num": [1, 2, 3, 4, 5], "rader": ut}


# --- Underhåll ------------------------------------------------------------------------------------------
def _underhall(rader: list[dict], idag: int) -> dict:
    if not rader:
        return {}
    kvar = [r for r in rader if r["genomfort_ar"] is None and r["planerat_ar"] is not None and r["planerat_ar"] > idag]
    def inom(n):
        return _tkr(_summa(r["planerad_kostnad"] for r in kvar if r["planerat_ar"] <= idag + n)) or 0.0
    v = {"uh_1": inom(1), "uh_3": inom(3), "uh_5": inom(5), "uh_10": inom(10)}
    for typ in UHTYPNAMN:
        v[f"uh_typ_{typ}"] = _tkr(_summa(r["planerad_kostnad"] for r in kvar if r["typ"] == typ and r["planerat_ar"] <= idag + 10))
    return v


def _underhallstabell(rader: list[dict], tal) -> dict:
    ut = [[r["atgard"], r["komponent"] or "–", UHTYPNAMN.get(r["typ"], "–"), str(r["planerat_ar"] or "–"), tal(r["planerad_kostnad"], 0),
           str(r["genomfort_ar"] or "–"), tal(r["faktisk_kostnad"], 0), r["status"] or "–"]
          for r in sorted(rader, key=lambda r: (r["planerat_ar"] or r["genomfort_ar"] or 9999, r["atgard"]))]
    return {"kolumner": ["Åtgärd", "Komponent", "Typ", "Planerat år", "Planerad kostnad, kr", "Genomfört år", "Faktisk kostnad, kr", "Status"],
            "num": [4, 6], "rader": ut}


# --- Kund & uthyrning -----------------------------------------------------------------------------------
def _kund(rader: list[dict], ar: int) -> dict:
    """Senaste uppgiften under året för varje mått."""
    v = {}
    for r in sorted((r for r in rader if _ar(r["period"]) == ar), key=lambda r: r["period"]):
        for falt in ("nki", "serviceindex", "trygghetsindex", "produktindex", "uthyrningsgrad", "vakansgrad", "tomma_lagenheter", "uppsagningar",
                     "omflyttning", "soktryck", "kotid"):
            if r[falt] is not None:
                v[f"kund_{falt}"] = r[falt]
        if r["hyresbortfall"] is not None:
            v["kund_hyresbortfall"] = r["hyresbortfall"] / 1000
    return v


# --- Sammanställning -----------------------------------------------------------------------------------
# Vilken inläsning varje nyckeltal kommer från (för källraden under fälten)
PREFIX = {"el_": "energi", "varme_": "energi", "vatten_": "energi", "energi_": "energi", "eko_": "ekonomi", "hyra_": "hyra", "tomma_objekt": "hyra",
          "hyresbortfall_objekt": "hyra", "fel_": "drift", "rep_": "drift", "uh_": "underhall", "kund_": "kund"}


def varden(con, fid: int, ar: int, yta, lgh) -> dict:
    """Nyckeltalen för året ur inlästa data. Nycklar som saknas betyder att inget är inläst."""
    v = {}
    v.update(_energi(_rader(con, "energi", fid), ar, yta))
    v.update(_ekonomi(_rader(con, "ekonomi", fid), ar))
    v.update(_hyra(_rader(con, "hyra", fid), ar))
    v.update(_drift(_rader(con, "drift", fid), ar, yta, lgh))
    v.update(_underhall(_rader(con, "underhall", fid), date.today().year))
    v.update(_kund(_rader(con, "kund", fid), ar))
    return v


def kalla_per_nyckel(v: dict, kallor_: dict[str, str]) -> dict[str, str]:
    ut = {}
    for nyckel in v:
        datatyp = next((d for p, d in PREFIX.items() if nyckel.startswith(p)), None)
        if datatyp in kallor_:
            ut[nyckel] = f"{DATATYPER[datatyp]['namn']} ({kallor_[datatyp]})"
    return ut


def tabeller(con, fid: int, ar: int, tal) -> dict:
    """Tabellen under fälten på varje flik. Tom lista rader = inget inläst för året."""
    return {"energi": _energitabell(_rader(con, "energi", fid), ar, tal), "ekonomi": _ekonomitabell(_rader(con, "ekonomi", fid), ar, tal),
            "hyra": _hyrestabell(_rader(con, "hyra", fid), ar, tal), "drift": _drifttabell(_rader(con, "drift", fid), ar, tal),
            "underhall": _underhallstabell(_rader(con, "underhall", fid), tal)}
