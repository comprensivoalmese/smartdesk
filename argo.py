"""Verifica di nome utente e password sul portale Argo (accesso OIDC come quello del sito).

Stesso percorso usato da Documents\\assenze-argo, riscritto con la sola libreria standard.
La password viene usata solo per questa verifica: non si salva e non si scrive nei log.
Si fa un solo tentativo: Argo blocca l'account dopo troppi errori.
"""
import base64
import hashlib
import http.cookiejar
import json
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
from html import unescape

AUTH = "https://auth.portaleargo.it"
PORTALE = "https://www.portaleargo.it"
CLIENT_ID = "963ed11e-33b2-41b4-8911-f4f1907bd208"
RITORNO = PORTALE + "/voti/oidc-callback.html?classic"
# programma Personale (assenze registrate dalla segreteria), letto in sola consultazione
PERSONALE_CLIENT = "ad175860-1847-4b12-8f0f-54041ebca714"
PERSONALE_RITORNO = PORTALE + "/argopersonale/oidc-callback.html"
PERSONALE_API = "https://personale.portaleargo.it/personale/rest/"
PERSONALE_VERSIONE = "1.50.2"
AGENTE = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


class ErroreArgo(Exception):
    pass


class _SenzaRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _apri(op, url, dati=None):
    corpo = urllib.parse.urlencode(dati).encode() if dati is not None else None
    req = urllib.request.Request(url, data=corpo, headers={"User-Agent": AGENTE, "Accept-Language": "it-IT,it"})
    try:
        with op.open(req, timeout=25) as r:
            return r.status, r.headers, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308):
            return e.code, e.headers, ""
        raise ErroreArgo(f"Argo ha risposto con un errore ({e.code}). Riprova tra poco.")
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ErroreArgo("Argo non è raggiungibile: controlla la connessione a internet del server.")


def _segui(op, url, dati=None, ritorno=None):
    """Segue i reindirizzamenti. Restituisce ("codice", code) se si arriva al ritorno OIDC,
    altrimenti ("pagina", html)."""
    base_ritorno = (ritorno or RITORNO).split("?")[0]
    for _ in range(15):
        stato, intest, corpo = _apri(op, url, dati)
        if stato not in (301, 302, 303, 307, 308):
            return "pagina", corpo
        url = urllib.parse.urljoin(url, intest.get("Location", ""))
        dati = None
        if url.startswith(base_ritorno):
            codice = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("code", [None])[0]
            if codice:
                return "codice", codice
    raise ErroreArgo("Troppi reindirizzamenti durante l'accesso ad Argo.")


def _campi_modulo(html, id_modulo):
    modulo = re.search(rf'<form\b[^>]*id="{id_modulo}".*?</form>', html, re.S)
    if not modulo:
        raise ErroreArgo("La pagina di accesso di Argo è cambiata: avvisa l'amministratore dello Sportello.")
    campi = {}
    for campo in re.findall(r"<input\b[^>]*>", modulo.group(0)):
        nome = re.search(r'name="([^"]*)"', campo)
        valore = re.search(r'value="([^"]*)"', campo)
        if nome:
            campi[nome.group(1)] = unescape(valore.group(1)) if valore else ""
    return campi


def _motivo(html):
    if 'id="otpForm"' in html:
        return ("Il tuo account Argo chiede il secondo codice (OTP): lo Sportello non lo gestisce ancora. "
                "Entra con l'account dello Sportello.")
    if 'id="selectForm"' in html:
        return "Argo chiede di scegliere tra più profili: lo Sportello non lo gestisce ancora."
    if 'id="consentForm"' in html:
        return "Argo chiede di accettare un consenso: entra una volta su portaleargo.it e accettalo."
    if 'id="loginForm"' in html:
        return "Nome utente o password di Argo non corretti."
    return "Argo ha risposto in modo inatteso."


def _jwt(token):
    try:
        parte = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(parte + "=" * (-len(parte) % 4)))
    except (IndexError, ValueError, AttributeError):
        return {}


def _pkce():
    verificatore = secrets.token_urlsafe(48)
    sfida = base64.urlsafe_b64encode(hashlib.sha256(verificatore.encode()).digest()).rstrip(b"=").decode()
    return verificatore, sfida


