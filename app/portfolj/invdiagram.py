"""KOPIA av Styrnings web/investeringsdiagram.py (importer och talformat ändrade) – håll den lika.

Diagram för Investeringsanalys (SVG ritade på servern, som resultatdiagrammet).

Varje stapel och tidplansrad har en <title> som visas vid hovring, och värden står utskrivna,
så att färgen aldrig ensam bär betydelsen. Tabeller med samma siffror finns på sidan.
"""
from datetime import date

from markupsafe import Markup, escape

from . import invanalys as ia


def fmt_tal(v, d=1):
    """Svenskt talformat, som i resten av appen."""
    s = f"{v:,.{d}f}".replace(",", " ").replace(".", ",")
    if s.lstrip("-").strip("0,") == "":
        s = s.lstrip("-")
    return s.replace("-", "−")


def _mkr(tkr: float) -> float:
    return tkr / 1000


def investeringar(per_ar: list[tuple[int, float, float]], valt_ar: int, bredd: int = 720, hojd: int = 260) -> Markup:
    """Staplade staplar per år: nyproduktion i botten och förnyelse ovanpå (mkr)."""
    hi = max(_mkr(n + f) for _, n, f in per_ar) * 1.15 or 1
    vx, hx, ov, nv = 48, 8, 18, 30
    steg = (bredd - vx - hx) / len(per_ar)
    sb = min(52, steg * 0.6)
    y = lambda v: ov + (hi - v) / hi * (hojd - ov - nv)  # noqa: E731
    d = [f'<svg class="invdiagram" viewBox="0 0 {bredd} {hojd}" role="img" aria-label="Investeringar per år och kategori">']
    for t in range(5):
        v = hi * t / 4
        d.append(f'<line x1="{vx}" x2="{bredd - hx}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="rutnat"/>'
                 f'<text x="{vx - 8}" y="{y(v) + 4:.1f}" class="axel" text-anchor="end">{fmt_tal(v, 0)}</text>')
    for i, (ar, ny, fo) in enumerate(per_ar):
        cx = vx + steg * (i + .5)
        n, f = _mkr(ny), _mkr(fo)
        valt = " valt" if ar == valt_ar else ""
        if valt:
            d.append(f'<rect class="valt-ar" x="{cx - steg / 2:.1f}" y="{ov - 6}" width="{steg:.1f}" height="{hojd - ov - nv + 6}"/>')
        d.append(f'<g class="stapelgrupp"><title>{ar}: nyproduktion {fmt_tal(n)} mkr, förnyelse {fmt_tal(f)} mkr, '
                 f'totalt {fmt_tal(n + f)} mkr</title>')
        bas = y(0)
        if n > 0:
            d.append(f'<rect class="seg nyproduktion" x="{cx - sb / 2:.1f}" y="{y(n):.1f}" width="{sb:.1f}" height="{bas - y(n):.1f}" rx="0"/>')
        if f > 0:
            topp = y(n + f)
            d.append(f'<rect class="seg fornyelse" x="{cx - sb / 2:.1f}" y="{topp:.1f}" width="{sb:.1f}" '
                     f'height="{max(y(n) - topp - 2, 0):.1f}" rx="3"/>')
        d.append(f'<rect class="traff" x="{cx - steg / 2:.1f}" y="{ov}" width="{steg:.1f}" height="{hojd - ov - nv}"/></g>'
                 f'<text x="{cx:.1f}" y="{y(n + f) - 7:.1f}" class="varde" text-anchor="middle">{fmt_tal(n + f, 0)}</text>'
                 f'<text x="{cx:.1f}" y="{hojd - 10}" class="axel ar{valt}" text-anchor="middle">{ar}</text>')
    d.append(f'<line x1="{vx}" x2="{bredd - hx}" y1="{y(0):.1f}" y2="{y(0):.1f}" class="baslinje"/></svg>')
    return Markup("".join(d))


