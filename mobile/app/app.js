'use strict';
/* SmartDesk mobile (by Wolf Team) – app per telefono, tablet e PC. Parla con Argo attraverso l'Apps Script
   della scuola (config.js). Con ?prova usa dati finti (finto.js) e non si collega a niente. */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const PROVA = new URLSearchParams(location.search).has('prova') || !window.SMARTDESK_SCRIPT;
const leggi = (k, d = null) => { try { const v = localStorage.getItem('sdm-' + k); return v === null ? d : JSON.parse(v); } catch { return d; } };
const scrivi = (k, v) => { try { v === null ? localStorage.removeItem('sdm-' + k) : localStorage.setItem('sdm-' + k, JSON.stringify(v)); } catch { /* niente */ } };
let S = null;      // { sessione, nome, cognome }
let DATI = null;   // assenze e richieste dal programma Personale
let BACHECA = null;

// ------------------------------------------------------------------ icone
const P = {
  home: '<path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/>',
  assenze: '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/>',
  bacheca: '<path d="M4 4h16v12H8l-4 4z"/><path d="M8 9h8M8 12h5"/>',
  profilo: '<circle cx="12" cy="8" r="4"/><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6"/>',
  sole: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  luna: '<path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z"/>',
  ok: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  scarica: '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
  esci: '<path d="M15 4h4v16h-4M10 8l-4 4 4 4M6 12h10"/>',
  aggiorna: '<path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7"/>',
  lupo: '<path d="M5 3l4 5h6l4-5 1 7 2 3-5 3-5 5-5-5-5-3 2-3z"/>',
};
const ico = (n, cls = '') => `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${P[n] || ''}</svg>`;

// ------------------------------------------------------------------ utilità
function toast(msg, errore = false) {
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'su' + (errore ? ' errore' : '');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { t.className = errore ? 'errore' : ''; }, errore ? 6000 : 2800);
}
const GIORNI = ['dom', 'lun', 'mar', 'mer', 'gio', 'ven', 'sab'];
const MESI = ['gen', 'feb', 'mar', 'apr', 'mag', 'giu', 'lug', 'ago', 'set', 'ott', 'nov', 'dic'];
const oggiIso = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
function fd(s, conGiorno = true) {
  if (!s) return '';
  const [y, m, g] = s.slice(0, 10).split('-').map(Number), d = new Date(y, m - 1, g);
  return `${conGiorno ? GIORNI[d.getDay()] + ' ' : ''}${g} ${MESI[m - 1]}${y !== new Date().getFullYear() ? ' ' + y : ''}`;
}
const num = n => (Math.round(n * 10) / 10).toString().replace('.', ',');
const periodo = x => x.inizio === x.fine ? fd(x.inizio) : `${fd(x.inizio)} → ${fd(x.fine)}`;
function livelloScadenza(iso, daFare = true) {
  if (!iso || !daFare) return '';
  const g = Math.round((new Date(iso + 'T12:00') - new Date(oggiIso() + 'T12:00')) / 864e5);
  return g < 0 ? 'scaduta' : g === 0 ? 'scade-oggi' : g === 1 ? 'scade-domani' : '';
}
// Bacheca: in alto solo i messaggi da confermare non ancora scaduti; quelli scaduti tornano al loro posto per data.
function ordinaBacheca(msg) {
  const oggi = oggiIso();
  const evid = x => ((x.pv_richiesta && !x.pv_fatta) || (x.ad_richiesta && !x.ad_fatta))
    && !(x.ad_richiesta && x.ad_scadenza && String(x.ad_scadenza).slice(0, 10) < oggi);
  return msg.map((x, i) => [x, i]).sort(([a, i], [b, j]) => (evid(b) - evid(a))
    || ((b.data || '') > (a.data || '') ? 1 : (b.data || '') < (a.data || '') ? -1 : i - j)).map(p => p[0]);
}
const NOMI_SCADENZA = { 'scade-domani': 'Scade domani', 'scade-oggi': 'Scade oggi', scaduta: 'Scaduta' };
const chipScadenza = l => l ? `<span class="chip ${l}">${NOMI_SCADENZA[l]}</span>` : '';

function leggiFile(f) {
  return new Promise((ok, ko) => { const r = new FileReader(); r.onload = () => ok({ nome: f.name, mime: f.type, dati: r.result }); r.onerror = ko; r.readAsDataURL(f); });
}

