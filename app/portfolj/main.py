"""HFAB Fastighetsportfölj – webbapplikationen (port 8405)."""
import io
import os
from datetime import date
import threading
import time
from urllib.parse import quote, urlencode

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from openpyxl import Workbook
from openpyxl.styles import Font

from . import flikar, importmotor, inloggning, invanalys, invdiagram, omraden, investering, investeringsplan_data, kund, lagring, modell, plats, projekt
from .datatyper import DATATYPER
from .importera import STAMFALT, las_underlag

HAR = os.path.dirname(__file__)
UNDERLAG_DIR = os.environ.get("UNDERLAG_DIR", "./Underlag")

app = FastAPI(title="HFAB Fastighetsportfölj", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=os.path.join(HAR, "static")), name="static")
mallar = Jinja2Templates(directory=os.path.join(HAR, "templates"))
if inloggning.pa():
    app.middleware("http")(inloggning.krav_inloggning)
    app.include_router(inloggning.router)

KUND_DIR = os.environ.get("KUND_DIR", "./Kundundersökning")
_underlag = las_underlag(UNDERLAG_DIR)


def _fastighetsnamn() -> dict[str, str]:
    """Nummer -> namn enligt senaste år där fastigheten finns."""
    return {k: next(f["namn"] for a in reversed(_underlag.ar) if (f := _underlag.fastighet(k, a))) for k in _underlag.koder()}


def _synka_fastigheter() -> None:
    """Fastighetstabellen i databasen följer underlaget: nya fastigheter läggs till, ingen tas bort."""
    senaste = {k: next(f for a in reversed(_underlag.ar) if (f := _underlag.fastighet(k, a))) for k in _underlag.koder()}
    importmotor.synka_fastigheter([(k, f["namn"], f["ao"]) for k, f in senaste.items() if not f.get("samlingsrad")])


_synka_fastigheter()


def _las_kund():
    return kund.las_kund(KUND_DIR, _fastighetsnamn(), lagring.kundkopplingar())


_kund = _las_kund()
PROJEKT_DIR = os.environ.get("PROJEKT_DIR", "./Projekt")
_projekt = projekt.las_projekt(PROJEKT_DIR, set(_underlag.koder()))

_platssokning = {"pagar": False, "kvar": 0, "fel": ""}


def _investeringar() -> list[dict]:
    return investering.projekt(set(_underlag.koder()), lagring.invplatser(), lagring.platser())


def _sok_investeringsplatser() -> None:
    """Slår upp platsen (t.ex. "Kullagård") för projekt i investeringsplanen som inte ligger på en fastighet med känt läge."""
    sparat = lagring.invplatser()
    try:
        for p in _investeringar():
            if p["plats"] is None and p["sokord"] and p["kod"] not in sparat:
                lage = plats.sla_upp(p["sokord"], "Halmstad")
                lagring.spara_invplats(p["kod"], adress=p["sokord"], egen=0, lat=lage[0] if lage else None, lon=lage[1] if lage else None)
                time.sleep(1.1)
    except Exception as e:
        _platssokning["fel"] = str(e)


def _sok_lagen(om: bool = False) -> None:
    """Slår upp läget för fastigheter som saknar det (om=True: även dem som inte hittades förra gången). Körs i bakgrunden,
    en fråga i sekunden mot OpenStreetMap."""
    if _platssokning["pagar"]:
        return
    kanda = lagring.platser()
    att_soka = [(k, n) for k, n in _fastighetsnamn().items()
                if k not in kanda or (om and kanda[k]["lat"] is None and not kanda[k]["egen"])]
    if not att_soka:
        threading.Thread(target=_sok_investeringsplatser, daemon=True).start()
        return
    _platssokning.update(pagar=True, kvar=len(att_soka), fel="")

    def kor():
        try:
            for kod, namn in att_soka:
                adress, lage = plats.sla_upp_fastighet(namn)
                lagring.spara_plats(kod, adress, lage, egen=False)
                _platssokning["kvar"] -= 1
                time.sleep(1.1)
            _sok_investeringsplatser()
        except Exception as e:  # t.ex. ingen internetförbindelse – resten provas nästa gång
            _platssokning["fel"] = str(e)
        finally:
            _platssokning["pagar"] = False

    threading.Thread(target=kor, daemon=True).start()


_sok_lagen()


def tal(v, d=1):
    """Svenskt talformat: mellanslag som tusentalsavgränsare, decimalkomma, riktigt minustecken."""
    if v is None:
        return "–"
    s = f"{v:,.{d}f}".replace(",", " ").replace(".", ",")
    if s.lstrip("-").strip("0,") == "":
        s = s.lstrip("-")
    return s.replace("-", "−")


mallar.env.filters["tal"] = tal


