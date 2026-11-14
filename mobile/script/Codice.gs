/**
 * SmartDesk mobile – intermediario con Argo (Google Apps Script, web app "esegui come me", accesso "chiunque").
 * by Wolf Team – I.C. Almese.
 *
 * Il telefono non può chiamare Argo direttamente (i server Argo non lo consentono da altri siti):
 * questo script fa le stesse chiamate che fanno Unica e DidUP, a nome del dipendente che entra.
 * - La password serve solo per entrare: non viene mai salvata né scritta nei log.
 * - La sessione (gettoni Argo) resta per qualche ora nella cache dello script, legata a un codice casuale.
 * - Si accettano solo nomi utente della scuola (….SC15290). Dopo 3 errori si aspetta: Argo blocca chi sbaglia troppo.
 * Le API sono ricavate dal codice pubblico di Argo Personale (1.50.2) e DidUP (4.54.2).
 */

var CODICE_SCUOLA = 'SC15290';
var AUTH = 'https://auth.portaleargo.it';
var PORTALE = 'https://www.portaleargo.it';
var DIDUP_CLIENT = '963ed11e-33b2-41b4-8911-f4f1907bd208';
var DIDUP_RITORNO = PORTALE + '/voti/oidc-callback.html?classic';
var PERSONALE_CLIENT = 'ad175860-1847-4b12-8f0f-54041ebca714';
var PERSONALE_RITORNO = PORTALE + '/argopersonale/oidc-callback.html';
var PERSONALE_API = 'https://personale.portaleargo.it/personale/rest/';
var PERSONALE_VERSIONE = '1.50.2';
var DIDUP_API = 'https://didattica.portaleargo.it/wsxrest/api/rest/';
var DIDUP_VERSIONE = '4.54.2', DIDUP_SMART = '2.5.1', DIDUP_BUILD = '(build:20251209)';
var AGENTE = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36';
var DURATA_SESSIONE = 6 * 3600; // massimo consentito dalla cache di Apps Script

function ErroreArgo(msg, codice) { this.message = msg; this.codice = codice || 400; }

// ------------------------------------------------------------------ porta d'ingresso
function doGet() {
  return risposta({ ok: true, servizio: 'SmartDesk mobile', versione: 1 });
}

function doPost(e) {
  var r;
  try {
    var c = JSON.parse((e && e.postData && e.postData.contents) || '{}');
    var f = AZIONI[c.azione];
    if (!f) throw new ErroreArgo('Azione non prevista.');
    r = f(c);
    r.ok = true;
  } catch (err) {
    r = { ok: false, errore: err instanceof ErroreArgo ? err.message : 'Errore imprevisto: ' + (err && err.message || err),
          codice: err instanceof ErroreArgo ? err.codice : 500 };
  }
  return risposta(r);
}

function risposta(o) {
  return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
}

var AZIONI = {
  accedi: azioneAccedi,
  dati: function (c) { var s = sessione(c); return { dati: leggiPersonale(s) }; },
  annulla: azioneAnnulla,
  bacheca: function (c) { var s = sessione(c); return bachecaNormalizzata(s); },
  conferma: azioneConferma,
  allegati: azioneAllegati,
  esci: function (c) { if (c.sessione) CacheService.getScriptCache().remove('s:' + c.sessione); return {}; }
};

// ------------------------------------------------------------------ sessioni
function salvaSessione(id, s) {
  CacheService.getScriptCache().put('s:' + id, JSON.stringify(s), DURATA_SESSIONE);
}

function sessione(c) {
  var grezzo = c.sessione && CacheService.getScriptCache().get('s:' + c.sessione);
  if (!grezzo) throw new ErroreArgo('Sessione scaduta: entra di nuovo con le credenziali Argo.', 401);
  var s = JSON.parse(grezzo);
  s.id = c.sessione;
  return s;
}

// ------------------------------------------------------------------ HTTP con biscotti (come un browser)
function Navigatore() { this.biscotti = {}; }

