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