def statisk(fil: str) -> str:
    """Länk till en statisk fil med versionsmärkning, så att webbläsaren hämtar en ändrad fil direkt."""
    try:
        return f"/static/{fil}?v={int(os.stat(os.path.join(HAR, 'static', fil)).st_mtime)}"
    except OSError:
        return f"/static/{fil}"


mallar.env.globals["statisk"] = statisk

FALTNAMN = {"byggar": "byggår", "toa": "TOA", "boa": "BOA", "loa": "LOA", "boa_loa": "BOA + LOA", "lgh": "antal lägenheter",
            "lokaler": "antal lokaler", "bokfort": "bokfört värde", "marknad": "marknadsvärde"}


def _ar(request: Request, ar: int | None) -> int:
    alla = _underlag.ar
    if not alla:
        raise HTTPException(503, "Det finns inga Fastighetsanalys-filer i Underlag.")
    if ar in alla:
        return ar
    try:
        kaka = int(request.cookies.get("ar", ""))
    except ValueError:
        kaka = None
    return kaka if kaka in alla else alla[-1]


def _visa(request: Request, mall: str, ar: int, **kontext):
    inst = lagring.installningar()
    lanat, meny_ao = {}, {}
    for f in (_underlag.fastighet(k, ar) for k in _underlag.koder()):
        if f and f.get("ao"):
            meny_ao[f["ao"]] = True
        for falt, fran in (f or {}).get("lanat", {}).items():
            lanat.setdefault(fran, set()).add(falt)
    kontext = {
        "ar": ar, "aren": _underlag.ar, "inst": inst, "STATUS": modell.STATUS, "nav": mall.removesuffix(".html"),
        "klassnamn": modell.klassnamn(inst["klasser"]), "vardenamn": "bokfört värde" if inst["vardebas"] == "bokfort" else "marknadsvärde",
        "vardekort": "BV" if inst["vardebas"] == "bokfort" else "MV", "sokvag": request.url.path,
        "projekt": _projekt, "PROJEKTLAGE": projekt.LAGESNAMN, "inv_per_fastighet": investering.per_fastighet(_investeringar()), "meny_ao": sorted(a for a in meny_ao if a != modell.ODEFINIERAT),
        "meny_odefinierat": modell.ODEFINIERAT if modell.ODEFINIERAT in meny_ao else "", "vald_ao": "",
        # Årsvalet behåller övriga val i adressen (t.ex. affärsområde)
        "arfraga": "".join("&" + urlencode({k: v}) for k, v in request.query_params.multi_items() if k not in ("ar", "sparat", "last")),
        "lanat": {fran: [FALTNAMN[f] for f in STAMFALT if f in falt] for fran, falt in sorted(lanat.items())},
        **kontext,
    }
    svar = mallar.TemplateResponse(request, mall, kontext)
    svar.set_cookie("ar", str(ar), max_age=60 * 60 * 24 * 365, samesite="lax")
    return svar


def _rader(ar: int) -> list[dict]:
    return modell.rader(_underlag, ar, lagring.installningar(), lagring.justeringar())


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(os.path.join(HAR, "static", "favicon.ico"), media_type="image/x-icon")


@app.get("/apple-touch-icon.png", include_in_schema=False)
@app.get("/apple-touch-icon-precomposed.png", include_in_schema=False)
def apple_touch_icon():
    return FileResponse(os.path.join(HAR, "static", "apple-touch-icon.png"), media_type="image/png")