def _gettone(op, client_id, ritorno, codice, verificatore):
    _, _, corpo = _apri(op, AUTH + "/oauth2/token", {
        "grant_type": "authorization_code", "client_id": client_id, "redirect_uri": ritorno,
        "code": codice, "code_verifier": verificatore})
    try:
        token = json.loads(corpo)
    except ValueError:
        raise ErroreArgo("Argo non ha rilasciato il gettone di accesso.")
    if "access_token" not in token:
        raise ErroreArgo("Argo non ha rilasciato il gettone di accesso.")
    return token


def accedi(utente, password, assenze=False):
    """Verifica le credenziali su Argo. Restituisce i dati dell'identità (claims dei token).
    Con assenze=True restituisce (claims, dati_personale): il secondo viene da leggi_personale()
    oppure è {"errore": ...} se la lettura non è riuscita (l'accesso vale comunque)."""
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()), _SenzaRedirect)
    verificatore, sfida = _pkce()
    tipo, pagina = _segui(op, AUTH + "/oauth2/auth?" + urllib.parse.urlencode({
        "client_id": CLIENT_ID, "redirect_uri": RITORNO, "response_type": "code",
        "scope": "openid profile user.roles argo", "state": secrets.token_urlsafe(16),
        "code_challenge": sfida, "code_challenge_method": "S256"}))
    if tipo != "pagina":
        raise ErroreArgo("Argo ha risposto in modo inatteso.")
    campi = _campi_modulo(pagina, "loginForm")
    campi.update(username=utente, password=password, login="true")
    tipo, valore = _segui(op, PORTALE + "/auth/sso/login", campi)
    if tipo != "codice":
        raise ErroreArgo(_motivo(valore))
    token = _gettone(op, CLIENT_ID, RITORNO, valore, verificatore)
    claims = {}
    claims.update(_jwt(token.get("access_token")))
    claims.update(_jwt(token.get("id_token")))
    if assenze:
        try:
            dati = leggi_personale(op, utente, password)
        except ErroreArgo as e:
            dati = {"errore": str(e)}
        except Exception as e:  # la lettura delle assenze non deve mai impedire l'accesso
            dati = {"errore": f"errore imprevisto ({type(e).__name__})"}
        return claims, dati
    return claims


