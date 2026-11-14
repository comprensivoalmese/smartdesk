'use strict';
/* SmartDesk (Sportello del personale, by Wolf Team) - interfaccia (JavaScript puro, nessuna libreria) */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
let IO = null;
let BADGE = { bacheca: 0, gestione: 0, notifiche: 0 };
let TIMER = null;

// ------------------------------------------------------------------ icone
const P = {
  home: '<path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/>',
  richieste: '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/>',
  situazione: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  bacheca: '<path d="M4 4h16v12H8l-4 4z"/><path d="M8 9h8M8 12h5"/>',
  presenze: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  documenti: '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/>',
  gestione: '<path d="M9 11l2 2 4-4"/><rect x="3" y="3" width="18" height="18" rx="3"/>',
  profilo: '<circle cx="12" cy="8" r="4"/><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6"/>',
  campana: '<path d="M6 16V11a6 6 0 1 1 12 0v5l2 2H4z"/><path d="M10 20a2 2 0 0 0 4 0"/>',
  piu: '<path d="M12 5v14M5 12h14"/>',
  altro: '<circle cx="5" cy="12" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="19" cy="12" r="1.5"/>',
  clip: '<path d="M21 11.5 12.5 20a5 5 0 0 1-7-7L14 4.5a3.5 3.5 0 0 1 5 5L10.5 18a2 2 0 0 1-3-3L15 7.5"/>',
  indietro: '<path d="M15 18l-6-6 6-6"/>',
  scarica: '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
  sole: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  cuore: '<path d="M12 20s-7-4.5-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.5-7 10-7 10z"/>',
  famiglia: '<circle cx="8" cy="7" r="3"/><circle cx="17" cy="9" r="2.5"/><path d="M2 20c.5-4 3-6 6-6s5.5 2 6 6M14 20c.3-2.5 1.5-4.5 3-4.5s2.7 2 3 4.5"/>',
  calendario: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
  esci: '<path d="M15 4h4v16h-4M10 8l-4 4 4 4M6 12h10"/>',
  ok: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  lupo: '<path d="M5 3l4 5h6l4-5 1 7 2 3-5 3-5 5-5-5-5-3 2-3z"/>',
  luna: '<path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z"/>',
};
const ico = (n, cls = '') => `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${P[n] || ''}</svg>`;
const ICO_GRUPPO = { 'Ferie e permessi': 'sole', 'Salute': 'cuore', 'Famiglia': 'famiglia', 'Altro': 'richieste' };

// ------------------------------------------------------------------ utilità
async function api(path, dati, metodo) {
  const opt = { method: metodo || (dati === undefined ? 'GET' : 'POST'), headers: {} };
  if (dati !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(dati); }
  const r = await fetch(path, opt);
  let j = null;
  try { j = await r.json(); } catch { /* vuoto */ }
  if (r.status === 401 && path !== '/api/accesso') { IO = null; mostraAccesso(); throw new Error(j?.errore || 'Accesso scaduto'); }
  if (!r.ok) throw new Error(j?.errore || `Errore ${r.status}`);
  return j;
}

function toast(msg, errore = false) {
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'su' + (errore ? ' errore' : '');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { t.className = errore ? 'errore' : ''; }, errore ? 5000 : 2800);
}

const GIORNI = ['dom', 'lun', 'mar', 'mer', 'gio', 'ven', 'sab'];
const MESI = ['gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno', 'luglio', 'agosto', 'settembre', 'ottobre', 'novembre', 'dicembre'];
const dIso = s => { const [y, m, d] = s.slice(0, 10).split('-').map(Number); return new Date(y, m - 1, d); };
// scadenza di un messaggio a cui si deve ancora rispondere: '' | scade-domani | scade-oggi | scaduta
function livelloScadenza(iso, daFare = true) {
  if (!iso || !daFare) return '';
  const g = Math.round((new Date(iso.slice(0, 10) + 'T12:00') - new Date(oggiIso() + 'T12:00')) / 864e5);
  return g < 0 ? 'scaduta' : g === 0 ? 'scade-oggi' : g === 1 ? 'scade-domani' : '';
}
const NOMI_SCADENZA = { 'scade-domani': 'Scade domani', 'scade-oggi': 'Scade oggi', scaduta: 'Scaduta' };
const chipScadenza = l => l ? `<span class="chip ${l}">${NOMI_SCADENZA[l]}</span>` : '';
const oggiIso = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
function fd(s, conGiorno = true) {
  if (!s) return '';
  const d = dIso(s);
  return `${conGiorno ? GIORNI[d.getDay()] + ' ' : ''}${d.getDate()} ${MESI[d.getMonth()].slice(0, 3)}${d.getFullYear() !== new Date().getFullYear() ? ' ' + d.getFullYear() : ''}`;
}
function fdt(s) { if (!s) return ''; return `${fd(s, false)} alle ${s.slice(11, 16)}`; }
const num = n => (Math.round(n * 10) / 10).toString().replace('.', ',');
function quantita(r) {
  if (r.unita === 'giorni') return `${num(r.quantita)} giorn${r.quantita === 1 ? 'o' : 'i'}`;
  if (r.unita === 'ore') return `${num(r.quantita)} or${r.quantita === 1 ? 'a' : 'e'}`;
  return '';
}
function periodo(r) {
  if (!r.dal) return r.campi?.oggetto || r.campi?.tipologia || '';
  if (r.unita === 'ore') return `${fd(r.dal)}, ${r.ora_da}–${r.ora_a}`;
  return r.dal === r.al ? fd(r.dal) : `${fd(r.dal)} → ${fd(r.al)}`;
}
const chip = (stato, nome) => `<span class="chip ${esc(stato)}">${esc(nome || IO.stati[stato] || stato)}</span>`;
const iniziali = u => (u.nome[0] + u.cognome[0]).toUpperCase();
const DEST = { tutti: 'Tutto il personale', docenti: 'Docenti', ata: 'Personale ATA' };

function leggiFile(f) {
  return new Promise((ok, ko) => {
    const r = new FileReader();
    r.onload = () => ok({ nome: f.name, mime: f.type, dati: r.result });
    r.onerror = ko;
    r.readAsDataURL(f);
  });
}

/* selettore di file: restituisce html; poi collegaFile(el) restituisce una funzione che dà i file letti */
const htmlFile = (id, etichetta = 'Allegati', aiuto = '') => `
  <label class="campo"><span>${esc(etichetta)}</span>
    <input type="file" id="${id}" multiple accept=".pdf,.jpg,.jpeg,.png,.doc,.docx,.odt,.txt">
    ${aiuto ? `<small>${esc(aiuto)}</small>` : ''}
    <div class="file-scelti" id="${id}-elenco"></div></label>`;
function collegaFile(id) {
  const inp = $('#' + id), elenco = $('#' + id + '-elenco');
  let scelti = [];
  const disegna = () => {
    elenco.innerHTML = scelti.map((f, i) => `<div>${ico('clip')}<span>${esc(f.name)}</span><small class="muted">${Math.ceil(f.size / 1024)} kB</small><button type="button" data-i="${i}" aria-label="Togli">✕</button></div>`).join('');
    $$('button', elenco).forEach(b => b.onclick = () => { scelti.splice(+b.dataset.i, 1); disegna(); });
  };
  inp.onchange = () => { scelti = scelti.concat([...inp.files]); inp.value = ''; disegna(); };
  return async () => {
    if (scelti.reduce((a, f) => a + f.size, 0) > 18 * 1024 * 1024) throw new Error('I file superano 18 MB in tutto.');
    return Promise.all(scelti.map(leggiFile));
  };
}

function finestra(html, alChiudere) {
  const velo = document.createElement('div');
  velo.className = 'velo';
  velo.innerHTML = `<div class="finestra" role="dialog" aria-modal="true">${html}</div>`;
  document.body.appendChild(velo);
  const chiudi = () => { velo.remove(); document.removeEventListener('keydown', tasto); alChiudere && alChiudere(); };
  const tasto = e => { if (e.key === 'Escape') chiudi(); };
  document.addEventListener('keydown', tasto);
  velo.addEventListener('mousedown', e => { if (e.target === velo) chiudi(); });
  $$('[data-chiudi]', velo).forEach(b => b.onclick = chiudi);
  setTimeout(() => $('input:not([type=hidden]),textarea,select,button.primario', velo)?.focus(), 30);
  return { el: velo, chiudi };
}

function chiedi({ titolo, testo = '', nota = false, notaObbligatoria = false, bottone = 'Conferma', pericolo = false }) {
  return new Promise(ok => {
    let fatto = false;
    const f = finestra(`<h2>${esc(titolo)}</h2>${testo ? `<p class="muted">${esc(testo)}</p>` : ''}
      ${nota ? `<label class="campo"><span>${notaObbligatoria ? 'Motivazione' : 'Nota (facoltativa)'}</span><textarea id="ch-nota"></textarea></label>` : ''}
      <div class="piede"><button class="btn" data-chiudi>Indietro</button><button class="btn ${pericolo ? 'pericolo' : 'primario'}" id="ch-ok">${esc(bottone)}</button></div>`,
    () => { if (!fatto) ok(null); });
    $('#ch-ok', f.el).onclick = () => {
      const v = nota ? $('#ch-nota', f.el).value.trim() : '';
      if (notaObbligatoria && !v) { toast('Scrivi una motivazione.', true); return; }
      fatto = true; f.chiudi(); ok({ nota: v });
    };
  });
}

// ------------------------------------------------------------------ accesso
async function mostraAccesso() {
  clearInterval(TIMER);
  document.title = 'SmartDesk – Accesso';
  let info = { scuola: '', argo: false };
  try { info = await (await fetch('/api/accesso-info')).json(); } catch { /* offline */ }
  let modo = 'sportello';
  try { modo = info.argo ? (localStorage.getItem('sp-modo') || 'argo') : 'sportello'; } catch { modo = info.argo ? 'argo' : 'sportello'; }
  $('#app').innerHTML = `
  <div class="accesso">${bottoneTema('tema-accesso')}<form class="card" id="f-acc">
    <div class="riga" style="margin-bottom:18px"><img src="/icona.svg" alt=""><div><h1 style="margin:0">SmartDesk</h1><div class="muted">Sportello del personale${info.scuola ? ' · ' + esc(info.scuola) : ''}</div></div></div>
    ${info.argo ? `<div class="schede" style="margin-bottom:16px"><button type="button" data-modo="argo">Credenziali Argo</button><button type="button" data-modo="sportello">Account SmartDesk</button></div>` : ''}
    <p class="muted piccolo" id="acc-spiega" style="margin-top:0"></p>
    <label class="campo"><span id="acc-utente">Nome utente</span><input type="text" name="username" autocomplete="username" autocapitalize="none" spellcheck="false" required></label>
    <label class="campo"><span>Password</span><input type="password" name="password" autocomplete="current-password" required></label>
    <div id="acc-errore"></div>
    <button class="btn primario grande" style="width:100%" id="acc-entra">Entra</button>
    <p class="muted piccolo" style="margin:14px 0 0" id="acc-aiuto"></p>
    <p class="credito">Sviluppata dal <b>Wolf Team</b> dell'Istituto Comprensivo di Almese · © 2026</p>
  </form></div>`;
  collegaTema();
  const f = $('#f-acc');
  const imposta = m => {
    modo = m;
    $$('[data-modo]', f).forEach(b => b.classList.toggle('attiva', b.dataset.modo === m));
    $('#acc-spiega').textContent = m === 'argo' ? 'Usa lo stesso nome utente e la stessa password del portale Argo. SmartDesk li controlla con Argo e non salva la password.' : '';
    $('#acc-utente').textContent = m === 'argo' ? 'Nome utente Argo' : 'Nome utente';
    f.username.placeholder = m === 'argo' ? 'nome.cognome.SC12345' : '';
    $('#acc-aiuto').textContent = m === 'argo' ? 'Password Argo dimenticata? Si recupera dal portale Argo.' : 'Password dimenticata? Chiedi alla segreteria del personale di reimpostarla.';
    $('#acc-errore').innerHTML = '';
  };
  $$('[data-modo]', f).forEach(b => b.onclick = () => { imposta(b.dataset.modo); f.username.focus(); });
  imposta(modo);
  f.onsubmit = async e => {
    e.preventDefault();
    const b = $('#acc-entra');
    b.disabled = true;
    b.textContent = modo === 'argo' ? 'Controllo con Argo…' : 'Entra';
    try {
      await api('/api/accesso', { username: f.username.value, password: f.password.value, modo });
      try { localStorage.setItem('sp-modo', modo); } catch { /* niente */ }
      avvia();
    } catch (err) {
      $('#acc-errore').innerHTML = `<div class="anteprima no">${esc(err.message)}</div>`;
      f.password.value = '';
      b.disabled = false; b.textContent = 'Entra';
    }
  };
  f.username.focus();
}

