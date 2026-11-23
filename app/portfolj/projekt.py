"""Byggprojekt per fastighet ur projektlistan (Excel-export) i mappen Projekt.

Bladet har en rad per projekt: Projektnummer, Projektnamn, Status, K-Ställe (fastighetens nummer), Förväntat slut,
Projektledare och belopp. Senaste filen (sist i bokstavsordning) gäller. Avslutade och avbrutna projekt visas inte.
"""
import os
import re
from datetime import date, datetime

from openpyxl import load_workbook

# Status i listan -> läge i appen
LAGEN = {"Pågående": "pagar", "Klar för avrop": "planerat", "Fastställd plan": "planerat", "Planerad plan": "planerat"}
LAGESNAMN = {"pagar": "Projekt pågår", "planerat": "Projekt planerat"}
BELOPP = ("Total Capex K3", "Total Capex Inv", "Total Opex")
# Kostnadsslag i listan: nyckel -> (kolumnprefix, namn)
SLAG = {"inv": ("Capex Inv", "Capex investering"), "k3": ("Capex K3", "Capex K3"), "opex": ("Opex", "Opex")}
STATUSORDNING = ["Pågående", "Klar för avrop", "Fastställd plan", "Planerad plan", "Avslutad", "Avbruten"]


class Projekt(dict):
    """kod -> [projekt], pågående först. ovriga = projekt utan fastighet (t.ex. nyproduktion med K-Ställe 0)."""

    def __init__(self):
        super().__init__()
        self.filnamn, self.fel, self.ovriga, self.antal = "", "", [], 0
        self.alla, self.aren = [], []   # alla projekt i listan (även avslutade och avbrutna) och åren med belopp

    def lage(self, kod: str) -> str:
        """"pagar" om något projekt pågår, annars "planerat" om något är planerat, annars tomt."""
        lagen = {p["lage"] for p in self.get(kod, [])}
        return "pagar" if "pagar" in lagen else "planerat" if lagen else ""


def las_projekt(mapp: str, koder: set[str]) -> Projekt:
    ut = Projekt()
    filer = sorted(f for f in os.listdir(mapp) if f.lower().endswith(".xlsx") and not f.startswith("~$")) if os.path.isdir(mapp) else []
    if not filer:
        return ut
    ut.filnamn = filer[-1]
    try:
        rader = load_workbook(os.path.join(mapp, ut.filnamn), read_only=True, data_only=True).worksheets[0].iter_rows(values_only=True)
        rubriker = [str(c or "").strip() for c in next(rader)]
        saknas = [r for r in ("Projektnamn", "Status", "K-Ställe") if r not in rubriker]
        if saknas:
            raise ValueError("Kolumner saknas: " + ", ".join(saknas))
        ut.aren = sorted({int(m.group(1)) for r in rubriker if (m := re.fullmatch(r"(?:Opex|Capex K3|Capex Inv) (20\d\d)", r))})
        tal = lambda v: float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0  # noqa: E731
        for rad in rader:
            d = dict(zip(rubriker, rad))
            status = str(d.get("Status") or "").strip()
            if not d.get("Projektnamn"):
                continue
            lage = LAGEN.get(status)
            kstalle = d.get("K-Ställe")
            kod = str(int(kstalle)) if isinstance(kstalle, (int, float)) else str(kstalle or "").strip()
            slut = d.get("Förväntat slut")
            belopp = [d.get(b) for b in BELOPP if isinstance(d.get(b), (int, float))]
            p = {"nummer": d.get("Projektnummer") or "", "namn": str(d["Projektnamn"]).strip(), "status": status, "lage": lage or "",
                 "slut": slut.date() if isinstance(slut, datetime) else slut if isinstance(slut, date) else None,
                 "projektledare": d.get("Projektledare") or "", "belopp": sum(belopp) if belopp else None,
                 "kod": kod if kod in koder else "", "paraply": d.get("Paraplyprojekt") or "", "godkannande": d.get("Godkännade status") or "",
                 "k3": tal(d.get("Total Capex K3")), "inv": tal(d.get("Total Capex Inv")), "opex": tal(d.get("Total Opex")),
                 "per_ar": {a: {s: tal(d.get(f"{prefix} {a}")) for s, (prefix, _) in SLAG.items()} for a in ut.aren}}
            ut.alla.append(p)
            if not lage:
                continue
            (ut.setdefault(kod, []) if kod in koder else ut.ovriga).append(p)
            ut.antal += 1
        for lista in list(ut.values()) + [ut.ovriga]:
            lista.sort(key=lambda p: (p["lage"] != "pagar", p["slut"] or date.max, p["namn"]))
    except Exception as e:  # en trasig fil ska inte stoppa appen
        ut.clear()
        ut.alla, ut.ovriga, ut.antal = [], [], 0
        ut.fel = str(e)
    return ut


def sammanstall(p: Projekt, ao_for_kod: dict[str, str], idag: date) -> dict:
    """Underlag till sidan Projektportfölj. Belopp i kr som i listan. Aktiva = pågående och planerade projekt."""
    aktiva = [x for x in p.alla if x["lage"]]
    for x in p.alla:
        x["ao"] = ao_for_kod.get(x["kod"], "") or "Utan fastighet"
        x["passerat"] = bool(x["lage"] == "pagar" and x["slut"] and x["slut"] < idag)

    def summa(lista):
        return {"antal": len(lista), "pagar": sum(1 for x in lista if x["lage"] == "pagar"), "planerat": sum(1 for x in lista if x["lage"] == "planerat"),
                **{s: sum(x[s] for x in lista) for s in SLAG}, "belopp": sum(x["k3"] + x["inv"] + x["opex"] for x in lista),
                "passerat": sum(1 for x in lista if x["passerat"])}

    def grupper(nyckel, sist):
        namn = sorted({x[nyckel] or sist for x in aktiva}, key=lambda n: (n == sist, n))
        return [(n, summa([x for x in aktiva if (x[nyckel] or sist) == n])) for n in namn]

    per_ar = [(a, {s: sum(x["per_ar"][a][s] for x in aktiva) for s in SLAG}) for a in p.aren]
    return {
        "total": summa(aktiva), "per_ar": [(a, v) for a, v in per_ar],
        "statusar": [(s, [x for x in p.alla if x["status"] == s]) for s in STATUSORDNING if any(x["status"] == s for x in p.alla)],
        "per_ao": grupper("ao", "Utan fastighet"), "per_ledare": sorted(grupper("projektledare", "Ingen projektledare angiven"), key=lambda g: -g[1]["belopp"]),
        "passerade": sorted([x for x in aktiva if x["passerat"]], key=lambda x: x["slut"]),
        "storsta": sorted(aktiva, key=lambda x: -(x["k3"] + x["inv"] + x["opex"]))[:10],
        "alla": sorted(p.alla, key=lambda x: (STATUSORDNING.index(x["status"]) if x["status"] in STATUSORDNING else 9, x["slut"] or date.max, x["namn"])),
        "ofordelat": sum(x["k3"] + x["inv"] + x["opex"] for x in aktiva) - sum(sum(v.values()) for _, v in per_ar),
    }
