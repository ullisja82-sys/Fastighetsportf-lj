"""Beräkningar: åldersklass, krav, utfall och gap per fastighet samt summering per grupp.

Överskottsgrad = driftsnetto exkl. underhåll / intäkter. Avkastning = driftsnetto exkl. underhåll / värde
(bokfört värde eller marknadsvärde enligt inställningen). Ålder = referensår − byggår + 1, dvs. inklusive referensåret.
"""
from .importera import ODEFINIERAT, Underlag

STATUS = {"gron": "Når kraven", "gul": "Når ett av kraven", "rod": "Når inte kraven", "ingen": "Ej bedömd"}


def klassnamn(klasser: list[dict]) -> list[str]:
    namn, fran = [], None
    for k in klasser:
        if k["max_alder"] is None:
            namn.append(f"Äldre än {fran - 1} år" if fran else "Alla åldrar")
        elif fran is None:
            namn.append(f"Upp till {k['max_alder']} år")
        else:
            namn.append(f"{fran}–{k['max_alder']} år")
        fran = (k["max_alder"] + 1) if k["max_alder"] is not None else fran
    return namn


def klass_for(alder: int | None, klasser: list[dict]) -> int | None:
    if alder is None:
        return None
    for i, k in enumerate(klasser):
        if k["max_alder"] is None or alder <= k["max_alder"]:
            return i
    return len(klasser) - 1


def byggar_intervall(klasser: list[dict], referensar: int) -> list[str]:
    ut, fran_alder = [], 1
    for k in klasser:
        nyast = referensar - fran_alder + 1
        if k["max_alder"] is None:
            ut.append(f"t.o.m. {nyast}")
        else:
            ut.append(f"{referensar - k['max_alder'] + 1}–{nyast}" if fran_alder > 1 else f"fr.o.m. {referensar - k['max_alder'] + 1}")
            fran_alder = k["max_alder"] + 1
    return ut


def berakna(f: dict, inst: dict, just: dict | None) -> dict:
    """En fastighets rad med krav och gap. f kommer från Underlag.fastighet()."""
    r = dict(f)
    klasser, ref = inst["klasser"], inst["referensar"]
    namn = klassnamn(klasser)
    r["byggar_underlag"] = f.get("byggar")
    r["anteckning"] = (just or {}).get("anteckning") or ""
    r["justerat_byggar"] = bool(just and just.get("byggar"))
    if r["justerat_byggar"]:
        r["byggar"] = just["byggar"]
    byggar = r.get("byggar")
    r["alder"] = max(ref - byggar + 1, 0) if byggar else None
    ki = klass_for(r["alder"], klasser)
    r["klass"] = ki
    r["klassnamn"] = namn[ki] if ki is not None else "Byggår saknas"
    r["krav_og"] = klasser[ki]["krav_og"] if ki is not None else None
    r["krav_avk"] = klasser[ki]["krav_avk"] if ki is not None else None

    intakter, dn = r.get("intakter"), r.get("driftsnetto")
    varde = r.get(inst["vardebas"])
    r["varde"] = varde
    r["og"] = dn / intakter if dn is not None and intakter and intakter > 0 else None
    r["avk"] = dn / varde if dn is not None and varde and varde > 0 else None
    r["avk_bv"] = dn / r["bokfort"] if dn is not None and r.get("bokfort") and r["bokfort"] > 0 else None
    r["avk_mv"] = dn / r["marknad"] if dn is not None and r.get("marknad") and r["marknad"] > 0 else None
    yta = r.get("boa_loa") or r.get("toa")
    r["yta"] = yta
    r["dn_kvm"] = dn * 1000 / yta if dn is not None and yta else None

    r["gap_og"] = r["og"] - r["krav_og"] if r["og"] is not None and r["krav_og"] is not None else None
    r["gap_avk"] = r["avk"] - r["krav_avk"] if r["avk"] is not None and r["krav_avk"] is not None else None
    # Driftsnettot som kraven motsvarar (tkr)
    r["dn_krav_og"] = r["krav_og"] * intakter if r["gap_og"] is not None else None
    r["dn_krav_avk"] = r["krav_avk"] * varde if r["gap_avk"] is not None else None
    kravbelopp = [v for v in (r["dn_krav_og"], r["dn_krav_avk"]) if v is not None]
    r["dn_krav"] = max(kravbelopp) if kravbelopp else None
    r["dn_mot_krav"] = dn - r["dn_krav"] if kravbelopp and dn is not None else None

    gap = [g for g in (r["gap_og"], r["gap_avk"]) if g is not None]
    if not gap:
        r["status"] = "ingen"
    elif all(g >= 0 for g in gap):
        r["status"] = "gron"
    elif all(g < 0 for g in gap):
        r["status"] = "rod"
    else:
        r["status"] = "gul"
    # En fastighet som bara kan prövas mot ett av kraven är inte fullt bedömd
    r["delvis_bedomd"] = len(gap) == 1

    flaggor = []
    if r.get("samlingsrad"):
        flaggor.append("Samlingsrad i underlaget")
    elif not byggar:
        flaggor.append("Saknar byggår")
    elif byggar < 1850 or byggar > ref:
        flaggor.append("Kontrollera byggår")
    if not r.get("bokfort"):
        flaggor.append("Saknar bokfört värde")
    if not r.get("marknad"):
        flaggor.append("Saknar marknadsvärde")
    if intakter is None or intakter <= 0:
        flaggor.append("Saknar intäkter")
    if r.get("saknas_i_aret"):
        flaggor.append("Finns inte i årets underlag")
    r["flaggor"] = flaggor
    return r