// ------------------------------------------------------------------ impalcatura
function voci() {
  const v = [['home', 'Home', '#/'], ['richieste', 'Le mie richieste', '#/richieste'], ['situazione', 'Situazione ferie e permessi', '#/situazione'],
    ['bacheca', 'Bacheca', '#/bacheca']];
  if (IO.timbrature || IO.staff) v.push(['presenze', IO.timbrature ? 'Presenze' : 'Cartellini', '#/presenze']);
  v.push(['documenti', 'Documenti', '#/documenti']);
  if (IO.staff) v.push(['gestione', 'Gestione', '#/gestione']);
  v.push(['profilo', 'Profilo', '#/profilo']);
  return v;
}
const bollo = n => n ? `<span class="bollo">${n > 99 ? '99+' : n}</span>` : '';

function disegnaShell() {
  const u = IO.utente;
  const v = voci();
  const mobile = IO.staff ? ['home', 'richieste', 'gestione', 'bacheca'] : ['home', 'richieste', 'bacheca', IO.timbrature ? 'presenze' : 'situazione'];
  const corto = { home: 'Home', richieste: 'Richieste', gestione: 'Gestione', bacheca: 'Bacheca', presenze: 'Presenze', situazione: 'Situazione' };
  $('#app').innerHTML = `
  <div class="shell">
    <aside class="lato">
      <div class="marchio"><img src="/icona.svg" alt=""><div><b>SmartDesk</b><small>${esc(IO.scuola || 'Sportello del personale')}</small></div></div>
      ${v.map(([k, n, h]) => `<a class="voce" data-voce="${k}" href="${h}">${ico(k)}<span>${n}</span><span class="bollo-slot" data-b="${k}"></span></a>`).join('')}
      <div class="sotto"><b style="color:var(--text)">${esc(u.nome)} ${esc(u.cognome)}</b><br>${esc(u.ruolo_nome)} · a.s. ${esc(IO.anno)}
        <div class="crediti-lato">${ico('lupo')} by Wolf Team</div></div>
    </aside>
    <div class="principale">
      <header class="barra">
        <img class="marchio-mobile" src="/icona.svg" alt="">
        <div class="titolo" id="titolo"></div>
        ${bottoneTema()}
        <button class="tondo campana" id="campana" aria-label="Notifiche">${ico('campana')}<span class="bollo-slot" data-b="notifiche"></span></button>
        <a class="avatar" href="#/profilo" title="Profilo">${esc(iniziali(u))}</a>
      </header>
      <main class="contenuto" id="contenuto"></main>
    </div>
    <nav class="nav-mobile">
      ${mobile.map(k => `<a data-voce="${k}" href="${v.find(x => x[0] === k)[2]}">${ico(k)}<span>${corto[k]}</span><span class="bollo-slot" data-b="${k}"></span></a>`).join('')}
      <button id="altro">${ico('altro')}<span>Altro</span></button>
    </nav>
  </div>`;
  $('#campana').onclick = apriNotifiche;
  collegaTema();
  $('#altro').onclick = () => {
    const f = finestra(`<h2>Menu</h2><div class="lista">${v.filter(x => !mobile.includes(x[0])).map(([k, n, h]) =>
      `<a class="elem" href="${h}"><span class="ico">${ico(k)}</span><span class="testo"><b>${n}</b></span></a>`).join('')}
      <button class="elem" id="m-esci" style="cursor:pointer;font:inherit;text-align:left"><span class="ico">${ico('esci')}</span><span class="testo"><b>Esci</b></span></button></div>`);
    $$('a', f.el).forEach(a => a.addEventListener('click', f.chiudi));
    $('#m-esci', f.el).onclick = esci;
  };
  disegnaBadge();
}

function disegnaBadge() {
  $$('.bollo-slot').forEach(s => { s.innerHTML = bollo(BADGE[s.dataset.b]); });
  document.title = (BADGE.notifiche ? `(${BADGE.notifiche}) ` : '') + 'SmartDesk';
}

async function aggiornaBadge() {
  try {
    const [h, n] = await Promise.all([api('/api/home'), api('/api/notifiche')]);
    BADGE = { bacheca: h.n_da_leggere, gestione: h.da_lavorare || 0, notifiche: n.non_lette, richieste: h.da_integrare };
    disegnaBadge();
  } catch { /* offline */ }
}

async function apriNotifiche() {
  const vecchio = $('.notifiche');
  if (vecchio) { vecchio.remove(); return; }
  const n = await api('/api/notifiche');
  const box = document.createElement('div');
  box.className = 'card notifiche';
  box.innerHTML = `<div class="riga" style="padding:6px 10px"><b>Notifiche</b></div>` + (n.elenco.length ? n.elenco.map(x =>
    `<a href="${esc(x.link || '#/')}" class="${x.letta ? '' : 'nuova'}">${esc(x.testo)}<small>${fdt(x.quando)}</small></a>`).join('') :
    '<div class="vuoto">Nessuna notifica</div>');
  document.body.appendChild(box);
  const fuori = e => { if (!box.contains(e.target) && !e.target.closest('#campana')) { box.remove(); document.removeEventListener('mousedown', fuori); } };
  document.addEventListener('mousedown', fuori);
  $$('a', box).forEach(a => a.addEventListener('click', () => box.remove()));
  if (n.non_lette) { await api('/api/notifiche/lette', {}); BADGE.notifiche = 0; disegnaBadge(); }
}

async function esci() {
  try { await api('/api/esci', {}); } catch { /* già fuori */ }
  IO = null;
  location.hash = '#/';
  mostraAccesso();
}

// ------------------------------------------------------------------ router
const ROTTE = [
  [/^\/?$/, vistaHome, 'home', 'Home'],
  [/^\/richieste$/, vistaRichieste, 'richieste', 'Le mie richieste'],
  [/^\/nuova(?:\/(\w+))?$/, vistaNuova, 'richieste', 'Nuova richiesta'],
  [/^\/richiesta\/(\d+)$/, vistaRichiesta, 'richieste', 'Richiesta'],
  [/^\/modifica\/(\d+)$/, vistaModifica, 'richieste', 'Integra la richiesta'],
  [/^\/situazione$/, vistaSituazione, 'situazione', 'Situazione ferie e permessi'],
  [/^\/bacheca$/, vistaBacheca, 'bacheca', 'Bacheca'],
  [/^\/circolare\/(\d+)$/, vistaCircolare, 'bacheca', 'Circolare'],
  [/^\/nuova-circolare$/, vistaNuovaCircolare, 'bacheca', 'Nuova circolare'],
  [/^\/presenze$/, vistaPresenze, 'presenze', 'Presenze'],
  [/^\/documenti$/, vistaDocumenti, 'documenti', 'Documenti'],
  [/^\/gestione(?:\/([\w-]+))?$/, vistaGestione, 'gestione', 'Gestione'],
  [/^\/profilo$/, vistaProfilo, 'profilo', 'Profilo'],
];

async function naviga() {
  if (!IO) return;
  clearInterval(TIMER);
  $('.notifiche')?.remove();
  const [percorso, qs] = (location.hash.slice(1) || '/').split('?');
  const q = Object.fromEntries(new URLSearchParams(qs || ''));
  const r = ROTTE.find(([re]) => re.test(percorso)) || ROTTE[0];
  const m = percorso.match(r[0]) || [];
  $$('[data-voce]').forEach(a => a.classList.toggle('attiva', a.dataset.voce === r[2]));
  $('#titolo').textContent = r[3];
  const c = $('#contenuto');
  c.innerHTML = '<div class="vuoto">Caricamento…</div>';
  try {
    await r[1](c, m, q);
  } catch (e) {
    c.innerHTML = `<div class="card"><h2>Qualcosa non va</h2><p>${esc(e.message)}</p><a class="btn" href="#/">Torna alla home</a></div>`;
  }
  window.scrollTo(0, 0);
}
window.addEventListener('hashchange', naviga);

async function avvia() {
  try {
    IO = await api('/api/io');
  } catch { return; }
  disegnaShell();
  await naviga();
  aggiornaBadge();
  setInterval(() => IO && aggiornaBadge(), 60000);
}

// ------------------------------------------------------------------ componenti
function elemRichiesta(r, conNome = false) {
  const t = IO.tipologie.find(x => x.id === r.tipo);
  return `<a class="elem" href="#/richiesta/${r.id}">
    <span class="ico">${ico(ICO_GRUPPO[t?.gruppo] || 'richieste')}</span>
    <span class="testo"><b>${conNome ? esc(r.richiedente) + ' · ' : ''}${esc(r.tipo_nome)}</b>
      <span>${esc(periodo(r))}${quantita(r) ? ' · ' + quantita(r) : ''}${r.n_allegati ? ' · 📎' + r.n_allegati : ''}</span></span>
    <span class="destra">${chip(r.stato, r.stato_nome)}<small class="muted">n. ${r.id}</small></span></a>`;
}

function cardTimbra(timbrature) {
  const ultima = timbrature[timbrature.length - 1];
  const verso = ultima && ultima.verso === 'E' ? 'U' : 'E';
  return `<div class="card"><div class="timbra">
    <div><div class="muted piccolo">${esc(fd(oggiIso()))}</div><div class="orologio" id="orologio">--:--</div></div>
    <div class="spazio"><div class="muted piccolo" style="margin-bottom:4px">Timbrature di oggi</div>
      <div class="timb-oggi">${timbrature.length ? timbrature.map(t => `<span>${t.verso === 'E' ? '▶ Entrata' : '■ Uscita'} ${t.quando.slice(11, 16)}</span>`).join('') : '<span class="muted">nessuna</span>'}</div></div>
    <button class="btn ${verso === 'E' ? 'primario' : 'ok'} grande" id="btn-timbra" data-verso="${verso}">${verso === 'E' ? 'Timbra entrata' : 'Timbra uscita'}</button>
  </div></div>`;
}
function collegaTimbra(dopo) {
  const o = $('#orologio');
  const tic = () => { const d = new Date(); o.textContent = d.toTimeString().slice(0, 8); };
  tic();
  TIMER = setInterval(() => { if (!document.body.contains(o)) return clearInterval(TIMER); tic(); }, 1000);
  $('#btn-timbra').onclick = async e => {
    const v = e.currentTarget.dataset.verso;
    try {
      await api('/api/timbra', { verso: v });
      toast(v === 'E' ? 'Entrata registrata. Buon lavoro!' : 'Uscita registrata. A domani!');
      dopo();
    } catch (err) { toast(err.message, true); }
  };
}

function barraContatore(k) {
  const tot = Math.max(k.totale, 0.0001);
  const u = Math.min(100, k.usati / tot * 100), a = Math.min(100 - u, k.attesa / tot * 100);
  const un = k.unita === 'ore' ? 'ore' : 'giorni';
  return `<div class="card contatore">
    <div class="riga"><b>${esc(k.nome)}</b><span class="spazio"></span><span class="${k.residuo < 0 ? 'neg' : ''}" style="font-size:1.25rem;font-weight:700">${num(k.residuo)}</span><span class="muted piccolo">${un} rimasti su ${num(k.totale)}</span></div>
    <div class="barra-prog"><i class="u" style="width:${u}%"></i><i class="a" style="width:${a}%"></i></div>
    <div class="legenda"><span><i style="background:var(--primary)"></i>usati ${num(k.usati)}</span><span><i style="background:color-mix(in srgb,var(--primary) 40%,transparent)"></i>in attesa ${num(k.attesa)}</span><span>${esc(k.dettaglio)}</span></div>
  </div>`;
}