@app.get("/")
def oversikt(request: Request, ar: int | None = None, ao: str = ""):
    ar = _ar(request, ar)
    inst = lagring.installningar()
    rr = _rader(ar)
    if ao not in modell.ao_ordning(rr):
        ao = ""
    if ao:  # ett affärsområde i taget; utan val visas hela portföljen
        rr = [r for r in rr if r["ao"] == ao]
    aos = modell.ao_ordning(rr)
    per_ao = [(a, modell.summera([r for r in rr if r["ao"] == a])) for a in aos]
    klasser = list(range(len(inst["klasser"]))) + [None]
    per_klass = [(k, modell.summera([r for r in rr if r["klass"] == k])) for k in klasser]
    matris = {(a, k): modell.summera([r for r in rr if r["ao"] == a and r["klass"] == k]) for a in aos for k in klasser}
    samst = sorted([r for r in rr if (r.get("dn_mot_krav") or 0) < 0], key=lambda r: r["dn_mot_krav"])[:10]
    lagen = lagring.platser()
    karta = [{"kod": r["kod"], "namn": r["namn"], "ao": r["ao"], "status": r["status"], "lat": lagen[r["kod"]]["lat"], "lon": lagen[r["kod"]]["lon"],
              "projekt": _projekt.lage(r["kod"]), "projektnamn": [p["namn"] for p in _projekt.get(r["kod"], [])][:4],
              "og": tal(r["og"] * 100, 1) + " %" if r["og"] is not None else "–", "avk": tal(r["avk"] * 100, 1) + " %" if r["avk"] is not None else "–"}
             for r in rr if lagen.get(r["kod"], {}).get("lat") is not None]
    inv = _investeringar()
    if ao:  # i ett affärsområde: bara projekt som ligger på områdets fastigheter
        i_ao = {r["kod"] for r in rr}
        inv = [p for p in inv if i_ao & set(p["koder"])]
    namn = {r["kod"]: r["namn"] for r in rr}
    invkarta = []
    for p in inv:
        post = {"kod": p["kod"], "namn": p["namn"], "typ": p["typ"], "typnamn": p["typnamn"], "period": p["period"],
                "volym": tal(p["volym"] / 1000, 0) + " mnkr", "fastigheter": [f"{k} {namn[k]}" for k in p["koder"] if k in namn][:6]}
        # Nyproduktion: en markering på projektets plats. Förnyelse och avyttring: en på varje berörd fastighet.
        punkter = [p["plats"]] if p["typ"] == "nyproduktion" and p["plats"] else p["punkter"] or ([p["plats"]] if p["plats"] else [])
        invkarta += [{**post, "lat": lat, "lon": lon} for lat, lon in punkter]
    return _visa(request, "oversikt.html", ar, investeringar=inv, invkarta=invkarta, total=modell.summera(rr), per_ao=per_ao, per_klass=per_klass, matris=matris,
                 aos=aos, klasser=klasser, samst=samst, vald_ao=ao, karta=karta, karta_utan=len(rr) - len(karta), platssokning=_platssokning, byggar_intervall=modell.byggar_intervall(inst["klasser"], inst["referensar"]))


@app.get("/investeringsportfolj")
@app.get("/investeringsplan", include_in_schema=False)   # tidigare adress
def investeringsplan(request: Request, planar: int | None = None):
    """Investeringsplanen i sin helhet, uppställd som Investeringsanalys i Styrning: nyckeltal, diagram, tidplan och projekt."""
    ia = invanalys
    planar = planar if planar in ia.DIAGRAMAR else investeringsplan_data.BUDGETAR
    typer = [(typ, namn, sorted(ia.projekt(typ), key=lambda p: (p["start"] or p["klar"] or "", p["kod"]))) for typ, namn in ia.TYPER.items()]
    alla = [p for _, _, lista in typer for p in lista]
    koder = {p["kod"]: p["koder"] for p in _investeringar()}
    return _visa(request, "investeringsplan.html", _ar(request, None), dolj_arsval=True, planar=planar, planaren=ia.DIAGRAMAR, data=investeringsplan_data,
                 ia=ia, typer=typer, nt=ia.nyckeltal(planar), per_ar=ia.investeringar_per_ar(), rk_per_ar=ia.resultatpaverkan_per_ar(),
                 diagram_inv=invdiagram.investeringar(ia.investeringar_per_ar(), planar),
                 diagram_rk=invdiagram.resultatpaverkan(ia.resultatpaverkan_per_ar(), planar), diagram_tid=invdiagram.tidplan(alla, planar),
                 fastighetskoder=koder)


@app.get("/projektportfolj")
def projektportfolj(request: Request):
    """Pågående och planerade byggprojekt ur projektlistan: läge, budget per år, vem som leder dem och vad som drar över tiden."""
    ar = _ar(request, None)
    ao = {k: f["ao"] for k in _underlag.koder() if (f := _underlag.fastighet(k, ar))}
    s = projekt.sammanstall(_projekt, ao, date.today())
    return _visa(request, "projektportfolj.html", ar, dolj_arsval=True, s=s, SLAG=projekt.SLAG, idag=date.today(), fastighetsnamn=_fastighetsnamn(),
                 diagram=invdiagram.projektbudget(s["per_ar"], projekt.SLAG) if s["per_ar"] else "")


@app.get("/fastigheter")
def fastigheter(request: Request, ar: int | None = None, ao: str = "", klass: str = "", status: str = ""):
    ar = _ar(request, ar)
    rr = sorted(_rader(ar), key=lambda r: (r["dn_mot_krav"] is None, r["dn_mot_krav"] or 0))
    aos = modell.ao_ordning(rr)
    return _visa(request, "fastigheter.html", ar, rader=rr, aos=aos, val={"ao": ao, "klass": klass, "status": status}, vald_ao=ao if ao in aos else "")


def _ser_flikar(request: Request) -> bool:
    """Flikarna är en förhandsvisning: bara administratörer ser dem tills de släpps till alla (Användare och behörigheter).
    Utan inloggning (lokal körning) finns inga roller, och då visas de."""
    anv = getattr(request.state, "anvandare", None)
    return anv is None or anv["roll"] == "admin" or lagring.flikar_for_alla()


