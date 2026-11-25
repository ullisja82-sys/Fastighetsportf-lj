"""Importmotorn: läser en fil till rader, tolkar och validerar dem mot en datatyp, visar vad som är nytt, ändrat,
oförändrat och fel, och skriver först när inläsningen godkänts.

Uppdelning (så att en API-koppling senare kan ersätta filen utan att något annat ändras):
  källadapter   las_fil()            fil -> blad med råa rader
  normalisering tolka_*()            råvärde -> internt värde (svenska decimaltal, perioder, datum, fasta värden)
  validering    validera()           rader i datatypens format -> status per rad; samma regler oavsett källa
  skrivning     importera()          en transaktion; tomma värden skriver aldrig över, inget raderas

Regler: en tom cell ändrar inte ett befintligt värde. En post som saknas i filen tas inte bort. Samma fil en gång till
ger bara oförändrade rader.
"""
import csv
import hashlib
import io
import json
import os
import re
from datetime import date, datetime

from openpyxl import load_workbook

from . import lagring
from .datatyper import DATATYPER, Kol

MAX_RADER = 200_000
SQLTYP = {"tal": "REAL", "andel": "REAL", "heltal": "INTEGER", "janej": "INTEGER"}
STATUSNAMN = {"ny": "Nya", "andrad": "Ändrade", "oforandrad": "Oförändrade", "fel": "Fel"}
MANADER = ["januari", "februari", "mars", "april", "maj", "juni", "juli", "augusti", "september", "oktober", "november", "december"]
_klara = set()


class Importfel(Exception):
    pass


def _nu() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def norm(s) -> str:
    """Jämförelseform för rubriker och fasta värden: gemener, bara bokstäver och siffror."""
    return re.sub(r"[^0-9a-zåäöéü³]", "", str(s if s is not None else "").casefold())


def lagrade(dt: dict) -> list[Kol]:
    return [k for k in dt["kolumner"] if k.lagras and k.typ != "fastighet"]


# --- Databasen ---------------------------------------------------------------------------------------
def anslut():
    con = lagring._anslut()
    if lagring.DB not in _klara:
        con.execute("CREATE TABLE IF NOT EXISTS fastighet (id INTEGER PRIMARY KEY, kod TEXT NOT NULL UNIQUE, namn TEXT, ao TEXT, skapad TEXT)")
        con.execute("CREATE TABLE IF NOT EXISTS externref (id INTEGER PRIMARY KEY, fastighet_id INTEGER NOT NULL REFERENCES fastighet(id), "
                    "system TEXT NOT NULL, externt_id TEXT NOT NULL, UNIQUE(system, externt_id))")
        con.execute("CREATE TABLE IF NOT EXISTS importlogg (id INTEGER PRIMARY KEY, datatyp TEXT NOT NULL, filnamn TEXT, filhash TEXT, uppladdad TEXT, "
                    "av TEXT, status TEXT NOT NULL, mappning TEXT, importerad TEXT, rader INTEGER, nya INTEGER, andrade INTEGER, oforandrade INTEGER, fel INTEGER)")
        con.execute("CREATE TABLE IF NOT EXISTS importrad (import_id INTEGER NOT NULL REFERENCES importlogg(id), radnr INTEGER NOT NULL, "
                    "status TEXT NOT NULL, data TEXT, meddelande TEXT, PRIMARY KEY (import_id, radnr))")
        for nyckel, dt in DATATYPER.items():
            tabell = f"d_{nyckel}"
            con.execute(f"CREATE TABLE IF NOT EXISTS {tabell} (id INTEGER PRIMARY KEY, fastighet_id INTEGER NOT NULL REFERENCES fastighet(id), "
                        "import_id INTEGER, radnr INTEGER, uppdaterad TEXT)")
            finns = {r["name"] for r in con.execute(f"PRAGMA table_info({tabell})")}
            for k in lagrade(dt):
                if k.falt not in finns:
                    con.execute(f"ALTER TABLE {tabell} ADD COLUMN {k.falt} {SQLTYP.get(k.typ, 'TEXT')}")
            con.execute(f"CREATE INDEX IF NOT EXISTS ix_{tabell} ON {tabell} (fastighet_id, {', '.join(dt['nyckel'])})")
        con.commit()
        _klara.add(lagring.DB)
    return con