# ---------------------------------------------------------------- programma Personale (sola lettura)
def _json(url, corpo=None, intestazioni=None):
    """POST JSON a un servizio del programma Personale."""
    h = {"User-Agent": AGENTE, "Accept": "application/json", "Origin": PORTALE,
         "Referer": PORTALE + "/argopersonale/"}
    if corpo is not None:
        h["Content-Type"] = "application/json"
    h.update(intestazioni or {})
    dati = json.dumps(corpo).encode() if corpo is not None else b""
    req = urllib.request.Request(url, data=dati, headers=h, method="POST")
    servizio = url.rsplit("/rest/", 1)[-1]
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(r.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        raise ErroreArgo(f"il programma Personale ha risposto {e.code} a «{servizio}»")
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ErroreArgo("il programma Personale non è raggiungibile")
    except ValueError:
        raise ErroreArgo(f"risposta non leggibile da «{servizio}»")


def leggi_personale(op, utente, password):
    """Con la sessione Argo appena aperta (op) entra nel programma Personale e legge, in sola lettura,
    le assenze registrate e le richieste del dipendente nell'anno scolastico in corso."""
    verificatore, sfida = _pkce()
    url = AUTH + "/oauth2/auth?" + urllib.parse.urlencode({
        "client_id": PERSONALE_CLIENT, "redirect_uri": PERSONALE_RITORNO, "response_type": "code",
        "scope": "openid profile argo", "state": secrets.token_urlsafe(16),
        "code_challenge": sfida, "code_challenge_method": "S256"})
    tipo, valore = _segui(op, url, ritorno=PERSONALE_RITORNO)
    if tipo != "codice" and 'id="loginForm"' in valore:
        # di solito basta la sessione appena aperta; se no si ripresentano le stesse credenziali, già verificate
        campi = _campi_modulo(valore, "loginForm")
        campi.update(username=utente, password=password, login="true")
        tipo, valore = _segui(op, PORTALE + "/auth/sso/login", campi, ritorno=PERSONALE_RITORNO)
    if tipo != "codice":
        raise ErroreArgo("accesso al programma Personale non riuscito: " + _motivo(valore))
    token = _gettone(op, PERSONALE_CLIENT, PERSONALE_RITORNO, valore, verificatore)["access_token"]
    sessione = _json(PERSONALE_API + "login", intestazioni={"Authorization": "Bearer " + token, "appCode": "WWP"})
    if not sessione.get("uid") or not sessione.get("uidSubAnagrafe"):
        raise ErroreArgo("il programma Personale non ha riconosciuto il dipendente"
                         + (f" ({sessione.get('msg')})" if sessione.get("msg") else ""))
    h = {"Authorization": "Bearer " + token, "x-auth-token": sessione["uid"],
         "argo-client-version": PERSONALE_VERSIONE, "argo-client-type": "wwp.web"}
    anno = sessione.get("annoScolastico") or {}
    dal, al = anno.get("datInizio"), anno.get("datFine")
    if not dal or not al:
        raise ErroreArgo("il programma Personale non ha indicato l'anno scolastico")
    filtro = {"dal": dal, "al": al, "uidSubAnagrafe": sessione["uidSubAnagrafe"], "page": 1, "start": 0, "limit": 500}
    registrate = _json(PERSONALE_API + "assenza/search", {"orarioGiornaliera": ""} | filtro, h)
    try:
        richieste = _json(PERSONALE_API + "richiestascodip/search", {"stato": "-1"} | filtro, h)
    except ErroreArgo:
        richieste = {"data": []}
    out = {"dal": dal, "al": al, "assenze": [], "richieste": []}
    for a in registrate.get("data") or []:
        t = a.get("tipoAssenza") or {}
        out["assenze"].append({
            "inizio": a.get("datInizio") or "", "fine": a.get("datFine") or a.get("datInizio") or "",
            "giorni": a.get("numGiorni") or 0,
            "ore": round((a.get("numOre") or 0) + (a.get("numMinuti") or 0) / 60, 2),
            "particolarita": t.get("codParticolarita") or "", "codice": t.get("uid") or a.get("uidTipoAssenza") or "",
            "descrizione": t.get("desDescrizione") or "", "oraria": t.get("codOrariaGiorn") == "O"})
    for r in richieste.get("data") or []:
        out["richieste"].append({
            "inizio": r.get("datInizio") or "", "fine": r.get("datFine") or r.get("datInizio") or "",
            "stato": r.get("codStato") or "", "particolarita": r.get("codParticolarita") or "",
            "codice": r.get("uidTipoAssenza") or "", "descrizione": r.get("desDescrizione") or "",
            "oraria": r.get("desOrariaGiorn") == "O",
            "ora_dal": r.get("datPermOraDal") or "", "ora_al": r.get("datPermOraAl") or ""})
    return out


# ---------------------------------------------------------------- lettura dei dati dell'identità
def _testi(valore):
    if isinstance(valore, str):
        yield valore
    elif isinstance(valore, dict):
        for v in valore.values():
            yield from _testi(v)
    elif isinstance(valore, list):
        for v in valore:
            yield from _testi(v)


def identita(claims, utente):
    """Nome, cognome e codici utili dai claims (i nomi dei campi di Argo non sono documentati)."""
    def primo(*chiavi):
        for k in chiavi:
            v = claims.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""
    nome = primo("given_name", "nome", "firstName")
    cognome = primo("family_name", "cognome", "lastName")
    completo = primo("name", "full_name", "nominativo")
    if (not nome or not cognome) and completo:
        parti = completo.split()
        if len(parti) >= 2:
            cognome, nome = cognome or parti[0], nome or " ".join(parti[1:])
    # nome utente Argo del personale: nome.cognome.SC12345 (es. anco.marzio.SC15290)
    m = re.fullmatch(r"([^.]+)\.(.+)\.(sc\w+)", utente.strip(), re.I)
    if m and (not nome or not cognome):
        nome = nome or m.group(1).replace("_", " ").replace("-", " ").title()
        cognome = cognome or m.group(2).replace(".", " ").replace("_", " ").title()
    return {
        "nome": nome.title() if nome.isupper() else nome,
        "cognome": cognome.title() if cognome.isupper() else cognome,
        "username": (primo("preferred_username", "username") or utente).lower(),
        "sub": primo("sub"),
        "testi": [t.upper() for t in _testi(claims)] + [utente.upper()],
        "codice_da_utente": m.group(3).upper() if m else "",
    }


def descrivi_claims(claims):
    """Per i log: nomi dei campi e lunghezza dei valori, senza i valori."""
    return {k: (type(v).__name__, len(v) if hasattr(v, "__len__") else None) for k, v in claims.items()}
