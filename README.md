# HFAB Fastighetsportfölj – prototyp

Alla HFAB:s fastigheter som en portfölj. Varje fastighet prövas mot krav på avkastning och överskottsgrad
som bestäms av fastighetens ålder. Bygger på rapporten Fastighetsanalys (samma som i Styrning).

## Starta

```bash
docker compose up -d --build      # http://<server>:8405
```

Adress: **https://fastighetsportfolj.hfab.se** (HTTPS-proxyn i `hfab-drift/portal` på servern skickar vidare till port 8405).

## Inloggning via Entra ID

Kopiera `.env.example` till `.env` och fyll i `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID`, `ENTRA_CLIENT_SECRET`,
`SESSION_SECRET` och `APP_URL`; kör sedan `docker compose up -d`. Då kräver alla sidor inloggning (OpenID Connect,
auktoriseringskod med PKCE, samma flöde som Styrning men utan roller). Vem som får logga in styrs i Entra ID:
företagsappen med *Tilldelning krävs* och tilldelade användare/grupper. Utan inställningarna saknar appen inloggning.

Appregistreringen: plattform *Webb*, omdirigerings-URI `https://fastighetsportfolj.hfab.se/auth/callback`,
utloggnings-URL `https://fastighetsportfolj.hfab.se/utloggad`, delegerade behörigheter `openid`, `profile`, `email`.
Sessionen gäller 10 timmar (`SESSION_TIMMAR`).

## Underlag

Excel-filerna i `Underlag/` läses vid start (`app/portfolj/importera.py`). Varje fil är ett år och året
tas från filnamnet (`December 2025 Fastighetsanalys ….xlsx`). Lägg en ny fil i mappen och välj
*Läs in underlagen på nytt* under Underlag och datakvalitet. Finns flera filer för samma år gäller den
med senast filnamn i bokstavsordning.

Byggår, ytor, bokfört värde och marknadsvärde som saknas i ett års fil hämtas från närmaste år som har
uppgiften (2026 års fil har bara resultatkolumnerna). Raden *Odefinierat* tas med som en egen post så att
summorna stämmer med underlaget.

## Kundundersökning (AktivBo)

Exporten från AktivBo Analytics (Excel) läggs i `Kundundersökning/` och läses av `app/portfolj/kund.py`. Serviceindex och
produktindex visas på varje fastighet. AktivBo anger fastigheten med namn, så enheterna paras ihop med fastigheterna på
namnet; de som inte går att para ihop säkert kopplas för hand under *Underlag och datakvalitet*. HFAB totalt och riket
finns inte i exporten och kan läggas i `Kundundersökning/Kundundersökning.csv` (`ar;niva;kod;serviceindex;produktindex`,
niva = hfab eller riket). Finns ingen fil alls visas fiktiva siffror, tydligt märkta.

## Byggprojekt

Projektlistan (Excel-export) läggs i `Projekt/` och läses av `app/portfolj/projekt.py`; senaste filen gäller. Projekten kopplas
till fastigheten via kolumnen K-Ställe. Pågående och planerade projekt märks ut i fastighetslistan, på fastigheten och på kartan.

## Investeringsplanen

Nyproduktion, förnyelse och avyttring kommer från Styrnings investeringsanalys: `app/portfolj/investeringsplan_data.py` är en kopia
av `Styrning/app/styrning/investeringsanalys_data.py` och kopieras på nytt när planen ändras. Vilka fastigheter ett projekt gäller och
var det ligger på kartan är antaganden i `app/portfolj/investering.py`, som kan rättas under *Underlag och datakvalitet*.

## Kartan

Förstasidan visar fastigheterna på en karta (Leaflet och OpenStreetMap, ingen nyckel behövs). Adressen tas ur fastighetens
namn (`app/portfolj/plats.py`), slås upp en gång hos OpenStreetMap och sparas i appens databas. Fastigheter som inte hittas
listas under *Underlag och datakvalitet*; en egen adress för kartan kan anges på fastigheten. Appen behöver kunna nå
nominatim.openstreetmap.org, och webbläsaren tile.openstreetmap.org.

## Beräkningar (`app/portfolj/modell.py`)

- Ålder = referensår − byggår + 1 (inklusive referensåret; byggt 2013 = 14 år 2026).
- Överskottsgrad = driftsnetto exkl. underhåll / intäkter.
- Avkastning = driftsnetto exkl. underhåll / bokfört värde (kan ändras till marknadsvärde).
- Beslutade krav: upp till 14 år 3 % och 70 %, 15–30 år 4 % och 60 %, 31–50 år 6 % och 60 %,
  äldre än 50 år 10 % och 55 %. Ändras under *Krav per ålder*.
- Driftsnetto mot krav = driftsnettot minus det driftsnetto som det strängaste av de två kraven motsvarar.

## Det som registreras i appen

Kravnivåer, kompletterade byggår och anteckningar sparas i SQLite i Docker-volymen `portfoljdata`
(`app/portfolj/lagring.py`). Underlagsfilerna ändras aldrig.