def synka_fastigheter(poster: list[tuple[str, str, str]]) -> None:
    """Fastigheterna i underlaget (nummer, namn, affärsområde) förs in i fastighetstabellen. Ingen tas bort."""
    with anslut() as con:
        for kod, namn, ao in poster:
            con.execute("INSERT INTO fastighet (kod, namn, ao, skapad) VALUES (?, ?, ?, ?) ON CONFLICT(kod) DO UPDATE SET namn = excluded.namn, ao = excluded.ao",
                        (kod, namn, ao, _nu()))


def fastighets_id(kod: str) -> int | None:
    with anslut() as con:
        rad = con.execute("SELECT id FROM fastighet WHERE kod = ?", (kod,)).fetchone()
    return rad["id"] if rad else None


# --- Källadapter: fil -> råa rader --------------------------------------------------------------------
def las_fil(sokvag: str) -> list[tuple[str, list[list]]]:
    """[(bladnamn, rader)] – ett blad för CSV. Cellerna lämnas som de är (tal, datum, text eller None)."""
    andelse = os.path.splitext(sokvag)[1].lower()
    if andelse == ".csv":
        with open(sokvag, "rb") as f:
            ra = f.read()
        for kodning in ("utf-8-sig", "cp1252"):
            try:
                text = ra.decode(kodning)
                break
            except UnicodeDecodeError:
                continue
        forsta = text[:5000]
        avgr = max(";\t,", key=forsta.count)
        rader = [[c.strip() or None for c in rad] for rad in csv.reader(io.StringIO(text), delimiter=avgr)]
        return [("CSV", rader[:MAX_RADER + 50])]
    if andelse in (".xlsx", ".xlsm"):
        wb = load_workbook(sokvag, read_only=True, data_only=True)
        blad = []
        for ws in wb.worksheets:
            rader = []
            for rad in ws.iter_rows(values_only=True):
                rader.append(list(rad))
                if len(rader) > MAX_RADER + 50:
                    break
            blad.append((ws.title, rader))
        wb.close()
        return blad
    raise Importfel("Filen ska vara .xlsx eller .csv. Äldre Excel-filer (.xls) sparas om som .xlsx först.")


def _rubriktraffar(dt: dict, rad: list) -> dict[int, str]:
    """Kolumnindex -> fält för de celler som känns igen som rubriker. Exakt rubrik går före alternativa namn."""
    exakt = {norm(k.rubrik): k.falt for k in dt["kolumner"]}
    alias = {}
    for k in dt["kolumner"]:
        for a in k.alias:
            alias.setdefault(norm(a), k.falt)
    ut, tagna = {}, set()
    # Rubriken utan parentes: "Förbrukning (Normalårskorrigering)" läses som "Förbrukning"
    rubriker = [norm(re.sub(r"\(.*?\)", "", str(c))) if c is not None else "" for c in rad]
    borjar = lambda r: next((f for n, f in exakt.items() if len(n) >= 5 and r.startswith(n)), None)   # "Enhet förbrukning" -> Enhet
    for sla_upp in (exakt.get, alias.get, borjar):
        for i, r in enumerate(rubriker):
            falt = sla_upp(r) if r and i not in ut else None
            if falt and falt not in tagna:
                ut[i] = falt
                tagna.add(falt)
    return ut


def foresla_mappning(dt: dict, blad: list[tuple[str, list[list]]]) -> dict:
    """Bladet och raden där flest rubriker känns igen. Hittas ingen används första raden med innehåll i första bladet."""
    basta = None
    for namn, rader in blad:
        for i, rad in enumerate(rader[:40]):
            if any(c is not None and not isinstance(c, str) for c in rad):   # en rad med tal eller datum är data, inte rubriker
                continue
            traffar = _rubriktraffar(dt, rad)
            if basta is None or len(traffar) > len(basta[2]):
                basta = (namn, i, traffar)
    if basta is None or not basta[2]:
        namn, rader = blad[0]
        forsta = next((i for i, r in enumerate(rader) if any(c is not None for c in r)), 0)
        basta = (namn, forsta, {})
    return {"blad": basta[0], "rubrikrad": basta[1], "kolumner": {str(i): f for i, f in basta[2].items()}}