@app.get("/fastighet/{kod}")
def fastighet(request: Request, kod: str, ar: int | None = None, sparat: int = 0, flik: str = ""):
    ar = _ar(request, ar)
    inst, just = lagring.installningar(), lagring.justeringar()
    if kod not in _underlag.koder():
        raise HTTPException(404, "Fastigheten finns inte i underlaget")
    per_ar = [(a, modell.berakna(f, inst, just.get(kod))) for a in _underlag.ar if (f := _underlag.fastighet(kod, a))]
    r = dict(per_ar)[ar]
    kundmatt = kund.jamforelse(_kund or kund.fiktiv(_underlag.koder(), _underlag.ar), kod, ar)
    kontext = {}
    if _ser_flikar(request):
        # Värden som flikarnas fält kan peka på: årets rad ur Fastighetsanalysen, projektlistan och kundundersökningen (aldrig de fiktiva siffrorna)
        def varden(a: int, rad: dict | None) -> dict | None:
            if rad is None:
                return None
            v = dict(rad)
            if _projekt.filnamn and a == ar:
                v["antal_projekt"] = len(_projekt.get(kod, []))
            v.update(_kund.get((a, "fastighet", kod), {}) if _kund else {})
            if fid:   # det som lästs in under Datainläsning; uppgifter som redan finns ur ett underlag behålls
                inlast = omraden.varden(con, fid, a, rad.get("yta"), rad.get("lgh"))
                v["_kallor"] = omraden.kalla_per_nyckel(inlast, kallor)
                v.update(inlast)
                for kort, lang in (("serviceindex", "kund_serviceindex"), ("produktindex", "kund_produktindex"), ("vakansgrad", "kund_vakansgrad")):
                    if v.get(kort) is None and inlast.get(lang) is not None:
                        v[kort], v["_kallor"][kort] = inlast[lang], v["_kallor"].get(lang)
            return v
        fid = importmotor.fastighets_id(kod)
        con = importmotor.anslut()
        kallor = omraden.kallor(con, fid) if fid else {}
        kontext = {"flikar": flikar.FLIKAR, "flik": flik if flik in dict(flikar.FLIKAR) else "oversikt", "flikar_for_alla": lagring.flikar_for_alla(),
                   "fliktabeller": flikar.TABELLER, "flikfalt": flikar.sammanstall(varden(ar, r), varden(ar - 1, dict(per_ar).get(ar - 1))),
                   "underlagsfil": _underlag.filer[ar].filnamn, "flikkallor": kallor,
                   "flikinnehall": omraden.tabeller(con, fid, ar, tal) if fid else {},
                   "energijamforelse": omraden.jamforelse(r, _rader(ar), omraden.forbrukning_per_fastighet(con, ar)) if flik == "energi" else [],
                   "JMF_AR": omraden.JMF_AR, "JMF_YTA": omraden.JMF_YTA}
        con.close()
    return _visa(request, "fastighet.html", ar, r=r, per_ar=per_ar, sparat=sparat, just=just.get(kod), vald_ao=r["ao"],
                 kundmatt=kundmatt, kund_fiktiv=not _kund,
                 kundenheter=_kund.get((ar, "fastighet", kod), {}).get("enheter", []), plats=lagring.platser().get(kod),
                 hfab_beraknad=_kund.get((ar, "hfab", ""), {}).get("beraknad"), **{"flik": "alla", **kontext})


@app.post("/fastighet/{kod}")
def spara_fastighet(kod: str, byggar: str = Form(""), anteckning: str = Form(""), kartadress: str = Form("")):
    if kod not in _underlag.koder():
        raise HTTPException(404, "Fastigheten finns inte i underlaget")
    byggar = byggar.strip()
    if byggar and not (byggar.isdigit() and 1000 <= int(byggar) <= 2100):
        raise HTTPException(400, "Byggår ska vara ett årtal med fyra siffror")
    lagring.spara_justering(kod, int(byggar) if byggar else None, anteckning.strip()[:2000])
    # Egen adress för kartan: slås upp direkt. Tomt fält återgår till adressen ur fastighetens namn.
    kartadress = kartadress.strip()[:200]
    kand = lagring.platser().get(kod)
    if kartadress and not (kand and kand["egen"] and kand["adress"] == kartadress):
        try:
            lagring.spara_plats(kod, *plats.sla_upp_fastighet("", kartadress), egen=True)
        except Exception:
            lagring.spara_plats(kod, kartadress, None, egen=True)
    elif not kartadress and kand and kand["egen"]:
        lagring.ta_bort_plats(kod)
        _sok_lagen()
    return RedirectResponse(f"/fastighet/{quote(kod)}?sparat=1", status_code=303)