def resultatpaverkan(per_ar: list[tuple[int, float]], valt_ar: int, bredd: int = 720, hojd: int = 230) -> Markup:
    """Påverkan på resultatkravet per år (mkr): under noll belastar projekten resultatet, över noll bidrar de."""
    varden = [_mkr(v) for _, v in per_ar]
    hi, lo = max(max(varden), 0) * 1.2 or 1, min(min(varden), 0) * 1.2
    vx, hx, ov, nv = 48, 8, 20, 30
    steg = (bredd - vx - hx) / len(per_ar)
    sb = min(52, steg * 0.6)
    y = lambda v: ov + (hi - v) / (hi - lo) * (hojd - ov - nv)  # noqa: E731
    d = [f'<svg class="invdiagram" viewBox="0 0 {bredd} {hojd}" role="img" aria-label="Påverkan på resultatkravet per år">']
    for v in (lo, lo / 2, 0, hi / 2, hi):
        if v == 0 or abs(v) > 0.01:
            d.append(f'<line x1="{vx}" x2="{bredd - hx}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="rutnat"/>'
                     f'<text x="{vx - 8}" y="{y(v) + 4:.1f}" class="axel" text-anchor="end">{fmt_tal(v, 0)}</text>')
    for i, ((ar, _), v) in enumerate(zip(per_ar, varden)):
        cx = vx + steg * (i + .5)
        valt = " valt" if ar == valt_ar else ""
        if valt:
            d.append(f'<rect class="valt-ar" x="{cx - steg / 2:.1f}" y="{ov - 6}" width="{steg:.1f}" height="{hojd - ov - nv + 6}"/>')
        top, bot = (y(v), y(0)) if v >= 0 else (y(0), y(v))
        slag = "plus" if v >= 0 else "minus"
        d.append(f'<g><title>{ar}: {"+" if v > 0 else ""}{fmt_tal(v)} mkr på resultatet</title>'
                 f'<rect class="seg {slag}" x="{cx - sb / 2:.1f}" y="{top:.1f}" width="{sb:.1f}" height="{max(bot - top, 1):.1f}" rx="3"/>'
                 f'<rect class="traff" x="{cx - steg / 2:.1f}" y="{ov}" width="{steg:.1f}" height="{hojd - ov - nv}"/></g>'
                 f'<text x="{cx:.1f}" y="{(top - 6) if v >= 0 else (bot + 14):.1f}" class="varde" text-anchor="middle">'
                 f'{"+" if v > 0 else ""}{fmt_tal(v, 1)}</text>'
                 f'<text x="{cx:.1f}" y="{hojd - 10}" class="axel ar{valt}" text-anchor="middle">{ar}</text>')
    d.append(f'<line x1="{vx}" x2="{bredd - hx}" y1="{y(0):.1f}" y2="{y(0):.1f}" class="baslinje"/></svg>')
    return Markup("".join(d))


def tidplan(projekt: list[dict], valt_ar: int, bredd: int = 960) -> Markup:
    """Tidplan per projekt från projektstart till färdigställande (avyttring: försäljningsdatum)."""
    a0, a1 = ia.TIDPLANAR
    vx, hx, radh, ov = 230, 12, 26, 28
    hojd = ov + radh * len(projekt) + 8
    t0, t1 = date(a0, 1, 1).toordinal(), date(a1, 12, 31).toordinal()
    x = lambda d_: vx + (d_.toordinal() - t0) / (t1 - t0) * (bredd - vx - hx)  # noqa: E731
    d = [f'<svg class="invdiagram tidplan" viewBox="0 0 {bredd} {hojd}" role="img" aria-label="Tidplan för projekten">']
    for ar in range(a0, a1 + 1):
        xa, xb = x(date(ar, 1, 1)), x(date(ar, 12, 31))
        if ar == valt_ar:
            d.append(f'<rect class="valt-ar" x="{xa:.1f}" y="{ov - 18}" width="{xb - xa:.1f}" height="{hojd - ov + 14}"/>')
        d.append(f'<line x1="{xa:.1f}" x2="{xa:.1f}" y1="{ov - 6}" y2="{hojd - 4}" class="rutnat"/>'
                 f'<text x="{(xa + xb) / 2:.1f}" y="{ov - 10}" class="axel ar{" valt" if ar == valt_ar else ""}" text-anchor="middle">{ar}</text>')
    for i, p in enumerate(projekt):
        yy = ov + radh * i
        namn = f'{p["kod"]} {p["namn"]}'
        d.append(f'<text x="{vx - 10}" y="{yy + radh / 2 + 4:.1f}" class="radnamn" text-anchor="end">{escape(namn[:34])}</text>')
        klar = date.fromisoformat(p["klar"]) if p["klar"] else None
        start = date.fromisoformat(p["start"]) if p["start"] else None
        if p["typ"] == "avyttring" and klar:
            cx, cy = x(klar), yy + radh / 2
            d.append(f'<g><title>{escape(p["namn"])}: försäljning {klar:%Y-%m-%d}, '
                     f'försäljningsvolym {fmt_tal(_mkr(p["volym"]))} mkr</title>'
                     f'<path class="seg avyttring" d="M{cx:.1f} {cy - 7:.1f} L{cx + 7:.1f} {cy:.1f} L{cx:.1f} {cy + 7:.1f} L{cx - 7:.1f} {cy:.1f} Z"/>'
                     f'<text x="{cx + 12:.1f}" y="{cy + 4:.1f}" class="axel">Försäljning {klar:%Y-%m}</text></g>')
            continue
        if not (start and klar):
            continue
        xa, xb = max(x(start), vx), x(min(klar, date(a1, 12, 31)))
        d.append(f'<g><title>{escape(p["namn"])} ({ia.TYPER[p["typ"]]}): {start:%Y-%m} – {klar:%Y-%m}, '
                 f'projektvolym {fmt_tal(_mkr(p["volym"]))} mkr</title>'
                 f'<rect class="seg {p["typ"]}" x="{xa:.1f}" y="{yy + 6}" width="{max(xb - xa, 3):.1f}" height="{radh - 12}" rx="4"/>'
                 f'<rect class="traff" x="{vx - 220}" y="{yy}" width="{bredd - vx + 220}" height="{radh}"/></g>')
    d.append("</svg>")
    return Markup("".join(d))