// ------------------------------------------------------------------ viste
async function vistaHome(c) {
  const d = await api('/api/home');
  const u = IO.utente;
  const ora = new Date().getHours();
  const saluto = ora < 13 ? 'Buongiorno' : ora < 18 ? 'Buon pomeriggio' : 'Buonasera';
  const ferie = d.contatori[0];
  c.innerHTML = `
    <div class="riga" style="margin-bottom:18px"><div><h1 style="margin:0">${saluto}, ${esc(u.nome)}</h1>
      <div class="muted">${esc(u.profilo || u.ruolo_nome)} · anno scolastico ${esc(IO.anno)}</div></div>
      <span class="spazio"></span><a class="btn primario" href="#/nuova">${ico('piu')} Nuova richiesta</a></div>
    ${u.cambia_password ? `<div class="avviso">Stai usando una password provvisoria. <a href="#/profilo">Cambiala adesso</a>.</div>` : ''}
    ${d.da_integrare ? `<div class="avviso">La segreteria ti chiede di integrare ${d.da_integrare === 1 ? 'una richiesta' : d.da_integrare + ' richieste'}. <a href="#/richieste">Vai alle richieste</a>.</div>` : ''}
    ${d.oggi_timbrature ? cardTimbra(d.oggi_timbrature) : ''}
    <div class="griglia sezione" style="margin-top:${d.oggi_timbrature ? 16 : 0}px">
      ${IO.staff ? `<a class="card tessera evid" href="#/gestione"><div class="num">${d.da_lavorare}</div><div class="lab">richieste da lavorare</div></a>
        <a class="card tessera" href="#/gestione/assenze"><div class="num">${d.assenti_oggi}</div><div class="lab">assenti oggi</div></a>` : ''}
      <a class="card tessera ${IO.staff ? '' : 'evid'}" href="#/situazione"><div class="num">${num(ferie.residuo)} <small>/ ${num(ferie.totale)}</small></div><div class="lab">giorni di ferie disponibili</div></a>
      <a class="card tessera" href="#/richieste"><div class="num">${d.attive}</div><div class="lab">richieste in corso</div></a>
      <a class="card tessera" href="#/bacheca?filtro=da-leggere"><div class="num">${d.n_da_leggere}</div><div class="lab">circolari da leggere</div></a>
    </div>
    <div class="due sezione">
      <div><h2>Prossime assenze <a href="#/richieste">tutte</a></h2>
        <div class="lista">${d.prossime.length ? d.prossime.map(r => elemRichiesta(r)).join('') : '<div class="card vuoto">Nessuna assenza in programma</div>'}</div></div>
      <div><h2>Bacheca <a href="#/bacheca">apri</a></h2>
        <div class="lista">${d.ultime_circolari.length ? d.ultime_circolari.map(elemCircolare).join('') : '<div class="card vuoto">Nessuna circolare</div>'}</div></div>
    </div>`;
  if (d.oggi_timbrature) collegaTimbra(() => naviga());
  BADGE.bacheca = d.n_da_leggere; BADGE.gestione = d.da_lavorare || 0; BADGE.richieste = d.da_integrare; disegnaBadge();
}

// stati delle richieste: in corso, concesse (giorni usati, si possono far annullare), chiuse
const IN_CORSO = ['inviata', 'verificata', 'da_integrare', 'annullamento'];
const CONCESSE = ['autorizzata', 'registrata', 'annullamento'];

// assenze registrate dalla segreteria che non corrispondono già a una richiesta fatta qui
function assenzeSoloSegreteria(assenze, richieste) {
  return assenze.filter(x => x.stato === 'registrata' && !x.richiesta && !richieste.some(r =>
    r.tipo === x.tipo && CONCESSE.concat('evasa').includes(r.stato) && r.dal && r.dal <= x.fine && (r.al || r.dal) >= x.inizio));
}

function elemAssenzaSegreteria(x) {
  const q = `${num(x.quantita)} ${x.unita === 'ore' ? 'ore' : x.quantita === 1 ? 'giorno' : 'giorni'}`;
  const r = x.richiesta;
  const destra = r && r.stato === 'annullamento' ? `<a class="chip annullamento" href="#/richiesta/${r.id}">Annullamento richiesto</a>`
    : r && r.stato === 'annullata' ? `<a class="chip letta" href="#/richiesta/${r.id}">Annullata: da togliere in segreteria</a>`
    : x.stato === 'registrata' ? `<button class="btn mini pericolo" data-annulla-seg="${x.id}" data-cosa="${esc((x.descrizione || 'Assenza') + ' del ' + fd(x.inizio))}">Chiedi l'annullamento</button>`
    : '<span class="chip">In attesa</span>';
  return `<div class="elem"><span class="ico">${ico('richieste')}</span><span class="testo"><b>${esc(x.descrizione || 'Assenza')}</b>
    <span>${fd(x.inizio)}${x.fine !== x.inizio ? ' – ' + fd(x.fine) : ''} · ${q} · registrata dalla segreteria</span></span>
    <span class="destra">${destra}</span></div>`;
}

function collegaAnnullaSegreteria(c) {
  $$('[data-annulla-seg]', c).forEach(b => b.onclick = async () => {
    const ris = await chiedi({
      titolo: "Chiedi l'annullamento", nota: true, notaObbligatoria: true, bottone: "Chiedi l'annullamento", pericolo: true,
      testo: `${b.dataset.cosa}. La richiesta va alla segreteria: quando la conferma, i giorni tornano disponibili.`,
    });
    if (!ris) return;
    try {
      const r = await api('/api/assenze-segreteria/annulla', { id: +b.dataset.annullaSeg, nota: ris.nota });
      toast('Richiesta di annullamento inviata alla segreteria.');
      location.hash = '#/richiesta/' + r.id;
    } catch (err) { toast(err.message, true); }
  });
}