Navigatore.prototype.intestazioneBiscotti = function (url) {
  var host = url.replace(/^https?:\/\//, '').split(/[\/?#]/)[0].toLowerCase();
  var parti = [];
  for (var k in this.biscotti) {
    var b = this.biscotti[k];
    var ok = b.dominio ? (host === b.dominio || host.slice(-(b.dominio.length + 1)) === '.' + b.dominio) : host === b.host;
    if (ok) parti.push(b.nome + '=' + b.valore);
  }
  return parti.join('; ');
};

Navigatore.prototype.ricorda = function (url, intestazioni) {
  var host = url.replace(/^https?:\/\//, '').split(/[\/?#]/)[0].toLowerCase();
  var sc = intestazioni['Set-Cookie'] || intestazioni['set-cookie'];
  if (!sc) return;
  if (!Array.isArray(sc)) sc = [sc];
  for (var i = 0; i < sc.length; i++) {
    var pezzi = String(sc[i]).split(';');
    var nv = pezzi[0], j = nv.indexOf('=');
    if (j < 1) continue;
    var b = { nome: nv.slice(0, j).trim(), valore: nv.slice(j + 1).trim(), host: host, dominio: '' };
    var scaduto = false;
    for (var p = 1; p < pezzi.length; p++) {
      var a = pezzi[p].trim().toLowerCase();
      if (a.indexOf('domain=') === 0) b.dominio = a.slice(7).replace(/^\./, '');
      if (a.indexOf('max-age=') === 0 && parseInt(a.slice(8), 10) <= 0) scaduto = true;
    }
    var chiave = b.nome + '@' + (b.dominio || b.host);
    if (scaduto || b.valore === '') delete this.biscotti[chiave]; else this.biscotti[chiave] = b;
  }
};

Navigatore.prototype.apri = function (url, modulo) {
  var opz = { method: modulo ? 'post' : 'get', followRedirects: false, muteHttpExceptions: true,
              headers: { 'User-Agent': AGENTE, 'Accept-Language': 'it-IT,it' } };
  var b = this.intestazioneBiscotti(url);
  if (b) opz.headers.Cookie = b;
  if (modulo) {
    opz.contentType = 'application/x-www-form-urlencoded';
    opz.payload = Object.keys(modulo).map(function (k) { return encodeURIComponent(k) + '=' + encodeURIComponent(modulo[k]); }).join('&');
  }
  var r;
  try { r = UrlFetchApp.fetch(url, opz); } catch (err) { throw new ErroreArgo('Argo non è raggiungibile in questo momento.', 502); }
  var h = r.getAllHeaders();
  this.ricorda(url, h);
  var stato = r.getResponseCode();
  if (stato >= 400) throw new ErroreArgo('Argo ha risposto con un errore (' + stato + '). Riprova tra poco.', 502);
  return { stato: stato, posizione: h.Location || h.location || '', testo: stato >= 300 ? '' : r.getContentText() };
};

function unisciUrl(base, rel) {
  if (/^https?:\/\//.test(rel)) return rel;
  var origine = base.match(/^https?:\/\/[^\/]+/)[0];
  if (rel.charAt(0) === '/') return origine + rel;
  return base.replace(/[?#].*$/, '').replace(/[^\/]*$/, '') + rel;
}

function parametri(url) {
  var q = {}, i = url.indexOf('?');
  if (i < 0) return q;
  url.slice(i + 1).split('#')[0].split('&').forEach(function (p) {
    var kv = p.split('=');
    if (kv[0]) q[decodeURIComponent(kv[0])] = decodeURIComponent((kv[1] || '').replace(/\+/g, ' '));
  });
  return q;
}

/** Segue i reindirizzamenti: {tipo:'codice', valore} al ritorno OIDC, altrimenti {tipo:'pagina', valore: html}. */
function segui(nav, url, modulo, ritorno) {
  var base = ritorno.split('?')[0];
  for (var n = 0; n < 15; n++) {
    var r = nav.apri(url, modulo);
    if (r.stato < 300 || r.stato >= 400) return { tipo: 'pagina', valore: r.testo };
    url = unisciUrl(url, r.posizione);
    modulo = null;
    if (url.indexOf(base) === 0) {
      var q = parametri(url);
      if (q.code) return { tipo: 'codice', valore: q.code };
      if (q.error) throw new ErroreArgo("Argo ha rifiutato l'accesso: " + q.error.slice(0, 60));
    }
  }
  throw new ErroreArgo("Troppi reindirizzamenti durante l'accesso ad Argo.");
}

function campiModulo(html, id) {
  var m = html.match(new RegExp('<form\\b[^>]*id="' + id + '"[\\s\\S]*?</form>'));
  if (!m) throw new ErroreArgo("La pagina di accesso di Argo è cambiata: avvisa il Wolf Team.");
  var campi = {}, re = /<input\b[^>]*>/g, x;
  while ((x = re.exec(m[0]))) {
    var nome = x[0].match(/name="([^"]*)"/), val = x[0].match(/value="([^"]*)"/);
    if (nome) campi[nome[1]] = val ? val[1].replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>') : '';
  }
  return campi;
}

function motivoPagina(html) {
  if (html.indexOf('id="otpForm"') >= 0) return 'Il tuo account Argo chiede il secondo codice (OTP): SmartDesk non lo gestisce ancora.';
  if (html.indexOf('id="selectForm"') >= 0) return 'Argo chiede di scegliere tra più profili: SmartDesk non lo gestisce ancora.';
  if (html.indexOf('id="consentForm"') >= 0) return 'Argo chiede di accettare un consenso: entra una volta su portaleargo.it e accettalo.';
  if (html.indexOf('id="loginForm"') >= 0) return 'Nome utente o password di Argo non corretti.';
  return 'Argo ha risposto in modo inatteso.';
}

function pkce() {
  var v = Utilities.base64EncodeWebSafe(Utilities.getUuid() + Utilities.getUuid()).replace(/=+$/, '');
  var sfida = Utilities.base64EncodeWebSafe(Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, v, Utilities.Charset.US_ASCII)).replace(/=+$/, '');
  return { verificatore: v, sfida: sfida };
}

function urlAuth(client, ritorno, scope, sfida) {
  var q = { client_id: client, redirect_uri: ritorno, response_type: 'code', scope: scope,
            state: Utilities.getUuid(), code_challenge: sfida, code_challenge_method: 'S256' };
  return AUTH + '/oauth2/auth?' + Object.keys(q).map(function (k) { return k + '=' + encodeURIComponent(q[k]); }).join('&');
}

function gettone(nav, client, ritorno, codice, verificatore) {
  var r = nav.apri(AUTH + '/oauth2/token', { grant_type: 'authorization_code', client_id: client, redirect_uri: ritorno,
                                            code: codice, code_verifier: verificatore });
  var t;
  try { t = JSON.parse(r.testo); } catch (err) { t = {}; }
  if (!t.access_token) throw new ErroreArgo('Argo non ha rilasciato il gettone di accesso.');
  return t;
}

function jwt(t) {
  try {
    var p = t.split('.')[1];
    return JSON.parse(Utilities.newBlob(Utilities.base64DecodeWebSafe(p + '===='.slice(p.length % 4 || 4))).getDataAsString());
  } catch (err) { return {}; }
}

// ------------------------------------------------------------------ accesso
function azioneAccedi(c) {
  var utente = String(c.utente || '').trim(), password = String(c.password || '');
  if (!utente || !password) throw new ErroreArgo('Scrivi nome utente e password di Argo.');
  if (!new RegExp('\\.' + CODICE_SCUOLA + '$', 'i').test(utente))
    throw new ErroreArgo('SmartDesk è per il personale della scuola: il nome utente Argo finisce con .' + CODICE_SCUOLA + '.');
  var cache = CacheService.getScriptCache(), chiaveErrori = 'err:' + utente.toLowerCase();
  var errori = parseInt(cache.get(chiaveErrori) || '0', 10);
  if (errori >= 3) throw new ErroreArgo('Troppi tentativi sbagliati: aspetta 15 minuti (Argo blocca l\'account dopo troppi errori).', 429);

  var nav = new Navigatore(), p = pkce();
  var pagina = segui(nav, urlAuth(DIDUP_CLIENT, DIDUP_RITORNO, 'openid profile user.roles argo', p.sfida), null, DIDUP_RITORNO);
  if (pagina.tipo !== 'pagina') throw new ErroreArgo('Argo ha risposto in modo inatteso.');
  var campi = campiModulo(pagina.valore, 'loginForm');
  campi.username = utente; campi.password = password; campi.login = 'true';
  if ('remember_me' in campi) campi.remember_me = 'true'; // serve al programma Personale per riconoscere l'accesso
  var esito = segui(nav, PORTALE + '/auth/sso/login', campi, DIDUP_RITORNO);
  if (esito.tipo !== 'codice') {
    var motivo = motivoPagina(esito.valore);
    if (motivo.indexOf('non corretti') >= 0) cache.put(chiaveErrori, String(errori + 1), 900);
    throw new ErroreArgo(motivo, 401);
  }
  cache.remove(chiaveErrori);
  var tok = gettone(nav, DIDUP_CLIENT, DIDUP_RITORNO, esito.valore, p.verificatore);
  var claims = jwt(tok.access_token), idc = jwt(tok.id_token || '');
  for (var k in idc) claims[k] = idc[k];
  var nome = claims.given_name || '', cognome = claims.family_name || '';
  var s = { utente: utente, nome: nome, cognome: cognome };

  var out = { nome: nome, cognome: cognome };
  try { s.personale = apriPersonale(nav, utente, password); }
  catch (err) { out.personale_errore = err.message || String(err); }
  try { s.didup = apriDidup(tok.access_token); }
  catch (err) { out.didup_errore = err.message || String(err); }
  var id = Utilities.getUuid().replace(/-/g, '') + Utilities.getUuid().replace(/-/g, '');
  s.id = id;
  if (s.personale) {
    try { out.dati = leggiPersonale(s); } catch (err) { out.personale_errore = err.message || String(err); }
  }
  salvaSessione(id, s);
  out.sessione = id;
  return out;
}

// ------------------------------------------------------------------ programma Personale
function apriPersonale(nav, utente, password) {
  var p = pkce();
  var r = segui(nav, urlAuth(PERSONALE_CLIENT, PERSONALE_RITORNO, 'openid profile', p.sfida), null, PERSONALE_RITORNO);
  if (r.tipo !== 'codice' && r.valore.indexOf('id="loginForm"') >= 0) {
    var campi = campiModulo(r.valore, 'loginForm');
    campi.username = utente; campi.password = password; campi.login = 'true';
    r = segui(nav, PORTALE + '/auth/sso/login', campi, PERSONALE_RITORNO);
  }
  if (r.tipo !== 'codice') throw new ErroreArgo('accesso al programma Personale non riuscito: ' + motivoPagina(r.valore));
  var t = gettone(nav, PERSONALE_CLIENT, PERSONALE_RITORNO, r.valore, p.verificatore).access_token;
  var login = chiama(PERSONALE_API + 'login', null, { Authorization: 'Bearer ' + t, appCode: 'WWP' }, 'post', '/argopersonale/');
  if (!login.uid || !login.uidSubAnagrafe) throw new ErroreArgo('il programma Personale non ha riconosciuto il dipendente' + (login.msg ? ' (' + login.msg + ')' : ''));
  var anno = login.annoScolastico || {};
  return { token: t, uid: login.uid, sub: login.uidSubAnagrafe, dal: anno.datInizio, al: anno.datFine };
}

function hPersonale(p) {
  return { Authorization: 'Bearer ' + p.token, 'x-auth-token': p.uid, 'argo-client-version': PERSONALE_VERSIONE, 'argo-client-type': 'wwp.web' };
}

function chiama(url, corpo, h, metodo, referer) {
  var opz = { method: metodo || 'post', muteHttpExceptions: true,
              headers: Object.assign({ 'User-Agent': AGENTE, Accept: 'application/json', Origin: PORTALE, Referer: PORTALE + (referer || '/argopersonale/') }, h || {}) };
  if (corpo !== null && corpo !== undefined) { opz.contentType = 'application/json'; opz.payload = JSON.stringify(corpo); }
  var r;
  try { r = UrlFetchApp.fetch(url, opz); } catch (err) { throw new ErroreArgo('Argo non è raggiungibile in questo momento.', 502); }
  var stato = r.getResponseCode(), servizio = url.split('/rest/').pop().split('?')[0];
  if (stato === 401) throw new ErroreArgo('Sessione Argo scaduta: entra di nuovo con le credenziali Argo.', 401);
  if (stato >= 400) {
    var spiega = motivoArgo(r.getContentText());
    console.log('Argo ' + stato + ' a ' + servizio + ': ' + String(r.getContentText()).slice(0, 500));
    throw new ErroreArgo(spiega ? 'Argo: ' + spiega : 'Argo ha risposto ' + stato + ' a «' + servizio + '»', 502);
  }
  try { return JSON.parse(r.getContentText() || '{}'); } catch (err) { throw new ErroreArgo('Risposta non leggibile da «' + servizio + '»', 502); }
}

/** Il messaggio che Argo mette nella risposta di errore (es. {success:false, msg:"..."}), se c'è. */
function motivoArgo(testo) {
  var t = String(testo || '').trim(), o = null;
  try { o = JSON.parse(t); } catch (err) { return /^</.test(t) ? '' : t.slice(0, 200); }
  if (!o || typeof o !== 'object') return '';
  var m = o.msg || o.message || o.messaggio || o.error_description || o.error || (o.errors && JSON.stringify(o.errors)) || '';
  return String(m).replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 200);
}

var PARTICOLARITA = { MOTPERS: 'motivi_personali', FERIE: 'ferie', ORARIA: 'permesso_breve', VISMEDORA: 'visita_oraria',
                      ASSISTE104: 'l104', ASSREF104: 'l104' };
var PAROLE = [['festivit', 'festivita'], ['motivi personali', 'motivi_personali'], ['ferie', 'ferie'], ['permesso breve', 'permesso_breve'],
              ['104', 'l104'], ['lutto', 'lutto'], ['matrimonio', 'matrimonio'], ['concors', 'concorsi'], ['congedo parentale', 'congedo_parentale'],
              ['malattia del figlio', 'malattia_figlio'], ['malattia figlio', 'malattia_figlio'], ['malattia', 'malattia'], ['visita', 'visita']];
var IN_CORSO = ['FWD', 'DAU', 'AUT', 'DSG', 'REF'];
var CHIUSE = ['NUL', 'NOF', 'RIF', 'ERR'];
var NOMI_STATO = { NEW: 'Bozza', FWD: 'Inoltrata', DAU: 'Da autorizzare', AUT: 'Autorizzata', DSG: 'Vistata DSGA', REF: 'Vistata',
                   DEF: 'Registrata', NUL: 'Annullata', NOF: 'Annullata dopo la registrazione', RIF: 'Rifiutata', ERR: 'Errata' };

function tipoDa(particolarita, descrizione) {
  if (PARTICOLARITA[particolarita]) return PARTICOLARITA[particolarita];
  var d = String(descrizione || '').toLowerCase();
  for (var i = 0; i < PAROLE.length; i++) if (d.indexOf(PAROLE[i][0]) >= 0) return PAROLE[i][1];
  return 'altro';
}

function giorno(v) { return String(v || '').slice(0, 10); }

/** Assenze registrate e richieste del dipendente nell'anno, già pronte per l'app (senza dati interni di Argo). */
function leggiPersonale(s) {
  if (!s.personale) throw new ErroreArgo('Il programma Personale non è collegato: entra di nuovo con le credenziali Argo.', 409);
  var p = s.personale, h = hPersonale(p);
  var filtro = { dal: p.dal, al: p.al, uidSubAnagrafe: p.sub, page: 1, start: 0, limit: 500 };
  var reg = chiama(PERSONALE_API + 'assenza/search', Object.assign({ orarioGiornaliera: '' }, filtro), h);
  var ric;
  try { ric = chiama(PERSONALE_API + 'richiestascodip/search', Object.assign({ stato: '-1' }, filtro), h); } catch (err) { ric = { data: [] }; }
  var rif = {}, richieste = [];
  (ric.data || []).forEach(function (r) {
    var orar = r.desOrariaGiorn === 'O';
    if (r.uid) rif[r.uid] = { uid: r.uid, desNote: r.desNote, prgReferente: r.prgReferente, uidAssenzaDef: r.uidAssenzaDef, stato: r.codStato };
    richieste.push({ id: r.uid || '', inizio: giorno(r.datInizio), fine: giorno(r.datFine || r.datInizio), stato: r.codStato || '',
                     stato_nome: NOMI_STATO[r.codStato] || r.codStato || '', tipo: tipoDa(r.codParticolarita, r.desDescrizione),
                     descrizione: r.desDescrizione || '', oraria: orar, ora_dal: String(r.datPermOraDal || '').slice(-8, -3),
                     ora_al: String(r.datPermOraAl || '').slice(-8, -3),
                     annullabile: !!r.uid && CHIUSE.indexOf(r.codStato) < 0 && r.codStato !== 'NEW' });
  });
  var assenze = (reg.data || []).map(function (a) {
    var t = a.tipoAssenza || {}, orar = t.codOrariaGiorn === 'O';
    var ini = giorno(a.datInizio), fin = giorno(a.datFine || a.datInizio);
    // la richiesta da cui è nata: prima stesse date, poi stesso tipo con periodo che si sovrappone
    var valide = richieste.filter(function (r) { return r.id && CHIUSE.indexOf(r.stato) < 0; });
    var tipo = tipoDa(t.codParticolarita, t.desDescrizione);
    var da = valide.filter(function (r) { return r.inizio === ini && r.fine === fin; })[0]
          || valide.filter(function (r) { return r.inizio <= fin && r.fine >= ini && r.tipo === tipo; })[0];
    return { inizio: ini, fine: fin, giorni: a.numGiorni || 0, ore: Math.round(((a.numOre || 0) + (a.numMinuti || 0) / 60) * 100) / 100,
             oraria: orar, tipo: tipoDa(t.codParticolarita, t.desDescrizione), descrizione: t.desDescrizione || '',
             richiesta: da ? da.id : '' };
  });
  s.rif = rif;
  salvaSessione(s.id, s);
  return { dal: giorno(p.dal), al: giorno(p.al), assenze: assenze, richieste: richieste };
}

function azioneAnnulla(c) {
  var s = sessione(c);
  var r = (s.rif || {})[c.richiesta];
  if (!r) throw new ErroreArgo('Richiesta non trovata: aggiorna i dati e riprova.', 404);
  if (CHIUSE.indexOf(r.stato) >= 0) throw new ErroreArgo('Questa richiesta è già annullata o chiusa.');
  var motivo = String(c.motivo || '').trim();
  if (!motivo) throw new ErroreArgo("Scrivi il motivo dell'annullamento.");
  if (motivo.length > 250) throw new ErroreArgo('Il motivo può avere al massimo 250 caratteri.');
  var allegati = (c.allegati || []).slice(0, 5);
  var esito = chiama(PERSONALE_API + 'richiestascodip/annulla/fwd',
                     { uid: r.uid, desNote: r.desNote, prgReferente: r.prgReferente, uidAssenzaDef: r.uidAssenzaDef, desNoteAnnullamento: motivo },
                     hPersonale(s.personale), 'put');
  if (esito.success === false) throw new ErroreArgo("Il programma Personale non ha accettato l'annullamento" + (esito.msg ? ': ' + esito.msg : ''));
  var nonCaricati = [];
  allegati.forEach(function (a) {
    try { caricaAllegato(s.personale, r.uid, a); } catch (err) { nonCaricati.push(a.nome + ': ' + (err.message || err)); }
  });
  return { messaggio: esito.msg || 'Annullamento inviato', allegati_non_caricati: nonCaricati, dati: leggiPersonale(s) };
}

function caricaAllegato(p, uidRichiesta, a) {
  var nome = String(a.nome || 'allegato').replace(/[\r\n"]/g, '_').slice(0, 120);
  var dati = Utilities.base64Decode(String(a.dati || '').split(',').pop());
  if (!dati.length || dati.length > 10 * 1024 * 1024) throw new ErroreArgo('vuoto o oltre 10 MB');
  var mime = a.mime || 'application/octet-stream', modulo = {};
  modulo[nome] = Utilities.newBlob(dati, mime, nome);
  var h = Object.assign(hPersonale(p), { 'User-Agent': AGENTE, Accept: 'text/plain', Origin: PORTALE, Referer: PORTALE + '/argopersonale/',
                                         'X-File-Name': Utilities.base64Encode(nome, Utilities.Charset.UTF_8), 'X-Filename-Encoder': 'base64',
                                         'X-File-Size': String(dati.length), 'X-File-Type': mime });
  var url = PERSONALE_API + 'richiestasco/uploadallegato?uidRichiesta=' + encodeURIComponent(uidRichiesta) + '&autore=DIP';
  var r = UrlFetchApp.fetch(url, { method: 'post', payload: modulo, headers: h, muteHttpExceptions: true });
  if (r.getResponseCode() >= 400) throw new ErroreArgo('il programma Personale ha risposto ' + r.getResponseCode());
  try { if (JSON.parse(r.getContentText() || '{}').success === false) throw new ErroreArgo('allegato non accettato'); } catch (err) { if (err instanceof ErroreArgo) throw err; }
}

// ------------------------------------------------------------------ bacheca DidUP
function hDidup(token, uid, anno) {
  var h = { Authorization: 'Bearer ' + token, 'argo-client-version': DIDUP_VERSIONE, 'argo-smart-version': DIDUP_SMART,
            'cod-prodotto': 'WSX', 'x-toolkit': 'classic', 'x-build': DIDUP_BUILD };
  if (uid) h['x-auth-token'] = uid;
  if (anno !== undefined && anno !== null) h['anno-scolastico'] = String(anno);
  return h;
}

function apriDidup(token) {
  var r = chiama(DIDUP_API + 'login', null, hDidup(token), 'post', '/voti/');
  if (r.success === false || !r.uid) throw new ErroreArgo('DidUP non ha aperto la sessione' + (r.msg ? ' (' + r.msg + ')' : ''));
  var anno = r.annoScolastico;
  if (anno && typeof anno === 'object') anno = anno.numAnno || anno.anno;
  return { token: token, uid: r.uid, anno: anno };
}

function didup(s, servizio, corpo) {
  if (!s.didup) throw new ErroreArgo('La bacheca DidUP non è collegata: entra di nuovo con le credenziali Argo.', 409);
  var r = chiama(DIDUP_API + servizio, corpo, hDidup(s.didup.token, s.didup.uid, s.didup.anno), 'post', '/voti/');
  if (r.success === false) throw new ErroreArgo('DidUP: ' + (r.msg || 'operazione «' + servizio + '» non riuscita'));
  return r.data || r;
}

function dataIso(v) {
  v = String(v || '');
  var m = v.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (m) return m[0];
  m = v.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})/);
  return m ? m[3] + '-' + ('0' + m[2]).slice(-2) + '-' + ('0' + m[1]).slice(-2) : '';
}

function messaggio(x) {
  var adRich = ['richiestaAd', 'docentiAd', 'personaleAtaAd', 'docentiSingoliAd', 'docentiAtaSingoliAd'].some(function (k) { return !!x[k]; });
  var testo = String(x.desMessaggio || x.desOggetto || '').trim();
  return { pk: String(x.pk), titolo: testo.split('\n')[0].slice(0, 200) || 'Messaggio', testo: testo.slice(0, 4000),
           categoria: x.desCategoria || '', data: dataIso(x.datGiorno || x.datPubblicazione), mittente: x.desMittente || '',
           n_allegati: x.numAllegati || 0, pv_richiesta: !!x.docentiPv, pv_fatta: !!x.docentiPvConfermata, pv_quando: x.dataConfermaPv || '',
           ad_richiesta: adRich, ad_fatta: !!x.docentiAdConfermata, adesione: x.docentiAdConfermata ? (x.flgAdesione || '') : '',
           ad_quando: x.dataConfermaAd || '', ad_scadenza: dataIso(x.datScadenzaAdesione), ad_modificabile: x.adesioneModificabile !== false };
}

function bachecaNormalizzata(s) {
  var elenco = didup(s, 'bachecanuova/listamessaggibachecadocente', { anno: s.didup.anno }).listaMessaggi || [];
  var msg = elenco.filter(function (x) { return x.pk !== null && x.pk !== undefined; }).map(messaggio);
  var daFare = function (m) { return (m.pv_richiesta && !m.pv_fatta) || (m.ad_richiesta && !m.ad_fatta); };
  msg.sort(function (a, b) { return (daFare(b) - daFare(a)) || (b.data > a.data ? 1 : b.data < a.data ? -1 : 0); });
  return { messaggi: msg, da_fare: msg.filter(daFare).length };
}

function trovaMessaggio(s, pk) {
  var elenco = didup(s, 'bachecanuova/listamessaggibachecadocente', { anno: s.didup.anno }).listaMessaggi || [];
  var x = elenco.filter(function (y) { return String(y.pk) === String(pk); })[0];
  if (!x) throw new ErroreArgo('Messaggio non trovato nella bacheca DidUP.', 404);
  return x;
}

/** Apre davvero gli allegati (come il pulsante di DidUP) e poi conferma presa visione o adesione. */
function azioneConferma(c) {
  var s = sessione(c), x = trovaMessaggio(s, c.pk), m = messaggio(x);
  var adesione = c.adesione || null;
  if (adesione) {
    if (['A', 'N', 'X'].indexOf(adesione) < 0) throw new ErroreArgo('Scegli una risposta di adesione.');
    if (!m.ad_richiesta) throw new ErroreArgo("Questo messaggio non chiede un'adesione.");
    if (m.ad_fatta && !m.ad_modificabile) throw new ErroreArgo("L'adesione a questo messaggio non è più modificabile.");
  } else if (!m.pv_richiesta) throw new ErroreArgo('Questo messaggio non chiede la presa visione.');
  var aperti = 0;
  if ((x.numAllegati || 0) > 0) {
    linkAllegati(s, x.pk).forEach(function (a) {
      var r;
      try { r = UrlFetchApp.fetch(a.url, { muteHttpExceptions: true, headers: { 'User-Agent': AGENTE } }); }
      catch (err) { throw new ErroreArgo('Download dell\'allegato «' + a.nome + '» non riuscito.', 502); }
      if (r.getResponseCode() >= 400) throw new ErroreArgo('Download dell\'allegato «' + a.nome + '» non riuscito.', 502);
      r.getBlob(); aperti++;
    });
  }
  didup(s, 'bachecanuova/confermapresavisioneadesione', { pk: x.pk, presaVisione: !adesione,
        flgAdesione: adesione || x.flgAdesione, downloadEffettuato: true });
  if (adesione) { x.docentiAdConfermata = true; x.flgAdesione = adesione; } else x.docentiPvConfermata = true;
  return { messaggio: messaggio(x), aperti: aperti };
}

function linkAllegati(s, pk) {
  var d = didup(s, 'bachecanuova/loaddatidettagliomessaggiobacheca', { pk: pk });
  return (d.listaAllegati || []).map(function (al) {
    var nome = al.desFile || 'allegato';
    var u = didup(s, 'bachecanuova/richiediurlallegato', { pk: al.pk, nomeFile: nome }).url;
    if (!u) throw new ErroreArgo('DidUP non ha dato il link dell\'allegato «' + nome + '»');
    return { nome: nome, url: u };
  });
}

/** Link freschi (valgono pochi minuti) per aprire gli allegati dal telefono. */
function azioneAllegati(c) {
  var s = sessione(c);
  trovaMessaggio(s, c.pk);
  return { allegati: linkAllegati(s, c.pk) };
}

/** Prova senza credenziali (dall'editor): la pagina di accesso di Argo risponde e ha ancora il modulo loginForm. */
function provaPaginaArgo() {
  var nav = new Navigatore(), p = pkce();
  var r = segui(nav, urlAuth(DIDUP_CLIENT, DIDUP_RITORNO, 'openid profile user.roles argo', p.sfida), null, DIDUP_RITORNO);
  var campi = campiModulo(r.valore, 'loginForm');
  Logger.log('Pagina di accesso Argo raggiungibile. Campi del modulo: ' + Object.keys(campi).join(', '));
}
