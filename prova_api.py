"""Collaudo automatico delle API dello Sportello Personale (solo libreria standard).

Uso:  python prova_api.py
Avvia il server su una porta libera con dati di prova in una cartella temporanea e prova
il giro completo: richiesta -> verifica -> autorizzazione, limiti, bacheca, timbrature, documenti.
"""
import base64
import datetime as dt
import http.cookiejar
import json
import os
import re
import sys
import tempfile
import threading
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402

ERRORI = []


def controlla(cond, msg):
    print(("  ok  " if cond else "  NO  ") + msg)
    if not cond:
        ERRORI.append(msg)


class Client:
    def __init__(self, base):
        self.base = base
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def chiama(self, path, dati=None):
        req = urllib.request.Request(self.base + path, method="POST" if dati is not None else "GET")
        if dati is not None:
            req.data = json.dumps(dati).encode()
            req.add_header("Content-Type", "application/json")
        try:
            with self.op.open(req) as r:
                corpo = r.read()
                return r.status, (json.loads(corpo) if r.headers.get_content_type() == "application/json" else corpo)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")


def avvia_finto_argo():
    """Server che imita auth.portaleargo.it / www.portaleargo.it nei passaggi usati da argo.py."""
    import argo
    from http.server import BaseHTTPRequestHandler
    from urllib.parse import parse_qs, urlparse

    persone = {
        "giulia.r": {"given_name": "GIULIA", "family_name": "RINALDI", "argo": {"codMin": "SC99999"}},
        "nuovo.doc": {"given_name": "Luca", "family_name": "Verdi", "scuole": ["SC99999"]},
        "altra.scuola": {"given_name": "Anna", "family_name": "Neri", "scuole": ["SC11111"]},
        "stefano.argo": {"name": "CONTI STEFANO", "scuole": ["SC99999"]},
        "anco.marzio.sc99999": {},
        "tullo.ostilio.sc999990": {},
    }

    a0 = server.inizio_anno().year
    lun = dt.date.today() + dt.timedelta(days=7 - dt.date.today().weekday())  # prossimo lunedì
    lunedi = lun.isoformat() if lun <= dt.date(a0 + 1, 6, 1) else f"{a0 + 1}-05-03"

    def jwt(d):
        b = lambda x: base64.urlsafe_b64encode(json.dumps(x).encode()).rstrip(b"=").decode()
        return f"{b({'alg': 'none'})}.{b(d)}.firma"

    class Finto(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def manda(self, codice, corpo="", loc=None, tipo="text/html", biscotto=None):
            self.send_response(codice)
            if loc:
                self.send_header("Location", loc)
            if biscotto:
                self.send_header("Set-Cookie", biscotto + "; Path=/")
            self.send_header("Content-Type", tipo)
            self.end_headers()
            self.wfile.write(corpo.encode())

        def modulo(self):
            return ('<html><form id="loginForm" action="/auth/sso/login" method="post">'
                    '<input type="hidden" name="challenge" value="abc&amp;1"><input type="hidden" name="remember_me" value="false"><input name="username">'
                    '<input type="password" name="password"><button name="login" value="true">Entra</button></form></html>')

        def do_GET(self):
            u = urlparse(self.path)
            if u.path == "/oauth2/auth":
                q = parse_qs(u.query)
                sso = re.search(r"sso=([^;]+)", self.headers.get("Cookie") or "")
                if q.get("client_id") == [argo.PERSONALE_CLIENT] and q.get("code_challenge_method") == ["S256"]:
                    if sso:  # sessione già aperta: si torna subito con il codice
                        return self.manda(302, loc=argo.PERSONALE_RITORNO + "?code=PCOD-" + sso.group(1) + "&scope=openid")
                    return self.manda(302, loc="/login?challenge=abc")
                ok = q.get("client_id") == [argo.CLIENT_ID] and q.get("code_challenge_method") == ["S256"]
                return self.manda(302, loc="/login?challenge=abc" if ok else "/errore")
            if u.path == "/login":
                return self.manda(200, self.modulo())
            if u.path == "/consenso-ok":
                q = parse_qs(u.query)
                un = q["u"][0]  # come Argo: la sessione resta solo con "Ricordami"
                return self.manda(302, loc=argo.RITORNO + "&code=COD-" + un,
                                  biscotto=("sso=" + un) if q.get("r") == ["true"] else None)
            self.manda(404)

        def personale(self, grezzo):
            """Imita il programma Personale: login e ricerche (solo per giulia.r ci sono assenze)."""
            tok = (self.headers.get("Authorization") or "").removeprefix("Bearer PTOK-")
            servizio = self.path.removeprefix("/personale/rest/")
            if servizio == "login":
                if tok == "nuovo.doc":
                    return {"success": False, "msg": "Utente non abilitato"}
                return {"uid": "sess-" + tok, "uidSubAnagrafe": "sub-" + tok,
                        "annoScolastico": {"datInizio": f"{a0}-09-01", "datFine": f"{a0 + 1}-08-31"}}
            if self.headers.get("x-auth-token") != "sess-" + tok or self.headers.get("argo-client-type") != "wwp.web":
                return None
            filtro = json.loads(grezzo)
            if filtro.get("uidSubAnagrafe") != "sub-giulia.r":
                return {"data": []}
            mp = {"codParticolarita": "MOTPERS", "desDescrizione": "Permesso per motivi personali o familiari",
                  "codOrariaGiorn": "G", "uid": "S_90_I"}
            if servizio == "assenza/search":
                return {"data": [
                    {"datInizio": f"{a0}-10-13", "datFine": f"{a0}-10-14", "numGiorni": 2, "tipoAssenza": mp},
                    {"datInizio": f"{a0}-10-20", "datFine": f"{a0}-10-20", "numGiorni": 1,
                     "tipoAssenza": {"codParticolarita": "FERIE", "desDescrizione": "Ferie", "codOrariaGiorn": "G"}}]}
            if servizio == "richiestascodip/search":
                return {"data": [
                    {"datInizio": lunedi, "datFine": lunedi, "codStato": "FWD", "codParticolarita": "MOTPERS",
                     "desDescrizione": "Permesso per motivi personali o familiari", "desOrariaGiorn": "G"},
                    {"datInizio": lunedi, "datFine": lunedi, "codStato": "NUL", "codParticolarita": "MOTPERS",
                     "desDescrizione": "Permesso per motivi personali o familiari", "desOrariaGiorn": "G"}]}
            return None

        def do_POST(self):
            grezzo = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
            if self.path.startswith("/personale/rest/"):
                r = self.personale(grezzo)
                return self.manda(200, json.dumps(r), tipo="application/json") if r is not None else self.manda(401)
            corpo = parse_qs(grezzo)
            v = {k: x[0] for k, x in corpo.items()}
            if self.path == "/auth/sso/login":
                if v.get("challenge") != "abc&1" or v.get("login") != "true":
                    return self.manda(400)
                un = v["username"].lower()
                srv.tentativi[un] = srv.tentativi.get(un, 0) + 1
                if un == "con.otp":
                    return self.manda(200, '<form id="otpForm"></form>')
                if un in persone and v["password"] == "giusta":
                    return self.manda(302, loc=f"/consenso-ok?u={un}&r={v.get('remember_me')}")
                return self.manda(200, self.modulo())
            if self.path == "/oauth2/token":
                if v.get("grant_type") != "authorization_code" or not v.get("code_verifier"):
                    return self.manda(400)
                if v["code"].startswith("PCOD-"):
                    if v.get("client_id") != argo.PERSONALE_CLIENT:
                        return self.manda(400)
                    return self.manda(200, json.dumps({"access_token": "PTOK-" + v["code"][5:]}), tipo="application/json")
                un = v["code"].removeprefix("COD-")
                d = {"sub": "id-" + un, "preferred_username": un} | persone[un]
                return self.manda(200, json.dumps({"access_token": jwt({"scope": "argo"}), "id_token": jwt(d)}),
                                  tipo="application/json")
            self.manda(404)

    srv = server.ThreadingHTTPServer(("127.0.0.1", 0), Finto)
    srv.tentativi = {}
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    argo.AUTH = argo.PORTALE = base
    argo.RITORNO = base + "/voti/oidc-callback.html?classic"
    argo.PERSONALE_RITORNO = base + "/argopersonale/oidc-callback.html"
    argo.PERSONALE_API = base + "/personale/rest/"
    return srv


def main():
    tmp = tempfile.mkdtemp(prefix="sportello-prova-")
    server.DATI = tmp
    server.prepara_db()
    pw = server.crea_demo()
    srv = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Gestore)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    imp = {"settimana_corta": "1", "patrono": ""}

    def lav(n):
        d = dt.date.today()
        while True:
            d += dt.timedelta(days=1)
            if server.lavorativo(d, imp):
                n -= 1
                if n <= 0:
                    return d

    def entra(u):
        c = Client(base)
        s, r = c.chiama("/api/accesso", {"username": u, "password": pw})
        controlla(s == 200, f"accesso di {u}")
        return c

    print("Accesso")
    anon = Client(base)
    controlla(anon.chiama("/api/home")[0] == 401, "senza accesso: 401")
    controlla(anon.chiama("/api/accesso", {"username": "g.rinaldi", "password": "sbagliata"})[0] == 401, "password sbagliata")
    doc, seg, dir_, dsga, ata = (entra(u) for u in ("s.conti", "segreteria", "dirigente", "dsga", "r.greco"))
    s, io = doc.chiama("/api/io")
    controlla(not io["staff"] and not io["timbrature"], "docente: niente gestione né timbrature")
    controlla("recupero" not in [t["id"] for t in io["tipologie"]], "docente non vede 'recupero ore'")

    print("Richiesta di ferie: giro completo")
    d1, d2 = lav(5), lav(6)
    s, a = doc.chiama("/api/richieste/anteprima", {"tipo": "ferie", "dal": d1.isoformat(), "al": d2.isoformat()})
    controlla(a["ok"] and a["quantita"] == 2, f"anteprima 2 giorni ({a})")
    s, r = doc.chiama("/api/richieste", {"tipo": "ferie", "dal": d1.isoformat(), "al": d2.isoformat(),
                                         "allegati": [{"nome": "nota.txt", "mime": "text/plain",
                                                       "dati": base64.b64encode(b"ciao").decode()}]})
    controlla(s == 200, f"richiesta inviata ({r})")
    rid = r["id"]
    s, e = doc.chiama("/api/richieste", {"tipo": "ferie", "dal": d2.isoformat(), "al": d2.isoformat()})
    controlla(s == 400 and "sovrappone" in e["errore"], "sovrapposizione bloccata")
    s, e = doc.chiama("/api/richieste", {"tipo": "ferie", "dal": dt.date.today().isoformat()})
    controlla(s == 400 and "anticipo" in e["errore"], f"preavviso ({e.get('errore')})")
    s, e = doc.chiama("/api/richieste", {"tipo": "festivita", "dal": lav(10).isoformat(), "al": lav(14).isoformat()})
    controlla(s == 400 and "Limite" in e["errore"], f"limite festività ({e.get('errore')})")
    s, e = doc.chiama(f"/api/richieste/{rid}/azione", {"azione": "autorizza"})
    controlla(s == 400, "il docente non può autorizzarsi")
    s, lst = seg.chiama("/api/gestione/da-lavorare")
    controlla(any(x["id"] == rid for x in lst), "la segreteria la vede da lavorare")
    s, e = seg.chiama(f"/api/richieste/{rid}/azione", {"azione": "autorizza"})
    controlla(s == 400, "la segreteria non autorizza")
    s, _ = seg.chiama(f"/api/richieste/{rid}/azione", {"azione": "verifica"})
    controlla(s == 200, "verificata")
    s, lst = dsga.chiama("/api/gestione/da-lavorare")
    controlla(not any(x["id"] == rid for x in lst), "il DSGA non autorizza le ferie dei docenti")
    s, lst = dir_.chiama("/api/gestione/da-lavorare")
    controlla(any(x["id"] == rid for x in lst), "il dirigente la vede")
    s, _ = dir_.chiama(f"/api/richieste/{rid}/azione", {"azione": "autorizza"})
    controlla(s == 200, "autorizzata")
    s, det = doc.chiama(f"/api/richieste/{rid}")
    controlla(det["stato"] == "autorizzata" and len(det["storico"]) == 3, "storico con 3 passaggi")
    s, f = doc.chiama(f"/api/allegati/{det['allegati'][0]['id']}")
    controlla(f == b"ciao", "allegato scaricabile dal proprietario")
    controlla(ata.chiama(f"/api/allegati/{det['allegati'][0]['id']}")[0] == 403, "allegato negato ad altri")
    controlla(ata.chiama(f"/api/richieste/{rid}")[0] == 404, "richiesta altrui invisibile")
    s, n = doc.chiama("/api/notifiche")
    controlla(any("autorizzata" in x["testo"] for x in n["elenco"]), "notifica di autorizzazione")

    print("Permesso breve ATA autorizzato dal DSGA, integrazione")
    s, r = ata.chiama("/api/richieste", {"tipo": "permesso_breve", "dal": lav(2).isoformat(), "ora_da": "09:00", "ora_a": "11:00"})
    controlla(s == 200, f"permesso breve ({r})")
    pid = r["id"]
    seg.chiama(f"/api/richieste/{pid}/azione", {"azione": "verifica"})
    s, lst = dsga.chiama("/api/gestione/da-lavorare")
    controlla(any(x["id"] == pid for x in lst), "il DSGA lo autorizza")
    s, e = dsga.chiama(f"/api/richieste/{pid}/azione", {"azione": "respingi"})
    controlla(s == 400 and "motivazione" in e["errore"], "respingere richiede motivazione")
    s, _ = dsga.chiama(f"/api/richieste/{pid}/azione", {"azione": "integra", "nota": "Indica chi ti sostituisce"})
    controlla(s == 200, "chiesta integrazione")
    s, _ = ata.chiama(f"/api/richieste/{pid}", {"dal": lav(2).isoformat(), "ora_da": "09:00", "ora_a": "10:30",
                                              "note": "Mi sostituisce Ricci"})
    s2, det = ata.chiama(f"/api/richieste/{pid}")
    controlla(s == 200 and det["stato"] == "inviata" and det["quantita"] == 1.5, "modificata e reinviata (1,5 ore)")
    s, e = ata.chiama("/api/richieste", {"tipo": "permesso_breve", "dal": lav(3).isoformat(), "ora_da": "08:00", "ora_a": "12:00"})
    controlla(s == 400 and "massimo" in e["errore"], "max 3 ore per volta")

    print("Malattia e richiesta generica")
    ul = dt.date.today()
    while not server.lavorativo(ul, imp):
        ul -= dt.timedelta(days=1)
    s, r = ata.chiama("/api/richieste", {"tipo": "malattia", "dal": ul.isoformat(), "al": lav(1).isoformat(),
                                         "campi": {"tipo_malattia": "Malattia ordinaria"}})
    controlla(s == 400 and "sovrappone" in r["errore"], "la malattia di prova di r.greco c'è già oggi")
    s, r = doc.chiama("/api/richieste", {"tipo": "generica", "campi": {"tipologia": "Certificato di servizio", "oggetto": "Per graduatoria"}})
    controlla(s == 200, "richiesta generica")
    s, det = seg.chiama(f"/api/richieste/{r['id']}")
    controlla([a["id"] for a in det["azioni"]] == ["evadi", "integra", "respingi"], f"azioni segreteria sulla generica")

    print("Bacheca")
    s, r = seg.chiama("/api/circolari", {"titolo": "Prova", "testo": "Testo", "destinatari": "ata", "adesione": True,
                                         "scadenza": lav(3).isoformat()})
    controlla(s == 200, "circolare pubblicata")
    cid = r["id"]
    controlla(doc.chiama(f"/api/circolari/{cid}")[0] == 404, "i docenti non vedono una circolare per l'ATA")
    s, e = ata.chiama(f"/api/circolari/{cid}/leggi", {"risposta": "boh"})
    controlla(s == 400, "risposta non valida")
    s, _ = ata.chiama(f"/api/circolari/{cid}/leggi", {"risposta": "Aderisco"})
    s, ci = seg.chiama(f"/api/circolari/{cid}")
    controlla(ci["statistiche"]["risposte"]["Aderisco"] == 1, "statistiche di adesione")
    s, lst = doc.chiama("/api/circolari?q=collegio")
    controlla(len(lst) == 1, "ricerca in bacheca")

    print("Bacheca dal feed pubblico Argo")
    ora_ms = int(dt.datetime.now().timestamp() * 1000)
    feed = {"categorie": [{"key": "k1", "descrizione": "Circolari"}], "items": [
        {"key": "a1", "titolo": "Circolare 50 - Assemblea sindacale", "descrizione": "Circolare 50 - Assemblea sindacale",
         "categorie": ["k1"], "lastModifiedAt": ora_ms, "files": [
             {"filename": "c50.pdf", "url": "https://esempio.it/c50"}, {"filename": "sigillo_c50.pdf", "url": "https://esempio.it/s"}]},
        {"key": "vecchia", "titolo": "Dell'anno scorso", "categorie": [], "lastModifiedAt": ora_ms - 400 * 86400000, "files": []}]}
    with server.db() as c0:
        c0.execute("UPDATE impostazioni SET valore='SC99999' WHERE chiave='argo_codice_scuola'")
        n1 = server.importa_bacheca_argo(c0, lambda url: feed)
        n2 = server.importa_bacheca_argo(c0, lambda url: feed)
    controlla(n1 == 1 and n2 == 0, "importata una volta sola, l'anno scorso escluso")
    s, lst = doc.chiama("/api/circolari?q=assemblea")
    controlla(len(lst) == 1 and lst[0]["fonte"] == "argo" and lst[0]["n_allegati"] == 1, "visibile in bacheca, senza la copia sigillata")
    s, det = doc.chiama(f"/api/circolari/{lst[0]['id']}")
    controlla(det["link_esterni"] == [{"nome": "c50.pdf", "url": "https://esempio.it/c50"}], "link al PDF di Argo")
    feed["items"] = feed["items"][1:]
    with server.db() as c0:
        server.importa_bacheca_argo(c0, lambda url: feed)
    controlla(not doc.chiama("/api/circolari?q=assemblea")[1], "tolta da Argo: tolta anche qui")

    print("Timbrature e cartellino")
    s, e = ata.chiama("/api/timbra", {"verso": "U"})
    controlla(s == 400, "uscita senza entrata bloccata")
    s, _ = ata.chiama("/api/timbra", {"verso": "E"})
    controlla(s == 200, "entrata")
    controlla(ata.chiama("/api/timbra", {"verso": "E"})[0] == 400, "doppia entrata bloccata")
    controlla(doc.chiama("/api/timbra", {"verso": "E"})[0] == 403, "docente: timbrature non attive")
    s, k = ata.chiama("/api/cartellino")
    controlla(s == 200 and k["ore"] > 0, f"cartellino del mese ({k.get('ore')} ore)")
    controlla(ata.chiama(f"/api/cartellino?utente=1")[0] == 403, "cartellino altrui negato")
    s, k = seg.chiama(f"/api/cartellino?utente={k['utente']['id']}")
    controlla(s == 200, "la segreteria vede il cartellino")
    s, csvb = seg.chiama(f"/api/cartellino.csv?utente={k['utente']['id']}")
    controlla(s == 200 and b"Giorno;Timbrature" in csvb, "CSV del cartellino")

    print("Documenti, personale, CSV")
    s, us = seg.chiama("/api/utenti")
    conti = next(x for x in us if x["username"] == "s.conti")
    s, r = seg.chiama("/api/documenti", {"tipo": "Cedolino", "titolo": "Cedolino prova", "utenti": [conti["id"]],
                                         "allegati": [{"nome": "c.pdf", "mime": "application/pdf",
                                                       "dati": base64.b64encode(server.pdf_semplice(["x"])).decode()}]})
    controlla(s == 200 and r["inviati"] == 1, "documento inviato")
    s, ds = doc.chiama("/api/documenti")
    controlla(any(d["titolo"] == "Cedolino prova" for d in ds), "il docente vede il documento")
    s, r = seg.chiama("/api/utenti", {"nome": "Mario", "cognome": "Bianchi", "username": "m.bianchi", "ruolo": "ata"})
    controlla(s == 200 and len(r["password"]) == 14, "nuovo utente con password provvisoria")
    controlla(seg.chiama("/api/utenti", {"nome": "X", "cognome": "Y", "username": "xy", "ruolo": "dirigente"})[0] == 403,
              "la segreteria non crea dirigenti")
    controlla(doc.chiama("/api/utenti")[0] == 403, "il docente non vede il personale")
    s, csvb = seg.chiama("/api/gestione/richieste.csv")
    controlla(s == 200 and csvb.startswith("﻿N.;".encode()), "CSV delle richieste")
    s, a = seg.chiama(f"/api/gestione/assenti?data={ul.isoformat()}")
    controlla(s == 200 and any("Greco" in x["nome"] for x in a["assenti"]), "assenti dell'ultimo giorno lavorativo")
    s, h = seg.chiama("/api/home")
    controlla(s == 200 and "da_lavorare" in h, "home della segreteria")
    s, _ = doc.chiama("/api/password", {"attuale": pw, "nuova": "breve"})
    controlla(s == 400, "password troppo corta")

    print("Accesso con Argo (finto server Argo)")
    finto = avvia_finto_argo()
    controlla(anon.chiama("/api/accesso", {"username": "giulia.r", "password": "giusta", "modo": "argo"})[0] == 403,
              "Argo disattivato: rifiutato")
    s, _ = dir_.chiama("/api/impostazioni", {"argo_attivo": "1", "argo_codice_scuola": "sc99999", "argo_nuovi": "0"})
    controlla(s == 200, "accesso Argo attivato dal dirigente")
    s, info = anon.chiama("/api/accesso-info")
    controlla(info["argo"] is True, "la pagina di accesso mostra Argo")
    g = Client(base)
    s, e = g.chiama("/api/accesso", {"username": "giulia.r", "password": "sbagliata", "modo": "argo"})
    controlla(s == 401 and "non corretti" in e["errore"], f"password Argo sbagliata ({e.get('errore')})")
    s, _ = g.chiama("/api/accesso", {"username": "giulia.r", "password": "giusta", "modo": "argo"})
    s2, io = g.chiama("/api/io")
    controlla(s == 200 and io["utente"]["username"] == "g.rinaldi", "riconosciuta per nome e cognome (Rinaldi Giulia)")
    controlla(io["utente"]["argo_utente"] == "giulia.r", "utente Argo collegato alla scheda")
    s, ct = g.chiama("/api/contatori")
    seg_ = ct.get("segreteria", {})
    ass = seg_.get("assenze", [])
    controlla(s == 200 and seg_.get("letto") and not seg_.get("errore"), "assenze lette dal programma della segreteria")
    controlla(sorted((x["tipo"], x["stato"], x["quantita"]) for x in ass)
              == [("ferie", "registrata", 1), ("motivi_personali", "registrata", 2), ("motivi_personali", "richiesta", 1)],
              f"assenze registrate e richiesta in attesa (le annullate no): {[(x['tipo'], x['stato']) for x in ass]}")
    mp = next(k for k in ct["contatori"] if k["tipo"] == "motivi_personali")
    controlla(mp["usati"] >= 2 and mp["attesa"] >= 1 and mp["residuo"] <= 0,
              f"motivi personali: usati {mp['usati']}, in attesa {mp['attesa']}, rimasti {mp['residuo']}")
    with server.db() as c0:
        uid_g = io["utente"]["id"]
        prima = server.utilizzo(c0, uid_g, "motivi_personali", server.inizio_anno(), server.fine_anno(server.oggi()))
        c0.execute("INSERT INTO richieste (utente_id,tipo,dal,al,quantita,stato,creata,aggiornata) VALUES "
                   "(?,?,?,?,?,?,?,?)", (uid_g, "motivi_personali", f"{server.inizio_anno().year}-10-14",
                                         f"{server.inizio_anno().year}-10-14", 1, "autorizzata", "x", "x"))
        dopo = server.utilizzo(c0, uid_g, "motivi_personali", server.inizio_anno(), server.fine_anno(server.oggi()))
        c0.execute("DELETE FROM richieste WHERE creata='x'")
    controlla(prima == dopo, "una richiesta dello Sportello già registrata in segreteria non si conta due volte")
    controlla(not any(x in open(os.path.join(tmp, "argo-personale.json"), encoding="utf-8").read()
                      for x in ("giusta", "Rinaldi", "MOTPERS")), "il file di diagnosi delle assenze ha solo i numeri")
    s, e = Client(base).chiama("/api/accesso", {"username": "nuovo.doc", "password": "giusta", "modo": "argo"})
    controlla(s == 403 and "non è ancora collegato" in e["errore"], "sconosciuto senza creazione automatica: rifiutato")
    dir_.chiama("/api/impostazioni", {"argo_nuovi": "1", "argo_ruolo_nuovi": "docente"})
    n1 = Client(base)
    s, _ = n1.chiama("/api/accesso", {"username": "nuovo.doc", "password": "giusta", "modo": "argo"})
    s2, io = n1.chiama("/api/io")
    controlla(s == 200 and io["utente"]["cognome"] == "Verdi" and io["utente"]["solo_argo"], "account creato da Argo")
    controlla(n1.chiama("/api/password", {"attuale": "x", "nuova": "abcdefghi"})[0] == 400, "niente cambio password per chi entra con Argo")
    s, ct = n1.chiama("/api/contatori")
    controlla(s == 200 and "non abilitato" in ct["segreteria"]["errore"],
              f"programma Personale non disponibile: si entra lo stesso e si vede il motivo ({ct['segreteria']['errore']})")
    controlla(Client(base).chiama("/api/accesso", {"username": "nuovo.doc", "password": "giusta"})[0] == 401,
              "chi entra con Argo non ha una password dello Sportello")
    s, n = seg.chiama("/api/notifiche")
    controlla(any("creato con Argo" in x["testo"] for x in n["elenco"]), "la segreteria riceve l'avviso del nuovo account")
    am = Client(base)
    s, _ = am.chiama("/api/accesso", {"username": "Anco.Marzio.SC99999", "password": "giusta", "modo": "argo"})
    io = am.chiama("/api/io")[1]["utente"] if s == 200 else {}
    controlla(io.get("nome") == "Anco" and io.get("cognome") == "Marzio" and io.get("ruolo") == "docente",
              f"nome.cognome.CODICE: account creato con nome e cognome dal nome utente ({io.get('nome')} {io.get('cognome')})")
    s, e = Client(base).chiama("/api/accesso", {"username": "tullo.ostilio.SC999990", "password": "giusta", "modo": "argo"})
    controlla(s == 403, "codice scuola nel nome utente diverso (SC999990): rifiutato")
    s, e = Client(base).chiama("/api/accesso", {"username": "altra.scuola", "password": "giusta", "modo": "argo"})
    controlla(s == 403 and "questa scuola" in e["errore"], "persona di un'altra scuola: rifiutata")
    s, e = Client(base).chiama("/api/accesso", {"username": "con.otp", "password": "giusta", "modo": "argo"})
    controlla(s == 401 and "OTP" in e["errore"], "account con OTP: messaggio chiaro")
    s, e = seg.chiama(f"/api/utenti/{conti['id']}", {"argo_utente": "giulia.r"})
    controlla(s == 400 and "già collegato" in e["errore"], "lo stesso utente Argo non va su due persone")
    s, _ = seg.chiama(f"/api/utenti/{conti['id']}", {"argo_utente": "stefano.argo"})
    sc = Client(base)
    s, _ = sc.chiama("/api/accesso", {"username": "STEFANO.ARGO", "password": "giusta", "modo": "argo"})
    controlla(s == 200 and sc.chiama("/api/io")[1]["utente"]["username"] == "s.conti", "collegamento dalla scheda (maiuscole ignorate)")
    controlla(not any(pw_ in open(os.path.join(tmp, "argo-campi.json"), encoding="utf-8").read() for pw_ in ("giusta", "Verdi")),
              "il file di diagnosi non contiene password né nomi")
    for _ in range(3):
        Client(base).chiama("/api/accesso", {"username": "bloccami", "password": "sbagliata", "modo": "argo"})
    s, e = Client(base).chiama("/api/accesso", {"username": "bloccami", "password": "sbagliata", "modo": "argo"})
    controlla(s == 429, "dopo 3 errori si aspetta (per non far bloccare l'account Argo)")
    controlla(finto.tentativi.get("bloccami") == 3, "ad Argo arrivano solo 3 tentativi")
    vuoto = tempfile.mkdtemp(prefix="sportello-vuoto-")
    vecchio, server.DATI = server.DATI, vuoto
    server.prepara_db()
    with server.db() as c0:
        c0.execute("UPDATE impostazioni SET valore='1' WHERE chiave IN ('argo_attivo','argo_nuovi')")
        c0.execute("UPDATE impostazioni SET valore='SC99999' WHERE chiave='argo_codice_scuola'")
        p1 = server.utente_da_argo(c0, "anco.marzio.SC99999", {})
        p2 = server.utente_da_argo(c0, "tullo.ostilio.sc99999", {})
    controlla(p1["ruolo"] == "dirigente" and p2["ruolo"] == "docente",
              "database vuoto: il primo che entra con Argo è amministratore, gli altri no")
    server.DATI = vecchio
    finto.shutdown()

    print("Calendario")
    controlla(server.pasqua(2027) == dt.date(2027, 3, 28), "Pasqua 2027")
    controlla(server.giorni_lavorativi(dt.date(2026, 12, 21), dt.date(2026, 12, 27), {"settimana_corta": "1"}) == 4,
              "settimana di Natale con settimana corta: 4 giorni (21-24)")
    srv.shutdown()
    print()
    print("TUTTO OK" if not ERRORI else f"{len(ERRORI)} PROBLEMI: " + "; ".join(ERRORI))
    sys.exit(1 if ERRORI else 0)


if __name__ == "__main__":
    main()