# --- Normalisering: råvärde -> internt värde -----------------------------------------------------------
def _tom(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def tolka_tal(v) -> float:
    if isinstance(v, bool):
        raise ValueError("inte ett tal")
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[\s   ]", "", str(v)).replace("−", "-").replace("–", "-")
    s = re.sub(r"(kr|sek|kwh|mwh|m3|m³|st)$", "", s, flags=re.I)
    if "," in s and "." in s:   # 1.234,56
        s = s.replace(".", "")
    s = s.replace(",", ".")
    if not re.fullmatch(r"-?\d+(\.\d+)?", s):
        raise ValueError(f"”{v}” är inte ett tal")
    return float(s)


def tolka_heltal(v) -> int:
    t = tolka_tal(v)
    if t != int(t):
        raise ValueError(f"”{v}” är inte ett heltal")
    return int(t)


def tolka_andel(v) -> float:
    if isinstance(v, str) and "%" in v:
        return tolka_tal(v.replace("%", "")) / 100
    t = tolka_tal(v)
    return t / 100 if abs(t) > 1 else t


def tolka_manad(v) -> int:
    if isinstance(v, (datetime, date)):
        return v.month
    s = str(v).strip().casefold().rstrip(".")
    for i, m in enumerate(MANADER, start=1):
        if len(s) >= 3 and m.startswith(s):
            return i
    try:
        n = tolka_heltal(v)
    except ValueError:
        n = 0
    if not 1 <= n <= 12:
        raise ValueError(f"”{v}” är inte en månad")
    return n


def _ar_ok(ar: int) -> int:
    if not 1950 <= ar <= 2100:
        raise ValueError(f"årtalet {ar} är orimligt")
    return ar


def tolka_period(v) -> str:
    """"2026" (helår), "2026-03" (månad) eller "2026-03-15" (dag)."""
    if isinstance(v, (datetime, date)):
        _ar_ok(v.year)
        return f"{v.year:04d}-{v.month:02d}" if v.day == 1 else f"{v.year:04d}-{v.month:02d}-{v.day:02d}"
    if isinstance(v, float) and v == int(v):
        v = int(v)
    s = str(v).strip()
    if m := re.fullmatch(r"(\d{4})", s):
        return f"{_ar_ok(int(m[1])):04d}"
    if m := re.fullmatch(r"(\d{4})(\d{2})", s) or re.fullmatch(r"(\d{4})\s*[-/. M]\s*(\d{1,2})", s):   # 202601, 2026-01, 2026-1
        if 1 <= int(m[2]) <= 12:
            return f"{_ar_ok(int(m[1])):04d}-{int(m[2]):02d}"
    if m := re.fullmatch(r"(\d{1,2})\s*[-/.]\s*(\d{4})", s):
        if 1 <= int(m[1]) <= 12:
            return f"{_ar_ok(int(m[2])):04d}-{int(m[1]):02d}"
    if m := re.fullmatch(r"([A-Za-zåäöÅÄÖ]{3,9})\.?[\s-]*(\d{4}|\d{2})", s) or re.fullmatch(r"(\d{4})[\s-]*([A-Za-zåäöÅÄÖ]{3,9})\.?", s):
        a, b = (m[1], m[2]) if not m[1].isdigit() else (m[2], m[1])
        ar = int(b) if len(b) == 4 else 2000 + int(b)
        return f"{_ar_ok(ar):04d}-{tolka_manad(a):02d}"
    try:
        return tolka_datum(s)
    except ValueError:
        raise ValueError(f"”{v}” är inte en period (skriv t.ex. 2026, 2026-03 eller mars 2026)")


def tolka_datum(v) -> str:
    if isinstance(v, datetime):
        v = v.date()
    if isinstance(v, date):
        _ar_ok(v.year)
        return v.isoformat()
    s = str(v).strip().split(" ")[0].split("T")[0]
    for monster, ordning in ((r"(\d{4})-(\d{1,2})-(\d{1,2})", (1, 2, 3)), (r"(\d{4})(\d{2})(\d{2})", (1, 2, 3)),
                             (r"(\d{1,2})[./](\d{1,2})[./](\d{4})", (3, 2, 1)), (r"(\d{4})/(\d{1,2})/(\d{1,2})", (1, 2, 3))):
        if m := re.fullmatch(monster, s):
            try:
                d = date(*(int(m[i]) for i in ordning))
            except ValueError:
                break
            _ar_ok(d.year)
            return d.isoformat()
    raise ValueError(f"”{v}” är inte ett datum (skriv t.ex. 2026-03-15)")


def tolka_janej(v) -> int:
    s = norm(v)
    if s in ("ja", "j", "x", "1", "10", "true", "sant", "akut", "yes"):
        return 1
    if s in ("nej", "n", "0", "00", "false", "falskt", "ejakut", "no"):
        return 0
    raise ValueError(f"”{v}” är varken ja eller nej")


def tolka_text(v) -> str:
    if isinstance(v, float) and v == int(v):
        v = int(v)
    if isinstance(v, (datetime, date)):
        return tolka_datum(v)
    return str(v).strip()[:500]


def tolka(k: Kol, v):
    """Internt värde, None för en tom cell. ValueError med en förklaring när värdet inte går att tolka."""
    if _tom(v) or (k.typ in ("tal", "heltal", "andel") and str(v).strip() in ("-", "–", "—")):   # ett streck i en talkolumn = inget värde
        return None
    if k.typ == "val":
        s = norm(v)
        for varde, stavningar in k.val.items():
            if s == norm(varde) or s in (norm(x) for x in stavningar):
                return varde
        raise ValueError(f"okänt värde ”{v}” (tillåtna: {', '.join(x[0] for x in k.val.values())})")
    return {"tal": tolka_tal, "heltal": tolka_heltal, "andel": tolka_andel, "period": tolka_period, "datum": tolka_datum,
            "janej": tolka_janej, "manad": tolka_manad}.get(k.typ, tolka_text)(v)


# --- Validering ---------------------------------------------------------------------------------------
class Fastighetsregister:
    """Slår upp en fastighet på nummer, på numret i början av en text, på namn eller på en sparad koppling."""

    def __init__(self, con, system: str):
        self.rader = {r["id"]: dict(r) for r in con.execute("SELECT * FROM fastighet")}
        self.kod = {r["kod"]: i for i, r in self.rader.items()}
        self.namn = {}
        for i, r in self.rader.items():
            for n in (norm(r["namn"]), norm(f"{r['kod']} {r['namn']}")):
                self.namn[n] = None if n in self.namn and self.namn[n] != i else i
        self.ext = {norm(r["externt_id"]): r["fastighet_id"] for r in con.execute("SELECT * FROM externref WHERE system = ?", (system,))}

    def hitta(self, v) -> int | None:
        s = tolka_text(v)
        if norm(s) in self.ext:
            return self.ext[norm(s)]
        if s in self.kod or s.lstrip("0") in self.kod:
            return self.kod.get(s) or self.kod[s.lstrip("0")]
        if self.namn.get(norm(s)):
            return self.namn[norm(s)]
        m = re.match(r"\s*(\d{3,6})\b", s)   # numret först, t.ex. "0110 Framtiden 6"; inledande nollor spelar ingen roll
        return (self.kod.get(m[1]) or self.kod.get(m[1].lstrip("0"))) if m else None

    def visa(self, fid: int) -> str:
        r = self.rader[fid]
        return f"{r['kod']} {r['namn']}"


def _lika(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))
    return a == b


