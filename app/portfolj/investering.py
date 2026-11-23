"""Investeringsplanen (nyproduktion, förnyelse, avyttring) kopplad till fastigheterna och kartan.

Projekten kommer från Styrnings investeringsanalys (investeringsplan_data.py, ur Budgetberäkning 2027). Planen anger
projekten med namn ("Hjässan etapp 1"), så kopplingen till fastighetsnummer och platsen på kartan är antaganden som
står här nedan och kan ändras under Underlag och datakvalitet (sparas då i appens databas).
"""
from . import investeringsplan_data as data

TYPNAMN = {"nyproduktion": "Nyproduktion", "fornyelse": "Förnyelse", "avyttring": "Avyttring"}
# Projektkod -> fastighetsnummer i portföljen (antagande utifrån namnet)
KOPPLING = {
    "U1": ["1500"],                                   # Katten -> Katten 17
    "U2": ["110", "120", "130", "140", "150"],        # Framtiden -> Framtiden 6, 7, 8, 9, 15
    "U3": ["7500", "7300", "7310", "7320", "7330"],   # G:a Bäckagård -> Bäckagård 1:154, 1:156–1:159
    "U4": ["1000"],                                   # Kv Jungfrun -> Jungfrun 1
    "U6": ["2040", "2050", "2060", "2070"],           # Hjässan etapp 1 -> Hjässan 2 (höghus, låghus, terrasshus)
    "U8": ["9120", "9100"],                           # Valhalla 2o5 -> Vallhalla 2 och 5
    "A1": ["9130"],                                   # Valhalla 3 -> Vallhalla 3
    "N3": ["4600"],                                   # Bulten -> Bulten 4
    "N5": ["1900"],                                   # Mickedala -> Mickedala Eliten 8
    "N6": ["7000"],                                   # Soldalen -> Bäckagård Eketånga 6:298 Soldalen
}
# Projektkod -> plats att slå upp på kartan när projektet inte ligger på en fastighet med känt läge
PLATS = {
    "N1-1": "Kullagård", "N1-2": "Kullagård", "N1-3": "Kullagård", "N2-1": "Högskolan i Halmstad", "N2-2": "Högskolan i Halmstad",
    "N3": "Bulten", "N4": "Knebilstorp", "N7": "Trönninge", "N8": "Bäckagård", "N9": "Koltrasten",
}


def _ar(datum: str | None) -> int | None:
    return int(datum[:4]) if datum else None


def projekt(koder_i_portfoljen: set[str], sparat: dict, lagen: dict) -> list[dict]:
    """Planens projekt med koppling och läge. sparat: lagring.invplatser(); lagen: lagring.platser()."""
    ut = []
    for p in data.PROJEKT:
        egen = sparat.get(p["kod"], {})
        koder = egen["koder"].split(",") if egen.get("koder") is not None else KOPPLING.get(p["kod"], [])
        koder = [k for k in (k.strip() for k in koder) if k in koder_i_portfoljen]
        start, klar = _ar(p["start"]), _ar(p["klar"])
        punkter = [(lagen[k]["lat"], lagen[k]["lon"]) for k in koder if lagen.get(k, {}).get("lat") is not None]
        if egen.get("lat") is not None:   # egen eller uppslagen plats för projektet går före fastigheternas läge för nyproduktion
            plats = (egen["lat"], egen["lon"])
        else:
            plats = punkter[0] if punkter else None
        ut.append({
            "kod": p["kod"], "namn": p["namn"], "typ": p["typ"], "typnamn": TYPNAMN[p["typ"]], "start": start, "klar": klar,
            "period": f"{start}–{klar}" if start and klar and start != klar else str(klar or start or ""),
            "volym": p["volym"], "hyra": p["hyra"], "driftnetto": p["driftnetto"], "koder": koder,
            "plats": plats, "punkter": punkter, "sokord": egen.get("adress") or PLATS.get(p["kod"], ""), "egen_adress": bool(egen.get("egen")),
        })
    return ut


def per_fastighet(alla: list[dict]) -> dict[str, list[dict]]:
    ut = {}
    for p in alla:
        for k in p["koder"]:
            ut.setdefault(k, []).append(p)
    return ut
