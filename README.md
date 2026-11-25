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
auktoriseringskod med PKCE, samma flöde som Styrning). Utan inställningarna saknar appen inloggning.

Behörigheter delas ut i appen under *Användare och behörigheter* (bara för administratörer), inte i Entra ID:

- **Ingen åtkomst** – alla som loggar in första gången. Ser ingenting förrän en administratör ger behörighet.
- **Läsare** – ser allt och kan exportera, ändrar ingenting.
- **Redigerare** – kan även ändra krav, byggår, anteckningar, kopplingar och läsa in underlagen på nytt.
- **Administratör** – kan även dela ut behörigheter. Adresserna i `ADMIN_EPOST` är alltid administratörer.

Rollen kontrolleras på servern vid varje anrop och sparas i tabellen `anvandare` (SQLite, volymen `portfoljdata`).
Vem som över huvud taget kan logga in styrs i Entra ID: företagsappen med *Tilldelning krävs*.

Appregistreringen: plattform *Webb*, omdirigerings-URI `https://fastighetsportfolj.hfab.se/auth/callback`,
utloggnings-URL `https://fastighetsportfolj.hfab.se/utloggad`, delegerade behörigheter `openid`, `profile`, `email`.
Sessionen gäller 10 timmar (`SESSION_TIMMAR`).

## Flikarna på fastigheten

Fastighetssidan har flikarna Översikt, Ekonomi, Hyra, Energi & media, Drift, Underhåll & investering och Kund & uthyrning.
Vilka fält varje flik visar står i `app/portfolj/flikar.py`; fält utan datakälla visas tomma med texten *Data saknas*.
Flikarna är en förhandsvisning som bara administratörer ser, tills en administratör väljer *Visa för alla* under
*Användare och behörigheter*. Övriga ser fastighetssidan som förut.

## Datainläsning

Under *Datainläsning* (bara administratörer) läses Excel och CSV in till flikarna: Energi & media, Ekonomi, Hyra,
Drift och felanmälningar, Underhåll och åtgärder samt Kund & uthyrning. Flödet är: välj datatyp och fil, kontrollera
kolumnerna, förhandsgranska nya, ändrade, oförändrade och felaktiga rader, godkänn. Inget sparas före godkännandet.

- Kolumner, alternativa rubriknamn och vad som gör en rad unik står i `app/portfolj/datatyper.py`. En tom mall hämtas på sidan.
- `app/portfolj/importmotor.py` tolkar (svenska decimaltal, perioder, datum), validerar och skriver i en transaktion.
  En tom cell skriver inte över ett värde, inget tas bort för att det saknas i filen, och samma fil två gånger ger inga dubbletter.
- Fastigheten anges med nummer eller namn. Värden som inte känns igen (t.ex. energisystemets eget ID) kopplas till en
  fastighet i förhandsgranskningen; kopplingen sparas i tabellen `externref` och används nästa gång.
- Nyckeltalen på flikarna räknas i `app/portfolj/omraden.py` ur de inlästa raderna (tabellerna `d_energi`, `d_ekonomi` …).
  Belopp i filerna är kronor. Varje inläsning finns kvar i historiken, och filen sparas i volymen `portfoljdata`.
- Tester: `python -m unittest discover -s tests` i mappen `app`.

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