@app.get("/krav")
def krav(request: Request, ar: int | None = None, sparat: int = 0):
    ar = _ar(request, ar)
    inst = lagring.installningar()
    rr = _rader(ar)
    antal = [sum(1 for r in rr if r["klass"] == i) for i in range(len(inst["klasser"]))]
    return _visa(request, "krav.html", ar, sparat=sparat, antal=antal, utan=sum(1 for r in rr if r["klass"] is None),
                 standard=inst == lagring.STANDARD, byggar_intervall=modell.byggar_intervall(inst["klasser"], inst["referensar"]))


def _procent(text: str, falt: str) -> float:
    try:
        v = float(text.replace("%", "").replace(" ", "").replace(" ", "").replace(",", "."))
    except ValueError:
        raise HTTPException(400, f"{falt}: ange ett tal i procent")
    if not 0 <= v <= 100:
        raise HTTPException(400, f"{falt}: ska ligga mellan 0 och 100 procent")
    return round(v / 100, 6)


@app.post("/krav")
async def spara_krav(request: Request):
    form = await request.form()
    if form.get("aterstall"):
        lagring.aterstall_installningar()
        return RedirectResponse("/krav?sparat=1", status_code=303)
    try:
        referensar = int(form.get("referensar", ""))
        granser = [int(form.get(f"max_{i}", "")) for i in range(3)]
    except ValueError:
        raise HTTPException(400, "Referensår och åldersgränser ska vara heltal")
    if not 1900 <= referensar <= 2100 or not 0 < granser[0] < granser[1] < granser[2]:
        raise HTTPException(400, "Åldersgränserna ska vara stigande och referensåret ett rimligt årtal")
    vardebas = form.get("vardebas")
    if vardebas not in ("bokfort", "marknad"):
        raise HTTPException(400, "Okänd värdebas")
    klasser = [{"max_alder": (granser + [None])[i], "krav_avk": _procent(form.get(f"avk_{i}", ""), "Avkastningskrav"),
                "krav_og": _procent(form.get(f"og_{i}", ""), "Krav på överskottsgrad")} for i in range(4)]
    lagring.spara_installningar({"referensar": referensar, "vardebas": vardebas, "klasser": klasser})
    return RedirectResponse("/krav?sparat=1", status_code=303)


@app.get("/underlag")
def underlag(request: Request, ar: int | None = None, last: int = 0):
    ar = _ar(request, ar)
    rr = _rader(ar)
    fil = _underlag.filer[ar]
    avstamning = []
    for ao in modell.ao_ordning(rr):
        s = modell.summera([r for r in rr if r["ao"] == ao and not r["lanat"].get("bokfort")])
        alla = modell.summera([r for r in rr if r["ao"] == ao])
        x = fil.ao_rader.get(ao, {})
        avstamning.append((ao, alla["antal"], [("Intäkter", alla["intakter"], x.get("intakter")), ("Driftsnetto", alla["driftsnetto"], x.get("driftsnetto")),
                                               ("Bokfört värde", s["bokfort"], x.get("bokfort"))]))
    flaggade = [r for r in rr if r["flaggor"]]
    justerade = [r for r in rr if r["justerat_byggar"] or r["anteckning"]]
    return _visa(request, "underlag.html", ar, filer=[_underlag.filer[a] for a in _underlag.ar], fel=_underlag.fel, avstamning=avstamning,
                 flaggade=flaggade, justerade=justerade, antal=len(rr), last=last, platser=lagring.platser(), platssokning=_platssokning, investeringar=_investeringar(),
                 kund=_kund, fastighetsnamn=dict(sorted(_fastighetsnamn().items(), key=lambda x: x[1].lower())))


@app.post("/underlag/las-om")
def las_om():
    global _underlag, _kund, _projekt
    _underlag = las_underlag(UNDERLAG_DIR)
    _kund = _las_kund()
    _projekt = projekt.las_projekt(PROJEKT_DIR, set(_underlag.koder()))
    _synka_fastigheter()
    return RedirectResponse("/underlag?last=1", status_code=303)


@app.post("/underlag/investering")
async def spara_investering(request: Request):
    """Koppling mellan investeringsplanens projekt och fastigheterna, samt projektets plats på kartan."""
    form = await request.form()
    sparat = lagring.invplatser()
    nu = {p["kod"]: p for p in _investeringar()}
    for kod in form.getlist("projekt"):
        if kod not in nu:
            continue
        koder = ",".join(k for k in (x.strip() for x in str(form.get(f"koder_{kod}", "")).replace(";", ",").split(",")) if k)
        if koder != ",".join(nu[kod]["koder"]):
            lagring.spara_invplats(kod, koder=koder)
        adress = str(form.get(f"adress_{kod}", "")).strip()[:200]
        if adress != (sparat.get(kod, {}).get("adress") or nu[kod]["sokord"] or ""):
            try:
                lage = plats.sla_upp(adress, "" if "," in adress else "Halmstad") if adress else None
            except Exception:
                lage = None
            lagring.spara_invplats(kod, adress=adress, egen=1 if adress else 0, lat=lage[0] if lage else None, lon=lage[1] if lage else None)
            time.sleep(1.1)
    return RedirectResponse("/underlag?last=1#investeringsplan", status_code=303)


