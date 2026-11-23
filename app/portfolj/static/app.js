// Fastighetslistan: filter, sortering och summarad som följer urvalet.
(() => {
  const tabell = document.getElementById('fastighetstabell');
  if (!tabell) return;
  const kropp = tabell.tBodies[0];
  const rader = [...kropp.rows];
  const el = id => document.getElementById(id);
  const sok = el('f-sok'), ao = el('f-ao'), klass = el('f-klass'), status = el('f-status'), flagga = el('f-flagga'), proj = el('f-projekt');
  const tal = (v, d = 0) => v.toLocaleString('sv-SE', { minimumFractionDigits: d, maximumFractionDigits: d });
  const pct = (t, n) => n > 0 ? tal(t / n * 100, 1) + ' %' : '–';

  function filtrera() {
    const q = sok.value.trim().toLowerCase();
    const s = { n: 0, int: 0, dn: 0, varde: 0, ogint: 0, ogdn: 0, avkdn: 0, avkv: 0, under: 0 };
    rader.forEach(r => {
      const d = r.dataset;
      const ok = (!q || d.sok.includes(q)) && (!ao.value || d.ao === ao.value) && (klass.value === '' || d.klass === klass.value)
        && (!status.value || d.status === status.value) && (!flagga.checked || d.flagga === '1')
        && (!proj.value || (proj.value === 'alla' ? d.projekt !== '' : proj.value === 'inv' ? d.inv === '1' : d.projekt === proj.value));
      r.hidden = !ok;
      if (!ok) return;
      s.n++;
      for (const k of Object.keys(s)) if (k !== 'n') s[k] += parseFloat(d[k]) || 0;
    });
    el('f-raknare').textContent = s.n + ' av ' + rader.length + ' fastigheter';
    el('s-antal').textContent = 'Summa ' + s.n + ' fastigheter';
    el('s-int').textContent = tal(s.int);
    el('s-dn').textContent = tal(s.dn);
    el('s-og').textContent = pct(s.ogdn, s.ogint);
    el('s-varde').textContent = tal(s.varde);
    el('s-avk').textContent = pct(s.avkdn, s.avkv);
    el('s-under').textContent = s.under ? tal(s.under) : '–';
  }
  [sok, ao, klass, status, flagga, proj].forEach(e => e.addEventListener('input', filtrera));
  // Undermenyn under Fastigheter följer valet av affärsområde i filtret
  const huvud = document.querySelector('.nav a[href="/fastigheter"]');
  ao.addEventListener('input', () => {
    document.querySelectorAll('#undernav-fastigheter a').forEach(a => a.classList.toggle('aktiv', a.dataset.ao === ao.value));
    if (huvud) { huvud.classList.toggle('aktiv', !ao.value); huvud.classList.toggle('oppen', !!ao.value); }
  });

  tabell.querySelectorAll('th[data-sort]').forEach((th, i) => th.addEventListener('click', e => {
    if (e.target.closest('.hjalp')) return;  // frågetecknet öppnar förklaringen, sorterar inte
    const fallande = th.classList.contains('stigande');
    tabell.querySelectorAll('th').forEach(x => x.classList.remove('stigande', 'fallande'));
    th.classList.add(fallande ? 'fallande' : 'stigande');
    const num = th.dataset.sort === 'num';
    const varde = r => r.cells[i].dataset.v;
    rader.sort((a, b) => {
      const x = varde(a), y = varde(b);
      if (x === '' || y === '') return (x === '') - (y === '');  // tomma sist oavsett riktning
      const j = num ? parseFloat(x) - parseFloat(y) : x.localeCompare(y, 'sv');
      return fallande ? -j : j;
    });
    rader.forEach(r => kropp.appendChild(r));
  }));
  filtrera();
})();

// Förklaringsrutor: öppnas vid frågetecknet man klickade på och stängs vid klick utanför eller Esc.
(() => {
  let knapp = null;
  document.addEventListener('click', e => { const k = e.target.closest('.hjalp[popovertarget]'); if (k) knapp = k; }, true);
  document.querySelectorAll('.hjalpruta').forEach(ruta => ruta.addEventListener('toggle', e => {
    if (e.newState !== 'open' || !knapp) return;
    const k = knapp.getBoundingClientRect(), b = ruta.offsetWidth, h = ruta.offsetHeight;
    const v = Math.max(12, Math.min(k.left + k.width / 2 - b / 2, innerWidth - b - 12));
    const under = k.bottom + 8 + h <= innerHeight - 12 || k.top - 8 - h < 12;
    ruta.style.left = v + 'px';
    ruta.style.top = Math.max(12, under ? k.bottom + 8 : k.top - 8 - h) + 'px';
  }));
})();

