"""Det som registreras i appen: kravnivåer (inställningar) och justeringar per fastighet. SQLite i DATA_DIR."""
import json
import os
import sqlite3
from datetime import datetime

DATA_DIR = os.environ.get("DATA_DIR", "./data")
DB = os.path.join(DATA_DIR, "portfolj.db")

# Beslutade krav: ålder räknas inklusive referensåret (byggt 2013 = 14 år 2026).
STANDARD = {
    "referensar": 2026,
    "vardebas": "bokfort",  # avkastningskravet räknas på bokfört värde ("bokfort") eller marknadsvärde ("marknad")
    "klasser": [
        {"max_alder": 14, "krav_avk": 0.03, "krav_og": 0.70},
        {"max_alder": 30, "krav_avk": 0.04, "krav_og": 0.60},
        {"max_alder": 50, "krav_avk": 0.06, "krav_og": 0.60},
        {"max_alder": None, "krav_avk": 0.10, "krav_og": 0.55},
    ],
}


def _anslut():
    os.makedirs(DATA_DIR, exist_ok=True)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE IF NOT EXISTS installning (nyckel TEXT PRIMARY KEY, varde TEXT NOT NULL)")
    con.execute("CREATE TABLE IF NOT EXISTS justering (kod TEXT PRIMARY KEY, byggar INTEGER, anteckning TEXT, andrad TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS kundkoppling (enhet TEXT PRIMARY KEY, kod TEXT NOT NULL)")
    con.execute("CREATE TABLE IF NOT EXISTS plats (kod TEXT PRIMARY KEY, adress TEXT, egen INTEGER NOT NULL DEFAULT 0, lat REAL, lon REAL)")
    con.execute("CREATE TABLE IF NOT EXISTS invplats (kod TEXT PRIMARY KEY, koder TEXT, adress TEXT, egen INTEGER NOT NULL DEFAULT 0, lat REAL, lon REAL)")
    con.execute("CREATE TABLE IF NOT EXISTS anvandare (oid TEXT PRIMARY KEY, namn TEXT, epost TEXT, roll TEXT NOT NULL, "
                "forst_inloggad TEXT, senast_inloggad TEXT, roll_andrad TEXT)")
    return con


def installningar() -> dict:
    with _anslut() as con:
        rad = con.execute("SELECT varde FROM installning WHERE nyckel = 'krav'").fetchone()
    return json.loads(rad["varde"]) if rad else json.loads(json.dumps(STANDARD))


def spara_installningar(inst: dict) -> None:
    with _anslut() as con:
        con.execute("INSERT INTO installning (nyckel, varde) VALUES ('krav', ?) ON CONFLICT(nyckel) DO UPDATE SET varde = excluded.varde",
                    (json.dumps(inst),))


def aterstall_installningar() -> None:
    with _anslut() as con:
        con.execute("DELETE FROM installning WHERE nyckel = 'krav'")


def flikar_for_alla() -> bool:
    """Flikarna på fastigheten visas bara för administratörer tills en administratör släpper dem till alla."""
    with _anslut() as con:
        rad = con.execute("SELECT varde FROM installning WHERE nyckel = 'flikar'").fetchone()
    return bool(rad) and rad["varde"] == "alla"


def satt_flikar_for_alla(alla: bool) -> None:
    with _anslut() as con:
        con.execute("INSERT INTO installning (nyckel, varde) VALUES ('flikar', ?) ON CONFLICT(nyckel) DO UPDATE SET varde = excluded.varde",
                    ("alla" if alla else "admin",))


def justeringar() -> dict:
    with _anslut() as con:
        return {r["kod"]: dict(r) for r in con.execute("SELECT * FROM justering")}


def spara_justering(kod: str, byggar: int | None, anteckning: str) -> None:
    with _anslut() as con:
        if byggar is None and not anteckning:
            con.execute("DELETE FROM justering WHERE kod = ?", (kod,))
        else:
            con.execute("INSERT INTO justering (kod, byggar, anteckning, andrad) VALUES (?, ?, ?, ?) "
                        "ON CONFLICT(kod) DO UPDATE SET byggar = excluded.byggar, anteckning = excluded.anteckning, andrad = excluded.andrad",
                        (kod, byggar, anteckning, datetime.now().strftime("%Y-%m-%d %H:%M")))


def kundkopplingar() -> dict:
    """AktivBo-enheter som kopplats till en fastighet för hand: enhetens namn -> fastighetsnummer."""
    with _anslut() as con:
        return {r["enhet"]: r["kod"] for r in con.execute("SELECT * FROM kundkoppling")}


