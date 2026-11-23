"""Personlig inloggning via Entra ID (OpenID Connect, auktoriseringskod med PKCE).

Samma flöde som i Styrning, men utan användartabell och roller: den som får logga in i
Entra ID (tilldelad företagsappen) får se allt. Namn och e-post tas ur id-token.

Inloggningen är på när ENTRA_TENANT_ID, ENTRA_CLIENT_ID, ENTRA_CLIENT_SECRET och APP_URL är satta.
Omdirigerings-URI i appregistreringen: APP_URL/auth/callback, utloggning: APP_URL/utloggad.

Id-tokenets signatur kontrolleras inte separat: token hämtas direkt från Entra ID:s
tokenslutpunkt över TLS av en konfidentiell klient (OpenID Connect Core 3.1.3.7, punkt 6).
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

TENANT_ID = os.environ.get("ENTRA_TENANT_ID", "").strip()
CLIENT_ID = os.environ.get("ENTRA_CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("ENTRA_CLIENT_SECRET", "").strip()
APP_URL = os.environ.get("APP_URL", "").strip().rstrip("/")
SESSION_TIMMAR = int(os.environ.get("SESSION_TIMMAR", "10") or 10)
LOGIN_URL = "https://login.microsoftonline.com"

SESSIONSKAKA = "session"
FLODESKAKA = "inloggning"
OPPNA_SOKVAGAR = ("/static/", "/favicon.ico", "/logga-in", "/auth/callback", "/logga-ut", "/utloggad")
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
    """{"namn": ..., "epost": ...} för den inloggade personen, eller None."""
    return las_signerad(request.cookies.get(SESSIONSKAKA))


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
    epost = claims.get("email") or claims.get("preferred_username") or ""
    resp = RedirectResponse(flode["t"], status_code=303)
    resp.delete_cookie(FLODESKAKA)
    resp.set_cookie(SESSIONSKAKA, signera({"namn": claims.get("name") or epost, "epost": epost,
                                           "exp": time.time() + SESSION_TIMMAR * 3600}),
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


async def krav_inloggning(request: Request, call_next):
    """Middleware: alla sidor utom inloggningsflödet kräver inloggning."""
    if not request.url.path.startswith(OPPNA_SOKVAGAR):
        anv = inloggad(request)
        if anv is None:
            if request.method == "GET":
                till = request.url.path + (f"?{request.url.query}" if request.url.query else "")
                return RedirectResponse("/logga-in?" + urllib.parse.urlencode({"till": till}), status_code=303)
            return HTMLResponse("Du är inte inloggad.", status_code=401)
        request.state.anvandare = anv
    return await call_next(request)