// Tillbakaknappen: leder till sidan man kom från i appen. Besökta sidor minns per flik; går man tillbaka till en
// tidigare sida kortas historiken, och en sida man just sparat på räknas inte som en ny sida.
(() => {
  const knapp = document.getElementById('tillbakaknapp');
  if (!knapp) return;
  let stack = [];
  try { stack = JSON.parse(sessionStorage.getItem('sidstack') || '[]'); } catch (e) { return; }
  const q = new URLSearchParams(location.search);
  q.delete('sparat'); q.delete('last');
  const har = location.pathname + (q.toString() ? '?' + q : '');
  const i = stack.lastIndexOf(har);
  if (i >= 0) stack.length = i + 1; else stack.push(har);
  stack = stack.slice(-50);
  try { sessionStorage.setItem('sidstack', JSON.stringify(stack)); } catch (e) {}
  if (stack.length > 1) { knapp.href = stack[stack.length - 2]; knapp.hidden = false; }
})();

// Kartan på förstasidan: en prick per fastighet, färgad efter status mot kraven, och romber för investeringsplanen.
// Kryssrutorna under kartan styr vad som visas; valet minns i webbläsaren.
(() => {
  const ruta = document.getElementById('karta'), data = document.getElementById('kartdata');
  if (!ruta || !data || !window.L) return;
  const punkter = JSON.parse(data.textContent);
  const inv = JSON.parse((document.getElementById('invkartdata') || { textContent: '[]' }).textContent);
  const farg = { gron: '#05806E', gul: '#d9ac00', rod: '#C31712', ingen: '#8a8a8a' };
  const namn = { gron: 'Når kraven', gul: 'Når ett av kraven', rod: 'Når inte kraven', ingen: 'Ej bedömd' };
  const text = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const karta = L.map(ruta, { scrollWheelZoom: false });
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' }).addTo(karta);
  const markeringar = [];   // { m: markering, grupp: 'gron' | … | 'nyproduktion' | …, projekt: '' | 'pagar' | 'planerat' }

  // Röda sist så att de hamnar överst där fastigheter ligger tätt
  const ordning = ['ingen', 'gron', 'gul', 'rod'];
  punkter.sort((a, b) => ordning.indexOf(a.status) - ordning.indexOf(b.status)).forEach(p => {
    const m = L.circleMarker([p.lat, p.lon], { radius: p.projekt ? 9 : 8, color: p.projekt === 'pagar' ? '#1D1D1D' : p.projekt ? '#2761A6' : '#fff', weight: p.projekt ? 3 : 2, fillColor: farg[p.status] || farg.ingen, fillOpacity: .95 })
      .bindTooltip(text(p.kod + ' ' + p.namn))
      .bindPopup('<div class="kartruta"><b>' + text(p.kod + ' ' + p.namn) + '</b>' + text(p.ao) + ' · ' + namn[p.status]
        + '<dl><dt>Överskottsgrad</dt><dd>' + text(p.og) + '</dd><dt>Avkastning</dt><dd>' + text(p.avk) + '</dd></dl>'
        + (p.projekt ? '<div class="kartprojekt"><b>' + (p.projekt === 'pagar' ? 'Projekt pågår' : 'Projekt planerat') + '</b>' + p.projektnamn.map(text).join('<br>') + '</div>' : '')
        + '<a href="/fastighet/' + encodeURIComponent(p.kod) + '">Öppna fastigheten</a></div>');
    markeringar.push({ m, grupp: p.status in farg ? p.status : 'ingen', projekt: p.projekt || '' });
  });

  // Investeringsplanen: romb med bokstav. Nyproduktion (N) på projektets plats, förnyelse (F) och avyttring (A) vid fastigheten.
  const platser = {};
  inv.forEach(p => { const k = p.typ + '|' + p.lat.toFixed(5) + '|' + p.lon.toFixed(5); (platser[k] = platser[k] || []).push(p); });
  Object.values(platser).forEach(lista => {
    const p = lista[0], ny = p.typ === 'nyproduktion';
    const ikon = L.divIcon({ className: '', html: '<span class="invmarke ' + p.typ + '"><b>' + p.typnamn[0] + '</b></span>',
      iconSize: [26, 26], iconAnchor: ny ? [13, 13] : [-3, 29] });   // F och A snett ovanför fastighetens prick
    const m = L.marker([p.lat, p.lon], { icon: ikon, zIndexOffset: ny ? 600 : 400 })
      .bindTooltip(p.typnamn + ': ' + lista.map(x => text(x.namn)).join(', '))
      .bindPopup('<div class="kartruta">' + lista.map(x => '<b>' + text(x.namn) + '</b>' + x.typnamn + ' i investeringsportföljen'
        + '<dl><dt>' + (x.typ === 'avyttring' ? 'År' : 'Period') + '</dt><dd>' + text(x.period) + '</dd><dt>'
        + (x.typ === 'avyttring' ? 'Försäljningspris' : 'Investering') + '</dt><dd>' + text(x.volym) + '</dd></dl>'
        + (x.fastigheter.length ? '<div class="kartprojekt">' + x.fastigheter.map(text).join('<br>') + '</div>' : '')).join('') + '</div>');
    markeringar.push({ m, grupp: p.typ, projekt: null });
  });

  // Kryssrutorna: data-kartlager="gron" osv. visar eller döljer en grupp; data-kartfilter="projekt" visar bara fastigheter med byggprojekt
  const rutor = [...document.querySelectorAll('[data-kartlager], [data-kartfilter]')];
  let sparat = {};
  try { sparat = JSON.parse(localStorage.getItem('kartval') || '{}'); } catch (e) {}
  rutor.forEach(r => { const k = r.dataset.kartlager || 'filter-' + r.dataset.kartfilter; if (k in sparat) r.checked = !!sparat[k]; });
  function visa() {
    const pa = {}, val = {};
    rutor.forEach(r => { const k = r.dataset.kartlager || 'filter-' + r.dataset.kartfilter; val[k] = r.checked; if (r.dataset.kartlager) pa[k] = r.checked; });
    let antal = 0;
    markeringar.forEach(x => {
      const syns = pa[x.grupp] !== false && !(val['filter-projekt'] && x.projekt === '');
      if (syns) { x.m.addTo(karta); if (x.projekt !== null) antal++; } else x.m.remove();
    });
    const rak = document.getElementById('kartantal');
    if (rak) rak.textContent = antal + ' av ' + punkter.length + ' fastigheter visas';
    try { localStorage.setItem('kartval', JSON.stringify(val)); } catch (e) {}
  }
  rutor.forEach(r => r.addEventListener('change', visa));
  document.querySelectorAll('[data-kartalla]').forEach(k => k.addEventListener('click', () => {
    rutor.forEach(r => { r.checked = r.dataset.kartlager ? k.dataset.kartalla === '1' : false; });
    visa();
  }));
  visa();
  karta.fitBounds(L.latLngBounds(punkter.concat(inv).map(p => [p.lat, p.lon])).pad(.08));
  karta.on('click', () => karta.scrollWheelZoom.enable());   // zoom med mushjulet först efter klick, så att sidan går att rulla förbi
})();

