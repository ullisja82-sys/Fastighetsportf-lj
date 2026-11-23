"""KOPIA av Styrnings logic/investeringsanalys.py (bara importen är ändrad) – håll den lika.

Investeringsanalys: planerade nyproduktioner, förnyelser och avyttringar.

Datan kommer ur Budgetberäkning 2027 (investeringsanalys_data.py, i tkr). Steg 1 är bolagsövergripande och riktar
sig till avdelningscheferna: vad som byggs och säljs, när, vad det kostar och hur det påverkar resultatkravet.
"""
from datetime import date

from . import investeringsplan_data as data

TYPER = {"nyproduktion": "Nyproduktion", "fornyelse": "Förnyelse", "avyttring": "Avyttring"}
DIAGRAMAR = list(range(2026, 2033))  # planperioden, som i underlagets sammanställning
TIDPLANAR = (2025, 2035)


def _i(ar: int) -> int | None:
    return data.AREN.index(ar) if ar in data.AREN else None


def varde(p: dict, nyckel: str, ar: int) -> float:
    i = _i(ar)
    return p[nyckel][i] if i is not None else 0.0


def summa(projekt: list[dict], nyckel: str, ar: int) -> float:
    return sum(varde(p, nyckel, ar) for p in projekt)


def projekt(typ: str | None = None) -> list[dict]:
    return [p for p in data.PROJEKT if typ is None or p["typ"] == typ]


def lage(p: dict, ar: int) -> str:
    """Projektets läge under året: planerat, pågår, klart (färdigställt/sålt) eller senare."""
    start = date.fromisoformat(p["start"]) if p["start"] else None
    klar = date.fromisoformat(p["klar"]) if p["klar"] else None
    if p["typ"] == "avyttring":
        return "sald" if klar and klar.year < ar else ("saljs" if klar and klar.year == ar else "planerad")
    if klar and klar.year < ar:
        return "klar"
    if klar and klar.year == ar:
        return "fardigstalls"
    if start and start.year <= ar:
        return "pagar"
    return "planerad"


LAGEN = {"planerad": "Planerad", "pagar": "Pågår", "fardigstalls": "Färdigställs", "klar": "Färdigställd",
         "saljs": "Säljs", "sald": "Såld"}


def direktavkastning(p: dict) -> float | None:
    """Driftnetto ett fullt år i förhållande till projektvolymen (för förnyelse: den intäktshöjande delen)."""
    bas = p.get("intaktshojande") if p["typ"] == "fornyelse" and p.get("intaktshojande") else p["volym"]
    return p["driftnetto"] / bas if p.get("driftnetto") and bas else None


def nyckeltal(ar: int) -> dict:
    ny, forn, avy = projekt("nyproduktion"), projekt("fornyelse"), projekt("avyttring")
    alla = ny + forn
    return dict(
        investering=summa(alla, "investering", ar), investering_ny=summa(ny, "investering", ar),
        investering_forn=summa(forn, "investering", ar),
        pagaende=sum(1 for p in alla if lage(p, ar) in ("pagar", "fardigstalls")),
        fardigstalls=[p for p in alla if lage(p, ar) == "fardigstalls"],
        driftnetto=summa(data.PROJEKT, "driftnetto_ar", ar),
        resultatpaverkan=summa(data.PROJEKT, "resultatpaverkan", ar),
        reavinst=sum(varde(p, "reavinst", ar) for p in avy),
        volym_ny=sum(p["volym"] for p in ny), volym_forn=sum(p["volym"] for p in forn),
        volym_avy=sum(p["volym"] for p in avy),
        investering_period=sum(summa(alla, "investering", a) for a in DIAGRAMAR),
    )


def investeringar_per_ar() -> list[tuple[int, float, float]]:
    """[(år, nyproduktion, förnyelse)] i tkr för planperioden."""
    return [(a, summa(projekt("nyproduktion"), "investering", a), summa(projekt("fornyelse"), "investering", a))
            for a in DIAGRAMAR]


def resultatpaverkan_per_ar() -> list[tuple[int, float]]:
    return [(a, summa(data.PROJEKT, "resultatpaverkan", a)) for a in DIAGRAMAR]