async function vistaRichieste(c, m, q) {
  const [tutte, cont] = await Promise.all([api('/api/richieste'), api('/api/contatori')]);
  const filtro = q.filtro || 'corso';
  const segreteria = assenzeSoloSegreteria(cont.segreteria.assenze, tutte);
  const el = tutte.filter(r => filtro === 'tutte' || (filtro === 'corso' ? IN_CORSO.includes(r.stato)
    : filtro === 'usufruite' ? CONCESSE.includes(r.stato) : !IN_CORSO.includes(r.stato) && !CONCESSE.includes(r.stato)));
  // nelle usufruite: prima le più recenti, insieme a quelle registrate dalla segreteria
  const voci = filtro !== 'usufruite' ? el.map(r => ({ html: elemRichiesta(r) }))
    : el.map(r => ({ d: r.dal || '', html: elemRichiesta(r) })).concat(segreteria.map(x => ({ d: x.inizio, html: elemAssenzaSegreteria(x) })))
      .sort((a, b) => b.d.localeCompare(a.d));
  const nCorso = tutte.filter(r => IN_CORSO.includes(r.stato)).length;
  c.innerHTML = `
    <div class="riga" style="margin-bottom:16px"><h1 style="margin:0">Le mie richieste</h1><span class="spazio"></span><a class="btn primario" href="#/nuova">${ico('piu')} Nuova richiesta</a></div>
    <div class="filtri">${[['corso', 'In corso' + (nCorso ? ` (${nCorso})` : '')], ['usufruite', 'Concesse e usufruite'], ['concluse', 'Chiuse'], ['tutte', 'Tutte']].map(([k, n]) =>
      `<a class="pillola ${filtro === k ? 'attiva' : ''}" href="#/richieste?filtro=${k}" style="text-decoration:none;color:inherit">${n}</a>`).join('')}</div>
    ${filtro === 'usufruite' ? `<p class="muted piccolo">Apri una richiesta per chiederne l'annullamento: la segreteria lo conferma e i giorni tornano disponibili.${segreteria.length ? ' Le assenze registrate direttamente dalla segreteria hanno il pulsante qui accanto.' : ''}</p>` : ''}
    ${filtro === 'corso' && nCorso ? '<p class="muted piccolo">Per ritirare una richiesta in corso aprila e tocca «Annulla la richiesta».</p>' : ''}
    <div class="lista">${voci.length ? voci.map(v => v.html).join('') : `<div class="card vuoto">Nessuna richiesta ${filtro === 'corso' ? 'in corso' : filtro === 'usufruite' ? 'concessa' : ''}.<br><br><a class="btn primario" href="#/nuova">Fai una richiesta</a></div>`}</div>`;
  collegaAnnullaSegreteria(c);
}

async function vistaNuova(c, m) {
  const tipo = m[1];
  if (!tipo) {
    const gruppi = [...new Set(IO.tipologie.map(t => t.gruppo))];
    c.innerHTML = `<h1>Che cosa vuoi chiedere?</h1>` + gruppi.map(g => `
      <div class="sezione"><h2>${ico(ICO_GRUPPO[g], '') .replace('<svg', '<svg style="width:20px;height:20px;color:var(--primary)"')} ${esc(g)}</h2>
      <div class="tipi">${IO.tipologie.filter(t => t.gruppo === g).map(t => `<a class="tipo" href="#/nuova/${t.id}" style="text-decoration:none;color:inherit"><b>${esc(t.nome)}</b><span>${esc(t.descr || '')}</span></a>`).join('')}</div></div>`).join('');
    return;
  }
  const t = IO.tipologie.find(x => x.id === tipo);
  if (!t) throw new Error('Tipo di richiesta non disponibile per il tuo profilo.');
  await formRichiesta(c, t, null);
}

async function vistaModifica(c, m) {
  const r = await api('/api/richieste/' + m[1]);
  if (!r.azioni.some(a => a.id === 'modifica')) { location.hash = '#/richiesta/' + r.id; return; }
  const t = IO.tipologie.find(x => x.id === r.tipo);
  await formRichiesta(c, t, r);
}

async function formRichiesta(c, t, r) {
  const cont = (await api('/api/contatori')).contatori.filter(k => k.tipo === t.id);
  const v = r || { campi: {}, note: '' };
  const domani = new Date(Date.now() + 86400000 * Math.max(t.preavviso, 0));
  const dIn = `${domani.getFullYear()}-${String(domani.getMonth() + 1).padStart(2, '0')}-${String(domani.getDate()).padStart(2, '0')}`;
  const integrazione = r && r.storico.filter(s => s.azione === 'da_integrare').pop();
  c.innerHTML = `
    <a href="${r ? '#/richiesta/' + r.id : '#/nuova'}" class="riga piccolo" style="text-decoration:none;margin-bottom:10px">${ico('indietro').replace('<svg', '<svg style="width:16px"')} ${r ? 'Torna alla richiesta' : 'Tutte le tipologie'}</a>
    <div class="due" style="align-items:start">
    <form class="card" id="f-rich" novalidate>
      <h1>${esc(t.nome)}</h1>
      <p class="muted" style="margin-top:-4px">${esc(t.descr || '')}</p>
      ${integrazione ? `<div class="avviso"><b>Richiesta della segreteria:</b> ${esc(integrazione.nota)}</div>` : ''}
      ${t.unita === 'giorni' ? `<div class="campi2">
          <label class="campo"><span>Dal</span><input type="date" name="dal" value="${esc(v.dal || '')}" min="${t.passato != null ? '' : dIn}"></label>
          <label class="campo"><span>Al</span><input type="date" name="al" value="${esc(v.al || '')}"></label></div>` : ''}
      ${t.unita === 'ore' ? `<label class="campo"><span>Giorno</span><input type="date" name="dal" value="${esc(v.dal || '')}" min="${dIn}"></label>
        <div class="campi2"><label class="campo"><span>Dalle ore</span><input type="time" name="ora_da" value="${esc(v.ora_da || '')}" step="300"></label>
          <label class="campo"><span>Alle ore</span><input type="time" name="ora_a" value="${esc(v.ora_a || '')}" step="300"></label></div>` : ''}
      ${t.campi.map(f => `<label class="campo"><span>${esc(f.etichetta)}${f.obbligatorio ? ' *' : ''}</span>
        ${f.tipo === 'select' ? `<select name="c_${f.id}"><option value="">— scegli —</option>${f.opzioni.map(o => `<option ${v.campi[f.id] === o ? 'selected' : ''}>${esc(o)}</option>`).join('')}</select>` :
        `<input type="${f.tipo === 'date' ? 'date' : 'text'}" name="c_${f.id}" value="${esc(v.campi[f.id] || '')}">`}
        ${f.aiuto ? `<small>${esc(f.aiuto)}</small>` : ''}</label>`).join('')}
      <label class="campo"><span>Note per la segreteria</span><textarea name="note" placeholder="${t.unita === 'nessuna' ? 'Descrivi la richiesta' : 'Facoltative (es. sostituzioni già concordate)'}">${esc(v.note || '')}</textarea></label>
      ${r ? `<label class="campo"><span>Che cosa hai integrato?</span><input type="text" name="nota_integrazione" placeholder="Es. ho allegato il programma del corso"></label>` : ''}
      ${t.allegato !== 'no' ? htmlFile('f-all', 'Allegati', t.allegato === 'dopo' ? 'Si possono aggiungere anche dopo l\'invio.' : 'PDF o foto, al massimo 15 MB ciascuno.') : ''}
      <div id="anteprima"></div>
      <div class="riga"><button class="btn primario grande" id="invia">${r ? 'Reinvia la richiesta' : 'Invia la richiesta'}</button>
        <a class="btn" href="${r ? '#/richiesta/' + r.id : '#/nuova'}">Annulla</a></div>
    </form>
    <div>${cont.map(barraContatore).join('')}
      <div class="card"><h3>Come funziona</h3><ol class="muted piccolo" style="margin:0;padding-left:18px">
        ${t.comunicazione ? '<li>Invii la comunicazione.</li><li>La segreteria la registra.</li>' :
          t.id === 'generica' ? '<li>Invii la richiesta.</li><li>La segreteria la prepara e la segna come evasa: trovi il documento in «Documenti» o nella richiesta.</li>' :
          '<li>Invii la richiesta.</li><li>La segreteria verifica la spettanza.</li><li>' + (t.approva_dsga && IO.utente.categoria === 'ata' ? 'Il DSGA o il Dirigente' : 'Il Dirigente') + ' autorizza.</li>'}
        <li>Ricevi una notifica a ogni passaggio.</li>
        ${t.preavviso ? `<li>Preavviso minimo: ${t.preavviso} giorn${t.preavviso === 1 ? 'o' : 'i'}.</li>` : ''}</ol></div></div>
    </div>`;
  const form = $('#f-rich');
  const prendiFile = t.allegato !== 'no' ? collegaFile('f-all') : async () => [];
  const corpo = () => {
    const fd_ = new FormData(form);
    const campi = {};
    t.campi.forEach(f => { campi[f.id] = fd_.get('c_' + f.id) || ''; });
    return { tipo: t.id, id: r?.id, dal: fd_.get('dal') || '', al: fd_.get('al') || fd_.get('dal') || '', ora_da: fd_.get('ora_da') || '', ora_a: fd_.get('ora_a') || '', campi, note: fd_.get('note') || '', nota_integrazione: fd_.get('nota_integrazione') || '' };
  };
  const ant = $('#anteprima');
  let tAnt = null;
  const anteprima = async () => {
    const b = corpo();
    if (t.unita === 'nessuna' || !b.dal || (t.unita === 'ore' && (!b.ora_da || !b.ora_a))) { ant.innerHTML = ''; return; }
    const a = await api('/api/richieste/anteprima', b);
    if (a.ok) ant.innerHTML = `<div class="anteprima ok">✓ ${t.unita === 'ore' ? num(a.quantita) + ' ore' : num(a.quantita) + (a.quantita === 1 ? ' giorno lavorativo' : ' giorni lavorativi')}${a.avvisi.length ? '<br><small>' + a.avvisi.map(esc).join('<br>') + '</small>' : ''}</div>`;
    else if (!/^Compila|^Scegli|^Hai indicato/.test(a.errore)) ant.innerHTML = `<div class="anteprima no">${esc(a.errore)}</div>`;
    else ant.innerHTML = '';
  };
  form.addEventListener('input', e => {
    if (e.target.name === 'dal' && form.al && (!form.al.value || form.al.value < e.target.value)) form.al.value = e.target.value;
    clearTimeout(tAnt); tAnt = setTimeout(anteprima, 250);
  });
  if (r) anteprima();
  form.onsubmit = async e => {
    e.preventDefault();
    const b = $('#invia');
    b.disabled = true;
    try {
      const dati = corpo();
      dati.allegati = await prendiFile();
      const ris = await api(r ? '/api/richieste/' + r.id : '/api/richieste', dati);
      toast(r ? 'Richiesta reinviata.' : 'Richiesta inviata alla segreteria.');
      location.hash = '#/richiesta/' + (r ? r.id : ris.id);
      aggiornaBadge();
    } catch (err) {
      toast(err.message, true);
      ant.innerHTML = `<div class="anteprima no">${esc(err.message)}</div>`;
      b.disabled = false;
    }
  };
}

const NOMI_STORICO = { inviata: 'Inviata', verificata: 'Verificata dalla segreteria', da_integrare: 'Richiesta integrazione', autorizzata: 'Autorizzata',
  respinta: 'Respinta', registrata: 'Registrata', evasa: 'Evasa', annullata: 'Annullata', revocata: 'Revocata', reinviata: 'Integrata e reinviata', allegato: 'Allegato aggiunto',
  chiedi_annullamento: 'Chiesto l\'annullamento', ritira_annullamento: 'Ritirata la richiesta di annullamento',
  conferma_annullamento: 'Annullamento confermato: giorni restituiti', nega_annullamento: 'Annullamento non accolto' };
const AZ_PERICOLO = ['respingi', 'annulla', 'revoca', 'chiedi_annullamento', 'nega_annullamento'];
const AZ_OK = ['autorizza', 'registra', 'evadi', 'conferma_annullamento'];

async function vistaRichiesta(c, m) {
  const r = await api('/api/richieste/' + m[1]);
  const mia = r.utente_id === IO.utente.id;
  const t = r.tipologia;
  $('#titolo').textContent = `Richiesta n. ${r.id}`;
  const dati = [['Numero', r.id]];
  if (!mia) dati.push(['Dipendente', `${r.richiedente} (${r.richiedente_ruolo})`]);
  if (r.dal) dati.push([t.unita === 'ore' ? 'Quando' : 'Periodo', periodo(r)], ['Durata', quantita(r)]);
  t.campi.forEach(f => { if (r.campi[f.id]) dati.push([f.etichetta, f.tipo === 'date' ? fd(r.campi[f.id], false) : r.campi[f.id]]); });
  if (r.campi.origine === 'segreteria') dati.push(['Assenza', r.campi.assenza + ' (registrata dalla segreteria)']);
  if (r.note) dati.push(['Note', r.note]);
  dati.push([r.campi.origine === 'segreteria' ? 'Annullamento chiesto' : 'Inviata', fdt(r.creata)]);
  const puoAllegare = (mia || IO.staff) && !['annullata'].includes(r.stato);
  const mancaAttestato = mia && r.allegato_richiesto === 'dopo' && !r.allegati.length && !['annullata', 'respinta'].includes(r.stato);
  c.innerHTML = `
    <a href="${mia ? '#/richieste' : '#/gestione'}" class="riga piccolo" style="text-decoration:none;margin-bottom:10px">${ico('indietro').replace('<svg', '<svg style="width:16px"')} ${mia ? 'Le mie richieste' : 'Gestione'}</a>
    <div class="due" style="align-items:start">
    <div>
      <div class="card">
        <div class="riga" style="margin-bottom:12px"><h1 style="margin:0">${esc(r.tipo_nome)}</h1>${chip(r.stato, r.stato_nome)}</div>
        <dl class="dati">${dati.map(([k, v]) => `<dt>${esc(k)}</dt><dd style="white-space:pre-wrap">${esc(v)}</dd>`).join('')}</dl>
        ${r.contatori_richiedente?.length ? `<div class="sezione">${r.contatori_richiedente.map(barraContatore).join('')}</div>` : ''}
      </div>
      ${mancaAttestato ? '<div class="avviso" style="margin-top:16px">Ricordati di allegare l\'attestazione.</div>' : ''}
      <div class="card"><div class="riga"><h2 style="margin:0">Allegati</h2><span class="spazio"></span>
        ${puoAllegare ? `<label class="btn mini">${ico('clip')} Aggiungi<input type="file" id="agg-all" multiple hidden></label>` : ''}</div>
        <div style="margin-top:10px">${r.allegati.length ? r.allegati.map(a => `<a class="allegato" href="/api/allegati/${a.id}" target="_blank" rel="noopener">${ico('documenti')} ${esc(a.nome)}</a>`).join('') : '<span class="muted">Nessun allegato</span>'}</div>
      </div>
      ${r.azioni.length ? `<div class="card"><h2>Azioni</h2><div class="riga">${r.azioni.map(a =>
        `<button class="btn ${AZ_OK.includes(a.id) ? 'ok' : a.id === 'verifica' || a.id === 'modifica' ? 'primario' : AZ_PERICOLO.includes(a.id) ? 'pericolo' : ''}" data-az="${a.id}" data-nota="${a.nota ? 1 : 0}">${esc(a.nome)}</button>`).join('')}</div></div>` : ''}
    </div>
    <div class="card"><h2>Cronologia</h2><ol class="storia">${r.storico.map(s => `<li><b>${esc(NOMI_STORICO[s.azione] || s.azione)}</b>
      <small>${fdt(s.quando)}${s.chi ? ' · ' + esc(s.chi) : ''}</small>${s.nota ? `<div class="nota">${esc(s.nota)}</div>` : ''}</li>`).join('')}</ol></div>
    </div>`;
  $('#agg-all')?.addEventListener('change', async e => {
    try {
      const files = await Promise.all([...e.target.files].map(leggiFile));
      await api(`/api/richieste/${r.id}/allegati`, { allegati: files });
      toast('Allegato aggiunto.');
      naviga();
    } catch (err) { toast(err.message, true); }
  });
  $$('[data-az]', c).forEach(b => b.onclick = async () => {
    const az = b.dataset.az;
    if (az === 'modifica') { location.hash = '#/modifica/' + r.id; return; }
    const nomeAz = r.azioni.find(a => a.id === az).nome;
    const ris = await chiedi({
      titolo: nomeAz, nota: !['annulla', 'ritira_annullamento'].includes(az), notaObbligatoria: b.dataset.nota === '1',
      testo: az === 'annulla' ? 'La richiesta verrà ritirata. Potrai farne una nuova.'
        : az === 'chiedi_annullamento' ? 'Scrivi il motivo. La richiesta va alla segreteria: quando conferma, i giorni tornano disponibili.'
        : az === 'ritira_annullamento' ? 'La richiesta resta valida com\'era prima.'
        : az === 'conferma_annullamento' ? `${r.richiedente} – ${r.tipo_nome}, ${periodo(r)}. I giorni tornano disponibili.${r.campi.origine === 'segreteria' ? ' Ricordati di togliere l\'assenza anche dal programma della segreteria.' : ''}`
        : az === 'integra' ? 'Spiega che cosa manca: il dipendente riceverà una notifica e potrà modificare la richiesta.' : `${r.richiedente} – ${r.tipo_nome}, ${periodo(r)}`,
      bottone: nomeAz, pericolo: AZ_PERICOLO.includes(az),
    });
    if (!ris) return;
    try {
      await api(`/api/richieste/${r.id}/azione`, { azione: az, nota: ris.nota });
      toast('Fatto: ' + nomeAz.toLowerCase() + '.');
      aggiornaBadge();
      naviga();
    } catch (err) { toast(err.message, true); }
  });
}

function notaSegreteria(s, altro) {
  if (!s) return '';
  const quando = s.letto ? new Date(s.letto).toLocaleString('it-IT', { dateStyle: 'short', timeStyle: 'short' }) : '';
  if (s.errore) return `<p class="avviso">Non è stato possibile leggere le assenze registrate dalla segreteria${quando ? ' (restano i dati del ' + esc(quando) + ')' : ''}: ${esc(s.errore)}.</p>`;
  if (quando) return `<p class="muted piccolo">Conteggi presi dal programma della segreteria all'ultimo accesso con Argo (${esc(quando)}), più le richieste fatte qui e non ancora registrate.${altro ? '' : ' Si aggiornano a ogni accesso.'}</p>`;
  return altro ? '' : `<p class="muted piccolo">Per vedere i giorni già registrati dalla segreteria, entra con le credenziali Argo.</p>`;
}

async function vistaSituazione(c, m, q) {
  const d = await api('/api/contatori' + (q.utente ? '?utente=' + q.utente : ''));
  const altro = d.utente.id !== IO.utente.id;
  c.innerHTML = `<h1>${altro ? 'Situazione di ' + esc(d.utente.nome + ' ' + d.utente.cognome) : 'Situazione ferie e permessi'}</h1>
    <p class="muted">Anno scolastico ${esc(d.anno)}. Le richieste in attesa sono già scalate dal disponibile.</p>
    ${notaSegreteria(d.segreteria, altro)}
    <div class="due">${d.contatori.map(barraContatore).join('')}</div>
    ${d.segreteria.assenze.length ? `<h2 style="margin-top:24px">Registrate dalla segreteria</h2>
      <div class="card lista">${d.segreteria.assenze.map(x => altro ? elemAssenzaSegreteria({ ...x, stato: x.stato === 'registrata' ? 'vista' : x.stato }).replace('<span class="chip">In attesa</span>', '') : elemAssenzaSegreteria(x)).join('')}</div>` : ''}`;
  collegaAnnullaSegreteria(c);
  // .card + .card aggiunge margine verticale nelle colonne: lo togliamo nella griglia
  $$('.due > .card', c).forEach(x => x.style.marginTop = '0');
}