@app.post("/underlag/sok-lagen")
def sok_lagen():
    _sok_lagen(om=True)
    return RedirectResponse("/underlag#karta", status_code=303)


@app.post("/underlag/kundkoppling")
async def spara_kundkoppling(request: Request):
    """Kopplar AktivBo-enheter som inte gick att para ihop automatiskt till en fastighet (tomt val tar bort kopplingen)."""
    global _kund
    form = await request.form()
    koder = set(_underlag.koder())
    for enhet, kod in zip(form.getlist("enhet"), form.getlist("kod")):
        if not kod or kod in koder:
            lagring.spara_kundkoppling(enhet, kod)
    _kund = _las_kund()
    return RedirectResponse("/underlag?last=1#kundundersokning", status_code=303)


@app.get("/anvandare")
def anvandare_sida(request: Request, sparat: int = 0):
    """Administratören delar ut behörigheter (sidan finns bara när inloggning via Entra ID är på)."""
    if not inloggning.pa():
        raise HTTPException(404)
    return _visa(request, "anvandare.html", _ar(request, None), dolj_arsval=True, anvandare=lagring.alla_anvandare(),
                 ROLLER=lagring.ROLLER, ROLLFORKLARING=lagring.ROLLFORKLARING, sparat=sparat, flikar_for_alla=lagring.flikar_for_alla(),
                 fasta=[a["oid"] for a in lagring.alla_anvandare() if inloggning.fast_admin(a["epost"])])


@app.post("/anvandare")
def spara_anvandare(request: Request, oid: str = Form(...), roll: str = Form(""), ta_bort: str = Form("")):
    if not inloggning.pa():
        raise HTTPException(404)
    anv = lagring.anvandare(oid)
    if anv is None:
        raise HTTPException(404, "Okänd användare")
    if inloggning.fast_admin(anv["epost"]):
        raise HTTPException(400, "Fasta administratörer (ADMIN_EPOST) kan inte ändras här")
    if oid == request.state.anvandare["oid"]:
        raise HTTPException(400, "Du kan inte ändra din egen behörighet")
    if ta_bort:
        lagring.ta_bort_anvandare(oid)
    else:
        try:
            lagring.satt_roll(oid, roll)
        except ValueError as e:
            raise HTTPException(400, str(e))
    return RedirectResponse("/anvandare?sparat=1", status_code=303)


@app.post("/anvandare/flikar")
def spara_flikar(visa: str = Form("")):
    """Släpper flikarna på fastigheten till alla, eller drar tillbaka dem till bara administratörer."""
    if not inloggning.pa():
        raise HTTPException(404)
    lagring.satt_flikar_for_alla(visa == "alla")
    return RedirectResponse("/anvandare?sparat=1", status_code=303)


# --- Datainläsning (bara administratörer; kontrolleras i inloggning.krav_inloggning) -------------------
def _inlasning(import_id: int) -> dict:
    imp = importmotor.inlasning(import_id)
    if imp is None:
        raise HTTPException(404, "Inläsningen finns inte")
    return imp


@app.get("/datainlasning")
def datainlasning(request: Request, fel: str = ""):
    return _visa(request, "datainlasning.html", _ar(request, None), dolj_arsval=True, DATATYPER=DATATYPER, historik=importmotor.historik(), fel=fel)


@app.post("/datainlasning")
async def ladda_upp(request: Request, datatyp: str = Form(...), fil: UploadFile = File(...)):
    innehall = await fil.read(30 * 1024 * 1024 + 1)
    if len(innehall) > 30 * 1024 * 1024:
        return RedirectResponse("/datainlasning?" + urlencode({"fel": "Filen är större än 30 MB."}), status_code=303)
    anv = getattr(request.state, "anvandare", None)
    try:
        import_id = importmotor.ny_inlasning(datatyp, fil.filename, innehall, (anv or {}).get("namn") or "")
    except importmotor.Importfel as e:
        return RedirectResponse("/datainlasning?" + urlencode({"fel": str(e)}), status_code=303)
    return RedirectResponse(f"/datainlasning/{import_id}", status_code=303)


