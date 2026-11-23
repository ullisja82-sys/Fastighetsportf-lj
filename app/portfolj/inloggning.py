"""Personlig inloggning via Entra ID (OpenID Connect, auktoriseringskod med PKCE).

Samma flöde som i Styrning. Behörigheten delas ut i appen (sidan Användare och behörigheter), inte i
Entra ID: den som loggar in första gången får Ingen åtkomst tills en administratör ger Läsare, Redigerare
eller Administratör. Adresserna i ADMIN_EPOST är alltid administratörer. Rollen läses ur databasen vid
varje anrop, så en ändring gäller direkt. Namn och e-post tas ur id-token.

Inloggningen är på när ENTRA_TENANT_ID, ENTRA_CLIENT_ID, ENTRA_CLIENT_SECRET och APP_URL är satta.
Omdirigerings-URI i appregistreringen: APP_URL/auth/callback, utloggning: APP_URL/utloggad.

Id-tokenets signatur kontrolleras inte separat: token hämtas direkt från Entra ID:s
tokenslutpunkt över TLS av en konfidentiell klient (OpenID Connect Core 3.1.3.7, punkt 6).
"""
import base64
import hashlib
import hmac
import html
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from . import lagring

TENANT_ID = os.environ.get("ENTRA_TENANT_ID", "").strip()
CLIENT_ID = os.environ.get("ENTRA_CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("ENTRA_CLIENT_SECRET", "").strip()
APP_URL = os.environ.get("APP_URL", "").strip().rstrip("/")
SESSION_TIMMAR = int(os.environ.get("SESSION_TIMMAR", "10") or 10)
LOGIN_URL = "https://login.microsoftonline.com"
ADMIN_EPOST = {a.strip().casefold() for a in os.environ.get("ADMIN_EPOST", "").split(",") if a.strip()}

SESSIONSKAKA = "session"
FLODESKAKA = "inloggning"
OPPNA_SOKVAGAR = ("/static/", "/favicon.ico", "/apple-touch-icon.png", "/apple-touch-icon-precomposed.png", "/logga-in", "/auth/callback", "/logga-ut", "/utloggad")
SCOPE = "openid profile email"

_hemlighet = (os.environ.get("SESSION_SECRET", "").strip() or secrets.token_urlsafe(32)).encode()

router = APIRouter()


def pa() -> bool:
    return bool(TENANT_ID and CLIENT_ID and CLIENT_SECRET and APP_URL)


# --- Signerade kakor --------------------------------------------------------------
def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def signera(data: dict) -> str:
    kropp = _b64(json.dumps(data, separators=(",", ":")).encode())
    return kropp + "." + _b64(hmac.new(_hemlighet, kropp.encode(), hashlib.sha256).digest())


def las_signerad(varde: str | None) -> dict | None:
    if not varde or "." not in varde:
        return None
    kropp, sig = varde.rsplit(".", 1)
    ratt = _b64(hmac.new(_hemlighet, kropp.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, ratt):
        return None
    try:
        data = json.loads(_unb64(kropp))
    except ValueError:
        return None
    return data if data.get("exp", 0) > time.time() else None


def inloggad(request: Request) -> dict | None:
    """Den inloggade personen ur tabellen anvandare (med aktuell roll), eller None."""
    data = las_signerad(request.cookies.get(SESSIONSKAKA))
    return lagring.anvandare(data["oid"]) if data and data.get("oid") else None


def fast_admin(*adresser: str | None) -> bool:
    return any(a and a.strip().casefold() in ADMIN_EPOST for a in adresser)


def _saker_kaka() -> bool:
    return APP_URL.startswith("https://")


# --- Entra ID ----------------------------------------------------------------------
def _entra(sokvag: str) -> str:
    return f"{LOGIN_URL}/{TENANT_ID}/{sokvag}"


def _redirect_uri() -> str:
    return f"{APP_URL}/auth/callback"


def _post_form(url: str, data: dict) -> dict:
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=20) as svar:
        return json.loads(svar.read().decode())


def _kontrollera_id_token(id_token: str, nonce: str) -> dict:
    try:
        claims = json.loads(_unb64(id_token.split(".")[1]))
    except (IndexError, ValueError) as e:
        raise ValueError("Ogiltigt id-token.") from e
    if claims.get("aud") != CLIENT_ID:
        raise ValueError("Id-token är inte utfärdat för den här appen.")
    if claims.get("iss") != _entra("v2.0"):
        raise ValueError("Id-token kommer från fel organisation (tenant).")
    if claims.get("nonce") != nonce:
        raise ValueError("Inloggningen kunde inte verifieras (nonce).")
    if claims.get("exp", 0) < time.time() - 60:
        raise ValueError("Id-token har gått ut.")
    return claims


def _felsida(text: str, status: int = 400) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><meta charset='utf-8'><title>Inloggningen misslyckades</title>"
        f"<body style='font-family:sans-serif;max-width:40rem;margin:4rem auto'>"
        f"<h1>Inloggningen misslyckades</h1><p>{text}</p><p><a href='/logga-in'>Försök igen</a></p>",
        status_code=status)


def _saker_till(till: str | None) -> str:
    return till if till and till.startswith("/") and not till.startswith("//") else "/"