def _befintlig(con, nyckel: str, dt: dict, fid: int, v: dict):
    villkor = " AND ".join(f"{f} IS ?" for f in dt["nyckel"])
    return con.execute(f"SELECT * FROM d_{nyckel} WHERE fastighet_id = ? AND {villkor}", (fid, *(v.get(f) for f in dt["nyckel"]))).fetchone()


def validera(con, nyckel: str, poster: list[tuple[int, dict]]) -> list[dict]:
    """poster = [(radnummer, {fält: råvärde})] i datatypens format, oavsett om de kommer från en fil eller ett API.
    Ger en post per rad: {radnr, status (ny|andrad|oforandrad|fel), data, meddelande}."""
    dt = DATATYPER[nyckel]
    kol = {k.falt: k for k in dt["kolumner"]}
    register = Fastighetsregister(con, nyckel)
    sedda, ut = {}, []
    for radnr, ra in poster:
        v, fel = {}, []
        for falt, k in kol.items():
            try:
                v[falt] = tolka(k, ra.get(falt)) if k.typ != "fastighet" else ra.get(falt)
            except ValueError as e:
                v[falt] = None
                fel.append(f"{k.rubrik}: {e}")
        # Perioden kan stå i kolumnerna År och Månad
        if "period" in kol and v.get("period") is None and v.get("_ar") is not None:
            try:
                v["period"] = f"{_ar_ok(v['_ar']):04d}" + (f"-{v['_manad']:02d}" if v.get("_manad") else "")
            except ValueError as e:
                fel.append(f"År: {e}")
        fid = None
        if _tom(v.get("fastighet")):
            fel.append("Fastighet saknas")
        else:
            fid = register.hitta(v["fastighet"])
            if fid is None:
                fel.append(f"Okänd fastighet ”{tolka_text(v['fastighet'])}”")
        # Utan mätpunktskolumn får källans namn på noden vara mätpunkt, så att flera noder på samma fastighet
        # ("2040 Hjässan Höghus" och "2040 Andersberg Hjässan 2 högh_701") inte krockar utan summeras
        if "matpunkt" in kol and v.get("matpunkt") is None and fid is not None and tolka_text(v["fastighet"]).lstrip("0") != register.rader[fid]["kod"]:
            v["matpunkt"] = tolka_text(v["fastighet"])
        for k in kol.values():
            if k.kravs and k.typ != "fastighet" and v.get(k.falt) is None and not any(f.startswith(k.rubrik + ":") for f in fel):
                fel.append(f"{k.rubrik} saknas")
        data = {"fastighet_id": fid, "fastighet": register.visa(fid) if fid else tolka_text(v["fastighet"]) if not _tom(v.get("fastighet")) else "",
                **{k.falt: v.get(k.falt) for k in lagrade(dt)}}
        post = {"radnr": radnr, "data": data, "status": "fel", "meddelande": "; ".join(fel)}
        ut.append(post)
        if fel:
            continue
        unik = (fid, *(data.get(f) for f in dt["nyckel"]))
        if unik in sedda:
            post["meddelande"] = f"Dubblett av rad {sedda[unik]} (samma {', '.join(kol[f].rubrik.lower() for f in dt['nyckel'] if data.get(f) is not None) or 'fastighet'})"
            continue
        sedda[unik] = radnr
        finns = _befintlig(con, nyckel, dt, fid, data)
        if finns is None:
            post["status"] = "ny"
            continue
        andrat = [f"{k.rubrik}: {_visa(finns[k.falt])} → {_visa(data[k.falt])}" for k in lagrade(dt)
                  if data.get(k.falt) is not None and not _lika(finns[k.falt], data[k.falt])]
        post["status"] = "andrad" if andrat else "oforandrad"
        post["meddelande"] = "; ".join(andrat)
    return ut