function finestra(html) {
  const velo = document.createElement('div');
  velo.className = 'velo';
  velo.innerHTML = `<div class="finestra" role="dialog" aria-modal="true">${html}</div>`;
  document.body.appendChild(velo);
  const chiudi = () => { velo.remove(); document.removeEventListener('keydown', tasto); };
  const tasto = e => { if (e.key === 'Escape') chiudi(); };
  document.addEventListener('keydown', tasto);
  velo.addEventListener('mousedown', e => { if (e.target === velo) chiudi(); });
  $$('[data-chiudi]', velo).forEach(b => b.onclick = chiudi);
  return { el: velo, chiudi };
}

// ------------------------------------------------------------------ collegamento con l'Apps Script
async function chiama(azione, dati = {}) {
  const corpo = { azione, ...dati };
  if (azione !== 'accedi' && S) corpo.sessione = S.sessione;
  let j;
  if (PROVA) j = await window.FINTO(corpo);
  else {
    let r;
    try {
      // text/plain: niente richiesta preliminare CORS, Apps Script la accetta
      r = await fetch(window.SMARTDESK_SCRIPT, { method: 'POST', body: JSON.stringify(corpo), headers: { 'Content-Type': 'text/plain;charset=utf-8' } });
    } catch { throw new Error('Connessione non riuscita: controlla internet e riprova.'); }
    try { j = await r.json(); } catch { throw new Error('Risposta non valida dal servizio SmartDesk.'); }
  }
  if (!j.ok) {
    if (j.codice === 401 && azione !== 'accedi') { esci(true); }
    throw new Error(j.errore || 'Operazione non riuscita.');
  }
  return j;
}

