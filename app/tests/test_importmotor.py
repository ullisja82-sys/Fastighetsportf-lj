"""Importmotorns regler. Körs med: python -m unittest discover -s tests (i mappen app)."""
import csv
import os
import tempfile
import unittest
from datetime import date, datetime

os.environ["DATA_DIR"] = tempfile.mkdtemp()

from portfolj import importmotor as im, omraden  # noqa: E402

RUBRIK = ["Fastighet", "Mätpunkt", "Period", "Media", "Förbrukning", "Enhet", "Kostnad"]


def fil(rader, rubrik=RUBRIK, namn="energi.csv") -> bytes:
    import io
    buf = io.StringIO()
    csv.writer(buf, delimiter=";").writerows([rubrik, *rader])
    return buf.getvalue().encode("utf-8")


def las_in(rader, **kw) -> dict:
    i = im.ny_inlasning("energi", "energi.csv", fil(rader, **kw), "test")
    return im.importera(i) if im.inlasning(i)["nya"] or im.inlasning(i)["andrade"] else im.inlasning(i)


def antal() -> int:
    with im.anslut() as con:
        return con.execute("SELECT COUNT(*) FROM d_energi").fetchone()[0]


class Tolkning(unittest.TestCase):
    def test_svenska_tal(self):
        self.assertEqual(im.tolka_tal("1 234,56"), 1234.56)
        self.assertEqual(im.tolka_tal("1.234,56"), 1234.56)
        self.assertEqual(im.tolka_tal("−12,5"), -12.5)
        self.assertEqual(im.tolka_tal("1 000 kr"), 1000)
        self.assertEqual(im.tolka_tal(0), 0)
        with self.assertRaises(ValueError):
            im.tolka_tal("tolv")

    def test_perioder(self):
        for ra, vantat in [("2026", "2026"), (2026, "2026"), (2026.0, "2026"), ("2026-03", "2026-03"), ("2026-1", "2026-01"), ("2026-12", "2026-12"), ("2026/3", "2026-03"), ("2026 - 1", "2026-01"), ("1-2026", "2026-01"), (202603, "2026-03"), ("mars 2026", "2026-03"),
                           ("mar-26", "2026-03"), ("03/2026", "2026-03"), (datetime(2026, 3, 1), "2026-03"), (date(2026, 3, 15), "2026-03-15"),
                           ("2026-03-15", "2026-03-15")]:
            self.assertEqual(im.tolka_period(ra), vantat, ra)
        with self.assertRaises(ValueError):
            im.tolka_period("snart")
        with self.assertRaises(ValueError):
            im.tolka_period("2026-13")

    def test_datum_och_andel(self):
        self.assertEqual(im.tolka_datum("15.03.2026"), "2026-03-15")
        self.assertEqual(im.tolka_datum("2026-03-15 08:00"), "2026-03-15")
        self.assertAlmostEqual(im.tolka_andel("3,5 %"), 0.035)
        self.assertAlmostEqual(im.tolka_andel(3.5), 0.035)
        self.assertAlmostEqual(im.tolka_andel(0.035), 0.035)

    def test_rubriker_med_andra_namn(self):
        m = im.foresla_mappning(im.DATATYPER["energi"], [("Blad1", [["Rapport"], [], ["Fastighetsnr", "Mätar-ID", "Månad", "Energislag", "kWh", "Kostnad kr"]])])
        self.assertEqual(m["rubrikrad"], 2)
        self.assertEqual(set(m["kolumner"].values()), {"fastighet", "matpunkt", "_manad", "media", "forbrukning", "kostnad"})


    def test_rubrikrad_med_datarader_som_liknar_rubriker(self):
        blad = [("Sheet1", [["Nodtyp", "Visningsnamn", "Rapportslag", "Period", "Förbrukning (Normalårskorrigering)", "Enhet förbrukning (Normalårskorrigering)"],
                            ["Fastighet", "0110 Framtiden 6", "Fastighetsel", "2026-1", 1234.5, "kWh"]])]
        m = im.foresla_mappning(im.DATATYPER["energi"], blad)
        self.assertEqual(m["rubrikrad"], 0)
        self.assertEqual(m["kolumner"], {"1": "fastighet", "2": "media", "3": "period", "4": "forbrukning", "5": "enhet"})