def _visa(v) -> str:
    if v is None:
        return "tomt"
    if isinstance(v, float):
        return f"{v:,.2f}".replace(",", " ").replace(".", ",").removesuffix(",00")
    return str(v)


# --- Inläsningar ---------------------------------------------------------------------------------------
def filmapp() -> str:
    mapp = os.path.join(lagring.DATA_DIR, "importfiler")
    os.makedirs(mapp, exist_ok=True)
    return mapp


def _sokvag(imp: dict) -> str:
    return os.path.join(filmapp(), f"{imp['id']}{os.path.splitext(imp['filnamn'])[1].lower()}")


def inlasning(import_id: int) -> dict | None:
    with anslut() as con:
        rad = con.execute("SELECT * FROM importlogg WHERE id = ?", (import_id,)).fetchone()
    return {**dict(rad), "mappning": json.loads(rad["mappning"] or "{}")} if rad else None


def historik() -> list[dict]:
    with anslut() as con:
        return [dict(r) for r in con.execute("SELECT * FROM importlogg ORDER BY id DESC LIMIT 200")]


def ny_inlasning(nyckel: str, filnamn: str, innehall: bytes, av: str) -> int:
    """Sparar filen, föreslår kolumner och validerar. Inget skrivs till datatabellerna."""
    if nyckel not in DATATYPER:
        raise Importfel("Okänd datatyp")
    if not innehall:
        raise Importfel("Filen är tom")
    filnamn = os.path.basename(filnamn or "fil")[:200]
    with anslut() as con:
        import_id = con.execute("INSERT INTO importlogg (datatyp, filnamn, filhash, uppladdad, av, status) VALUES (?, ?, ?, ?, ?, 'granskas')",
                                (nyckel, filnamn, hashlib.sha256(innehall).hexdigest(), _nu(), av)).lastrowid
    imp = inlasning(import_id)
    with open(_sokvag(imp), "wb") as f:
        f.write(innehall)
    try:
        blad = las_fil(_sokvag(imp))
        if not blad or not any(r for _, r in blad):
            raise Importfel("Filen innehåller inga rader")
        forbered(import_id, foresla_mappning(DATATYPER[nyckel], blad), blad)
    except Exception as e:
        with anslut() as con:
            con.execute("DELETE FROM importlogg WHERE id = ?", (import_id,))
        os.remove(_sokvag(imp))
        raise e if isinstance(e, Importfel) else Importfel(f"Filen gick inte att läsa: {e}")
    return import_id


