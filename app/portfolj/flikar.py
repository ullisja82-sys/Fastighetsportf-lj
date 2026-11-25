"""Flikarna på fastigheten: vilka fält varje flik visar.

Här ändras rubriker, grupper och fält. Varje fält är (namn, enhet, nyckel). Nyckeln pekar på ett värde som appen
har: ur Fastighetsanalysen (t.ex. "intakter") eller ur det som lästs in under Datainläsning (räknas fram i omraden.py,
t.ex. "el_kwh"). None betyder att det inte finns någon datakälla alls. Ett fält utan värde visas som ett streck med
texten "Data saknas", aldrig som 0.

Enheten styr formatet: "%" = andel (0,035 visas som 3,5 %), "tkr", "kr/kvm", "kWh", "m³" m.fl. = heltal,
"index" = en decimal. Små tal som inte är heltal visas med en decimal.
"""

FLIKAR = [
    ("oversikt", "Översikt"),
    ("ekonomi", "Ekonomi"),
    ("hyra", "Hyra"),
    ("energi", "Energi & media"),
    ("drift", "Drift"),
    ("underhall", "Underhåll & investering"),
    ("kund", "Kund & uthyrning"),
]
FASTIGHETSANALYS = "Fastighetsanalys"
# Var värdena kommer ifrån (visas under varje grupp som har någon uppgift)
KALLA = {
    "intakter": FASTIGHETSANALYS, "driftsnetto": FASTIGHETSANALYS, "og": FASTIGHETSANALYS, "dn_kvm": FASTIGHETSANALYS,
    "avskrivningar": FASTIGHETSANALYS, "resultat": FASTIGHETSANALYS, "driftkostnad_kvm": FASTIGHETSANALYS,
    "hyra_kvm": FASTIGHETSANALYS, "vakansgrad": FASTIGHETSANALYS,
    "antal_projekt": "Projektlistan", "serviceindex": "AktivBo", "produktindex": "AktivBo",
}

# Översikten: några få nyckeltal per område, med länk till fliken
OVERSIKT = [
    ("ekonomi", [("Intäkter", "tkr", "intakter"), ("Driftsnetto exkl. underhåll", "tkr", "driftsnetto"), ("Överskottsgrad", "%", "og")]),
    ("hyra", [("Hyra per kvm", "kr/kvm", "hyra_kvm"), ("Faktisk hyra", "tkr", "hyra_faktisk"), ("Vakansgrad", "%", "vakansgrad")]),
    ("energi", [("El och värme", "kWh/kvm", "energi_kwh_kvm"), ("Vatten", "m³/kvm", "vatten_m3_kvm")]),
    ("drift", [("Felanmälningar", "st", "fel_antal"), ("Reparationskostnad", "kr/kvm", "rep_kostnad_kvm")]),
    ("underhall", [("Underhållsbehov inom 5 år", "tkr", "uh_5"), ("Pågående och planerade projekt", "st", "antal_projekt")]),
    ("kund", [("Serviceindex", "index", "serviceindex"), ("Produktindex", "index", "produktindex"), ("NKI", "index", "kund_nki"), ("Omflyttning", "%", "kund_omflyttning")]),
]