// ------------------------------------------------------------------ tema
function temaAttuale() { return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark'; }
function applicaTema(t) {
  scrivi('tema', t);
  if (t === 'light') document.documentElement.setAttribute('data-theme', 'light'); else document.documentElement.removeAttribute('data-theme');
  const mc = $('meta[name=theme-color]');
  if (mc) mc.content = t === 'light' ? '#f4f1ff' : '#0b0719';
  $$('.cambia-tema').forEach(b => { b.innerHTML = ico(t === 'light' ? 'luna' : 'sole'); });
}
const bottoneTema = (cls = '') => `<button type="button" class="tondo cambia-tema ${cls}" aria-label="Cambia tema chiaro o scuro">${ico(temaAttuale() === 'light' ? 'luna' : 'sole')}</button>`;
function collegaTema() {
  $$('.cambia-tema').forEach(b => b.onclick = () => {
    document.documentElement.classList.add('tema-in-cambio');
    applicaTema(temaAttuale() === 'light' ? 'dark' : 'light');
    setTimeout(() => document.documentElement.classList.remove('tema-in-cambio'), 450);
  });
}

// ------------------------------------------------------------------ accesso
function mostraAccesso() {
  document.title = 'SmartDesk – Accesso';
  $('#app').innerHTML = `
  <div class="accesso">${bottoneTema('tema-accesso')}<form class="card" id="f-acc">
    <div class="riga" style="margin-bottom:18px"><img src="icona.svg" alt=""><div><h1 style="margin:0">SmartDesk</h1><div class="muted">Sportello del personale · I.C. Almese</div></div></div>
    ${PROVA ? '<p class="avviso piccolo">Modalità di prova: dati finti, nessun collegamento ad Argo. Scrivi qualunque nome utente e password.</p>' : ''}
    <label class="campo"><span>Nome utente Argo</span><input name="utente" type="text" autocomplete="username" autocapitalize="none" placeholder="nome.cognome.SC15290" required></label>
    <label class="campo"><span>Password Argo</span><input name="password" type="password" autocomplete="current-password" required></label>
    <div id="acc-errore"></div>
    <button class="btn primario" style="width:100%;justify-content:center;margin-top:6px">Entra</button>
    <p class="muted piccolo" style="margin-top:14px">La password serve solo per entrare in Argo: SmartDesk non la salva.</p>
    <p class="credito">Sviluppata dal <b>Wolf Team</b> dell'Istituto Comprensivo di Almese · © 2026</p>
  </form></div>`;
  collegaTema();
  const f = $('#f-acc');
  f.onsubmit = async e => {
    e.preventDefault();
    const b = $('button.primario', f);
    b.disabled = true; b.textContent = 'Entro in Argo…';
    $('#acc-errore').innerHTML = '';
    try {
      const r = await chiama('accedi', { utente: f.utente.value.trim(), password: f.password.value });
      S = { sessione: r.sessione, nome: r.nome, cognome: r.cognome, avvisi: [r.personale_errore, r.didup_errore].filter(Boolean) };
      DATI = r.dati || null; BACHECA = null;
      scrivi('s', S); scrivi('dati', DATI);
      avvia();
    } catch (err) {
      $('#acc-errore').innerHTML = `<div class="anteprima no">${esc(err.message)}</div>`;
      f.password.value = '';
      b.disabled = false; b.textContent = 'Entra';
    }
  };
}

function esci(scaduta = false) {
  if (S && !scaduta) chiama('esci').catch(() => {});
  S = null; DATI = null; BACHECA = null;
  scrivi('s', null); scrivi('dati', null);
  if (scaduta) toast('Sessione scaduta: entra di nuovo con le credenziali Argo.', true);
  mostraAccesso();
}

// ------------------------------------------------------------------ impalcatura
const VOCI = [['home', 'Home', '#/'], ['assenze', 'Assenze', '#/assenze'], ['bacheca', 'Bacheca', '#/bacheca'], ['profilo', 'Profilo', '#/profilo']];
function disegnaShell() {
  const nome = `${S.nome || ''} ${S.cognome || ''}`.trim() || 'Personale';
  $('#app').innerHTML = `
  <div class="shell">
    <aside class="lato">
      <div class="marchio"><img src="icona.svg" alt=""><div><b>SmartDesk</b><small>Sportello del personale</small></div></div>
      ${VOCI.map(([k, n, h]) => `<a class="voce" data-voce="${k}" href="${h}">${ico(k)}<span>${n}</span><span class="bollo-slot" data-b="${k}"></span></a>`).join('')}
      <div class="sotto"><b style="color:var(--text)">${esc(nome)}</b>${PROVA ? '<br>modalità di prova' : ''}
        <div class="crediti-lato">${ico('lupo')} by Wolf Team</div></div>
    </aside>
    <div class="principale">
      <header class="barra">
        <img class="marchio-mobile" src="icona.svg" alt="">
        <div class="titolo" id="titolo"></div>
        ${bottoneTema()}
        <button class="tondo" id="aggiorna" aria-label="Aggiorna">${ico('aggiorna')}</button>
      </header>
      <main class="contenuto" id="contenuto"></main>
    </div>
    <nav class="nav-mobile">
      ${VOCI.map(([k, n, h]) => `<a data-voce="${k}" href="${h}">${ico(k)}<span>${n}</span><span class="bollo-slot" data-b="${k}"></span></a>`).join('')}
    </nav>
  </div>`;
  collegaTema();
  $('#aggiorna').onclick = async () => { DATI = null; BACHECA = null; await naviga(); toast('Dati aggiornati.'); };
}

function bollo(k, n) {
  $$(`[data-b="${k}"]`).forEach(x => { x.innerHTML = n ? `<span class="bollo">${n > 99 ? '99+' : n}</span>` : ''; });
}

const ROTTE = [[/^\/?$/, vistaHome, 'home', 'Home'], [/^\/assenze$/, vistaAssenze, 'assenze', 'Le mie assenze'],
               [/^\/bacheca$/, vistaBacheca, 'bacheca', 'Bacheca DidUP'], [/^\/profilo$/, vistaProfilo, 'profilo', 'Profilo']];
async function naviga() {
  const h = location.hash.replace(/^#/, '') || '/';
  const [percorso] = h.split('?');
  const r = ROTTE.find(([re]) => re.test(percorso)) || ROTTE[0];
  $$('[data-voce]').forEach(a => a.classList.toggle('attiva', a.dataset.voce === r[2]));
  $('#titolo').textContent = r[3];
  document.title = r[3] + ' – SmartDesk';
  const c = $('#contenuto');
  c.innerHTML = '<div class="caricamento">Caricamento…</div>';
  try { await r[1](c); } catch (err) { c.innerHTML = `<div class="card"><p class="avviso">${esc(err.message)}</p></div>`; }
  window.scrollTo(0, 0);
}

async function dati() {
  if (!DATI) { DATI = (await chiama('dati')).dati; scrivi('dati', DATI); }
  return DATI;
}
async function bacheca() {
  if (!BACHECA) { BACHECA = await chiama('bacheca'); }
  bollo('bacheca', BACHECA.da_fare);
  return BACHECA;
}

// ------------------------------------------------------------------ contatori
const LIMITI = {
  festivita: { nome: 'Festività soppresse', totale: 4, unita: 'giorni' },
  motivi_personali: { nome: 'Permesso per motivi personali o familiari', totale: 3, unita: 'giorni' },
  permesso_breve: { nome: 'Permesso breve (da recuperare)', totale: { docente: 18, ata: 36 }, unita: 'ore' },
};
function contatori(d) {
  const prof = leggi('profilo', { categoria: 'docente', ferie: 32, residui: 0 });
  const somma = (tipo, stati) => {
    const reg = d.assenze.filter(a => a.tipo === tipo).reduce((t, a) => t + (a.oraria ? a.ore : a.giorni), 0);
    // le richieste in corso contano "in attesa" solo se non sono già un'assenza registrata
    const att = d.richieste.filter(r => r.tipo === tipo && stati.includes(r.stato) && !d.assenze.some(a => a.richiesta === r.id))
      .reduce((t, r) => t + (r.oraria ? oreTra(r.ora_dal, r.ora_al) : giorniLav(r.inizio, r.fine)), 0);
    return [reg, att];
  };
  const inCorso = ['FWD', 'DAU', 'AUT', 'DSG', 'REF'];
  const out = [];
  const [fu, fa] = somma('ferie', inCorso);
  const ftot = (+prof.ferie || 0) + (+prof.residui || 0);
  out.push({ nome: 'Ferie', unita: 'giorni', totale: ftot, usati: fu, attesa: fa, dettaglio: `${prof.ferie} dell'anno + ${prof.residui || 0} residui (da Profilo)` });
  for (const [tipo, l] of Object.entries(LIMITI)) {
    const tot = typeof l.totale === 'object' ? l.totale[prof.categoria] : l.totale;
    const [u, a] = somma(tipo, inCorso);
    out.push({ nome: l.nome, unita: l.unita, totale: tot, usati: u, attesa: a, dettaglio: "nell'anno scolastico" });
  }
  return out.map(k => ({ ...k, residuo: k.totale - k.usati - k.attesa }));
}
function giorniLav(a, b) { let n = 0; for (let d = new Date(a + 'T12:00'); d <= new Date(b + 'T12:00'); d.setDate(d.getDate() + 1)) if (d.getDay() !== 0) n++; return n; }
function oreTra(a, b) { const m = s => { const [h, mi] = String(s || '0:0').split(':').map(Number); return h * 60 + (mi || 0); }; return Math.max(0, m(b) - m(a)) / 60; }

function barraContatore(k) {
  const tot = Math.max(k.totale, 0.0001);
  const u = Math.min(100, k.usati / tot * 100), a = Math.min(100 - u, k.attesa / tot * 100);
  return `<div class="card contatore">
    <div class="riga"><b>${esc(k.nome)}</b><span class="spazio"></span><span class="${k.residuo < 0 ? 'neg' : ''}" style="font-size:1.25rem;font-weight:700">${num(k.residuo)}</span><span class="muted piccolo">${k.unita} rimasti su ${num(k.totale)}</span></div>
    <div class="barra-prog"><i class="u" style="width:${u}%"></i><i class="a" style="width:${a}%"></i></div>
    <div class="legenda"><span><i style="background:var(--primary)"></i>usati ${num(k.usati)}</span><span><i style="background:color-mix(in srgb,var(--primary) 40%,transparent)"></i>in attesa ${num(k.attesa)}</span><span>${esc(k.dettaglio)}</span></div>
  </div>`;
}

// ------------------------------------------------------------------ viste
async function vistaHome(c) {
  const d = await dati();
  const avvisi = (S.avvisi || []).map(a => `<p class="avviso piccolo">${esc(a)}</p>`).join('');
  c.innerHTML = `<h1>Ciao ${esc(S.nome || '')}</h1>${avvisi}
    <div class="griglia" id="tessere">
      <a class="card tessera" href="#/assenze"><div class="num">${d.richieste.filter(r => ['FWD', 'DAU', 'AUT', 'DSG', 'REF'].includes(r.stato)).length}</div><div class="lab">richieste in corso</div></a>
      <a class="card tessera evid" href="#/bacheca"><div class="num" id="n-bacheca">…</div><div class="lab">circolari da confermare</div></a>
    </div>
    <h2 style="margin-top:22px">Ferie e permessi</h2>
    <div class="due">${contatori(d).map(barraContatore).join('')}</div>
    <p class="muted piccolo">Dati letti ora dal programma della segreteria (a.s. ${esc(d.dal.slice(0, 4))}/${esc(d.al.slice(2, 4))}). Le richieste in corso sono già scalate.</p>`;
  bacheca().then(b => { const n = $('#n-bacheca'); if (n) n.textContent = b.da_fare; })
    .catch(err => { const n = $('#n-bacheca'); if (n) { n.textContent = '–'; n.title = err.message; } });
}

async function vistaAssenze(c) {
  const d = await dati();
  const filtro = new URLSearchParams(location.hash.split('?')[1] || '').get('f') || 'tutte';
  const reg = d.assenze.map(a => ({ ...a, genere: 'assenza' }));
  const ric = d.richieste.filter(r => !d.assenze.some(a => a.richiesta === r.id)).map(r => ({ ...r, genere: 'richiesta' }));
  let voci = reg.concat(ric).sort((a, b) => b.inizio.localeCompare(a.inizio));
  if (filtro === 'corso') voci = voci.filter(v => v.genere === 'richiesta' && ['FWD', 'DAU', 'AUT', 'DSG', 'REF'].includes(v.stato));
  if (filtro === 'registrate') voci = voci.filter(v => v.genere === 'assenza');
  c.innerHTML = `<div class="filtri">${[['tutte', 'Tutte'], ['registrate', 'Registrate'], ['corso', 'In corso']].map(([k, n]) =>
      `<a class="pillola ${filtro === k ? 'attiva' : ''}" href="#/assenze?f=${k}" style="text-decoration:none;color:inherit">${n}</a>`).join('')}</div>
    <p class="muted piccolo">Come in Unica: l'annullamento arriva alla segreteria con il motivo e gli allegati.</p>
    <div class="lista">${voci.length ? voci.map(elemAssenza).join('') : '<div class="card vuoto">Nessuna assenza.</div>'}</div>`;
  $$('[data-annulla]', c).forEach(b => b.onclick = () => finestraAnnulla(b.dataset.annulla, b.dataset.cosa, !!b.dataset.bozza));
}

function elemAssenza(x) {
  const q = x.oraria ? `${num(x.genere === 'assenza' ? x.ore : oreTra(x.ora_dal, x.ora_al))} ore` : x.genere === 'assenza' ? `${num(x.giorni)} ${x.giorni === 1 ? 'giorno' : 'giorni'}` : '';
  const rich = x.genere === 'assenza' ? (DATI.richieste.find(r => r.id === x.richiesta) || null) : x;
  const annullabile = rich && rich.annullabile;
  const stato = x.genere === 'assenza' ? '<span class="chip letta">Registrata</span>'
    : `<span class="chip ${['NUL', 'NOF', 'RIF', 'ERR'].includes(x.stato) ? 'annullata' : x.stato === 'DEF' ? 'registrata' : 'inviata'}">${esc(x.stato_nome)}</span>`;
  const cosa = `${x.descrizione || 'Assenza'} – ${periodo(x)}`;
  return `<div class="elem"><span class="testo"><b>${esc(x.descrizione || 'Assenza')}</b>
      <span>${esc(periodo(x))}${x.oraria && x.ora_dal ? `, ${esc(x.ora_dal)}–${esc(x.ora_al)}` : ''}${q ? ' · ' + q : ''}${x.genere === 'assenza' && !x.richiesta ? ' · inserita dalla segreteria' : ''}</span></span>
    <span class="destra">${stato}${annullabile ? `<button class="btn mini pericolo" data-annulla="${esc(rich.id)}"${rich.stato === 'NEW' ? ' data-bozza="1"' : ''} data-cosa="${esc(cosa)}">Annulla</button>` : ''}</span></div>`;
}

function finestraAnnulla(id, cosa, bozza) {
  if (bozza) {  // bozza mai inoltrata: come in Argo Personale si annulla subito, senza motivo
    const f = finestra(`<h2>Annulla la bozza</h2>
      <p class="muted">${esc(cosa)}. È una bozza salvata su Argo e mai inviata: la segreteria non l'ha vista, quindi non serve il motivo.</p>
      <div class="piede"><button class="btn" data-chiudi>Indietro</button><button class="btn pericolo" id="an-ok">Annulla la bozza</button></div>`);
    $('#an-ok', f.el).onclick = async e => {
      e.target.disabled = true; e.target.textContent = 'Invio…';
      try {
        const r = await chiama('annulla', { richiesta: id });
        f.chiudi(); DATI = r.dati; scrivi('dati', DATI); toast('Bozza annullata.'); naviga();
      } catch (err) { toast(err.message, true); e.target.disabled = false; e.target.textContent = 'Annulla la bozza'; }
    };
    return;
  }
  const f = finestra(`<h2>Chiedi l'annullamento</h2>
    <p class="muted">${esc(cosa)}. L'annullamento arriva alla segreteria, come da Unica.</p>
    <label class="campo"><span>Motivo dell'annullamento <small class="muted" id="an-conta">0/250</small></span><textarea id="an-nota" maxlength="250"></textarea></label>
    <label class="campo"><span>Allegati (facoltativi, fino a 5)</span><input type="file" id="an-file" multiple></label>
    <div class="piede"><button class="btn" data-chiudi>Indietro</button><button class="btn pericolo" id="an-ok">Invia l'annullamento</button></div>`);
  const nota = $('#an-nota', f.el);
  nota.oninput = () => { $('#an-conta', f.el).textContent = `${nota.value.length}/250`; };
  $('#an-ok', f.el).onclick = async e => {
    const motivo = nota.value.trim();
    if (!motivo) { toast("Scrivi il motivo dell'annullamento.", true); return; }
    const files = [...$('#an-file', f.el).files];
    if (files.length > 5) { toast('Al massimo 5 allegati.', true); return; }
    if (files.reduce((t, x) => t + x.size, 0) > 15 * 1024 * 1024) { toast('Gli allegati superano 15 MB in tutto.', true); return; }
    e.target.disabled = true; e.target.textContent = 'Invio…';
    try {
      const r = await chiama('annulla', { richiesta: id, motivo, allegati: await Promise.all(files.map(leggiFile)) });
      f.chiudi();
      DATI = r.dati; scrivi('dati', DATI);
      toast(r.allegati_non_caricati?.length ? `Annullamento inviato, ma ${r.allegati_non_caricati.length} allegati non sono arrivati.` : 'Annullamento inviato alla segreteria.', !!r.allegati_non_caricati?.length);
      naviga();
    } catch (err) { toast(err.message, true); e.target.disabled = false; e.target.textContent = "Invia l'annullamento"; }
  };
}

// ------------------------------------------------------------------ bacheca DidUP
async function vistaBacheca(c, tutte = false) {
  const d = await bacheca();
  const daFare = x => (x.pv_richiesta && !x.pv_fatta) || (x.ad_richiesta && !x.ad_fatta);
  d.messaggi = ordinaBacheca(d.messaggi);
  const msg = tutte ? d.messaggi : d.messaggi.filter((x, i) => daFare(x) || i < d.da_fare + 8);
  const soloPv = d.messaggi.filter(x => x.pv_richiesta && !x.pv_fatta && !x.ad_richiesta);
  c.innerHTML = `<div class="card didup">
    <div class="riga" style="margin-bottom:6px"><h2 style="margin:0">Circolari DidUP</h2>
      ${d.da_fare ? `<span class="chip nonletta">${d.da_fare} da confermare</span>` : '<span class="chip letta">Tutto confermato</span>'}
      <span class="spazio"></span>
      ${soloPv.length > 1 ? `<button class="btn primario mini" id="dd-tutte">${ico('ok')} Prendi visione di tutte (${soloPv.length})</button>` : ''}</div>
    <p class="muted piccolo" style="margin:0 0 12px">Un tocco basta: SmartDesk apre l'allegato al posto tuo e poi conferma su Argo.</p>
    <div class="lista">${msg.map(elemDidup).join('') || '<div class="vuoto">Nessun messaggio.</div>'}</div>
    ${!tutte && msg.length < d.messaggi.length ? `<button class="btn mini" id="dd-altre" style="margin-top:10px">Mostra anche le altre (${d.messaggi.length - msg.length})</button>` : ''}
  </div>`;
  $('#dd-altre', c)?.addEventListener('click', () => vistaBacheca(c, true));
  const conferma = async (pk, adesione, bottone) => {
    const el = bottone.closest('.didup-msg');
    el.classList.add('occupato');
    $$('button', el).forEach(b => b.disabled = true);
    const vecchio = bottone.innerHTML;
    bottone.innerHTML = adesione ? 'Invio…' : 'Apro e confermo…';
    try {
      const r = await chiama('conferma', { pk, adesione: adesione || null });
      const i = BACHECA.messaggi.findIndex(x => x.pk === pk);
      if (i >= 0) BACHECA.messaggi[i] = r.messaggio;
      BACHECA.da_fare = BACHECA.messaggi.filter(daFare).length;
      bollo('bacheca', BACHECA.da_fare);
      el.outerHTML = elemDidup(r.messaggio);
      return r;
    } catch (err) {
      toast(err.message, true);
      el.classList.remove('occupato');
      $$('button', el).forEach(b => b.disabled = false);
      bottone.innerHTML = vecchio;
      throw err;
    }
  };
  c.onclick = async e => {
    const al = e.target.closest('[data-apri]');
    if (al) { apriAllegati(al.dataset.apri, al); return; }
    const b = e.target.closest('[data-pv],[data-ad]');
    if (!b || b.disabled) return;
    try {
      await conferma(b.dataset.pv || b.dataset.pk, b.dataset.ad, b);
      toast(b.dataset.ad ? 'Adesione registrata su Argo.' : 'Presa visione registrata su Argo.');
    } catch { /* già segnalato */ }
  };
  $('#dd-tutte', c)?.addEventListener('click', async e => {
    e.stopPropagation();
    if (!confirm(`Confermare la presa visione di ${soloPv.length} circolari su Argo? SmartDesk apre prima ogni allegato.`)) return;
    e.target.disabled = true;
    let ok = 0, ko = 0;
    for (const x of soloPv) {
      const b = $(`[data-pv="${CSS.escape(x.pk)}"]`, c);
      if (!b) continue;
      try { await conferma(x.pk, null, b); ok++; } catch (err) { ko++; if (/sessione|credenziali/i.test(err.message)) break; }
    }
    toast(`Presa visione registrata per ${ok} circolari${ko ? `; ${ko} non riuscite (riprova da sole)` : ''}.`, ko > 0);
    vistaBacheca(c, tutte);
  });
}

function elemDidup(x) {
  const pvDaFare = x.pv_richiesta && !x.pv_fatta;
  const scadAd = x.ad_scadenza && x.ad_scadenza < oggiIso();
  const bloccaAd = scadAd || (x.ad_fatta && !x.ad_modificabile);
  const scad = livelloScadenza(x.ad_richiesta && x.ad_scadenza, !x.ad_fatta);
  return `<div class="didup-msg ${pvDaFare || (x.ad_richiesta && !x.ad_fatta) ? 'da-fare' : ''} ${scad}">
    <div class="riga" style="align-items:flex-start;flex-wrap:nowrap">
      <span class="ico">${ico('bacheca')}</span>
      <div class="spazio" style="min-width:0">
        <b class="tit">${esc(x.titolo)}</b>${scad ? ' ' + chipScadenza(scad) : ''}
        <div class="muted piccolo">${x.data ? fd(x.data) : ''}${x.categoria ? ' · ' + esc(x.categoria) : ''}${x.mittente ? ' · ' + esc(x.mittente) : ''}</div>
        ${x.testo && x.testo !== x.titolo ? `<details><summary class="piccolo">Testo</summary><div class="testo-circ piccolo">${esc(x.testo)}</div></details>` : ''}
        ${x.n_allegati ? `<button class="allegato" data-apri="${esc(x.pk)}" style="margin-top:8px">${ico('scarica')} Apri ${x.n_allegati === 1 ? "l'allegato" : x.n_allegati + ' allegati'}</button>` : ''}
      </div>
    </div>
    <div class="azioni">
      ${pvDaFare ? `<button class="btn primario" data-pv="${esc(x.pk)}">${ico('ok')} Prendo visione</button>`
        : x.pv_fatta ? `<span class="chip letta">Presa visione${x.pv_quando ? ' · ' + esc(x.pv_quando) : ''}</span>` : ''}
      ${x.ad_richiesta ? `<div class="adesione">${Object.entries({ A: 'Aderisco', N: 'Non aderisco', X: 'Non ho deciso' }).map(([k, n]) =>
        `<button class="pillola ${x.adesione === k ? 'attiva' : ''}" data-ad="${k}" data-pk="${esc(x.pk)}" ${bloccaAd ? 'disabled' : ''}>${n}</button>`).join('')}
        ${x.ad_scadenza ? `<span class="muted piccolo">entro ${fd(x.ad_scadenza)}${scadAd ? ' (scaduto)' : ''}</span>` : ''}</div>` : ''}
    </div>
  </div>`;
}

async function apriAllegati(pk, bottone) {
  // la finestra si apre subito (i telefoni bloccano le finestre aperte dopo un'attesa), poi si riempie col link
  const w = window.open('', '_blank');
  const vecchio = bottone.innerHTML;
  bottone.disabled = true; bottone.textContent = 'Apro…';
  try {
    const r = await chiama('allegati', { pk });
    if (!r.allegati.length) throw new Error('Nessun allegato.');
    if (w) w.location = r.allegati[0].url; else location.href = r.allegati[0].url;
    if (r.allegati.length > 1) finestra(`<h2>Allegati</h2><div>${r.allegati.map(a => `<a class="allegato" href="${esc(a.url)}" target="_blank" rel="noopener">${ico('scarica')} ${esc(a.nome)}</a>`).join('')}</div>
      <p class="muted piccolo">I link valgono pochi minuti.</p><div class="piede"><button class="btn" data-chiudi>Chiudi</button></div>`);
  } catch (err) { if (w) w.close(); toast(err.message, true); }
  bottone.disabled = false; bottone.innerHTML = vecchio;
}

// ------------------------------------------------------------------ profilo
async function vistaProfilo(c) {
  const p = leggi('profilo', { categoria: 'docente', ferie: 32, residui: 0 });
  c.innerHTML = `<div class="card">
    <div class="riga" style="margin-bottom:14px"><span class="avatar" style="width:54px;height:54px;font-size:1.1rem">${esc(((S.nome || '?')[0] + (S.cognome || '?')[0]).toUpperCase())}</span>
      <div><h1 style="margin:0">${esc(S.nome || '')} ${esc(S.cognome || '')}</h1><div class="muted">${PROVA ? 'Modalità di prova' : 'Collegato ad Argo'}</div></div></div>
    <form id="f-prof">
      <div class="sezione"><h3>Per calcolare i giorni rimasti</h3>
        <label class="campo"><span>Sono</span><select name="categoria"><option value="docente">Docente</option><option value="ata">Personale ATA</option></select></label>
        <div class="campi2"><label class="campo"><span>Giorni di ferie dell'anno</span><input name="ferie" type="number" min="0" max="40" value="${esc(p.ferie)}"></label>
        <label class="campo"><span>Residui dell'anno precedente</span><input name="residui" type="number" min="0" max="40" value="${esc(p.residui || 0)}"></label></div>
        <small class="muted">Di solito 32 giorni (30 nei primi tre anni di servizio). Restano salvati solo su questo dispositivo.</small></div>
      <div class="sezione"><h3>Aspetto</h3><div class="filtri">${[['dark', 'Scuro viola'], ['light', 'Chiaro lavanda']].map(([k, n]) => `<button type="button" class="pillola ${temaAttuale() === k ? 'attiva' : ''}" data-tema="${k}">${n}</button>`).join('')}</div></div>
    </form>
    <div class="sezione"><button class="btn pericolo" id="esci">${ico('esci')} Esci</button></div>
    <p class="credito">SmartDesk · sviluppata dal <b>Wolf Team</b> dell'Istituto Comprensivo di Almese · © 2026</p>
  </div>`;
  const f = $('#f-prof', c);
  f.categoria.value = p.categoria;
  f.onchange = () => { scrivi('profilo', { categoria: f.categoria.value, ferie: +f.ferie.value || 0, residui: +f.residui.value || 0 }); toast('Salvato.'); };
  $$('[data-tema]', c).forEach(b => b.onclick = () => { applicaTema(b.dataset.tema); vistaProfilo(c); });
  $('#esci', c).onclick = () => esci();
}

// ------------------------------------------------------------------ avvio
function avvia() {
  S = S || leggi('s');
  DATI = DATI || leggi('dati');
  if (!S) { mostraAccesso(); return; }
  disegnaShell();
  naviga();
  if (!BACHECA) bacheca().catch(() => {});
}
window.addEventListener('hashchange', () => { if (S) naviga(); });
if (leggi('tema') === 'light') applicaTema('light');
if ('serviceWorker' in navigator && !PROVA) navigator.serviceWorker.register('sw.js').catch(() => {});
avvia();