def filrader(imp: dict, blad=None) -> tuple[list, list[list], list[str]]:
    """(rubriker, datarader, bladnamn) enligt inläsningens val av blad och rubrikrad."""
    blad = blad or las_fil(_sokvag(imp))
    m = imp["mappning"]
    rader = dict(blad).get(m.get("blad"), blad[0][1])
    i = min(m.get("rubrikrad", 0), max(len(rader) - 1, 0))
    return (rader[i] if rader else []), rader[i + 1:], [n for n, _ in blad]


def forbered(import_id: int, mappning: dict | None = None, blad=None) -> None:
    """Validerar filen mot databasens nuvarande innehåll och sparar resultatet per rad (förhandsgranskningen)."""
    imp = inlasning(import_id)
    if imp["status"] != "granskas":
        raise Importfel("Inläsningen är redan avslutad")
    if mappning is not None:
        imp["mappning"] = mappning
    dt = DATATYPER[imp["datatyp"]]
    _, datarader, _ = filrader(imp, blad)
    if len(datarader) > MAX_RADER:
        raise Importfel(f"Filen har fler än {MAX_RADER} rader. Dela upp den.")
    kolumner = {int(i): f for i, f in imp["mappning"]["kolumner"].items() if f}
    start = imp["mappning"]["rubrikrad"] + 2   # radnummer som i Excel
    poster = [(start + n, {f: rad[i] if i < len(rad) else None for i, f in kolumner.items()})
              for n, rad in enumerate(datarader) if any(not _tom(c) for c in rad)]
    with anslut() as con:
        saknas = [k.rubrik for k in dt["kolumner"] if k.kravs and k.falt not in kolumner.values()
                  and not (k.falt == "period" and "_ar" in kolumner.values())]
        resultat = validera(con, imp["datatyp"], poster) if not saknas else []
        con.execute("DELETE FROM importrad WHERE import_id = ?", (import_id,))
        con.executemany("INSERT INTO importrad (import_id, radnr, status, data, meddelande) VALUES (?, ?, ?, ?, ?)",
                        [(import_id, p["radnr"], p["status"], json.dumps(p["data"], ensure_ascii=False), p["meddelande"]) for p in resultat])
        antal = {s: sum(1 for p in resultat if p["status"] == s) for s in STATUSNAMN}
        imp["mappning"]["saknade_kolumner"] = saknas
        con.execute("UPDATE importlogg SET mappning = ?, rader = ?, nya = ?, andrade = ?, oforandrade = ?, fel = ? WHERE id = ?",
                    (json.dumps(imp["mappning"], ensure_ascii=False), len(poster), antal["ny"], antal["andrad"], antal["oforandrad"], antal["fel"], import_id))


def rader(import_id: int, status: str = "", grans: int = 200) -> list[dict]:
    with anslut() as con:
        fraga = "SELECT * FROM importrad WHERE import_id = ?" + (" AND status = ?" if status else "") + " ORDER BY radnr LIMIT ?"
        return [{**dict(r), "data": json.loads(r["data"])} for r in con.execute(fraga, (import_id, *([status] if status else []), grans))]