class Inlasning(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        im.synka_fastigheter([("2232", "Valutan 3. Vallås Centrum 25", "Vallås"), ("1101", "Kärnan 1", "Centrum")])

    def setUp(self):
        with im.anslut() as con:
            con.execute("DELETE FROM d_energi")

    def test_ny_andrad_oforandrad(self):
        rader = [["2232", "M1", "2026-01", "El", "1 000,5", "kWh", "1500"], ["2232 Valutan 3", "M1", "2026-02", "el", "900", "kWh", "1400"]]
        imp = las_in(rader)
        self.assertEqual((imp["nya"], imp["andrade"], imp["fel"]), (2, 0, 0))
        self.assertEqual(antal(), 2)
        imp = las_in(rader)                                   # samma fil igen: inga dubbletter
        self.assertEqual((imp["nya"], imp["andrade"], imp["oforandrade"]), (0, 0, 2))
        self.assertEqual(antal(), 2)
        imp = las_in([["2232", "M1", "2026-01", "El", "1100", "kWh", "1500"]])   # ändrat värde; februari saknas i filen
        self.assertEqual((imp["nya"], imp["andrade"]), (0, 1))
        self.assertEqual(antal(), 2)                          # det som saknas i filen tas inte bort

    def test_tom_cell_skriver_inte_over(self):
        las_in([["2232", "M1", "2026-01", "El", "1000", "kWh", "1500"]])
        imp = las_in([["2232", "M1", "2026-01", "El", "", "", ""]])
        self.assertEqual(imp["oforandrade"], 1)
        las_in([["2232", "M1", "2026-01", "El", "0", "", ""]])  # 0 är ett värde, inte tomt
        with im.anslut() as con:
            rad = con.execute("SELECT forbrukning, kostnad FROM d_energi").fetchone()
        self.assertEqual((rad["forbrukning"], rad["kostnad"]), (0, 1500))

    def test_fel_hoppas_over(self):
        i = im.ny_inlasning("energi", "e.csv", fil([["9999", "M1", "2026-01", "El", "10", "kWh", "1"], ["2232", "M1", "2026-01", "Ved", "10", "kWh", "1"],
                                                    ["2232", "M1", "2026-01", "El", "tio", "kWh", "1"], ["2232", "M1", "2026-01", "El", "10", "kWh", "1"],
                                                    ["2232", "M1", "2026-01", "El", "11", "kWh", "1"], ["", "", "", "", "", "", ""]]), "test")
        imp = im.inlasning(i)
        self.assertEqual((imp["rader"], imp["nya"], imp["fel"]), (5, 1, 4))
        fel = " | ".join(r["meddelande"] for r in im.rader(i, "fel"))
        for text in ("Okänd fastighet", "okänt värde", "inte ett tal", "Dubblett av rad 5"):
            self.assertIn(text, fel)
        self.assertEqual(antal(), 0)                          # inget skrivs före godkännandet
        im.koppla(i, {"9999": "1101"})                        # källans ID kopplas till en fastighet
        self.assertEqual(im.inlasning(i)["nya"], 2)

    def test_inledande_nolla_och_streck(self):
        im.synka_fastigheter([("110", "Framtiden 6. Engelbrektsg 59", "Centrum")])
        imp = las_in([["0110 Framtiden 6", "", "2026-1", "Fastighetsel", "1234,5", "kWh", ""], ["0110 Framtiden 6", "", "2026-2", "Fastighetsel", "-", "kWh", ""]])
        self.assertEqual((imp["nya"], imp["fel"]), (2, 0))
        with im.anslut() as con:
            self.assertEqual([r["forbrukning"] for r in con.execute("SELECT forbrukning FROM d_energi ORDER BY period")], [1234.5, None])

    def test_tva_noder_pa_samma_fastighet(self):
        imp = las_in([["2232 Valutan Höghus", "", "2026-1", "El", "100", "kWh", ""], ["2232 Valutan 3 högh_701", "", "2026-1", "El", "50", "kWh", ""]])
        self.assertEqual((imp["nya"], imp["fel"]), (2, 0))
        with im.anslut() as con:
            self.assertEqual(omraden.varden(con, im.fastighets_id("2232"), 2026, 100, 1)["el_kwh"], 150)

    def test_period_i_tva_kolumner_och_nyckeltal(self):
        rubrik = ["Fastighet", "År", "Månad", "Media", "Förbrukning", "Enhet", "Kostnad"]
        las_in([["2232", 2025, "jan", "Värme", "10", "MWh", "8000"], ["2232", 2026, 1, "Värme", "12", "MWh", "10800"],
                ["2232", 2026, 2, "Värme", "11", "MWh", "9900"], ["2232", 2026, 1, "Vatten", "50", "m3", "1500"]], rubrik=rubrik)
        with im.anslut() as con:
            v = omraden.varden(con, im.fastighets_id("2232"), 2026, 1000, 10)
        self.assertEqual(v["varme_kwh"], 23000)
        self.assertEqual(v["varme_kwh_kvm"], 23)
        self.assertAlmostEqual(v["varme_kostnad"], 20.7)
        self.assertEqual(v["vatten_m3"], 50)
        self.assertNotIn("el_kwh", v)                         # inget inläst är inte samma sak som noll
        # januari mot januari: 2 MWh mer till 2025 års pris 0,8 kr/kWh = 1,6 tkr; priset 0,8 -> 0,9 på 12 MWh = 1,2 tkr
        self.assertAlmostEqual(v["energi_forbrukningseffekt"], 1.6)
        self.assertAlmostEqual(v["energi_priseffekt"], 1.2)


if __name__ == "__main__":
    unittest.main()