# Flikarna: grupper av fält
FALT = {
    "ekonomi": [
        ("Intäkter", [("Intäkter totalt", "tkr", "intakter"), ("Hyresintäkter", "tkr", "eko_hyresintakter"), ("Övriga intäkter", "tkr", "eko_ovriga_intakter")]),
        ("Kostnader", [("Driftkostnader", "tkr", "eko_driftkostnader"), ("Driftkostnader per kvm", "kr/kvm", "driftkostnad_kvm"), ("Reparationer", "tkr", "eko_reparationer"),
                       ("Underhåll", "tkr", "eko_underhall"), ("El", "tkr", "eko_el"), ("Värme", "tkr", "eko_varme"), ("Vatten", "tkr", "eko_vatten"), ("Avfall", "tkr", "eko_avfall"),
                       ("Fastighetsskatt/avgift", "tkr", "eko_fastighetsskatt"), ("Övriga kostnader", "tkr", "eko_ovriga_kostnader")]),
        ("Resultat", [("Driftsnetto exkl. underhåll", "tkr", "driftsnetto"), ("Överskottsgrad", "%", "og"), ("Driftsnetto per kvm", "kr/kvm", "dn_kvm"),
                      ("Avskrivningar", "tkr", "avskrivningar"), ("Resultat", "tkr", "resultat")]),
        ("Budget och prognos", [("Budget driftsnetto", "tkr", "eko_budget_dn"), ("Prognos driftsnetto", "tkr", "eko_prognos_dn"), ("Budgetavvikelse", "tkr", "eko_budgetavvikelse")]),
    ],
    "hyra": [
        ("Hyresnivå", [("Hyresintäkter per kvm", "kr/kvm", "hyra_kvm"), ("Hyra per kvm enligt hyreslistan", "kr/kvm", "hyra_kvm_objekt"), ("Bashyra", "tkr", "hyra_bas"),
                       ("Tillägg", "tkr", "hyra_tillagg"), ("Rabatter", "tkr", "hyra_rabatt"), ("Faktisk hyra", "tkr", "hyra_faktisk")]),
        ("Utveckling och jämförelse", [("Hyresutveckling", "%", None), ("Spridning inom fastigheten", "kr/kvm", "hyra_spridning"),
                                       ("Mot likvärdiga lägenheter", "%", None), ("Mot andra fastigheter", "%", None)]),
        ("Vakans och bortfall", [("Vakansgrad", "%", "vakansgrad"), ("Vakanta objekt", "st", "tomma_objekt"), ("Hyra för vakanta objekt", "tkr", "hyresbortfall_objekt")]),
    ],
    "energi": [
        ("El", [("Förbrukning", "kWh", "el_kwh"), ("Per kvm", "kWh/kvm", "el_kwh_kvm"), ("Kostnad", "tkr", "el_kostnad")]),
        ("Värme", [("Förbrukning", "kWh", "varme_kwh"), ("Per kvm", "kWh/kvm", "varme_kwh_kvm"), ("Kostnad", "tkr", "varme_kostnad")]),
        ("Vatten", [("Förbrukning", "m³", "vatten_m3"), ("Per kvm", "m³/kvm", "vatten_m3_kvm"), ("Kostnad", "tkr", "vatten_kostnad")]),
        ("Kostnadsförändring mot samma perioder året före", [("Förbrukningseffekt", "tkr", "energi_forbrukningseffekt"), ("Priseffekt", "tkr", "energi_priseffekt")]),
    ],
    "drift": [
        ("Felanmälningar", [("Antal", "st", "fel_antal"), ("Per 1 000 kvm", "st", "fel_per_1000kvm"), ("Per lägenhet", "st", "fel_per_lgh"), ("Akuta", "st", "fel_akuta"),
                            ("Återkommande", "st", "fel_aterkommande"), ("Ledtid", "dagar", "fel_ledtid")]),
        ("Reparationer", [("Reparationskostnad", "tkr", "rep_kostnad"), ("Per kvm", "kr/kvm", "rep_kostnad_kvm")]),
    ],
    "underhall": [
        ("Planerat underhåll", [("Nästa år", "tkr", "uh_1"), ("Inom 3 år", "tkr", "uh_3"), ("Inom 5 år", "tkr", "uh_5"), ("Inom 10 år", "tkr", "uh_10")]),
        ("Fördelning, kommande 10 år", [("Normalt planerat underhåll", "tkr", "uh_typ_planerat"), ("Eftersatt underhåll", "tkr", "uh_typ_eftersatt"), ("Investering", "tkr", "uh_typ_investering"),
                        ("Förnyelse", "tkr", "uh_typ_fornyelse"), ("Energieffektivisering", "tkr", "uh_typ_energi")]),
    ],
    "kund": [
        ("Kundundersökning", [("Serviceindex", "index", "serviceindex"), ("Produktindex", "index", "produktindex"), ("NKI", "index", "kund_nki"),
                              ("Trygghetsindex", "index", "kund_trygghetsindex")]),
        ("Uthyrning", [("Uthyrningsgrad", "%", "kund_uthyrningsgrad"), ("Vakansgrad", "%", "vakansgrad"), ("Tomma lägenheter", "st", "kund_tomma_lagenheter"), ("Uppsägningar", "st", "kund_uppsagningar"),
                       ("Omflyttning", "%", "kund_omflyttning"), ("Söktryck", "st", "kund_soktryck"), ("Kötid", "år", "kund_kotid"), ("Hyresbortfall", "tkr", "kund_hyresbortfall")]),
    ],
}

# Tabellen under fälten: rubrik och kolumner som visas tomma tills underlaget är inläst (innehållet kommer ur omraden.py)
TABELLER = {
    "ekonomi": ("Per konto och kategori", ["Konto", "Kategori", "Utfall", "Budget", "Prognos", "Utfall − budget"]),
    "hyra": ("Lägenheter och lokaler", ["Objekt", "Typ", "Area", "Rum", "Hyra", "Tillägg", "Rabatt", "Hyra per kvm", "Kontrakt"]),
    "energi": ("Mätpunkter", ["Mätpunkt", "Media", "Byggnad", "Period", "Förbrukning", "Enhet", "Kostnad", "Pris/taxa", "Källa"]),
    "drift": ("Vanligaste felkategorier", ["Kategori", "Antal", "Andel", "Akuta", "Kostnad", "Ledtid"]),
    "underhall": ("Åtgärder per komponent", ["Åtgärd", "Komponent", "Typ", "Planerat år", "Planerad kostnad", "Genomfört år", "Faktisk kostnad", "Status"]),
}


def _falt(falt: list[tuple], nu: dict, fore: dict | None) -> list[dict]:
    return [{"namn": namn, "enhet": enhet, "ansluten": nyckel is not None, "varde": nu.get(nyckel) if nyckel else None,
             "fore": fore.get(nyckel) if nyckel and fore else None, "kalla": nu.get("_kallor", {}).get(nyckel) or KALLA.get(nyckel)} for namn, enhet, nyckel in falt]


def _grupp(rubrik: str, falt: list[tuple], nu: dict, fore: dict | None) -> dict:
    ff = _falt(falt, nu, fore)
    return {"rubrik": rubrik, "falt": ff, "kallor": list(dict.fromkeys(f["kalla"] for f in ff if f["varde"] is not None and f["kalla"])),
            "med_varde": sum(1 for f in ff if f["varde"] is not None), "anslutna": sum(1 for f in ff if f["ansluten"])}


def sammanstall(nu: dict, fore: dict | None) -> dict:
    """Fälten per flik med årets värde och föregående års (None där uppgiften saknas)."""
    namn = dict(FLIKAR)
    return {
        "oversikt": [{**_grupp(namn[flik], falt, nu, fore), "flik": flik} for flik, falt in OVERSIKT],
        **{flik: [_grupp(rubrik, falt, nu, fore) for rubrik, falt in grupper] for flik, grupper in FALT.items()},
    }