function elemCircolare(ci) {
  const daLeggere = ci.presa_visione && !ci.letta;
  const scad = livelloScadenza(ci.adesione && ci.scadenza, !ci.letta);
  return `<a class="elem ${scad}" href="#/circolare/${ci.id}">
    <span class="ico">${ico('bacheca')}</span>
    <span class="testo"><b>${ci.fonte === 'argo' ? '' : 'n. ' + ci.numero + ' · '}${esc(ci.titolo)}</b><span>${fd(ci.data)} · ${ci.fonte === 'argo' ? 'Argo' + (ci.categoria ? ' – ' + esc(ci.categoria) : '') : esc(DEST[ci.destinatari])}${ci.n_allegati ? ' · 📎' + ci.n_allegati : ''}</span></span>
    <span class="destra">${chipScadenza(scad)}${daLeggere && !scad ? `<span class="chip nonletta">${ci.adesione ? 'Da rispondere' : 'Da leggere'}</span>` : ci.letta ? `<span class="chip letta">${ci.risposta ? esc(ci.risposta) : 'Letta'}</span>` : ''}</span></a>`;
}

async function vistaBacheca(c, m, q) {
  const filtro = q.filtro || 'tutte';
  c.innerHTML = `
    <div class="riga" style="margin-bottom:16px"><h1 style="margin:0">Bacheca</h1><span class="spazio"></span>
      ${IO.staff && IO.impostazioni.argo_codice_scuola ? `<button class="btn" id="agg-argo">Aggiorna da Argo</button>` : ''}
      ${IO.staff ? `<a class="btn primario" href="#/nuova-circolare">${ico('piu')} Nuova circolare</a>` : ''}</div>
    ${IO.impostazioni.argo_codice_scuola && IO.impostazioni.argo_bacheca === '1' ? `<p class="muted piccolo" style="margin-top:-8px">Comprende le pubblicazioni di «La Segreteria Comunica» di Argo (${esc(IO.impostazioni.argo_codice_scuola)}), aggiornate ogni 30 minuti. Le circolari interne di DidUP sono nel riquadro qui sopra.</p>` : ''}
    <div id="didup"></div>
    <div class="filtri">
      <input type="search" id="cerca" placeholder="Cerca per titolo, testo o numero…" value="${esc(q.q || '')}" style="max-width:380px">
      ${[['tutte', 'Tutte'], ['da-leggere', 'Da leggere']].map(([k, n]) => `<button class="pillola ${filtro === k ? 'attiva' : ''}" data-f="${k}">${n}</button>`).join('')}
    </div>
    <div class="lista" id="elenco-circ"></div>`;
  let filtroAtt = filtro;
  const carica = async () => {
    const cerca = $('#cerca').value.trim();
    const el = await api(`/api/circolari?q=${encodeURIComponent(cerca)}${filtroAtt === 'da-leggere' ? '&da_leggere=1' : ''}`);
    $('#elenco-circ').innerHTML = el.length ? el.map(elemCircolare).join('') : '<div class="card vuoto">Nessuna circolare trovata.</div>';
  };
  let tt = null;
  $('#cerca').oninput = () => { clearTimeout(tt); tt = setTimeout(carica, 250); };
  $('#agg-argo')?.addEventListener('click', async e => {
    e.target.disabled = true;
    try { const r = await api('/api/circolari/aggiorna-argo', {}); toast(r.nuove ? `${r.nuove} pubblicazioni nuove da Argo.` : 'Bacheca già aggiornata.'); await carica(); } catch (err) { toast(err.message, true); }
    e.target.disabled = false;
  });
  $$('[data-f]', c).forEach(b => b.onclick = () => { filtroAtt = b.dataset.f; $$('[data-f]', c).forEach(x => x.classList.toggle('attiva', x === b)); carica(); });
  caricaDidup($('#didup'));
  await carica();
}