def rader(u: Underlag, ar: int, inst: dict, just: dict) -> list[dict]:
    ut = []
    for kod in u.koder():
        f = u.fastighet(kod, ar)
        if f:
            ut.append(berakna(f, inst, just.get(kod)))
    return ut


def _s(rr, nyckel):
    return sum(r.get(nyckel) or 0 for r in rr)


def summera(rr: list[dict]) -> dict:
    """Summor och vägda nyckeltal för en grupp fastigheter.

    Överskottsgrad och avkastning räknas på fastigheter där måttet går att beräkna (intäkter respektive värde finns).
    Kraven vägs med intäkter respektive värde, och jämförs med utfallet för samma fastigheter.
    """
    med_og = [r for r in rr if r["og"] is not None]
    med_avk = [r for r in rr if r["avk"] is not None]
    krav_og = [r for r in rr if r["gap_og"] is not None]
    krav_avk = [r for r in rr if r["gap_avk"] is not None]
    s = {
        "antal": len(rr),
        "intakter": _s(rr, "intakter"), "driftsnetto": _s(rr, "driftsnetto"), "resultat": _s(rr, "resultat"),
        "bokfort": _s(rr, "bokfort"), "marknad": _s(rr, "marknad"), "yta": _s(rr, "yta"), "lgh": _s(rr, "lgh"),
        "og": _s(med_og, "driftsnetto") / _s(med_og, "intakter") if _s(med_og, "intakter") else None,
        "avk": _s(med_avk, "driftsnetto") / _s(med_avk, "varde") if _s(med_avk, "varde") else None,
        "krav_og": _s(krav_og, "dn_krav_og") / _s(krav_og, "intakter") if _s(krav_og, "intakter") else None,
        "krav_avk": _s(krav_avk, "dn_krav_avk") / _s(krav_avk, "varde") if _s(krav_avk, "varde") else None,
        "status": {k: sum(1 for r in rr if r["status"] == k) for k in STATUS},
        "dn_mot_krav": _s(rr, "dn_mot_krav"),
        "underskott": sum(r["dn_mot_krav"] for r in rr if (r.get("dn_mot_krav") or 0) < 0),
    }
    s["avk_bv"] = (lambda m: _s(m, "driftsnetto") / _s(m, "bokfort") if _s(m, "bokfort") else None)([r for r in rr if r["avk_bv"] is not None])
    s["avk_mv"] = (lambda m: _s(m, "driftsnetto") / _s(m, "marknad") if _s(m, "marknad") else None)([r for r in rr if r["avk_mv"] is not None])
    og_k = _s(krav_og, "driftsnetto") / _s(krav_og, "intakter") if _s(krav_og, "intakter") else None
    avk_k = _s(krav_avk, "driftsnetto") / _s(krav_avk, "varde") if _s(krav_avk, "varde") else None
    # Utfallet för de fastigheter som kan prövas mot krav – samma underlag som kravet och gapet
    s["og_provad"], s["avk_provad"] = og_k, avk_k
    s["gap_og"] = og_k - s["krav_og"] if og_k is not None and s["krav_og"] is not None else None
    s["gap_avk"] = avk_k - s["krav_avk"] if avk_k is not None and s["krav_avk"] is not None else None
    return s


def ao_ordning(rr: list[dict]) -> list[str]:
    aos = list(dict.fromkeys(r["ao"] for r in rr))
    return [a for a in aos if a != ODEFINIERAT] + [a for a in aos if a == ODEFINIERAT]