def projektbudget(per_ar: list[tuple[int, dict]], slag: dict, bredd: int = 720, hojd: int = 260) -> Markup:
    """Projektportföljen (inte ur Styrning): budget per år i mnkr, staplad per kostnadsslag. per_ar i kr."""
    varden = [(ar, [(s, v[s] / 1e6) for s in slag]) for ar, v in per_ar]
    hi = max([sum(x for _, x in v) for _, v in varden] + [0.001]) * 1.15
    vx, hx, ov, nv = 48, 8, 18, 30
    steg = (bredd - vx - hx) / max(len(varden), 1)
    sb = min(64, steg * 0.6)
    y = lambda v: ov + (hi - v) / hi * (hojd - ov - nv)  # noqa: E731
    d = [f'<svg class="invdiagram" viewBox="0 0 {bredd} {hojd}" role="img" aria-label="Budget per år och kostnadsslag">']
    for t in range(5):
        v = hi * t / 4
        d.append(f'<line x1="{vx}" x2="{bredd - hx}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="rutnat"/>'
                 f'<text x="{vx - 8}" y="{y(v) + 4:.1f}" class="axel" text-anchor="end">{fmt_tal(v, 0)}</text>')
    for i, (ar, delar) in enumerate(varden):
        cx = vx + steg * (i + .5)
        total = sum(x for _, x in delar)
        text = ", ".join(f"{slag[s][1]} {fmt_tal(x)} mnkr" for s, x in delar)
        d.append(f'<g><title>{ar}: {text}, totalt {fmt_tal(total)} mnkr</title>')
        niva = 0.0
        for s, x in delar:
            if x > 0:
                topp, botten = y(niva + x), y(niva)
                d.append(f'<rect class="seg {s}" x="{cx - sb / 2:.1f}" y="{topp:.1f}" width="{sb:.1f}" height="{max(botten - topp - 2, 1):.1f}" rx="2"/>')
                niva += x
        d.append(f'<rect class="traff" x="{cx - steg / 2:.1f}" y="{ov}" width="{steg:.1f}" height="{hojd - ov - nv}"/></g>'
                 f'<text x="{cx:.1f}" y="{y(total) - 7:.1f}" class="varde" text-anchor="middle">{fmt_tal(total, 1)}</text>'
                 f'<text x="{cx:.1f}" y="{hojd - 10}" class="axel ar" text-anchor="middle">{ar}</text>')
    d.append(f'<line x1="{vx}" x2="{bredd - hx}" y1="{y(0):.1f}" y2="{y(0):.1f}" class="baslinje"/></svg>')
    return Markup("".join(d))