// Projektportföljen: filter i tabellen Alla projekt, med summarad som följer urvalet.
(() => {
  const tabell = document.getElementById('projekttabell');
  if (!tabell) return;
  const rader = [...tabell.tBodies[0].rows], el = id => document.getElementById(id);
  const sok = el('p-sok'), status = el('p-status'), ao = el('p-ao'), ledare = el('p-ledare'), passerat = el('p-passerat');
  const mn = v => (v / 1e6).toLocaleString('sv-SE', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  function filtrera() {
    const q = sok.value.trim().toLowerCase(), s = { n: 0, k3: 0, inv: 0, opex: 0 };
    rader.forEach(r => {
      const d = r.dataset;
      const ok = (!q || d.sok.includes(q)) && (status.value === '' || (status.value === 'aktiva' ? d.aktiv === '1' : d.status === status.value))
        && (!ao.value || d.ao === ao.value) && (!ledare.value || d.ledare === ledare.value) && (!passerat.checked || d.passerat === '1');
      r.hidden = !ok;
      if (!ok) return;
      s.n++; s.k3 += +d.k3; s.inv += +d.inv; s.opex += +d.opex;
    });
    el('p-raknare').textContent = s.n + ' av ' + rader.length + ' projekt';
    el('ps-antal').textContent = 'Summa ' + s.n + ' projekt';
    el('ps-k3').textContent = mn(s.k3); el('ps-inv').textContent = mn(s.inv); el('ps-opex').textContent = mn(s.opex);
    el('ps-tot').textContent = mn(s.k3 + s.inv + s.opex);
  }
  [sok, status, ao, ledare, passerat].forEach(e => e.addEventListener('input', filtrera));
  // Statusrutorna överst väljer den statusen i tabellen
  document.querySelectorAll('[data-valj-status]').forEach(a => a.addEventListener('click', () => { status.value = a.dataset.valjStatus; passerat.checked = false; filtrera(); }));
  filtrera();
})();


// Läsbehörighet: formulär som sparar något stängs av (servern nekar ändå).
if (document.body.hasAttribute("data-endast-las")) {
  document.querySelectorAll('form[method="post"]').forEach(function (f) {
    f.querySelectorAll("input, select, textarea, button").forEach(function (el) { el.disabled = true; });
    var not = document.createElement("p");
    not.className = "mini dampad";
    not.textContent = "Du har läsbehörighet och kan inte ändra här.";
    f.appendChild(not);
  });
}