def okanda_fastigheter(import_id: int) -> list[tuple[str, int]]:
    """Värden i fastighetskolumnen som inte gick att para ihop, med antal rader."""
    antal = {}
    with anslut() as con:
        for r in con.execute("SELECT data FROM importrad WHERE import_id = ? AND status = 'fel' AND meddelande LIKE '%Okänd fastighet%'", (import_id,)):
            namn = json.loads(r["data"])["fastighet"]
            antal[namn] = antal.get(namn, 0) + 1
    return sorted(antal.items(), key=lambda x: -x[1])[:200]


def koppla(import_id: int, kopplingar: dict[str, str]) -> None:
    """Sparar att ett värde i källan (t.ex. energisystemets ID) hör till en fastighet, och validerar om."""
    imp = inlasning(import_id)
    with anslut() as con:
        for externt, kod in kopplingar.items():
            rad = con.execute("SELECT id FROM fastighet WHERE kod = ?", (kod,)).fetchone()
            if rad and externt.strip():
                con.execute("INSERT INTO externref (fastighet_id, system, externt_id) VALUES (?, ?, ?) "
                            "ON CONFLICT(system, externt_id) DO UPDATE SET fastighet_id = excluded.fastighet_id", (rad["id"], imp["datatyp"], externt.strip()))
    forbered(import_id)


def importera(import_id: int) -> dict:
    """Skriver nya och ändrade rader i en transaktion. Rader med fel hoppas över och finns kvar i felrapporten."""
    forbered(import_id)   # databasen kan ha ändrats sedan förhandsgranskningen
    imp = inlasning(import_id)
    if imp["mappning"].get("saknade_kolumner"):
        raise Importfel("Obligatoriska kolumner saknas: " + ", ".join(imp["mappning"]["saknade_kolumner"]))
    nyckel, dt = imp["datatyp"], DATATYPER[imp["datatyp"]]
    falt = [k.falt for k in lagrade(dt)]
    con = anslut()
    try:
        with con:   # allt eller inget
            for r in con.execute("SELECT * FROM importrad WHERE import_id = ? AND status IN ('ny', 'andrad') ORDER BY radnr", (import_id,)).fetchall():
                d = json.loads(r["data"])
                if r["status"] == "ny":
                    con.execute(f"INSERT INTO d_{nyckel} (fastighet_id, import_id, radnr, uppdaterad, {', '.join(falt)}) VALUES (?, ?, ?, ?, {', '.join('?' * len(falt))})",
                                (d["fastighet_id"], import_id, r["radnr"], _nu(), *(d.get(f) for f in falt)))
                else:
                    finns = _befintlig(con, nyckel, dt, d["fastighet_id"], d)
                    satt = [f for f in falt if d.get(f) is not None]   # en tom cell skriver aldrig över
                    con.execute(f"UPDATE d_{nyckel} SET import_id = ?, radnr = ?, uppdaterad = ?, {', '.join(f + ' = ?' for f in satt)} WHERE id = ?",
                                (import_id, r["radnr"], _nu(), *(d[f] for f in satt), finns["id"]))
            con.execute("UPDATE importlogg SET status = 'importerad', importerad = ? WHERE id = ?", (_nu(), import_id))
    finally:
        con.close()
    return inlasning(import_id)


def avbryt(import_id: int) -> None:
    with anslut() as con:
        con.execute("UPDATE importlogg SET status = 'avbruten' WHERE id = ? AND status = 'granskas'", (import_id,))
        con.execute("DELETE FROM importrad WHERE import_id = ? AND (SELECT status FROM importlogg WHERE id = ?) = 'avbruten'", (import_id, import_id))


def tidigare_inlast(imp: dict) -> dict | None:
    """Samma fil (samma innehåll) inläst tidigare för samma datatyp."""
    with anslut() as con:
        rad = con.execute("SELECT * FROM importlogg WHERE filhash = ? AND datatyp = ? AND status = 'importerad' AND id != ? ORDER BY id DESC",
                          (imp["filhash"], imp["datatyp"], imp["id"])).fetchone()
    return dict(rad) if rad else None