@app.get("/datainlasning/mall/{datatyp}.xlsx")
def importmall(datatyp: str):
    """Tom mall med datatypens rubriker och en förklaring av varje kolumn."""
    if datatyp not in DATATYPER:
        raise HTTPException(404)
    dt = DATATYPER[datatyp]
    wb = Workbook()
    ws = wb.active
    ws.title = dt["namn"][:31]
    ws.append([k.rubrik for k in dt["kolumner"]])
    ws2 = wb.create_sheet("Förklaring")
    ws2.append(["Kolumn", "Obligatorisk", "Format", "Kommentar", "Andra rubriker som känns igen"])
    typnamn = {"text": "text", "tal": "tal", "heltal": "heltal", "andel": "procent", "period": "period", "datum": "datum", "janej": "ja/nej",
               "val": "fast värde", "fastighet": "fastighet", "manad": "månad"}
    for k in dt["kolumner"]:
        ws2.append([k.rubrik, "ja" if k.kravs else "", typnamn[k.typ], k.hjalp, ", ".join(k.alias)])
    for blad in (ws, ws2):
        for c in blad[1]:
            c.font = Font(bold=True)
        blad.freeze_panes = "A2"
        for kol in blad.columns:
            blad.column_dimensions[kol[0].column_letter].width = min(max(len(str(c.value or "")) for c in kol) + 2, 70)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="Importmall-{datatyp}.xlsx"'})


@app.get("/datainlasning/{import_id}")
def inlasning_sida(request: Request, import_id: int, visa: str = "", fel: str = ""):
    imp = _inlasning(import_id)
    dt = DATATYPER[imp["datatyp"]]
    rubriker, datarader, bladnamn = importmotor.filrader(imp) if imp["status"] == "granskas" else ([], [], [])
    visa = visa if visa in importmotor.STATUSNAMN else ("fel" if imp["fel"] else "ny" if imp["nya"] else "andrad" if imp["andrade"] else "oforandrad")
    return _visa(request, "inlasning.html", _ar(request, None), dolj_arsval=True, imp=imp, dt=dt, rubriker=rubriker, bladnamn=bladnamn,
                 exempel=[next((r[i] for r in datarader[:50] if i < len(r) and r[i] is not None), None) for i in range(len(rubriker))],
                 visa=visa, rader=importmotor.rader(import_id, visa), STATUSNAMN=importmotor.STATUSNAMN, lagrade=importmotor.lagrade(dt),
                 okanda=importmotor.okanda_fastigheter(import_id) if imp["status"] == "granskas" else [],
                 fastighetsnamn=dict(sorted(_fastighetsnamn().items(), key=lambda x: x[1].lower())),
                 tidigare=importmotor.tidigare_inlast(imp), fel=fel)


def _inlasningssteg(import_id: int, steg) -> RedirectResponse:
    try:
        steg()
    except importmotor.Importfel as e:
        return RedirectResponse(f"/datainlasning/{import_id}?" + urlencode({"fel": str(e)}), status_code=303)
    return RedirectResponse(f"/datainlasning/{import_id}", status_code=303)


@app.post("/datainlasning/{import_id}/kolumner")
async def inlasning_kolumner(request: Request, import_id: int):
    """Användarens val av blad, rubrikrad och vilken kolumn som är vad; filen valideras om."""
    imp = _inlasning(import_id)
    form = await request.form()
    try:
        rubrikrad = max(int(form.get("rubrikrad", "1")) - 1, 0)
    except ValueError:
        rubrikrad = imp["mappning"]["rubrikrad"]
    falt = {k.falt for k in DATATYPER[imp["datatyp"]]["kolumner"]}
    mappning = {"blad": form.get("blad") or imp["mappning"]["blad"], "rubrikrad": rubrikrad}
    if mappning["blad"] != imp["mappning"]["blad"] or rubrikrad != imp["mappning"]["rubrikrad"]:   # ny rubrikrad: föreslå kolumnerna på nytt
        blad = importmotor.las_fil(importmotor._sokvag(imp))
        rader = dict(blad).get(mappning["blad"], blad[0][1])
        mappning["kolumner"] = {str(i): f for i, f in importmotor._rubriktraffar(DATATYPER[imp["datatyp"]], rader[rubrikrad] if rubrikrad < len(rader) else []).items()}
    else:
        valda = {}
        for nyckel, varde in form.multi_items():
            if nyckel.startswith("kol_") and varde in falt and varde not in valda.values():
                valda[nyckel[4:]] = varde
        mappning["kolumner"] = valda
    return _inlasningssteg(import_id, lambda: importmotor.forbered(import_id, mappning))


@app.post("/datainlasning/{import_id}/koppla")
async def inlasning_koppla(request: Request, import_id: int):
    _inlasning(import_id)
    form = await request.form()
    kopplingar = {e: k for e, k in zip(form.getlist("externt"), form.getlist("kod")) if k}
    return _inlasningssteg(import_id, lambda: importmotor.koppla(import_id, kopplingar))


@app.post("/datainlasning/{import_id}/importera")
def inlasning_importera(import_id: int):
    _inlasning(import_id)
    return _inlasningssteg(import_id, lambda: importmotor.importera(import_id))