// ---- circolari DidUP: presa visione e adesione in un tocco (SmartDesk apre davvero l'allegato al posto tuo)
async function caricaDidup(box, tutte = false) {
  if (!box) return;
  box.innerHTML = `<div class="card didup"><div class="riga"><h2 style="margin:0">Circolari DidUP</h2><span class="spazio"></span><span class="muted piccolo">Caricamento…</span></div></div>`;
  let d;
  try { d = await api('/api/didup/bacheca'); } catch (err) { d = { collegata: false, motivo: err.message }; }
  if (!d.collegata) {
    box.innerHTML = `<div class="card didup spenta"><div class="riga" style="flex-wrap:nowrap"><span class="ico-didup">${ico('bacheca')}</span>
      <div class="spazio"><b>Circolari DidUP</b><div class="muted piccolo">${esc(d.motivo)}</div></div></div></div>`;
    return;
  }
  const msg = tutte ? d.messaggi : d.messaggi.filter((x, i) => (x.pv_richiesta && !x.pv_fatta) || (x.ad_richiesta && !x.ad_fatta) || i < d.da_fare + 5);
  const soloPv = d.messaggi.filter(x => x.pv_richiesta && !x.pv_fatta && !x.ad_richiesta);
  box.innerHTML = `<div class="card didup">
    <div class="riga" style="margin-bottom:6px"><h2 style="margin:0">Circolari DidUP</h2>
      ${d.da_fare ? `<span class="chip nonletta">${d.da_fare} da confermare</span>` : '<span class="chip letta">Tutto confermato</span>'}
      <span class="spazio"></span>
      ${soloPv.length > 1 ? `<button class="btn primario mini" id="dd-tutte">${ico('ok')} Prendi visione di tutte (${soloPv.length})</button>` : ''}</div>
    <p class="muted piccolo" style="margin:0 0 12px">Un tocco basta: SmartDesk scarica l'allegato al posto tuo e poi conferma su Argo. I file restano qui, pronti da aprire.</p>
    <div class="lista">${msg.map(elemDidup).join('') || '<div class="vuoto">Nessun messaggio.</div>'}</div>
    ${!tutte && msg.length < d.messaggi.length ? `<button class="btn mini" id="dd-altre" style="margin-top:10px">Mostra anche le altre (${d.messaggi.length - msg.length})</button>` : ''}
  </div>`;
  $('#dd-altre', box)?.addEventListener('click', () => caricaDidup(box, true));
  const conferma = async (pk, adesione, bottone) => {
    const el = bottone.closest('.didup-msg');
    el.classList.add('occupato');
    $$('button', el).forEach(b => b.disabled = true);
    const vecchio = bottone.innerHTML;
    bottone.innerHTML = adesione ? 'Invio…' : 'Apro e confermo…';
    try {
      const r = await api(`/api/didup/bacheca/${pk}/conferma`, { adesione: adesione || null });
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
  box.onclick = async e => {
    const b = e.target.closest('[data-pv],[data-ad]');
    if (!b || b.disabled) return;
    try {
      const r = await conferma(b.dataset.pv || b.dataset.pk, b.dataset.ad, b);
      toast(b.dataset.ad ? `Adesione registrata su Argo: ${d.adesioni[b.dataset.ad]}.` : `Presa visione registrata su Argo${r.scaricati ? ' (allegato aperto e salvato)' : ''}.`);
    } catch { /* già segnalato */ }
  };
  $('#dd-tutte', box)?.addEventListener('click', async e => {
    e.stopPropagation();
    if (!confirm(`Confermare la presa visione di ${soloPv.length} circolari su Argo? SmartDesk scarica prima ogni allegato.`)) return;
    e.target.disabled = true;
    let ok = 0;
    for (const x of soloPv) {
      const b = $(`[data-pv="${x.pk}"]`, box);
      if (!b) continue;
      try { await conferma(x.pk, null, b); ok++; } catch { break; }
    }
    toast(`Presa visione registrata per ${ok} circolari.`);
    caricaDidup(box, tutte);
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
        <div class="muted piccolo">${x.data ? fd(x.data) : ''}${x.categoria ? ' · ' + esc(x.categoria) : ''}${x.mittente ? ' · ' + esc(x.mittente) : ''}${x.n_allegati ? ' · 📎 ' + x.n_allegati : ''}</div>
        ${x.testo && x.testo !== x.titolo ? `<details><summary class="piccolo">Testo</summary><div class="testo-circ piccolo">${esc(x.testo)}</div></details>` : ''}
        ${x.scaricati.length ? `<div style="margin-top:8px">${x.scaricati.map(a => `<a class="allegato" href="${a.url}" target="_blank" rel="noopener">${ico('scarica')} ${esc(a.nome)}</a>`).join('')}</div>` : ''}
      </div>
    </div>
    <div class="azioni">
      ${pvDaFare ? `<button class="btn primario" data-pv="${x.pk}">${ico('ok')} Prendo visione</button>`
        : x.pv_fatta ? `<span class="chip letta">Presa visione${x.pv_quando ? ' · ' + esc(x.pv_quando) : ''}</span>` : ''}
      ${x.ad_richiesta ? `<div class="adesione">${Object.entries({ A: 'Aderisco', N: 'Non aderisco', X: 'Non ho deciso' }).map(([k, n]) =>
        `<button class="pillola ${x.adesione === k ? 'attiva' : ''}" data-ad="${k}" data-pk="${x.pk}" ${bloccaAd ? 'disabled' : ''}>${n}</button>`).join('')}
        ${x.ad_scadenza ? `<span class="muted piccolo">entro ${fd(x.ad_scadenza)}${scadAd ? ' (scaduto)' : ''}</span>` : ''}</div>` : ''}
    </div>
  </div>`;
}

async function vistaCircolare(c, m) {
  const ci = await api('/api/circolari/' + m[1]);
  const daArgo = ci.fonte === 'argo';
  $('#titolo').textContent = daArgo ? 'Bacheca' : `Circolare n. ${ci.numero}`;
  const scaduta = ci.scadenza && ci.scadenza < oggiIso();
  let azione = '';
  if (ci.adesione) {
    azione = `<div class="card"><h2>La tua risposta</h2>
      ${ci.scadenza ? (() => { const l = livelloScadenza(ci.scadenza, !ci.letta);
        return l ? `<p class="avviso ${l}">Rispondi entro ${fd(ci.scadenza)}: ${l === 'scaduta' ? '<b>termine scaduto.</b>' : l === 'scade-oggi' ? '<b>scade oggi.</b>' : '<b>scade domani.</b>'}</p>`
          : `<p class="muted">Rispondi entro ${fd(ci.scadenza)}.${scaduta ? ' <b>Termine scaduto.</b>' : ''}</p>`; })() : ''}
      <div class="riga">${['Aderisco', 'Non aderisco', 'Non ho ancora deciso'].map(rr => `<button class="btn ${ci.risposta === rr ? 'primario' : ''}" data-risp="${rr}" ${scaduta ? 'disabled' : ''}>${rr}</button>`).join('')}</div>
      ${ci.letta ? `<p class="muted piccolo">Risposta inviata ${fdt(ci.quando_letta)}.</p>` : ''}</div>`;
  } else if (ci.presa_visione) {
    azione = ci.letta ? `<div class="card"><span class="chip letta">Presa visione</span> <span class="muted piccolo">${fdt(ci.quando_letta)}</span></div>` :
      `<div class="card riga"><span class="spazio">Questa circolare richiede la presa visione.</span><button class="btn primario" data-risp="">Confermo la presa visione</button></div>`;
  }
  const st = ci.statistiche;
  c.innerHTML = `
    <a href="#/bacheca" class="riga piccolo" style="text-decoration:none;margin-bottom:10px">${ico('indietro').replace('<svg', '<svg style="width:16px"')} Bacheca</a>
    <div class="card"><div class="muted piccolo">${daArgo ? `Argo – La Segreteria Comunica${ci.categoria ? ' · ' + esc(ci.categoria) : ''}` : `Circolare n. ${ci.numero} · a.s. ${esc(ci.anno)}`} · ${fd(ci.data)}${daArgo ? '' : ' · ' + esc(DEST[ci.destinatari])}</div>
      <h1 style="margin-top:6px">${esc(ci.titolo)}</h1>
      <div class="testo-circ">${esc(ci.testo)}</div>
      ${ci.allegati.length || ci.link_esterni.length ? `<div class="sezione">${ci.allegati.map(a => `<a class="allegato" href="/api/allegati/${a.id}" target="_blank" rel="noopener">${ico('documenti')} ${esc(a.nome)}</a>`).join('')}${ci.link_esterni.map(a => `<a class="allegato" href="${esc(a.url)}" target="_blank" rel="noopener noreferrer">${ico('documenti')} ${esc(a.nome)}</a>`).join('')}</div>` : ''}
    </div>
    ${azione}
    ${st ? `<div class="card"><div class="riga"><h2 style="margin:0">Letture</h2><span class="spazio"></span><a class="btn mini" href="/api/circolari/${ci.id}/letture.csv">${ico('scarica')} CSV</a></div>
      <p><b>${st.lette}</b> su ${st.destinatari} hanno ${ci.adesione ? 'risposto' : 'preso visione'}.
      ${Object.entries(st.risposte).map(([k, v]) => `<span class="chip" style="margin-left:6px">${esc(k)}: ${v}</span>`).join('')}</p>
      <div class="barra-prog" style="height:10px;border-radius:99px;background:var(--grey-soft);overflow:hidden;display:flex"><i class="u" style="width:${st.destinatari ? st.lette / st.destinatari * 100 : 0}%;background:var(--primary)"></i></div>
      <div class="filtri" style="margin-top:14px"><button class="pillola attiva" data-l="tutti">Tutti</button><button class="pillola" data-l="no">Non ancora</button></div>
      <div class="tabella-wrap"><table><thead><tr><th>Nome</th><th class="nascondi-mobile">Ruolo</th><th>Letta</th>${ci.adesione ? '<th>Risposta</th>' : ''}</tr></thead>
      <tbody>${st.elenco.map(x => `<tr data-letto="${x.quando ? 1 : 0}"><td>${esc(x.nome)}</td><td class="nascondi-mobile muted">${esc(x.ruolo)}</td><td>${x.quando ? fdt(x.quando) : '<span class="neg">no</span>'}</td>${ci.adesione ? `<td>${esc(x.risposta)}</td>` : ''}</tr>`).join('')}</tbody></table></div></div>` : ''}`;
  $$('[data-risp]', c).forEach(b => b.onclick = async () => {
    try {
      await api(`/api/circolari/${ci.id}/leggi`, { risposta: b.dataset.risp });
      toast('Grazie, registrato.');
      aggiornaBadge();
      naviga();
    } catch (err) { toast(err.message, true); }
  });
  $$('[data-l]', c).forEach(b => b.onclick = () => {
    $$('[data-l]', c).forEach(x => x.classList.toggle('attiva', x === b));
    $$('tr[data-letto]', c).forEach(tr => { tr.hidden = b.dataset.l === 'no' && tr.dataset.letto === '1'; });
  });
}

async function vistaNuovaCircolare(c) {
  if (!IO.staff) throw new Error('Funzione riservata alla segreteria e alla dirigenza.');
  c.innerHTML = `<form class="card" id="f-circ" style="max-width:720px"><h1>Nuova circolare</h1>
    <label class="campo"><span>Titolo *</span><input type="text" name="titolo" required maxlength="200"></label>
    <label class="campo"><span>Destinatari</span><select name="destinatari"><option value="tutti">Tutto il personale</option><option value="docenti">Docenti</option><option value="ata">Personale ATA</option></select></label>
    <label class="campo"><span>Testo</span><textarea name="testo" style="min-height:180px"></textarea></label>
    ${htmlFile('f-call', 'Allegati')}
    <label class="spunta"><input type="checkbox" name="presa_visione" checked><span>Richiede la presa visione</span></label>
    <label class="spunta"><input type="checkbox" name="adesione"><span>Chiede una risposta di adesione (es. sciopero: aderisco / non aderisco / non ho ancora deciso)</span></label>
    <label class="campo" id="sc-box" hidden><span>Rispondere entro</span><input type="date" name="scadenza"></label>
    <div class="riga"><button class="btn primario grande">Pubblica e notifica</button><a class="btn" href="#/bacheca">Annulla</a></div></form>`;
  const f = $('#f-circ');
  const prendi = collegaFile('f-call');
  f.adesione.onchange = () => { $('#sc-box').hidden = !f.adesione.checked; };
  f.onsubmit = async e => {
    e.preventDefault();
    try {
      const ris = await api('/api/circolari', {
        titolo: f.titolo.value, destinatari: f.destinatari.value, testo: f.testo.value, presa_visione: f.presa_visione.checked,
        adesione: f.adesione.checked, scadenza: f.adesione.checked ? f.scadenza.value : '', allegati: await prendi(),
      });
      toast(`Circolare n. ${ris.numero} pubblicata.`);
      location.hash = '#/circolare/' + ris.id;
    } catch (err) { toast(err.message, true); }
  };
}

async function vistaPresenze(c, m, q) {
  const mese = q.mese || oggiIso().slice(0, 7);
  let utenti = null;
  if (IO.staff) utenti = await api('/api/utenti');
  const target = q.utente || (IO.timbrature ? IO.utente.id : utenti.find(u => u.categoria === 'ata' && u.attivo)?.id);
  if (!target) {
    c.innerHTML = `<h1>Cartellini</h1><div class="card vuoto">Non c'è ancora personale ATA in SmartDesk.<br>I cartellini compaiono quando i collaboratori entrano con Argo o vengono aggiunti in Gestione › Personale.</div>`;
    return;
  }
  const k = await api(`/api/cartellino?mese=${mese}&utente=${target}`);
  const mio = k.utente.id === IO.utente.id;
  const oggiT = mio && IO.timbrature ? (k.giorni.find(g => g.data === oggiIso())?.timbrature || []) : null;
  const [ay, am] = mese.split('-').map(Number);
  const sposta = n => { const d = new Date(ay, am - 1 + n, 1); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`; };
  const link = me => `#/presenze?mese=${me}${q.utente ? '&utente=' + q.utente : ''}`;
  const segno = n => { if (n == null) return ''; n = Math.round(n * 10) / 10; return `<span class="${n > 0 ? 'pos' : n < 0 ? 'neg' : ''}">${n > 0 ? '+' : ''}${num(n)}</span>`; };
  const correggi = IO.staff && (!mio || IO.utente.ruolo === 'dirigente');
  c.innerHTML = `
    ${oggiT ? cardTimbra(oggiT) : ''}
    <div class="riga sezione" style="margin-bottom:14px;margin-top:${oggiT ? 20 : 0}px">
      <h1 style="margin:0">Cartellino${mio ? '' : ' di ' + esc(k.utente.nome + ' ' + k.utente.cognome)}</h1><span class="spazio"></span>
      ${utenti ? `<select id="sel-ut" style="max-width:260px">${utenti.filter(u => u.attivo && (u.categoria === 'ata' || IO.impostazioni.timbrature_docenti === '1' || u.id === k.utente.id)).map(u => `<option value="${u.id}" ${u.id === k.utente.id ? 'selected' : ''}>${esc(u.cognome + ' ' + u.nome)}</option>`).join('')}</select>` : ''}
    </div>
    <div class="filtri"><a class="btn mini" href="${link(sposta(-1))}">‹</a><b style="min-width:150px;text-align:center;text-transform:capitalize">${MESI[am - 1]} ${ay}</b><a class="btn mini" href="${link(sposta(1))}">›</a>
      <span class="spazio"></span>
      ${correggi ? `<button class="btn mini" id="agg-timb">${ico('piu')} Aggiungi timbratura</button>` : ''}
      <a class="btn mini" href="/api/cartellino.csv?mese=${mese}&utente=${k.utente.id}">${ico('scarica')} CSV</a><button class="btn mini" onclick="print()">Stampa</button></div>
    <div class="griglia" style="margin-bottom:16px">
      <div class="card tessera"><div class="num">${num(k.ore)}</div><div class="lab">ore lavorate</div></div>
      <div class="card tessera"><div class="num">${num(k.teorico)}</div><div class="lab">ore dovute (${num(k.utente.ore_giornaliere)} al giorno)</div></div>
      <div class="card tessera"><div class="num">${segno(k.saldo) || '0'}</div><div class="lab">saldo del mese</div></div>
    </div>
    <div class="tabella-wrap"><table><thead><tr><th>Giorno</th><th>Timbrature</th><th class="num">Ore</th><th class="num">Saldo</th><th>Note</th></tr></thead><tbody>
    ${k.giorni.map(g => `<tr class="${!g.lavorativo ? 'festa' : ''} ${g.data === oggiIso() ? 'oggi' : ''}">
      <td style="white-space:nowrap">${fd(g.data, true).replace(/ \d{4}$/, '')}</td>
      <td>${g.timbrature.map(t => `<span style="white-space:nowrap;margin-right:8px" title="${esc(t.fonte + (t.nota ? ' – ' + t.nota : ''))}">${t.verso === 'E' ? '▶' : '■'} ${t.quando.slice(11, 16)}${t.fonte !== 'app' ? '*' : ''}${correggi ? ` <button class="btn mini" style="min-height:22px;padding:0 6px" data-del="${t.id}" title="Elimina">✕</button>` : ''}</span>`).join('')}${g.aperta && g.data !== oggiIso() ? ' <span class="neg">manca l\'uscita</span>' : ''}</td>
      <td class="num">${g.ore ? num(g.ore) : ''}</td><td class="num">${segno(g.saldo)}</td>
      <td>${g.assenze.map(a => `<a href="#/richiesta/${a.id}" class="piccolo">${esc(a.tipo)}${a.ore ? ' ' + a.ore : ''}</a>${['inviata', 'verificata'].includes(a.stato) ? ' <small class="muted">(in attesa)</small>' : ''}`).join('<br>')}${!g.lavorativo ? '<span class="muted piccolo">non lavorativo</span>' : ''}</td></tr>`).join('')}
    </tbody></table></div>
    <p class="muted piccolo">* timbratura inserita o corretta dalla segreteria. Le ore dei permessi orari autorizzati contano nel saldo.</p>`;
  if (oggiT) collegaTimbra(() => naviga());
  $('#sel-ut')?.addEventListener('change', e => { location.hash = `#/presenze?mese=${mese}&utente=${e.target.value}`; });
  $$('[data-del]', c).forEach(b => b.onclick = async () => {
    const ok = await chiedi({ titolo: 'Eliminare la timbratura?', bottone: 'Elimina', pericolo: true });
    if (!ok) return;
    try { await api(`/api/timbrature/${b.dataset.del}/elimina`, {}); toast('Timbratura eliminata.'); naviga(); } catch (err) { toast(err.message, true); }
  });
  $('#agg-timb')?.addEventListener('click', () => {
    const f = finestra(`<h2>Aggiungi timbratura</h2><p class="muted">${esc(k.utente.nome + ' ' + k.utente.cognome)}</p>
      <div class="campi2"><label class="campo"><span>Verso</span><select id="t-v"><option value="E">Entrata</option><option value="U">Uscita</option></select></label>
      <label class="campo"><span>Data e ora</span><input type="datetime-local" id="t-q" value="${oggiIso()}T07:30"></label></div>
      <label class="campo"><span>Motivo della correzione *</span><input type="text" id="t-n" placeholder="Es. dimenticata la timbratura"></label>
      <div class="piede"><button class="btn" data-chiudi>Annulla</button><button class="btn primario" id="t-ok">Aggiungi</button></div>`);
    $('#t-ok', f.el).onclick = async () => {
      try {
        await api('/api/timbrature', { utente_id: k.utente.id, verso: $('#t-v', f.el).value, quando: $('#t-q', f.el).value, nota: $('#t-n', f.el).value });
        f.chiudi(); toast('Timbratura aggiunta.'); naviga();
      } catch (err) { toast(err.message, true); }
    };
  });
}

async function vistaDocumenti(c, m, q) {
  const scheda = IO.staff ? (q.vista || 'miei') : 'miei';
  const docs = await api('/api/documenti' + (scheda === 'inviati' ? '?tutti=1' : ''));
  c.innerHTML = `
    <div class="riga" style="margin-bottom:16px"><h1 style="margin:0">Documenti</h1><span class="spazio"></span>
      ${IO.staff ? `<button class="btn primario" id="carica-doc">${ico('piu')} Carica documento</button>` : ''}</div>
    ${IO.staff ? `<div class="schede"><button class="${scheda === 'miei' ? 'attiva' : ''}" data-v="miei">I miei documenti</button><button class="${scheda === 'inviati' ? 'attiva' : ''}" data-v="inviati">Inviati al personale</button></div>` : ''}
    <p class="muted">${scheda === 'miei' ? 'Cedolini, Certificazione Unica, contratti e altri documenti che la segreteria ti ha inviato.' : 'Ultimi 300 documenti inviati. «Aperto» indica che il dipendente l\'ha scaricato.'}</p>
    <div class="lista">${docs.length ? docs.map(d => `<div class="elem"><span class="ico">${ico('documenti')}</span>
      <span class="testo"><b>${esc(d.titolo)}</b><span>${scheda === 'inviati' ? esc(d.cognome + ' ' + d.nome) + ' · ' : ''}${esc(d.tipo)} · ${fd(d.creato, false)}</span></span>
      <span class="destra">${scheda === 'inviati' ? (d.letto ? '<span class="chip letta">Aperto</span>' : '<span class="chip">Non aperto</span>') : (d.letto ? '' : '<span class="chip nonletta">Nuovo</span>')}
      <span class="riga">${d.allegati.map(a => `<a class="btn mini" href="/api/allegati/${a.id}" target="_blank" rel="noopener">${ico('scarica')} Apri</a>`).join('')}</span></span></div>`).join('') : '<div class="card vuoto">Nessun documento.</div>'}</div>`;
  $$('[data-v]', c).forEach(b => b.onclick = () => { location.hash = '#/documenti?vista=' + b.dataset.v; });
  $('#carica-doc')?.addEventListener('click', async () => {
    const utenti = (await api('/api/utenti')).filter(u => u.attivo);
    const f = finestra(`<h2>Carica documento</h2>
      <div class="campi2"><label class="campo"><span>Tipo</span><select id="d-tipo">${['Cedolino', 'Certificazione Unica', 'Contratto', 'Decreto', 'Altro'].map(x => `<option>${x}</option>`).join('')}</select></label>
      <label class="campo"><span>Periodo</span><input type="month" id="d-per"></label></div>
      <label class="campo"><span>Titolo *</span><input type="text" id="d-tit" placeholder="Es. Cedolino ottobre 2026"></label>
      <label class="campo"><span>Destinatari *</span><input type="search" id="d-cerca" placeholder="Cerca…"></label>
      <div style="max-height:200px;overflow:auto;border:1px solid var(--line);border-radius:10px;padding:8px 10px;margin:-6px 0 14px">
        <label class="spunta"><input type="checkbox" id="d-tutti"><b>Seleziona tutti</b></label>
        ${utenti.map(u => `<label class="spunta" data-n="${esc((u.cognome + ' ' + u.nome).toLowerCase())}"><input type="checkbox" value="${u.id}" class="d-ut"><span>${esc(u.cognome + ' ' + u.nome)} <small class="muted">${esc(u.ruolo_nome)}</small></span></label>`).join('')}</div>
      ${htmlFile('d-file', 'File *', 'Con più destinatari si invia un solo file uguale per tutti.')}
      <div class="piede"><button class="btn" data-chiudi>Annulla</button><button class="btn primario" id="d-ok">Invia</button></div>`);
    const prendi = collegaFile('d-file');
    $('#d-tutti', f.el).onchange = e => $$('.d-ut', f.el).forEach(x => { if (!x.closest('label').hidden) x.checked = e.target.checked; });
    $('#d-cerca', f.el).oninput = e => $$('[data-n]', f.el).forEach(l => { l.hidden = !l.dataset.n.includes(e.target.value.toLowerCase()); });
    $('#d-ok', f.el).onclick = async () => {
      try {
        const r = await api('/api/documenti', { tipo: $('#d-tipo', f.el).value, periodo: $('#d-per', f.el).value, titolo: $('#d-tit', f.el).value,
          utenti: $$('.d-ut:checked', f.el).map(x => +x.value), allegati: await prendi() });
        f.chiudi(); toast(`Documento inviato a ${r.inviati} ${r.inviati === 1 ? 'persona' : 'persone'}.`);
        location.hash = '#/documenti?vista=inviati';
      } catch (err) { toast(err.message, true); }
    };
  });
}

// ------------------------------------------------------------------ gestione
async function vistaGestione(c, m) {
  if (!IO.staff) throw new Error('Funzione riservata alla segreteria e alla dirigenza.');
  const scheda = m[1] || 'da-lavorare';
  const schede = [['da-lavorare', 'Da lavorare'], ['richieste', 'Tutte le richieste'], ['assenze', 'Calendario assenze'], ['personale', 'Personale']];
  if (['dsga', 'dirigente'].includes(IO.utente.ruolo)) schede.push(['impostazioni', 'Impostazioni']);
  c.innerHTML = `<div class="schede">${schede.map(([k, n]) => `<button class="${k === scheda ? 'attiva' : ''}" data-s="${k}">${n}${k === 'da-lavorare' ? bollo(BADGE.gestione) : ''}</button>`).join('')}</div><div id="g-corpo"></div>`;
  $$('[data-s]', c).forEach(b => b.onclick = () => { location.hash = '#/gestione/' + b.dataset.s; });
  const g = $('#g-corpo');
  await ({ 'da-lavorare': gDaLavorare, richieste: gRichieste, assenze: gAssenze, personale: gPersonale, impostazioni: gImpostazioni }[scheda] || gDaLavorare)(g);
}

async function gDaLavorare(g) {
  const el = await api('/api/gestione/da-lavorare');
  BADGE.gestione = el.length; disegnaBadge();
  const rapide = ['verifica', 'autorizza', 'registra', 'evadi'];
  const spiega = IO.utente.ruolo === 'segreteria' ? 'Richieste nuove da verificare (spettanza, documentazione) o da registrare.' :
    'Richieste già verificate dalla segreteria, in attesa della tua autorizzazione.';
  g.innerHTML = `<p class="muted">${spiega}</p><div class="lista">${el.length ? el.map(r => `<div class="elem" style="flex-wrap:wrap">
      <a href="#/richiesta/${r.id}" class="testo" style="text-decoration:none;color:inherit;min-width:220px"><b>${esc(r.richiedente)} · ${esc(r.tipo_nome)}</b>
        <span>${esc(periodo(r))}${quantita(r) ? ' · ' + quantita(r) : ''} · ${esc(r.richiedente_ruolo)}${r.n_allegati ? ' · 📎' + r.n_allegati : ''}</span></a>
      ${chip(r.stato, r.stato_nome)}
      <span class="riga">${r.azioni.filter(a => rapide.includes(a.id)).map(a => `<button class="btn mini ${a.id === 'verifica' ? 'primario' : 'ok'}" data-id="${r.id}" data-az="${a.id}">${esc(a.nome.replace(' (spettanza ok)', ''))}</button>`).join('')}
        <a class="btn mini" href="#/richiesta/${r.id}">Apri</a></span></div>`).join('') : '<div class="card vuoto">Niente da lavorare. 🎉</div>'}</div>`;
  $$('[data-az]', g).forEach(b => b.onclick = async () => {
    b.disabled = true;
    try { await api(`/api/richieste/${b.dataset.id}/azione`, { azione: b.dataset.az, nota: '' }); toast('Fatto.'); aggiornaBadge(); naviga(); } catch (err) { toast(err.message, true); b.disabled = false; }
  });
}

async function gRichieste(g) {
  const utenti = await api('/api/utenti');
  const [, qs] = location.hash.split('?');
  const q = Object.fromEntries(new URLSearchParams(qs || ''));
  g.innerHTML = `<form class="filtri" id="g-filtri">
      <select name="stato" style="width:auto"><option value="">Tutti gli stati</option>${Object.entries(IO.stati).map(([k, n]) => `<option value="${k}" ${q.stato === k ? 'selected' : ''}>${n}</option>`).join('')}</select>
      <select name="tipo" style="width:auto"><option value="">Tutti i tipi</option>${Object.entries(IO.tutte_tipologie).map(([k, n]) => `<option value="${k}" ${q.tipo === k ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select>
      <select name="utente" style="width:auto"><option value="">Tutto il personale</option>${utenti.map(u => `<option value="${u.id}" ${q.utente == u.id ? 'selected' : ''}>${esc(u.cognome + ' ' + u.nome)}</option>`).join('')}</select>
      <input type="date" name="dal" value="${esc(q.dal || '')}" style="width:auto" title="Dal"><input type="date" name="al" value="${esc(q.al || '')}" style="width:auto" title="Al">
      <a class="btn mini" id="g-csv">${ico('scarica')} CSV</a></form><div id="g-el"></div>`;
  const f = $('#g-filtri');
  const carica = async () => {
    const p = new URLSearchParams([...new FormData(f)].filter(([, v]) => v)).toString();
    history.replaceState(null, '', '#/gestione/richieste' + (p ? '?' + p : ''));
    $('#g-csv').href = '/api/gestione/richieste.csv?' + p;
    const el = await api('/api/gestione/richieste?' + p);
    $('#g-el').innerHTML = `<p class="muted piccolo">${el.length} richieste</p><div class="tabella-wrap"><table><thead><tr><th>N.</th><th>Dipendente</th><th>Tipo</th><th>Periodo</th><th class="num">Q.tà</th><th>Stato</th></tr></thead><tbody>
      ${el.map(r => `<tr class="cliccabile" data-id="${r.id}"><td>${r.id}</td><td>${esc(r.richiedente)}</td><td>${esc(r.tipo_nome)}</td><td>${esc(periodo(r))}</td><td class="num">${quantita(r)}</td><td>${chip(r.stato, r.stato_nome)}</td></tr>`).join('') || '<tr><td colspan="6" class="vuoto">Nessuna richiesta</td></tr>'}</tbody></table></div>`;
    $$('tr[data-id]', g).forEach(tr => tr.onclick = () => { location.hash = '#/richiesta/' + tr.dataset.id; });
  };
  f.onchange = carica;
  f.onsubmit = e => e.preventDefault();
  await carica();
}

async function gAssenze(g) {
  let mese = oggiIso().slice(0, 7), giorno = oggiIso();
  const disegna = async () => {
    const [cal, ass] = await Promise.all([api('/api/gestione/calendario?mese=' + mese), api('/api/gestione/assenti?data=' + giorno)]);
    const [y, mm] = mese.split('-').map(Number);
    const primo = (new Date(y, mm - 1, 1).getDay() + 6) % 7;
    const giorni = Object.entries(cal.giorni);
    g.innerHTML = `<div class="due" style="align-items:start">
      <div class="card"><div class="riga" style="margin-bottom:12px"><button class="btn mini" data-m="-1">‹</button><b class="spazio" style="text-align:center;text-transform:capitalize">${MESI[mm - 1]} ${y}</b><button class="btn mini" data-m="1">›</button></div>
        <div class="cal">${['lun', 'mar', 'mer', 'gio', 'ven', 'sab', 'dom'].map(x => `<div class="tes">${x}</div>`).join('')}
        ${'<button class="vuota" tabindex="-1"></button>'.repeat(primo)}
        ${giorni.map(([d, n]) => `<button data-g="${d}" class="${d === giorno ? 'sel' : ''} ${dIso(d).getDay() === 0 ? 'festa' : ''}"><b>${+d.slice(8)}</b>${n ? `<small>${n}</small>` : ''}</button>`).join('')}</div>
        <p class="muted piccolo" style="margin-bottom:0">Il numero indica quante persone sono assenti (anche con richieste in attesa).</p></div>
      <div class="card"><h2>Assenti ${giorno === oggiIso() ? 'oggi' : fd(giorno)}</h2>
        <div class="lista">${ass.assenti.length ? ass.assenti.map(a => `<a class="elem" href="#/richiesta/${a.id}"><span class="testo"><b>${esc(a.nome)}</b><span>${esc(a.tipo)}${a.orario ? ' · ' + esc(a.orario) : ''} · ${esc(a.ruolo)}${a.plesso ? ' · ' + esc(a.plesso) : ''}</span></span>${chip(a.stato, a.stato_nome)}</a>`).join('') : '<div class="vuoto">Nessun assente</div>'}</div></div></div>`;
    $$('[data-g]', g).forEach(b => b.onclick = () => { giorno = b.dataset.g; disegna(); });
    $$('[data-m]', g).forEach(b => b.onclick = () => { const d = new Date(y, mm - 1 + +b.dataset.m, 1); mese = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`; giorno = mese + '-01'; disegna(); });
  };
  await disegna();
}

async function gPersonale(g) {
  const utenti = await api('/api/utenti');
  g.innerHTML = `<div class="filtri"><input type="search" id="p-cerca" placeholder="Cerca…" style="max-width:300px"><span class="spazio"></span><button class="btn primario" id="p-nuovo">${ico('piu')} Nuovo dipendente</button></div>
    <div class="tabella-wrap"><table><thead><tr><th>Nome</th><th>Ruolo</th><th class="nascondi-mobile">Plesso</th><th class="nascondi-mobile">Utente</th><th class="num">Ferie residue</th></tr></thead><tbody>
    ${utenti.map(u => `<tr class="cliccabile" data-id="${u.id}" data-n="${esc((u.cognome + ' ' + u.nome + ' ' + u.username).toLowerCase())}" style="${u.attivo ? '' : 'opacity:.5'}"><td><b>${esc(u.cognome)} ${esc(u.nome)}</b><br><small class="muted">${esc(u.profilo)}</small></td><td>${esc(u.ruolo_nome)}${u.attivo ? '' : ' (disattivato)'}</td><td class="nascondi-mobile">${esc(u.plesso)}</td><td class="nascondi-mobile">${esc(u.username)}</td><td class="num">${num(u.ferie_residue)}</td></tr>`).join('')}
    </tbody></table></div>`;
  $('#p-cerca').oninput = e => $$('tr[data-n]', g).forEach(tr => { tr.hidden = !tr.dataset.n.includes(e.target.value.toLowerCase()); });
  $$('tr[data-id]', g).forEach(tr => tr.onclick = () => schedaDipendente(utenti.find(u => u.id === +tr.dataset.id)));
  $('#p-nuovo').onclick = () => schedaDipendente(null);
}

function mostraPassword(pw, chi) {
  finestra(`<h2>Password provvisoria</h2><p>Comunica questa password a <b>${esc(chi)}</b>: al primo accesso gli verrà chiesto di cambiarla. Non verrà più mostrata.</p>
    <div class="password-mostra">${esc(pw)}</div><div class="piede"><button class="btn primario" data-chiudi>Ho annotato la password</button></div>`);
}

function schedaDipendente(u) {
  const nuovo = !u;
  u = u || { nome: '', cognome: '', username: '', ruolo: 'docente', profilo: '', plesso: '', email: '', ferie_spettanti: 32, ferie_ap: 0, ore_giornaliere: 0, attivo: 1 };
  const f = finestra(`<h2>${nuovo ? 'Nuovo dipendente' : esc(u.cognome + ' ' + u.nome)}</h2>
    <form id="f-ut"><div class="campi2">
      <label class="campo"><span>Nome *</span><input type="text" name="nome" value="${esc(u.nome)}"></label>
      <label class="campo"><span>Cognome *</span><input type="text" name="cognome" value="${esc(u.cognome)}"></label>
      <label class="campo"><span>Nome utente *</span><input type="text" name="username" value="${esc(u.username)}" placeholder="es. m.rossi"></label>
      <label class="campo"><span>Ruolo</span><select name="ruolo">${Object.entries(IO.ruoli).map(([k, n]) => `<option value="${k}" ${u.ruolo === k ? 'selected' : ''}>${n}</option>`).join('')}</select></label>
      <label class="campo"><span>Profilo</span><input type="text" name="profilo" value="${esc(u.profilo)}" placeholder="es. Docente di lettere"></label>
      <label class="campo"><span>Plesso</span><input type="text" name="plesso" value="${esc(u.plesso)}"></label>
      <label class="campo"><span>Email</span><input type="email" name="email" value="${esc(u.email)}"></label>
      <label class="campo"><span>Ore giornaliere (cartellino)</span><input type="number" name="ore_giornaliere" step="0.1" min="0" max="12" value="${u.ore_giornaliere}"></label>
      <label class="campo"><span>Ferie spettanti</span><input type="number" name="ferie_spettanti" min="0" max="40" value="${u.ferie_spettanti}"><small>32, oppure 30 nei primi 3 anni</small></label>
      <label class="campo"><span>Ferie residue anno precedente</span><input type="number" name="ferie_ap" min="0" max="40" value="${u.ferie_ap}"></label>
      <label class="campo"><span>Utente Argo</span><input type="text" name="argo_utente" value="${esc(u.argo_utente || '')}" autocapitalize="none" spellcheck="false" placeholder="nome utente del portale Argo"><small>Per entrare con le credenziali Argo</small></label>
    </div>
    ${nuovo ? `<label class="spunta"><input type="checkbox" name="solo_argo"><span>Entra solo con Argo (nessuna password di SmartDesk)</span></label>` : (u.solo_argo ? '<p class="muted piccolo">Entra solo con Argo. «Reimposta password» gli dà anche una password di SmartDesk.</p>' : '')}
    ${nuovo ? '' : `<label class="spunta"><input type="checkbox" name="attivo" ${u.attivo ? 'checked' : ''}><span>Account attivo</span></label>`}
    </form>
    ${nuovo ? '' : `<div class="riga" style="margin-top:6px"><a class="btn mini" href="#/situazione?utente=${u.id}">Situazione</a><a class="btn mini" href="#/presenze?utente=${u.id}">Cartellino</a><a class="btn mini" href="#/gestione/richieste?utente=${u.id}">Richieste</a><button class="btn mini pericolo" id="u-pw">Reimposta password</button></div>`}
    <div class="piede"><button class="btn" data-chiudi>Annulla</button><button class="btn primario" id="u-ok">${nuovo ? 'Crea' : 'Salva'}</button></div>`);
  $$('a', f.el).forEach(a => a.addEventListener('click', f.chiudi));
  const form = $('#f-ut', f.el);
  const valori = () => {
    const o = Object.fromEntries(new FormData(form));
    if (!nuovo) o.attivo = form.attivo.checked;
    else o.solo_argo = form.solo_argo.checked;
    return o;
  };
  $('#u-ok', f.el).onclick = async () => {
    try {
      const r = await api(nuovo ? '/api/utenti' : '/api/utenti/' + u.id, valori());
      f.chiudi();
      toast(nuovo ? 'Dipendente creato.' : 'Salvato.');
      if (r.password) mostraPassword(r.password, `${form.nome.value} ${form.cognome.value}`);
      naviga();
    } catch (err) { toast(err.message, true); }
  };
  $('#u-pw', f.el)?.addEventListener('click', async () => {
    f.chiudi();
    const ok = await chiedi({ titolo: 'Reimpostare la password?', testo: `${u.nome} ${u.cognome} dovrà entrare con una password provvisoria nuova.`, bottone: 'Reimposta', pericolo: true });
    if (!ok) return;
    try { const r = await api('/api/utenti/' + u.id, { reimposta_password: true }); mostraPassword(r.password, `${u.nome} ${u.cognome}`); } catch (err) { toast(err.message, true); }
  });
}

async function gImpostazioni(g) {
  const imp = (await api('/api/io')).impostazioni;
  g.innerHTML = `<form class="card" id="f-imp" style="max-width:620px">
    <label class="campo"><span>Nome della scuola</span><input type="text" name="scuola" value="${esc(imp.scuola)}"></label>
    <label class="spunta"><input type="checkbox" name="settimana_corta" ${imp.settimana_corta === '1' ? 'checked' : ''}><span>Settimana corta: il sabato non è lavorativo (nel conteggio dei giorni)</span></label>
    <label class="campo"><span>Festa del patrono (MM-GG)</span><input type="text" name="patrono" value="${esc(imp.patrono)}" placeholder="es. 06-24" style="max-width:160px"><small>Domeniche e festività nazionali sono già escluse.</small></label>
    <label class="spunta"><input type="checkbox" name="timbrature_docenti" ${imp.timbrature_docenti === '1' ? 'checked' : ''}><span>Timbrature dall'app anche per i docenti</span></label>
    <h2 class="sezione">Accesso con Argo</h2>
    <label class="spunta"><input type="checkbox" name="argo_attivo" ${imp.argo_attivo === '1' ? 'checked' : ''}><span>Il personale può entrare con nome utente e password del portale Argo (verificati con Argo, mai salvati)</span></label>
    <label class="campo"><span>Codice della scuola su Argo</span><input type="text" name="argo_codice_scuola" value="${esc(imp.argo_codice_scuola)}" placeholder="es. SC12345" style="max-width:200px"></label>
    <label class="spunta"><input type="checkbox" name="argo_nuovi" ${imp.argo_nuovi === '1' ? 'checked' : ''}><span>Crea l'account al primo accesso con Argo se la persona non è ancora nell'elenco (serve il codice scuola)</span></label>
    <label class="campo"><span>Ruolo degli account creati così</span><select name="argo_ruolo_nuovi" style="max-width:220px"><option value="docente" ${imp.argo_ruolo_nuovi === 'docente' ? 'selected' : ''}>Docente</option><option value="ata" ${imp.argo_ruolo_nuovi === 'ata' ? 'selected' : ''}>Personale ATA</option></select>
      <small>La segreteria riceve una notifica e può correggere il ruolo in Personale. Chi è già nell'elenco viene riconosciuto dal campo «Utente Argo» o da nome e cognome.</small></label>
    <button class="btn primario">Salva</button></form>`;
  const f = $('#f-imp');
  f.onsubmit = async e => {
    e.preventDefault();
    try {
      await api('/api/impostazioni', { scuola: f.scuola.value, patrono: f.patrono.value, settimana_corta: f.settimana_corta.checked ? '1' : '0', timbrature_docenti: f.timbrature_docenti.checked ? '1' : '0',
        argo_attivo: f.argo_attivo.checked ? '1' : '0', argo_codice_scuola: f.argo_codice_scuola.value, argo_nuovi: f.argo_nuovi.checked ? '1' : '0', argo_ruolo_nuovi: f.argo_ruolo_nuovi.value });
      IO = await api('/api/io');
      toast('Impostazioni salvate.');
      disegnaShell(); naviga();
    } catch (err) { toast(err.message, true); }
  };
}

// ------------------------------------------------------------------ profilo
async function vistaProfilo(c) {
  const u = IO.utente;
  const tema = (() => { try { return localStorage.getItem('sp-tema') === 'light' ? 'light' : 'dark'; } catch { return 'dark'; } })();
  c.innerHTML = `<div class="due" style="align-items:start">
    <div class="card"><div class="riga" style="margin-bottom:14px"><span class="avatar" style="width:54px;height:54px;font-size:1.1rem">${esc(iniziali(u))}</span><div><h1 style="margin:0">${esc(u.nome)} ${esc(u.cognome)}</h1><div class="muted">${esc(u.ruolo_nome)}</div></div></div>
      <dl class="dati"><dt>Nome utente</dt><dd>${esc(u.username)}</dd><dt>Profilo</dt><dd>${esc(u.profilo || '—')}</dd><dt>Plesso</dt><dd>${esc(u.plesso || '—')}</dd><dt>Email</dt><dd>${esc(u.email || '—')}</dd></dl>
      <div class="sezione"><h3>Aspetto</h3><div class="filtri">${[['dark', 'Scuro viola'], ['light', 'Chiaro lavanda']].map(([k, n]) => `<button class="pillola ${tema === k ? 'attiva' : ''}" data-tema="${k}">${n}</button>`).join('')}</div></div>
      <button class="btn pericolo" id="p-esci">${ico('esci')} Esci</button></div>
    ${u.solo_argo ? `<div class="card"><h2>Accesso</h2><p>Entri con le credenziali del portale Argo (utente <b>${esc(u.argo_utente)}</b>). La password si cambia sul portale Argo.</p></div>` : `
    <form class="card" id="f-pw"><h2>Cambia password</h2>
      ${u.cambia_password ? '<div class="avviso">Stai usando una password provvisoria: sceglierne una tua.</div>' : ''}
      <label class="campo"><span>Password attuale</span><input type="password" name="attuale" autocomplete="current-password"></label>
      <label class="campo"><span>Nuova password</span><input type="password" name="nuova" autocomplete="new-password" minlength="8"><small>Almeno 8 caratteri.</small></label>
      <label class="campo"><span>Ripeti la nuova password</span><input type="password" name="ripeti" autocomplete="new-password"></label>
      <button class="btn primario">Cambia password</button></form>`}</div>`;
  $('#p-esci').onclick = esci;
  $$('[data-tema]', c).forEach(b => b.onclick = () => { applicaTema(b.dataset.tema); naviga(); });
  const f = $('#f-pw');
  if (f) f.onsubmit = async e => {
    e.preventDefault();
    if (f.nuova.value !== f.ripeti.value) { toast('Le due password non coincidono.', true); return; }
    try {
      await api('/api/password', { attuale: f.attuale.value, nuova: f.nuova.value });
      toast('Password cambiata.');
      IO.utente.cambia_password = 0;
      f.reset(); naviga();
    } catch (err) { toast(err.message, true); }
  };
}

function temaAttuale() { return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark'; }
function applicaTema(t) {
  try { localStorage.setItem('sp-tema', t); } catch { /* niente */ }
  if (t === 'light') document.documentElement.setAttribute('data-theme', 'light');
  else document.documentElement.removeAttribute('data-theme');
  const mc = document.querySelector('meta[name=theme-color]');
  if (mc) mc.content = t === 'light' ? '#f4f1ff' : '#0b0719';
  $$('.cambia-tema').forEach(b => { b.innerHTML = ico(t === 'light' ? 'luna' : 'sole'); b.title = t === 'light' ? 'Passa al tema scuro' : 'Passa al tema chiaro'; });
}
// interruttore chiaro/scuro (barra in alto e pagina di accesso)
function bottoneTema(cls = '') {
  const t = temaAttuale();
  return `<button type="button" class="tondo cambia-tema ${cls}" title="${t === 'light' ? 'Passa al tema scuro' : 'Passa al tema chiaro'}" aria-label="Cambia tema chiaro o scuro">${ico(t === 'light' ? 'luna' : 'sole')}</button>`;
}
function collegaTema() {
  $$('.cambia-tema').forEach(b => b.onclick = () => {
    document.documentElement.classList.add('tema-in-cambio');
    applicaTema(temaAttuale() === 'light' ? 'dark' : 'light');
    setTimeout(() => document.documentElement.classList.remove('tema-in-cambio'), 450);
  });
}
try { if (localStorage.getItem('sp-tema') === 'light') applicaTema('light'); } catch { /* niente */ }

avvia();