@router.get("/logga-in")
def logga_in(till: str = "/"):
    state, nonce, verifierare = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    url = _entra("oauth2/v2.0/authorize") + "?" + urllib.parse.urlencode({
        "client_id": CLIENT_ID, "response_type": "code", "redirect_uri": _redirect_uri(),
        "response_mode": "query", "scope": SCOPE, "state": state, "nonce": nonce,
        "code_challenge": _b64(hashlib.sha256(verifierare.encode()).digest()), "code_challenge_method": "S256",
    })
    resp = RedirectResponse(url, status_code=303)
    resp.set_cookie(FLODESKAKA, signera({"s": state, "n": nonce, "v": verifierare, "t": _saker_till(till),
                                         "exp": time.time() + 600}),
                    max_age=600, httponly=True, secure=_saker_kaka(), samesite="lax")
    return resp


@router.get("/auth/callback")
def callback(request: Request, code: str | None = None, state: str | None = None,
             error: str | None = None, error_description: str | None = None):
    if error:
        if error in ("access_denied", "consent_required", "interaction_required"):
            return _felsida("Du har inte behörighet till Fastighetsportföljen. Kontakta IT för att bli tilldelad appen.", 403)
        return _felsida(f"Entra ID svarade: {error_description or error}")
    flode = las_signerad(request.cookies.get(FLODESKAKA))
    if not flode or not code or not state or not hmac.compare_digest(state, flode["s"]):
        return _felsida("Inloggningen tog för lång tid eller startades i en annan flik.")
    try:
        token = _post_form(_entra("oauth2/v2.0/token"), {
            "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
            "grant_type": "authorization_code", "code": code, "redirect_uri": _redirect_uri(),
            "code_verifier": flode["v"], "scope": SCOPE,
        })
        claims = _kontrollera_id_token(token["id_token"], flode["n"])
    except urllib.error.HTTPError as e:
        return _felsida(f"Microsoft svarade med fel {e.code}. Kontrollera appregistreringen.", 502)
    except (urllib.error.URLError, TimeoutError):
        return _felsida("Kunde inte nå Microsoft.", 502)
    except (KeyError, ValueError) as e:
        return _felsida(str(e))
    if not claims.get("oid"):
        return _felsida("Id-token saknar användarens objekt-id (oid).")
    epost = claims.get("email") or claims.get("preferred_username") or ""
    lagring.registrera_inloggning(claims["oid"], claims.get("name") or epost, epost,
                                  fast_admin(claims.get("email"), claims.get("preferred_username")))
    resp = RedirectResponse(flode["t"], status_code=303)
    resp.delete_cookie(FLODESKAKA)
    resp.set_cookie(SESSIONSKAKA, signera({"oid": claims["oid"], "exp": time.time() + SESSION_TIMMAR * 3600}),
                    max_age=SESSION_TIMMAR * 3600, httponly=True, secure=_saker_kaka(), samesite="lax")
    return resp


@router.get("/logga-ut")
def logga_ut():
    url = _entra("oauth2/v2.0/logout") + "?" + urllib.parse.urlencode(
        {"post_logout_redirect_uri": f"{APP_URL}/utloggad"})
    resp = RedirectResponse(url, status_code=303)
    resp.delete_cookie(SESSIONSKAKA)
    return resp


@router.get("/utloggad")
def utloggad():
    return HTMLResponse(
        "<!doctype html><meta charset='utf-8'><title>Utloggad</title>"
        "<body style='font-family:sans-serif;max-width:40rem;margin:4rem auto'>"
        "<h1>Du är utloggad från Fastighetsportföljen</h1><p><a href='/logga-in'>Logga in igen</a></p>")


def _sida(rubrik: str, text: str, status: int) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><meta charset='utf-8'><title>{rubrik}</title>"
        f"<body style='font-family:sans-serif;max-width:40rem;margin:4rem auto'>"
        f"<h1>{rubrik}</h1><p>{text}</p><p><a href='/logga-ut'>Logga ut</a></p>", status_code=status)


async def krav_inloggning(request: Request, call_next):
    """Middleware: alla sidor utom inloggningsflödet kräver inloggning och rätt behörighet."""
    if request.url.path.startswith(OPPNA_SOKVAGAR):
        return await call_next(request)
    anv = inloggad(request)
    if anv is None:
        if request.method == "GET":
            till = request.url.path + (f"?{request.url.query}" if request.url.query else "")
            return RedirectResponse("/logga-in?" + urllib.parse.urlencode({"till": till}), status_code=303)
        return HTMLResponse("Du är inte inloggad.", status_code=401)
    if anv["roll"] == "ingen":
        return _sida("Du väntar på behörighet",
                     f"Du är inloggad som {html.escape(anv['namn'] or anv['epost'] or '')}, men har ännu inte fått behörighet "
                     "till Fastighetsportföljen. En administratör behöver ge dig behörighet.", 403)
    if request.url.path.startswith("/anvandare") and anv["roll"] != "admin":
        return _sida("Ingen behörighet", "Bara administratörer kan dela ut behörigheter.", 403)
    if request.method != "GET" and anv["roll"] not in ("redigerare", "admin"):
        return _sida("Ingen behörighet", "Du har läsbehörighet och kan inte ändra något. Be en administratör om "
                     "behörigheten Redigerare.", 403)
    request.state.anvandare = anv
    return await call_next(request)