def spara_kundkoppling(enhet: str, kod: str) -> None:
    with _anslut() as con:
        if not kod:
            con.execute("DELETE FROM kundkoppling WHERE enhet = ?", (enhet,))
        else:
            con.execute("INSERT INTO kundkoppling (enhet, kod) VALUES (?, ?) ON CONFLICT(enhet) DO UPDATE SET kod = excluded.kod", (enhet, kod))


def platser() -> dict:
    """Fastigheternas läge på kartan: kod -> {adress, egen, lat, lon}. lat/lon är None när adressen inte hittades."""
    with _anslut() as con:
        return {r["kod"]: dict(r) for r in con.execute("SELECT * FROM plats")}


def spara_plats(kod: str, adress: str, lage: tuple[float, float] | None, egen: bool) -> None:
    with _anslut() as con:
        con.execute("INSERT INTO plats (kod, adress, egen, lat, lon) VALUES (?, ?, ?, ?, ?) ON CONFLICT(kod) DO UPDATE SET "
                    "adress = excluded.adress, egen = excluded.egen, lat = excluded.lat, lon = excluded.lon",
                    (kod, adress, int(egen), lage[0] if lage else None, lage[1] if lage else None))


def ta_bort_plats(kod: str) -> None:
    with _anslut() as con:
        con.execute("DELETE FROM plats WHERE kod = ?", (kod,))


def invplatser() -> dict:
    """Investeringsplanens projekt: kod -> {koder (kommaseparerade fastighetsnummer, None = appens antagande), adress, egen, lat, lon}."""
    with _anslut() as con:
        return {r["kod"]: dict(r) for r in con.execute("SELECT * FROM invplats")}


def spara_invplats(kod: str, **falt) -> None:
    """Sätter angivna fält (koder, adress, egen, lat, lon) för projektet; övriga lämnas."""
    with _anslut() as con:
        con.execute("INSERT OR IGNORE INTO invplats (kod) VALUES (?)", (kod,))
        for namn, varde in falt.items():
            if namn in ("koder", "adress", "egen", "lat", "lon"):
                con.execute(f"UPDATE invplats SET {namn} = ? WHERE kod = ?", (varde, kod))


# --- Användare och behörigheter (bara när inloggning via Entra ID är på) ------------------------------
ROLLER = {"ingen": "Ingen åtkomst", "lasare": "Läsare", "redigerare": "Redigerare", "admin": "Administratör"}
ROLLFORKLARING = {
    "ingen": "Har loggat in men väntar på att få behörighet. Ser ingenting.",
    "lasare": "Ser alla sidor och kan exportera till Excel, men ändrar ingenting.",
    "redigerare": "Som läsare, och kan dessutom ändra krav, byggår, anteckningar, kopplingar och läsa in underlagen på nytt.",
    "admin": "Som redigerare, och delar dessutom ut behörigheter till andra.",
}


def _nu() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def anvandare(oid: str) -> dict | None:
    with _anslut() as con:
        rad = con.execute("SELECT * FROM anvandare WHERE oid = ?", (oid,)).fetchone()
    return dict(rad) if rad else None


def alla_anvandare() -> list[dict]:
    with _anslut() as con:
        return [dict(r) for r in con.execute("SELECT * FROM anvandare ORDER BY roll = 'ingen' DESC, lower(namn)")]


def registrera_inloggning(oid: str, namn: str, epost: str, fast_admin: bool) -> dict:
    """Sparar/uppdaterar personen vid inloggning. Nya personer får Ingen åtkomst tills en administratör ger behörighet."""
    with _anslut() as con:
        finns = con.execute("SELECT roll FROM anvandare WHERE oid = ?", (oid,)).fetchone()
        roll = "admin" if fast_admin else (finns["roll"] if finns else "ingen")
        if finns:
            con.execute("UPDATE anvandare SET namn = ?, epost = ?, roll = ?, senast_inloggad = ? WHERE oid = ?",
                        (namn, epost, roll, _nu(), oid))
        else:
            con.execute("INSERT INTO anvandare (oid, namn, epost, roll, forst_inloggad, senast_inloggad) VALUES (?, ?, ?, ?, ?, ?)",
                        (oid, namn, epost, roll, _nu(), _nu()))
    return anvandare(oid)


def satt_roll(oid: str, roll: str) -> None:
    if roll not in ROLLER:
        raise ValueError("Okänd behörighet")
    with _anslut() as con:
        con.execute("UPDATE anvandare SET roll = ?, roll_andrad = ? WHERE oid = ?", (roll, _nu(), oid))


def ta_bort_anvandare(oid: str) -> None:
    with _anslut() as con:
        con.execute("DELETE FROM anvandare WHERE oid = ?", (oid,))