@app.post("/datainlasning/{import_id}/avbryt")
def inlasning_avbryt(import_id: int):
    _inlasning(import_id)
    importmotor.avbryt(import_id)
    return RedirectResponse("/datainlasning", status_code=303)


@app.get("/datainlasning/{import_id}/fel.csv")
def inlasning_felrapport(import_id: int):
    imp = _inlasning(import_id)
    rader = ["Rad;Fastighet;Fel"] + [f"{r['radnr']};{r['data']['fastighet'].replace(';', ',')};{r['meddelande'].replace(';', ',')}"
                                     for r in importmotor.rader(import_id, "fel", grans=1_000_000)]
    return StreamingResponse(io.BytesIO(("\ufeff" + "\r\n".join(rader)).encode("utf-8")), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="Felrapport-inlasning-{imp["id"]}.csv"'})


@app.get("/export.xlsx")
def export(request: Request, ar: int | None = None):
    ar = _ar(request, ar)
    inst = lagring.installningar()
    rr = _rader(ar)
    vk = "BV" if inst["vardebas"] == "bokfort" else "MV"
    wb = Workbook()
    ws = wb.active
    ws.title = "Fastigheter"
    kolumner = [("Nr", "kod"), ("Fastighet", "namn"), ("Affärsområde", "ao"), ("Byggår", "byggar"), ("Ålder", "alder"), ("Åldersklass", "klassnamn"),
                ("BOA + LOA", "boa_loa"), ("Antal lgh", "lgh"), ("Intäkter tkr", "intakter"), ("Driftsnetto exkl UH tkr", "driftsnetto"),
                ("Resultat tkr", "resultat"), ("Bokfört värde tkr", "bokfort"), ("Marknadsvärde tkr", "marknad"), ("Överskottsgrad", "og"),
                ("Krav överskottsgrad", "krav_og"), ("Gap överskottsgrad", "gap_og"), (f"Avkastning {vk}", "avk"), ("Avkastningskrav", "krav_avk"),
                ("Gap avkastning", "gap_avk"), ("Driftsnetto enligt krav ÖG tkr", "dn_krav_og"), ("Driftsnetto enligt avkastningskrav tkr", "dn_krav_avk"),
                ("Driftsnetto mot strängaste kravet tkr", "dn_mot_krav"), ("Status", "status"), ("Datakvalitet", "flaggor"), ("Anteckning", "anteckning")]
    ws.append([k[0] for k in kolumner])
    for r in rr:
        ws.append([modell.STATUS[r["status"]] if f == "status" else ", ".join(r["flaggor"]) if f == "flaggor" else r.get(f) for _, f in kolumner])
    procent = {i for i, (_, f) in enumerate(kolumner, start=1) if f in ("og", "krav_og", "gap_og", "avk", "krav_avk", "gap_avk")}
    belopp = {i for i, (rubrik, _) in enumerate(kolumner, start=1) if rubrik.endswith("tkr")}
    for rad in ws.iter_rows(min_row=2):
        for c in rad:
            if c.column in procent:
                c.number_format = "0.0%"
            elif c.column in belopp:
                c.number_format = "#,##0"
    ws2 = wb.create_sheet("Affärsområden")
    ws2.append(["Affärsområde", "Fastigheter", "Intäkter tkr", "Driftsnetto tkr", "Bokfört värde tkr", "Marknadsvärde tkr", "Överskottsgrad prövade fastigheter",
                "Krav överskottsgrad (vägt)", f"Avkastning {vk} prövade fastigheter", "Avkastningskrav (vägt)", "Når kraven", "Når ett av kraven", "Når inte kraven",
                "Ej bedömd", "Underskott mot krav tkr"])
    grupper = [(a, [r for r in rr if r["ao"] == a]) for a in modell.ao_ordning(rr)] + [("Totalt", rr)]
    for namn, grupp in grupper:
        s = modell.summera(grupp)
        ws2.append([namn, s["antal"], s["intakter"], s["driftsnetto"], s["bokfort"], s["marknad"], s["og_provad"], s["krav_og"], s["avk_provad"], s["krav_avk"],
                    s["status"]["gron"], s["status"]["gul"], s["status"]["rod"], s["status"]["ingen"], s["underskott"]])
    for rad in ws2.iter_rows(min_row=2):
        for c in rad:
            c.number_format = "0.0%" if c.column in (7, 8, 9, 10) else "#,##0" if c.column in (3, 4, 5, 6, 15) else c.number_format
    for blad in (ws, ws2):
        for c in blad[1]:
            c.font = Font(bold=True)
        blad.freeze_panes = "A2"
        for kol in blad.columns:
            blad.column_dimensions[kol[0].column_letter].width = min(max(len(str(c.value or "")) for c in kol[:40]) + 2, 50)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="Fastighetsportfolj-{ar}.xlsx"'})
