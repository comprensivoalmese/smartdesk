#!/usr/bin/env python3
"""Sportello Personale - richieste di assenza, bacheca, presenze e documenti
del personale scolastico. Usa solo la libreria standard di Python (3.10+).

Avvio:  python server.py [--porta 8850] [--host 127.0.0.1] [--demo]
"""
import argparse
import base64
import csv
import datetime as dt
import hashlib
import hmac
import io
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
import unicodedata
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

import argo

QUI = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(QUI, "static")
DATI = os.environ.get("SPORTELLO_DATI") or os.path.join(QUI, "dati")
MAX_CORPO = 25 * 1024 * 1024
DURATA_SESSIONE = 14 * 24 * 3600

RUOLI = {
    "docente": "Docente",
    "ata": "Personale ATA",
    "segreteria": "Segreteria del personale",
    "dsga": "DSGA",
    "dirigente": "Dirigente scolastico",
}
STAFF = {"segreteria", "dsga", "dirigente"}
ATTIVE = ("inviata", "verificata", "da_integrare")
CONCLUSE_OK = ("autorizzata", "registrata", "evasa")
# giorni già concessi: contano come usati anche mentre si aspetta la conferma dell'annullamento
USATE = CONCLUSE_OK + ("annullamento",)

STATI = {
    "inviata": "Inviata",
    "verificata": "Verificata",
    "da_integrare": "Da integrare",
    "autorizzata": "Autorizzata",
    "registrata": "Registrata",
    "evasa": "Evasa",
    "respinta": "Respinta",
    "annullata": "Annullata",
    "revocata": "Revocata",
    "annullamento": "Annullamento richiesto",
}

AZIONI = {
    "verifica": "Verifica (spettanza ok)",
    "integra": "Chiedi integrazione",
    "autorizza": "Autorizza",
    "respingi": "Respingi",
    "registra": "Registra",
    "evadi": "Segna come evasa",
    "revoca": "Revoca",
    "annulla": "Annulla la richiesta",
    "modifica": "Modifica e reinvia",
    "chiedi_annullamento": "Chiedi l'annullamento",
    "ritira_annullamento": "Ritira la richiesta di annullamento",
    "conferma_annullamento": "Conferma l'annullamento",
    "nega_annullamento": "Non annullare",
}
AZIONI_CON_NOTA = {"integra", "respingi", "revoca", "chiedi_annullamento", "nega_annullamento"}

# ---------------------------------------------------------------- tipologie
TIPOLOGIE = [
    dict(id="ferie", nome="Ferie", gruppo="Ferie e permessi", unita="giorni", preavviso=3,
         contatore="ferie", approva_dsga=True,
         descr="Giorni di ferie dell'anno scolastico (prima si usano i residui dell'anno precedente)."),
    dict(id="festivita", nome="Festività soppresse", gruppo="Ferie e permessi", unita="giorni",
         preavviso=3, max_anno=4, approva_dsga=True,
         descr="Quattro giornate all'anno, da usare entro l'anno scolastico."),
    dict(id="motivi_personali", nome="Permesso per motivi personali o familiari", gruppo="Ferie e permessi",
         unita="giorni", preavviso=1, max_anno=3, allegato="facoltativo",
         descr="Fino a 3 giorni all'anno, documentati anche con autocertificazione.",
         campi=[dict(id="documentazione", etichetta="Documentazione", tipo="select", obbligatorio=True,
                     opzioni=["Autocertificazione", "Documentazione allegata"])]),
    dict(id="permesso_breve", nome="Permesso breve (da recuperare)", gruppo="Ferie e permessi", unita="ore",
         preavviso=1, max_anno_ore={"docente": 18, "ata": 36}, max_ore_volta=3, approva_dsga=True,
         descr="Permesso di poche ore, da recuperare entro i due mesi successivi."),
    dict(id="recupero", nome="Recupero ore / riposo compensativo", gruppo="Ferie e permessi", unita="ore",
         per=["ata"], preavviso=1, approva_dsga=True,
         descr="Uso delle ore di straordinario accumulate."),
    dict(id="malattia", nome="Malattia", gruppo="Salute", unita="giorni", preavviso=0, comunicazione=True,
         passato=7, allegato="facoltativo",
         descr="Comunicazione dell'assenza: la segreteria la registra con il numero del certificato.",
         campi=[dict(id="tipo_malattia", etichetta="Tipo", tipo="select", obbligatorio=True,
                     opzioni=["Malattia ordinaria", "Ricovero ospedaliero", "Day hospital",
                              "Terapia salvavita", "Infortunio sul lavoro"]),
                dict(id="protocollo", etichetta="Numero di protocollo del certificato medico", tipo="text",
                     aiuto="Se non l'hai ancora, puoi scriverlo dopo nelle note.")]),
    dict(id="visita_oraria", nome="Assenza oraria per visita medica", gruppo="Salute", unita="ore",
         per=["ata"], preavviso=1, max_anno_ore={"ata": 18}, allegato="dopo", approva_dsga=True,
         descr="Per visite, terapie ed esami (attestazione da allegare anche dopo)."),
    dict(id="visita_giornata", nome="Visita medica o esami (giornata intera)", gruppo="Salute", unita="giorni",
         preavviso=1, allegato="dopo",
         descr="Assenza per l'intera giornata, con attestazione della struttura sanitaria."),
    dict(id="l104", nome="Permesso Legge 104/92", gruppo="Famiglia", unita="giorni", preavviso=3, max_mese=3,
         allegato="facoltativo",
         descr="Fino a 3 giorni al mese, possibilmente programmati a inizio mese.",
         campi=[dict(id="per_chi", etichetta="Il permesso è", tipo="select", obbligatorio=True,
                     opzioni=["Per me stesso", "Per assistenza a un familiare"]),
                dict(id="assistito", etichetta="Familiare assistito (nome e parentela)", tipo="text")]),
    dict(id="congedo_parentale", nome="Congedo parentale", gruppo="Famiglia", unita="giorni", preavviso=5,
         descr="Astensione facoltativa per i figli fino a 12 anni.",
         campi=[dict(id="figlio", etichetta="Nome del figlio o della figlia", tipo="text", obbligatorio=True),
                dict(id="nascita", etichetta="Data di nascita", tipo="date", obbligatorio=True),
                dict(id="indennita", etichetta="Trattamento", tipo="select", obbligatorio=True,
                     opzioni=["Indennità all'80%", "Indennità al 30%", "Senza retribuzione"])]),
    dict(id="malattia_figlio", nome="Malattia del figlio", gruppo="Famiglia", unita="giorni", preavviso=0,
         comunicazione=True, passato=7, allegato="dopo",
         descr="Con il certificato del pediatra o del medico.",
         campi=[dict(id="figlio", etichetta="Nome del figlio o della figlia", tipo="text", obbligatorio=True)]),
    dict(id="lutto", nome="Permesso per lutto", gruppo="Famiglia", unita="giorni", preavviso=0, passato=3,
         max_volta=3, allegato="facoltativo",
         descr="Fino a 3 giorni per evento (familiari entro il 2° grado, coniuge, convivente).",
         campi=[dict(id="parentela", etichetta="Parentela con la persona scomparsa", tipo="text",
                     obbligatorio=True)]),
    dict(id="matrimonio", nome="Congedo per matrimonio", gruppo="Famiglia", unita="giorni", preavviso=7,
         max_volta=15, descr="15 giorni consecutivi, a partire da una settimana prima fino a due mesi dopo."),
    dict(id="concorsi", nome="Concorsi o esami", gruppo="Altro", unita="giorni", preavviso=3, max_anno=8,
         allegato="dopo", descr="Fino a 8 giorni all'anno, compresi quelli di viaggio.",
         campi=[dict(id="prova", etichetta="Concorso o esame", tipo="text", obbligatorio=True)]),
    dict(id="formazione", nome="Formazione e aggiornamento", gruppo="Altro", unita="giorni", per=["docente"],
         preavviso=5, max_anno=5, descr="Fino a 5 giorni all'anno per iniziative riconosciute.",
         campi=[dict(id="corso", etichetta="Corso e ente organizzatore", tipo="text", obbligatorio=True)]),
    dict(id="generica", nome="Richiesta generica alla segreteria", gruppo="Altro", unita="nessuna",
         preavviso=0, allegato="facoltativo",
         descr="Certificati, dichiarazioni, cambio IBAN e altre pratiche.",
         campi=[dict(id="tipologia", etichetta="Tipo di richiesta", tipo="select", obbligatorio=True,
                     opzioni=["Certificato di servizio", "Dichiarazione dei servizi", "Ricostruzione di carriera",
                              "Modifica dati anagrafici o IBAN", "Accesso agli atti", "Altro"]),
                dict(id="oggetto", etichetta="Oggetto", tipo="text", obbligatorio=True)]),
]
TIPI = {t["id"]: t for t in TIPOLOGIE}
for _t in TIPOLOGIE:
    _t.setdefault("per", ["docente", "ata"])
    _t.setdefault("allegato", "no")
    _t.setdefault("campi", [])


class Errore(Exception):
    def __init__(self, messaggio, codice=400):
        super().__init__(messaggio)
        self.codice = codice


# ---------------------------------------------------------------- date e calendario
def oggi():
    return dt.date.today()


def adesso():
    return dt.datetime.now().replace(microsecond=0)


def data(s, nome="data"):
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        raise Errore(f"Manca o non è valida la {nome}.")


def ora_min(s, nome="ora"):
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", str(s or ""))
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise Errore(f"Manca o non è valida l'{nome}.")
    return int(m.group(1)) * 60 + int(m.group(2))


def pasqua(y):
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    mese = (h + l_ - 7 * m + 114) // 31
    giorno = (h + l_ - 7 * m + 114) % 31 + 1
    return dt.date(y, mese, giorno)


FESTE_FISSE = ["01-01", "01-06", "04-25", "05-01", "06-02", "08-15", "11-01", "12-08", "12-25", "12-26"]


def festivo(d, imp):
    if d.strftime("%m-%d") in FESTE_FISSE or d.strftime("%m-%d") == imp.get("patrono", ""):
        return True
    return d == pasqua(d.year) + dt.timedelta(days=1) or d == pasqua(d.year)


def lavorativo(d, imp):
    if d.weekday() == 6 or festivo(d, imp):
        return False
    if d.weekday() == 5 and imp.get("settimana_corta") == "1":
        return False
    return True


def giorni_lavorativi(dal, al, imp):
    n, d = 0, dal
    while d <= al:
        n += lavorativo(d, imp)
        d += dt.timedelta(days=1)
    return n


def inizio_anno(d=None):
    d = d or oggi()
    return dt.date(d.year if d.month >= 9 else d.year - 1, 9, 1)


def nome_anno(d=None):
    a = inizio_anno(d).year
    return f"{a}/{str(a + 1)[2:]}"


# ---------------------------------------------------------------- database
SCHEMA = """
CREATE TABLE IF NOT EXISTS utenti (
  id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, nome TEXT NOT NULL, cognome TEXT NOT NULL,
  ruolo TEXT NOT NULL, profilo TEXT DEFAULT '', plesso TEXT DEFAULT '', email TEXT DEFAULT '',
  hash TEXT NOT NULL, sale TEXT NOT NULL, cambia_password INTEGER DEFAULT 0,
  ferie_spettanti INTEGER DEFAULT 32, ferie_ap INTEGER DEFAULT 0, ore_giornaliere REAL DEFAULT 6,
  attivo INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS sessioni (token TEXT PRIMARY KEY, utente_id INTEGER NOT NULL, scade REAL NOT NULL);
CREATE TABLE IF NOT EXISTS richieste (
  id INTEGER PRIMARY KEY, utente_id INTEGER NOT NULL, tipo TEXT NOT NULL, dal TEXT, al TEXT,
  ora_da TEXT, ora_a TEXT, quantita REAL DEFAULT 0, campi TEXT DEFAULT '{}', note TEXT DEFAULT '',
  stato TEXT NOT NULL, creata TEXT NOT NULL, aggiornata TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS storico (
  id INTEGER PRIMARY KEY, richiesta_id INTEGER NOT NULL, quando TEXT NOT NULL, utente_id INTEGER,
  azione TEXT NOT NULL, nota TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS allegati (
  id TEXT PRIMARY KEY, proprietario TEXT NOT NULL, rif_id INTEGER NOT NULL, nome TEXT NOT NULL,
  mime TEXT NOT NULL, dimensione INTEGER NOT NULL, caricato TEXT NOT NULL, utente_id INTEGER);
CREATE TABLE IF NOT EXISTS circolari (
  id INTEGER PRIMARY KEY, numero INTEGER NOT NULL, anno TEXT NOT NULL, titolo TEXT NOT NULL, testo TEXT,
  destinatari TEXT NOT NULL, presa_visione INTEGER DEFAULT 1, adesione INTEGER DEFAULT 0,
  scadenza TEXT, data TEXT NOT NULL, autore_id INTEGER);
CREATE TABLE IF NOT EXISTS letture (
  circolare_id INTEGER NOT NULL, utente_id INTEGER NOT NULL, quando TEXT NOT NULL, risposta TEXT DEFAULT '',
  PRIMARY KEY (circolare_id, utente_id));
CREATE TABLE IF NOT EXISTS timbrature (
  id INTEGER PRIMARY KEY, utente_id INTEGER NOT NULL, quando TEXT NOT NULL, verso TEXT NOT NULL,
  fonte TEXT DEFAULT 'app', nota TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS documenti (
  id INTEGER PRIMARY KEY, utente_id INTEGER NOT NULL, tipo TEXT NOT NULL, titolo TEXT NOT NULL,
  periodo TEXT DEFAULT '', creato TEXT NOT NULL, letto TEXT);
CREATE TABLE IF NOT EXISTS notifiche (
  id INTEGER PRIMARY KEY, utente_id INTEGER NOT NULL, testo TEXT NOT NULL, link TEXT DEFAULT '',
  quando TEXT NOT NULL, letta INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS impostazioni (chiave TEXT PRIMARY KEY, valore TEXT);
CREATE TABLE IF NOT EXISTS assenze_argo (
  id INTEGER PRIMARY KEY, utente_id INTEGER NOT NULL, tipo TEXT DEFAULT '', inizio TEXT NOT NULL,
  fine TEXT NOT NULL, quantita REAL DEFAULT 0, stato TEXT NOT NULL, descrizione TEXT DEFAULT '',
  particolarita TEXT DEFAULT '', rif TEXT DEFAULT '');
CREATE INDEX IF NOT EXISTS i_ass_argo ON assenze_argo(utente_id, tipo);
CREATE INDEX IF NOT EXISTS i_rich_ut ON richieste(utente_id);
CREATE INDEX IF NOT EXISTS i_timb ON timbrature(utente_id, quando);
CREATE INDEX IF NOT EXISTS i_not ON notifiche(utente_id, letta);
"""

IMPOSTAZIONI_BASE = {
    "scuola": "Istituto Comprensivo",
    "settimana_corta": "0",
    "patrono": "",
    "timbrature_docenti": "0",
    "argo_attivo": "0",          # accesso con le credenziali Argo
    "argo_codice_scuola": "",    # es. SC15290: per creare account nuovi deve comparire nei dati Argo
    "argo_nuovi": "0",           # crea l'account al primo accesso Argo se non c'è
    "argo_ruolo_nuovi": "docente",
    "argo_bacheca": "1",         # importa il feed pubblico "La Segreteria Comunica" del codice scuola
    "argo_bacheca_ultima": "",   # ultima importazione riuscita
}


def db():
    c = sqlite3.connect(os.path.join(DATI, "sportello.db"), timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c


def prepara_db():
    os.makedirs(os.path.join(DATI, "allegati"), exist_ok=True)
    with db() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(SCHEMA)
        colonne = {r["name"] for r in c.execute("PRAGMA table_info(utenti)")}
        for col in ("argo_utente", "argo_letto", "argo_errore"):
            if col not in colonne:
                c.execute(f"ALTER TABLE utenti ADD COLUMN {col} TEXT DEFAULT ''")
        if "rif" not in {r["name"] for r in c.execute("PRAGMA table_info(assenze_argo)")}:
            c.execute("ALTER TABLE assenze_argo ADD COLUMN rif TEXT DEFAULT ''")
        colonne = {r["name"] for r in c.execute("PRAGMA table_info(circolari)")}
        for col in ("fonte", "chiave_esterna", "categoria", "link_esterni"):
            if col not in colonne:
                c.execute(f"ALTER TABLE circolari ADD COLUMN {col} TEXT DEFAULT ''")
        for k, v in IMPOSTAZIONI_BASE.items():
            c.execute("INSERT OR IGNORE INTO impostazioni VALUES (?,?)", (k, v))


def impostazioni(c):
    return {r["chiave"]: r["valore"] for r in c.execute("SELECT * FROM impostazioni")}


def hash_password(pw, sale=None):
    sale = sale or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(sale), 200_000).hex()
    return h, sale


def password_giusta(pw, u):
    if not u["hash"]:  # account che entra solo con Argo
        return False
    return hmac.compare_digest(hash_password(pw, u["sale"])[0], u["hash"])


def password_nuova():
    alfabeto = "abcdefghjkmnpqrstuvwxyz23456789"
    return "-".join("".join(secrets.choice(alfabeto) for _ in range(4)) for _ in range(3))


def categoria(u):
    return "docente" if u["ruolo"] in ("docente", "dirigente") else "ata"


def nome_completo(u):
    return f"{u['cognome']} {u['nome']}"


def notifica(c, utente_id, testo, link=""):
    c.execute("INSERT INTO notifiche (utente_id,testo,link,quando) VALUES (?,?,?,?)",
              (utente_id, testo, link, adesso().isoformat()))


def notifica_ruoli(c, ruoli, testo, link="", tranne=None):
    q = "SELECT id FROM utenti WHERE attivo=1 AND ruolo IN (%s)" % ",".join("?" * len(ruoli))
    for r in c.execute(q, list(ruoli)).fetchall():
        if r["id"] != tranne:
            notifica(c, r["id"], testo, link)


def utente_pubblico(u):
    return {k: u[k] for k in ("id", "username", "nome", "cognome", "ruolo", "profilo", "plesso", "email",
                              "ferie_spettanti", "ferie_ap", "ore_giornaliere", "attivo", "cambia_password",
                              "argo_utente")} | {
        "ruolo_nome": RUOLI.get(u["ruolo"], u["ruolo"]), "categoria": categoria(u),
        "solo_argo": not u["hash"]}


# ---------------------------------------------------------------- allegati
def salva_allegato(c, proprietario, rif_id, file, utente_id):
    nome = os.path.basename(str(file.get("nome") or "allegato"))[:120] or "allegato"
    try:
        dati = base64.b64decode(str(file.get("dati", "")).split(",")[-1], validate=False)
    except Exception:
        raise Errore("L'allegato non è leggibile.")
    if not dati:
        raise Errore(f"L'allegato «{nome}» è vuoto.")
    if len(dati) > 15 * 1024 * 1024:
        raise Errore(f"L'allegato «{nome}» supera 15 MB.")
    mime = str(file.get("mime") or mimetypes.guess_type(nome)[0] or "application/octet-stream")[:100]
    aid = uuid.uuid4().hex
    with open(os.path.join(DATI, "allegati", aid), "wb") as f:
        f.write(dati)
    c.execute("INSERT INTO allegati VALUES (?,?,?,?,?,?,?,?)",
              (aid, proprietario, rif_id, nome, mime, len(dati), adesso().isoformat(), utente_id))
    return aid


def elenco_allegati(c, proprietario, rif_id):
    return [dict(r) for r in c.execute(
        "SELECT id,nome,mime,dimensione,caricato FROM allegati WHERE proprietario=? AND rif_id=? ORDER BY caricato",
        (proprietario, rif_id))]


# ---------------------------------------------------------------- richieste
def utilizzo(c, utente_id, tipo, da, a, escludi=None):
    """Quantità (giorni o ore) usata e in attesa per un tipo, con dal in [da, a].
    Le assenze lette dal programma della segreteria (assenze_argo) valgono per prime; le richieste dello
    Sportello si aggiungono solo se lì non c'è già un'assenza o una richiesta negli stessi giorni."""
    righe = c.execute("SELECT stato, quantita, dal, al FROM richieste WHERE utente_id=? AND tipo=? AND dal>=?"
                      " AND dal<=? AND id IS NOT ?", (utente_id, tipo, da.isoformat(), a.isoformat(), escludi)).fetchall()
    esterne = c.execute("SELECT inizio, fine, quantita, stato FROM assenze_argo WHERE utente_id=? AND tipo=?"
                        " AND inizio>=? AND inizio<=?", (utente_id, tipo, da.isoformat(), a.isoformat())).fetchall()

    def gia_in_argo(r):
        return any(x["inizio"] <= (r["al"] or r["dal"]) and r["dal"] <= x["fine"] for x in esterne)

    usati = sum(x["quantita"] for x in esterne if x["stato"] == "registrata")
    attesa = sum(x["quantita"] for x in esterne if x["stato"] == "richiesta")
    usati += sum(r["quantita"] for r in righe if r["stato"] in USATE and not gia_in_argo(r))
    attesa += sum(r["quantita"] for r in righe if r["stato"] in ATTIVE and not gia_in_argo(r))
    return usati, attesa


# tipi di assenza del programma della segreteria -> tipologie dello Sportello
ARGO_PARTICOLARITA = {"MOTPERS": "motivi_personali", "FERIE": "ferie", "ORARIA": "permesso_breve",
                      "VISMEDORA": "visita_oraria", "ASSISTE104": "l104", "ASSREF104": "l104"}
ARGO_PAROLE = [("festivit", "festivita"), ("motivi personali", "motivi_personali"), ("ferie", "ferie"),
               ("permesso breve", "permesso_breve"), ("104", "l104"), ("lutto", "lutto"),
               ("matrimonio", "matrimonio"), ("concors", "concorsi"), ("congedo parentale", "congedo_parentale"),
               ("malattia del figlio", "malattia_figlio"), ("malattia figlio", "malattia_figlio"),
               ("malattia", "malattia"), ("visita", "visita_giornata")]
ARGO_IN_ATTESA = ("FWD", "DAU", "AUT", "DSG", "REF")  # inoltrata, da autorizzare, autorizzata, vistate
ARGO_CHIUSE = ("NUL", "NOF", "RIF", "ERR")  # annullata, annullata dopo la formalizzazione, rifiutata, errata


def tipo_da_argo(a):
    tipo = ARGO_PARTICOLARITA.get(a.get("particolarita") or "")
    if not tipo:
        testo = (a.get("descrizione") or "").lower()
        tipo = next((t for parola, t in ARGO_PAROLE if parola in testo), "")
    if tipo == "visita_giornata" and a.get("oraria"):
        tipo = "visita_oraria"
    if tipo and (TIPI[tipo]["unita"] == "ore") != bool(a.get("oraria")):
        return ""  # unità diversa (es. motivi personali a ore): non si mescola con i giorni
    return tipo


def salva_assenze_argo(c, utente_id, dati):
    """Salva le assenze e le richieste lette da Argo al momento dell'accesso."""
    if not isinstance(dati, dict):
        return
    if dati.get("errore"):
        c.execute("UPDATE utenti SET argo_errore=? WHERE id=?", (str(dati["errore"])[:300], utente_id))
        return
    imp = impostazioni(c)
    c.execute("DELETE FROM assenze_argo WHERE utente_id=?", (utente_id,))

    def rif_di(a):
        """La richiesta Argo che ha generato l'assenza, per poterla annullare come in Unica: prima quella con le
        stesse date, poi una dello stesso tipo che si sovrappone al periodo dell'assenza."""
        ini, fin = str(a["inizio"])[:10], str(a.get("fine") or a["inizio"])[:10]
        valide = [r for r in dati.get("richieste", []) if r.get("rif") and r.get("stato") not in ARGO_CHIUSE]
        uguali = [r for r in valide if str(r.get("inizio"))[:10] == ini and str(r.get("fine") or r["inizio"])[:10] == fin]
        sovrapposte = [r for r in valide if str(r.get("inizio"))[:10] <= fin and str(r.get("fine") or r["inizio"])[:10] >= ini
                       and ((r.get("codice") and r.get("codice") == a.get("codice"))
                            or (r.get("particolarita") and r.get("particolarita") == a.get("particolarita")))]
        r = (uguali or sovrapposte or [None])[0]
        return json.dumps(r["rif"] | {"stato": r.get("stato")}) if r else ""

    for a in dati.get("assenze", []):
        if not a.get("inizio"):
            continue
        q = a.get("ore") if a.get("oraria") else a.get("giorni")
        c.execute("INSERT INTO assenze_argo (utente_id,tipo,inizio,fine,quantita,stato,descrizione,particolarita,rif)"
                  " VALUES (?,?,?,?,?,?,?,?,?)", (utente_id, tipo_da_argo(a), a["inizio"], a.get("fine") or a["inizio"],
                                                  q or 0, "registrata", (a.get("descrizione") or "")[:200],
                                                  a.get("particolarita") or "", rif_di(a)))
    for r in dati.get("richieste", []):
        if r.get("stato") not in ARGO_IN_ATTESA or not r.get("inizio"):
            continue
        try:
            if r.get("oraria"):
                hh = [re.search(r"\d{1,2}:\d{2}", str(r.get(k) or "")) for k in ("ora_dal", "ora_al")]
                q = max(0, ora_min(hh[1] and hh[1].group()) - ora_min(hh[0] and hh[0].group())) / 60
            else:
                q = giorni_lavorativi(data(r["inizio"]), data(r.get("fine") or r["inizio"]), imp)
        except Errore:
            q = 0
        c.execute("INSERT INTO assenze_argo (utente_id,tipo,inizio,fine,quantita,stato,descrizione,particolarita,rif)"
                  " VALUES (?,?,?,?,?,?,?,?,?)", (utente_id, tipo_da_argo(r), r["inizio"], r.get("fine") or r["inizio"],
                                                  q, "richiesta", (r.get("descrizione") or "")[:200],
                                                  r.get("particolarita") or "",
                                                  json.dumps(r["rif"] | {"stato": r.get("stato")}) if r.get("rif") else ""))
    c.execute("UPDATE utenti SET argo_letto=?, argo_errore='' WHERE id=?",
              (adesso().isoformat(timespec="minutes"), utente_id))


def fine_anno(d):
    s = inizio_anno(d)
    return dt.date(s.year + 1, 8, 31)


def contatori(c, u, rif=None):
    rif = rif or oggi()
    da, a = inizio_anno(rif), fine_anno(rif)
    cat = categoria(u)
    out = []
    usati, attesa = utilizzo(c, u["id"], "ferie", da, a)
    tot = u["ferie_spettanti"] + u["ferie_ap"]
    out.append(dict(tipo="ferie", nome="Ferie", unita="giorni", totale=tot, usati=usati, attesa=attesa,
                    residuo=tot - usati - attesa,
                    dettaglio=f"{u['ferie_spettanti']} dell'anno + {u['ferie_ap']} residui dell'anno precedente"))
    for t in TIPOLOGIE:
        if cat not in t["per"]:
            continue
        if t.get("max_anno"):
            us, at = utilizzo(c, u["id"], t["id"], da, a)
            out.append(dict(tipo=t["id"], nome=t["nome"], unita="giorni", totale=t["max_anno"], usati=us,
                            attesa=at, residuo=t["max_anno"] - us - at, dettaglio="nell'anno scolastico"))
        if t.get("max_anno_ore") and cat in t["max_anno_ore"]:
            m = t["max_anno_ore"][cat]
            us, at = utilizzo(c, u["id"], t["id"], da, a)
            out.append(dict(tipo=t["id"], nome=t["nome"], unita="ore", totale=m, usati=us, attesa=at,
                            residuo=m - us - at, dettaglio="nell'anno scolastico"))
        if t.get("max_mese"):
            m0 = rif.replace(day=1)
            m1 = (m0 + dt.timedelta(days=32)).replace(day=1) - dt.timedelta(days=1)
            us, at = utilizzo(c, u["id"], t["id"], m0, m1)
            out.append(dict(tipo=t["id"], nome=t["nome"], unita="giorni", totale=t["max_mese"], usati=us,
                            attesa=at, residuo=t["max_mese"] - us - at, dettaglio="nel mese corrente"))
    return out


def valida_richiesta(c, u, corpo, escludi=None):
    """Controlla una richiesta. Restituisce i valori puliti oppure solleva Errore."""
    imp = impostazioni(c)
    t = TIPI.get(corpo.get("tipo"))
    if not t:
        raise Errore("Scegli il tipo di richiesta.")
    cat = categoria(u)
    if cat not in t["per"]:
        raise Errore("Questo tipo di richiesta non è previsto per il tuo profilo.")
    campi = {}
    for f in t["campi"]:
        v = str((corpo.get("campi") or {}).get(f["id"], "")).strip()[:300]
        if f.get("obbligatorio") and not v:
            raise Errore(f"Compila il campo «{f['etichetta']}».")
        if v and f["tipo"] == "select" and v not in f["opzioni"]:
            raise Errore(f"Valore non valido per «{f['etichetta']}».")
        if v and f["tipo"] == "date":
            data(v, f["etichetta"].lower())
        campi[f["id"]] = v
    note = str(corpo.get("note") or "").strip()[:2000]
    v = dict(tipo=t["id"], campi=campi, note=note, dal=None, al=None, ora_da=None, ora_a=None, quantita=0)
    if t["unita"] == "nessuna":
        return v, []
    dal = data(corpo.get("dal"), "data di inizio")
    if t["unita"] == "giorni":
        al = data(corpo.get("al") or corpo.get("dal"), "data di fine")
        if al < dal:
            raise Errore("La data di fine è prima di quella di inizio.")
        if (al - dal).days > 366:
            raise Errore("Il periodo è troppo lungo.")
        q = giorni_lavorativi(dal, al, imp)
        v.update(dal=dal.isoformat(), al=al.isoformat(), quantita=q)
    else:
        a_, b_ = ora_min(corpo.get("ora_da"), "ora di inizio"), ora_min(corpo.get("ora_a"), "ora di fine")
        if b_ <= a_:
            raise Errore("L'ora di fine deve essere dopo quella di inizio.")
        q = round((b_ - a_) / 60, 2)
        if t.get("max_ore_volta") and q > t["max_ore_volta"]:
            raise Errore(f"Al massimo {t['max_ore_volta']} ore per volta.")
        v.update(dal=dal.isoformat(), al=dal.isoformat(), ora_da=corpo["ora_da"], ora_a=corpo["ora_a"], quantita=q)
        al = dal
    avvisi = []
    # preavviso e date nel passato
    anticipo = (dal - oggi()).days
    if t.get("passato") is not None:
        if anticipo < -t["passato"]:
            raise Errore(f"Si può comunicare al massimo {t['passato']} giorni dopo l'inizio dell'assenza.")
    elif anticipo < t["preavviso"]:
        if anticipo < 0:
            raise Errore("Non si può chiedere un'assenza per una data passata.")
        raise Errore(f"Questa richiesta va inviata con almeno {t['preavviso']} "
                     f"giorn{'o' if t['preavviso'] == 1 else 'i'} di anticipo.")
    if t["unita"] == "giorni" and v["quantita"] == 0:
        raise Errore("Nel periodo scelto non ci sono giorni lavorativi.")
    if t["unita"] == "ore" and not lavorativo(dal, imp):
        raise Errore("Il giorno scelto non è lavorativo.")
    if t.get("max_volta") and v["quantita"] > t["max_volta"]:
        raise Errore(f"Al massimo {t['max_volta']} giorni per questa richiesta.")
    # limiti
    da, a = inizio_anno(dal), fine_anno(dal)
    if t["id"] == "ferie":
        us, at = utilizzo(c, u["id"], "ferie", da, a, escludi)
        resto = u["ferie_spettanti"] + u["ferie_ap"] - us - at
        if v["quantita"] > resto:
            raise Errore(f"Ti restano {fmt(resto)} giorni di ferie (compresi quelli già chiesti).")
    if t.get("max_anno"):
        us, at = utilizzo(c, u["id"], t["id"], da, a, escludi)
        if us + at + v["quantita"] > t["max_anno"]:
            raise Errore(f"Limite di {t['max_anno']} giorni all'anno: ne restano {fmt(t['max_anno'] - us - at)}.")
    if t.get("max_anno_ore") and cat in t["max_anno_ore"]:
        m = t["max_anno_ore"][cat]
        us, at = utilizzo(c, u["id"], t["id"], da, a, escludi)
        if us + at + v["quantita"] > m:
            raise Errore(f"Limite di {m} ore all'anno: ne restano {fmt(m - us - at)}.")
    if t.get("max_mese"):
        m0 = dal.replace(day=1)
        m1 = (m0 + dt.timedelta(days=32)).replace(day=1) - dt.timedelta(days=1)
        if al > m1:
            raise Errore("Chiedi i giorni di ciascun mese con richieste separate.")
        us, at = utilizzo(c, u["id"], t["id"], m0, m1, escludi)
        if us + at + v["quantita"] > t["max_mese"]:
            raise Errore(f"Limite di {t['max_mese']} giorni al mese: ne restano {fmt(t['max_mese'] - us - at)}.")
    # sovrapposizioni
    for r in c.execute("SELECT * FROM richieste WHERE utente_id=? AND dal IS NOT NULL AND dal<=? AND al>=? "
                       "AND id IS NOT ? AND stato IN ('inviata','verificata','da_integrare','autorizzata','registrata',"
                       "'annullamento')",
                       (u["id"], v["al"], v["dal"], escludi)):
        if t["unita"] == "ore" and r["ora_da"]:
            if ora_min(r["ora_da"]) < ora_min(v["ora_a"]) and ora_min(r["ora_a"]) > ora_min(v["ora_da"]):
                raise Errore(f"Si sovrappone alla richiesta n. {r['id']} ({TIPI[r['tipo']]['nome']}).")
            continue
        raise Errore(f"Si sovrappone alla richiesta n. {r['id']} ({TIPI[r['tipo']]['nome']}, "
                     f"{it_data(r['dal'])}{' - ' + it_data(r['al']) if r['al'] != r['dal'] else ''}).")
    if t["allegato"] == "dopo":
        avvisi.append("Ricordati di allegare l'attestazione (anche dopo l'invio).")
    return v, avvisi


def fmt(n):
    return str(int(n)) if float(n).is_integer() else f"{n:.1f}".replace(".", ",")


def it_data(s):
    return dt.date.fromisoformat(s).strftime("%d/%m/%Y") if s else ""


def puo_autorizzare(u, r, richiedente):
    t = TIPI[r["tipo"]]
    if u["ruolo"] == "dirigente":
        return True
    return u["ruolo"] == "dsga" and t.get("approva_dsga") and categoria(richiedente) == "ata"


def azioni_possibili(u, r, richiedente):
    t = TIPI[r["tipo"]]
    s = r["stato"]
    mia = r["utente_id"] == u["id"]
    az = []
    if '"origine": "segreteria"' in (r["campi"] or ""):
        # assenza del programma della segreteria: l'annullamento si manda ad Argo (come Unica), non si gestisce qui
        return az
    if mia and s in ATTIVE:
        az.append("annulla")
    if mia and s == "da_integrare":
        az.append("modifica")
    if mia and s in ("autorizzata", "registrata") and t["unita"] != "nessuna":
        az.append("chiedi_annullamento")
    if mia and s == "annullamento":
        az.append("ritira_annullamento")
    if u["ruolo"] in STAFF and (not mia or u["ruolo"] == "dirigente"):
        if s == "annullamento":
            az += ["conferma_annullamento", "nega_annullamento"]
        elif t.get("comunicazione"):
            if s == "inviata":
                az += ["registra", "integra"]
        elif t["id"] == "generica":
            if s == "inviata":
                az += ["evadi", "integra", "respingi"]
        else:
            aut = puo_autorizzare(u, r, richiedente)
            if s == "inviata":
                az += ["verifica", "integra"]
            if s in ("inviata", "verificata") and aut:
                az += ["autorizza", "respingi"]
            if s == "verificata" and "integra" not in az:
                az.append("integra")
            if s == "autorizzata" and aut and r["dal"] and r["dal"] >= oggi().isoformat():
                az.append("revoca")
    return az


def richiesta_pubblica(c, r, u, dettaglio=False):
    rich = c.execute("SELECT * FROM utenti WHERE id=?", (r["utente_id"],)).fetchone()
    t = TIPI[r["tipo"]]
    d = dict(r)
    d["campi"] = json.loads(r["campi"] or "{}")
    d["tipo_nome"] = t["nome"]
    d["unita"] = t["unita"]
    d["stato_nome"] = STATI.get(r["stato"], r["stato"])
    d["richiedente"] = nome_completo(rich)
    d["richiedente_ruolo"] = RUOLI.get(rich["ruolo"])
    d["azioni"] = [{"id": a, "nome": AZIONI[a], "nota": a in AZIONI_CON_NOTA} for a in azioni_possibili(u, r, rich)]
    d["n_allegati"] = c.execute("SELECT COUNT(*) FROM allegati WHERE proprietario='richiesta' AND rif_id=?",
                                (r["id"],)).fetchone()[0]
    if dettaglio:
        d["allegati"] = elenco_allegati(c, "richiesta", r["id"])
        d["storico"] = [dict(s) | {"chi": nome_completo(s) if s["cognome"] else ""} for s in c.execute(
            "SELECT s.*, u.nome, u.cognome FROM storico s LEFT JOIN utenti u ON u.id=s.utente_id "
            "WHERE richiesta_id=? ORDER BY s.id", (r["id"],))]
        d["tipologia"] = t
        d["allegato_richiesto"] = t["allegato"]
    return d


def leggi_richiesta(c, u, rid):
    r = c.execute("SELECT * FROM richieste WHERE id=?", (rid,)).fetchone()
    if not r or (r["utente_id"] != u["id"] and u["ruolo"] not in STAFF):
        raise Errore("Richiesta non trovata.", 404)
    return r


# ---------------------------------------------------------------- presenze
def cartellino(c, u, anno, mese):
    imp = impostazioni(c)
    m0 = dt.date(anno, mese, 1)
    m1 = (m0 + dt.timedelta(days=32)).replace(day=1)
    timb = c.execute("SELECT * FROM timbrature WHERE utente_id=? AND quando>=? AND quando<? ORDER BY quando",
                     (u["id"], m0.isoformat(), m1.isoformat())).fetchall()
    assenze = c.execute("SELECT * FROM richieste WHERE utente_id=? AND dal<? AND al>=? AND stato IN "
                        "('autorizzata','registrata','inviata','verificata','annullamento')",
                        (u["id"], m1.isoformat(), m0.isoformat())).fetchall()
    giorni, tot_lav, tot_teo = [], 0.0, 0.0
    d = m0
    while d < m1:
        iso = d.isoformat()
        tt = [dict(t) for t in timb if t["quando"][:10] == iso]
        lavorato, aperta = 0.0, None
        for t in tt:
            ora = dt.datetime.fromisoformat(t["quando"])
            if t["verso"] == "E":
                aperta = ora
            elif aperta:
                lavorato += (ora - aperta).total_seconds() / 3600
                aperta = None
        ass = [a for a in assenze if a["dal"] <= iso <= a["al"]]
        ass_giorno = [a for a in ass if TIPI[a["tipo"]]["unita"] == "giorni"]
        ass_ore = sum(a["quantita"] for a in ass if TIPI[a["tipo"]]["unita"] == "ore"
                      and a["stato"] in USATE)
        lav = lavorativo(d, imp)
        teorico = u["ore_giornaliere"] if lav and not ass_giorno else 0
        passato = d < oggi() or (d == oggi() and lavorato > 0)
        saldo = round(lavorato + ass_ore - teorico, 2) if passato and lav and not ass_giorno else None
        if passato:
            tot_lav += lavorato
            tot_teo += teorico
        giorni.append(dict(data=iso, lavorativo=lav, timbrature=tt, ore=round(lavorato, 2), teorico=teorico,
                           saldo=saldo, aperta=aperta is not None,
                           assenze=[{"id": a["id"], "tipo": TIPI[a["tipo"]]["nome"], "stato": a["stato"],
                                     "ore": a["ora_da"] and f"{a['ora_da']}-{a['ora_a']}"} for a in ass]))
        d += dt.timedelta(days=1)
    saldo_tot = round(sum(g["saldo"] or 0 for g in giorni), 2)
    return dict(utente=utente_pubblico(u), anno=anno, mese=mese, giorni=giorni, ore=round(tot_lav, 2),
                teorico=round(tot_teo, 2), saldo=saldo_tot)


def timbrature_abilitate(c, u):
    return categoria(u) == "ata" or impostazioni(c).get("timbrature_docenti") == "1"


# ---------------------------------------------------------------- circolari
FEED_ARGO = "https://sgd2awp.portaleargo.it/sgd2awp/all/{codice}"


def importa_bacheca_argo(c, scarica=None):
    """Copia nella bacheca le pubblicazioni del feed pubblico Argo dell'anno scolastico in corso.
    Restituisce il numero di pubblicazioni nuove."""
    imp = impostazioni(c)
    codice = imp.get("argo_codice_scuola", "").strip().upper()
    if imp.get("argo_bacheca") != "1" or not re.fullmatch(r"SC\d+", codice):
        return 0
    if scarica is None:
        def scarica(url):
            req = urllib.request.Request(url, headers={"User-Agent": "SportelloPersonale/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
    dati = scarica(FEED_ARGO.format(codice=codice))
    categorie = {x["key"]: x["descrizione"] for x in dati.get("categorie", [])}
    da = dt.datetime.combine(inizio_anno(), dt.time())
    presenti = {r["chiave_esterna"]: r for r in c.execute("SELECT * FROM circolari WHERE fonte='argo'")}
    prima_volta = not presenti
    visti, nuove = set(), 0
    for v in dati.get("items", []):
        quando = dt.datetime.fromtimestamp(v["lastModifiedAt"] / 1000).replace(microsecond=0)
        if quando < da or not v.get("key"):
            continue
        visti.add(v["key"])
        nomi = {f["filename"] for f in v.get("files", [])}
        link = [{"nome": f["filename"], "url": f["url"]} for f in v.get("files", [])
                if not f["filename"].startswith("sigillo_") and not (
                    f["filename"].lower().endswith(".docx") and (f["filename"][:-5] + ".pdf") in nomi)
                and str(f.get("url", "")).startswith("https://")]
        cat = ", ".join(categorie.get(k, "") for k in v.get("categorie", []) if categorie.get(k))
        testo = v.get("descrizione") if v.get("descrizione") and v.get("descrizione") != v.get("titolo") else ""
        valori = (v.get("titolo", "")[:200], testo, cat, json.dumps(link, ensure_ascii=False), quando.isoformat())
        if v["key"] in presenti:
            r = presenti[v["key"]]
            if (r["titolo"], r["testo"], r["categoria"], r["link_esterni"], r["data"]) != valori:
                c.execute("UPDATE circolari SET titolo=?, testo=?, categoria=?, link_esterni=?, data=? WHERE id=?",
                          valori + (r["id"],))
            continue
        cur = c.execute("INSERT INTO circolari (numero,anno,titolo,testo,destinatari,presa_visione,adesione,scadenza,"
                        "data,autore_id,fonte,chiave_esterna,categoria,link_esterni) VALUES "
                        "(0,?,?,?,'tutti',0,0,NULL,?,NULL,'argo',?,?,?)",
                        (nome_anno(), valori[0], testo, quando.isoformat(), v["key"], cat, valori[3]))
        nuove += 1
        if not prima_volta:
            for x in c.execute("SELECT id FROM utenti WHERE attivo=1").fetchall():
                notifica(c, x["id"], f"Nuova in bacheca (Argo): {valori[0]}", f"#/circolare/{cur.lastrowid}")
    for chiave, r in presenti.items():
        if chiave not in visti and r["data"] >= da.isoformat():
            c.execute("DELETE FROM letture WHERE circolare_id=?", (r["id"],))
            c.execute("DELETE FROM circolari WHERE id=?", (r["id"],))
    c.execute("UPDATE impostazioni SET valore=? WHERE chiave='argo_bacheca_ultima'", (adesso().isoformat(),))
    return nuove


def ciclo_bacheca_argo():
    while True:
        try:
            with db() as c:
                n = importa_bacheca_argo(c)
            if n:
                print(f"Bacheca Argo: {n} pubblicazioni nuove")
        except Exception as e:  # noqa: BLE001 - la rete può mancare: si riprova al giro dopo
            print(f"Bacheca Argo non aggiornata ({e.__class__.__name__})")
        time.sleep(30 * 60)


def circolare_visibile(u, ci):
    return u["ruolo"] in STAFF or ci["destinatari"] == "tutti" or \
        (ci["destinatari"] == "docenti" and categoria(u) == "docente") or \
        (ci["destinatari"] == "ata" and categoria(u) == "ata")


def destinatari_circolare(c, ci):
    cond = {"tutti": "1=1", "docenti": "ruolo IN ('docente','dirigente')",
            "ata": "ruolo IN ('ata','segreteria','dsga')"}[ci["destinatari"]]
    return c.execute(f"SELECT * FROM utenti WHERE attivo=1 AND {cond} ORDER BY cognome, nome").fetchall()


# ---------------------------------------------------------------- PDF minimo (per i dati di prova)
def pdf_semplice(righe):
    def esc(s):
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    corpo = "BT /F1 12 Tf 60 780 Td 18 TL " + " ".join(f"({esc(r)}) Tj T*" for r in righe) + " ET"
    stream = corpo.encode("cp1252", "replace")
    oggetti = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
               b"/Resources << /Font << /F1 5 0 R >> >> >>",
               b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    pos = []
    for i, o in enumerate(oggetti, 1):
        pos.append(out.tell())
        out.write(b"%d 0 obj\n" % i + o + b"\nendobj\n")
    x = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(oggetti) + 1))
    for p in pos:
        out.write(b"%010d 00000 n \n" % p)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(oggetti) + 1, x))
    return out.getvalue()


# ---------------------------------------------------------------- API
ROTTE = []


def rotta(metodo, schema, ruoli=None, pubblica=False):
    def dec(f):
        ROTTE.append((metodo, re.compile("^" + schema + "$"), f, ruoli, pubblica))
        return f
    return dec


class Risposta:
    def __init__(self, corpo, tipo="application/json; charset=utf-8", codice=200, intestazioni=None):
        self.corpo, self.tipo, self.codice, self.intestazioni = corpo, tipo, codice, intestazioni or {}


def file_da_scaricare(dati, nome, mime, inline=True):
    disp = ("inline" if inline else "attachment") + f"; filename*=UTF-8''{quote(nome)}"
    return Risposta(dati, mime, intestazioni={"Content-Disposition": disp})


def csv_risposta(nome, intestazione, righe):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(intestazione)
    w.writerows(righe)
    return file_da_scaricare(("﻿" + buf.getvalue()).encode("utf-8"), nome, "text/csv; charset=utf-8", False)


TENTATIVI = {}
TENTATIVI_ARGO = {}


def norma(testo):
    testo = unicodedata.normalize("NFD", testo or "")
    testo = "".join(ch for ch in testo if unicodedata.category(ch) != "Mn").upper()
    return re.sub(r"[^A-Z]", "", testo)


def utente_da_argo(c, digitato, claims):
    """Trova (o crea) l'utente dello Sportello che corrisponde all'identità Argo."""
    imp = impostazioni(c)
    idn = argo.identita(claims, digitato)
    chiavi = {digitato.lower(), idn["username"]}
    for x in c.execute("SELECT * FROM utenti WHERE argo_utente<>''").fetchall():
        if x["argo_utente"].lower() in chiavi:
            if not x["attivo"]:
                raise Errore("Il tuo account di SmartDesk è disattivato: chiedi alla segreteria.", 403)
            if x["cognome"] == "(da completare)" and idn["cognome"]:
                c.execute("UPDATE utenti SET nome=?, cognome=? WHERE id=?", (idn["nome"] or x["nome"], idn["cognome"], x["id"]))
            return c.execute("SELECT * FROM utenti WHERE id=?", (x["id"],)).fetchone()
    if idn["nome"] and idn["cognome"]:
        cand = [x for x in c.execute("SELECT * FROM utenti WHERE attivo=1 AND (argo_utente='' OR argo_utente IS NULL)")
                if norma(x["cognome"]) == norma(idn["cognome"]) and norma(x["nome"]) == norma(idn["nome"])]
        if len(cand) == 1:
            c.execute("UPDATE utenti SET argo_utente=? WHERE id=?", (digitato.lower(), cand[0]["id"]))
            return c.execute("SELECT * FROM utenti WHERE id=?", (cand[0]["id"],)).fetchone()
    if imp.get("argo_nuovi") != "1":
        raise Errore("Le credenziali Argo sono giuste, ma il tuo account non è ancora collegato a SmartDesk: "
                     "chiedi alla segreteria di inserire il tuo nome utente Argo nella tua scheda.", 403)
    codice = imp.get("argo_codice_scuola", "").strip().upper()
    if idn["codice_da_utente"]:
        della_scuola = idn["codice_da_utente"] == codice
    else:
        della_scuola = bool(codice) and any(codice in t for t in idn["testi"])
    if not codice or not della_scuola:
        raise Errore("Non risulti tra il personale di questa scuola: chiedi alla segreteria di collegare il tuo "
                     "account Argo.", 403)
    primo = not c.execute("SELECT 1 FROM utenti WHERE ruolo IN ('segreteria','dsga','dirigente') AND attivo=1").fetchone()
    base = re.sub(r"[^a-z0-9._-]", "", digitato.lower())[:36] or "utente"
    username, i = base, 1
    while c.execute("SELECT 1 FROM utenti WHERE username=?", (username,)).fetchone():
        i += 1
        username = f"{base}-{i}"
    ruolo = imp.get("argo_ruolo_nuovi") if imp.get("argo_ruolo_nuovi") in ("docente", "ata") else "docente"
    if primo:  # nessun amministratore ancora: il primo che entra con Argo gestisce lo Sportello
        ruolo = "dirigente"
    nome, cognome = idn["nome"] or digitato, idn["cognome"] or "(da completare)"
    cur = c.execute("INSERT INTO utenti (username,nome,cognome,ruolo,profilo,hash,sale,ore_giornaliere,argo_utente) "
                    "VALUES (?,?,?,?,?,?,?,?,?)", (username, nome, cognome, ruolo, "", "", "",
                                                   0 if ruolo == "docente" else 6, digitato.lower()))
    notifica_ruoli(c, ["segreteria", "dsga", "dirigente"],
                   f"Nuovo account creato con Argo: {cognome} {nome} – controlla ruolo e ferie in Personale",
                   "#/gestione/personale")
    return c.execute("SELECT * FROM utenti WHERE id=?", (cur.lastrowid,)).fetchone()


SESSIONI_DIDUP = {}  # token SmartDesk -> sessione DidUP (solo in memoria: al riavvio si rientra con Argo)
SESSIONI_DIDUP_ERRORE = {}
SESSIONI_PERSONALE = {}  # token SmartDesk -> sessione del programma Personale (per gli annullamenti)


def nuova_sessione(c, user, didup=None, didup_errore="", personale=None):
    tok = secrets.token_urlsafe(32)
    if personale:
        SESSIONI_PERSONALE[tok] = dict(personale, utente_id=user["id"])
    if didup:
        SESSIONI_DIDUP[tok] = dict(didup, utente_id=user["id"])
    elif didup_errore:
        SESSIONI_DIDUP_ERRORE[tok] = didup_errore
    c.execute("DELETE FROM sessioni WHERE scade<?", (time.time(),))
    c.execute("INSERT INTO sessioni VALUES (?,?,?)", (tok, user["id"], time.time() + DURATA_SESSIONE))
    r = Risposta(json.dumps({"ok": True}).encode())
    r.intestazioni["Set-Cookie"] = (f"sp_sessione={tok}; Path=/; HttpOnly; SameSite=Lax; "
                                    f"Max-Age={DURATA_SESSIONE}")
    return r


@rotta("GET", "/api/accesso-info", pubblica=True)
def api_accesso_info(c, u, m, corpo, q, req):
    imp = impostazioni(c)
    return {"scuola": imp["scuola"], "argo": imp.get("argo_attivo") == "1"}


@rotta("POST", "/api/accesso", pubblica=True)
def api_accesso(c, u, m, corpo, q, req):
    ip = req.client_address[0]
    n, t0 = TENTATIVI.get(ip, (0, 0))
    if n >= 5 and time.time() - t0 < 60:
        raise Errore("Troppi tentativi: riprova tra un minuto.", 429)
    nome_ut = str(corpo.get("username", "")).strip()
    pw = str(corpo.get("password", ""))
    if corpo.get("modo") == "argo":
        if impostazioni(c).get("argo_attivo") != "1":
            raise Errore("L'accesso con Argo non è attivo.", 403)
        if not nome_ut or not pw:
            raise Errore("Scrivi nome utente e password di Argo.")
        chiave = nome_ut.lower()
        na, ta = TENTATIVI_ARGO.get(chiave, (0, 0))
        if na >= 3 and time.time() - ta < 900:
            raise Errore("Tre tentativi non riusciti: aspetta 15 minuti, così Argo non blocca il tuo account.", 429)
        try:
            claims, personale = argo.accedi(nome_ut, pw, assenze=True)
        except argo.ErroreArgo as e:
            if "non corretti" in str(e):
                TENTATIVI_ARGO[chiave] = (na + 1 if time.time() - ta < 900 else 1, time.time())
                TENTATIVI[ip] = (n + 1 if time.time() - t0 < 600 else 1, time.time())
            raise Errore(str(e), 401)
        TENTATIVI_ARGO.pop(chiave, None)
        try:
            with open(os.path.join(DATI, "argo-campi.json"), "w", encoding="utf-8") as f:
                json.dump(argo.descrivi_claims(claims), f, indent=1)  # solo i nomi dei campi, per diagnosi
        except OSError:
            pass
        user = utente_da_argo(c, nome_ut, claims)
        salva_assenze_argo(c, user["id"], personale)
        try:  # per diagnosi: solo esito e quantità, nessun dato personale
            with open(os.path.join(DATI, "argo-personale.json"), "w", encoding="utf-8") as f:
                json.dump({"quando": adesso().isoformat(), "errore": personale.get("errore", ""),
                           "assenze": len(personale.get("assenze", [])),
                           "richieste": len(personale.get("richieste", [])),
                           "periodi_richieste": [[str(r.get("inizio"))[:10], str(r.get("fine"))[:10], r.get("stato"),
                                                  bool(r.get("rif"))] for r in personale.get("richieste", [])],
                           "periodi_assenze": [[str(x.get("inizio"))[:10], str(x.get("fine"))[:10]]
                                               for x in personale.get("assenze", [])]}, f, indent=1)
        except OSError:
            pass
        return nuova_sessione(c, user, personale.get("didup"), personale.get("didup_errore", ""),
                              personale.get("sessione"))
    user = c.execute("SELECT * FROM utenti WHERE username=? AND attivo=1", (nome_ut.lower(),)).fetchone()
    if not user or not password_giusta(pw, user):
        TENTATIVI[ip] = (n + 1 if time.time() - t0 < 600 else 1, time.time())
        raise Errore("Nome utente o password non corretti." + (
            " Se di solito entri con Argo, scegli «Credenziali Argo»." if user and not user["hash"] else ""), 401)
    TENTATIVI.pop(ip, None)
    return nuova_sessione(c, user)


@rotta("POST", "/api/esci")
def api_esci(c, u, m, corpo, q, req):
    c.execute("DELETE FROM sessioni WHERE token=?", (req.token,))
    SESSIONI_DIDUP.pop(req.token, None)
    SESSIONI_DIDUP_ERRORE.pop(req.token, None)
    SESSIONI_PERSONALE.pop(req.token, None)
    r = Risposta(b'{"ok":true}')
    r.intestazioni["Set-Cookie"] = "sp_sessione=; Path=/; Max-Age=0"
    return r


# ---------------------------------------------------------------- bacheca DidUP: presa visione e adesione
ADESIONI = {"A": "Aderisco", "N": "Non aderisco", "X": "Non ho ancora deciso"}


def sessione_didup(req, u):
    """La sessione DidUP aperta all'accesso con Argo, se c'è ed è ancora valida."""
    s = SESSIONI_DIDUP.get(req.token)
    if not s or s["utente_id"] != u["id"]:
        motivo = SESSIONI_DIDUP_ERRORE.get(req.token)
        raise Errore(("DidUP non disponibile: " + motivo) if motivo else
                     "Per confermare le circolari di DidUP entra con le credenziali Argo.", 409)
    if s.get("scade") and time.time() > s["scade"] - 30:
        SESSIONI_DIDUP.pop(req.token, None)
        raise Errore("La sessione Argo è scaduta: esci e rientra con le credenziali Argo.", 409)
    return s


def chiave_didup(pk):
    """I codici dei messaggi DidUP sono lunghe stringhe esadecimali (non numeri): li usiamo come testo."""
    k = str(pk)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,300}", k):
        raise Errore("Messaggio non trovato.", 404)
    return k


def cartella_didup(utente_id, pk):
    # cartella corta: con il codice DidUP intero (~190 caratteri) Windows supera i 260 caratteri di percorso
    breve = hashlib.sha1(chiave_didup(pk).encode()).hexdigest()[:16]
    return os.path.join(DATI, "didup-allegati", str(int(utente_id)), breve)


def nome_file_breve(nome, massimo=90):
    nome = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", os.path.basename(nome)).strip(" .") or "allegato"
    base, est = os.path.splitext(nome)
    est = est[:10]
    return (base[:max(1, massimo - len(est))].rstrip(" .") or "allegato") + est


def allegati_didup(utente_id, pk):
    d = cartella_didup(utente_id, pk)
    nomi = sorted(os.listdir(d)) if os.path.isdir(d) else []
    return [{"nome": n, "url": f"/api/didup/allegato/{chiave_didup(pk)}/{i}"} for i, n in enumerate(nomi)]


def data_iso(v):
    """Data in formato AAAA-MM-GG da '2026-11-20...' o '20/11/2026'."""
    v = str(v or "")
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", v)
    if m:
        return m.group(0)
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", v)
    return f"{m[3]}-{int(m[2]):02d}-{int(m[1]):02d}" if m else ""


def messaggio_didup(x, utente_id):
    ad_rich = any(x.get(k) for k in ("richiestaAd", "docentiAd", "personaleAtaAd", "docentiSingoliAd", "docentiAtaSingoliAd"))
    testo = (x.get("desMessaggio") or x.get("desOggetto") or "").strip()
    return {
        "pk": x.get("pk"), "titolo": testo.split("\n")[0][:200] or "Messaggio", "testo": testo[:4000],
        "categoria": x.get("desCategoria") or "", "data": data_iso(x.get("datGiorno") or x.get("datPubblicazione")),
        "mittente": x.get("desMittente") or "", "n_allegati": x.get("numAllegati") or 0,
        "pv_richiesta": bool(x.get("docentiPv")), "pv_fatta": bool(x.get("docentiPvConfermata")),
        "pv_quando": x.get("dataConfermaPv") or "",
        "ad_richiesta": ad_rich, "ad_fatta": bool(x.get("docentiAdConfermata")),
        "adesione": x.get("flgAdesione") if x.get("docentiAdConfermata") else "",
        "ad_quando": x.get("dataConfermaAd") or "", "ad_scadenza": data_iso(x.get("datScadenzaAdesione")),
        "ad_modificabile": x.get("adesioneModificabile", True) is not False,
        "scaricati": allegati_didup(utente_id, x["pk"]) if x.get("pk") is not None else [],
    }


@rotta("GET", "/api/didup/bacheca")
def api_didup_bacheca(c, u, m, corpo, q, req):
    try:
        s = sessione_didup(req, u)
        elenco = argo.bacheca_didup(s)
    except Errore as e:
        return {"collegata": False, "motivo": str(e)}
    except argo.ErroreArgo as e:
        if "scaduta" in str(e):
            SESSIONI_DIDUP.pop(req.token, None)
        return {"collegata": False, "motivo": str(e)}
    s["ultimo_elenco"] = {str(x.get("pk")): x for x in elenco if x.get("pk") is not None}
    msg = [messaggio_didup(x, u["id"]) for x in elenco if x.get("pk") is not None]
    da_fare = [x for x in msg if (x["pv_richiesta"] and not x["pv_fatta"]) or (x["ad_richiesta"] and not x["ad_fatta"])]
    altri = sorted([x for x in msg if x not in da_fare], key=lambda x: x["data"], reverse=True)
    da_fare.sort(key=lambda x: x["data"], reverse=True)
    return {"collegata": True, "messaggi": da_fare + altri, "da_fare": len(da_fare), "adesioni": ADESIONI}


@rotta("POST", r"/api/didup/bacheca/([A-Za-z0-9_-]+)/conferma")
def api_didup_conferma(c, u, m, corpo, q, req):
    s = sessione_didup(req, u)
    pk = chiave_didup(m.group(1))
    x = (s.get("ultimo_elenco") or {}).get(pk)
    try:
        if x is None:
            x = next((y for y in argo.bacheca_didup(s) if str(y.get("pk")) == pk), None)
        if x is None:
            raise Errore("Messaggio non trovato nella bacheca DidUP.", 404)
        adesione = corpo.get("adesione") or None
        info = messaggio_didup(x, u["id"])
        if adesione is not None:
            if adesione not in ADESIONI:
                raise Errore("Scegli una risposta di adesione.")
            if not info["ad_richiesta"]:
                raise Errore("Questo messaggio non chiede un'adesione.")
            if info["ad_fatta"] and not info["ad_modificabile"]:
                raise Errore("L'adesione a questo messaggio non è più modificabile.")
        elif not info["pv_richiesta"]:
            raise Errore("Questo messaggio non chiede la presa visione.")
        file = argo.conferma_didup(s, x, adesione)
    except argo.ErroreArgo as e:
        if "scaduta" in str(e):
            SESSIONI_DIDUP.pop(req.token, None)
        raise Errore(str(e), 502)
    # la conferma su DidUP è già fatta: se la copia locale non si salva non è un errore per l'utente
    try:
        d = cartella_didup(u["id"], pk)
        os.makedirs(d, exist_ok=True)
        for nome, dati in file:
            with open(os.path.join(d, nome_file_breve(nome)), "wb") as f:
                f.write(dati)
    except OSError as e:
        print("Copia locale dell'allegato DidUP non salvata:", e, file=sys.stderr)
    if adesione is None:
        x["docentiPvConfermata"] = True
    else:
        x["docentiAdConfermata"], x["flgAdesione"] = True, adesione
    return {"ok": True, "messaggio": messaggio_didup(x, u["id"]), "scaricati": len(file)}


@rotta("GET", r"/api/didup/allegato/([A-Za-z0-9_-]+)/(\d+)")
def api_didup_allegato(c, u, m, corpo, q, req):
    el = allegati_didup(u["id"], m.group(1))
    i = int(m.group(2))
    if i >= len(el):
        raise Errore("Allegato non trovato.", 404)
    percorso = os.path.join(cartella_didup(u["id"], m.group(1)), el[i]["nome"])
    with open(percorso, "rb") as f:
        dati = f.read()
    return file_da_scaricare(dati, el[i]["nome"], mimetypes.guess_type(el[i]["nome"])[0] or "application/octet-stream")


@rotta("GET", "/api/io")
def api_io(c, u, m, corpo, q, req):
    imp = impostazioni(c)
    return {"utente": utente_pubblico(u), "scuola": imp["scuola"], "anno": nome_anno(),
            "staff": u["ruolo"] in STAFF, "timbrature": timbrature_abilitate(c, u),
            "tipologie": [t for t in TIPOLOGIE if categoria(u) in t["per"]],
            "tutte_tipologie": {t["id"]: t["nome"] for t in TIPOLOGIE}, "stati": STATI, "ruoli": RUOLI,
            "impostazioni": imp}


@rotta("POST", "/api/password")
def api_password(c, u, m, corpo, q, req):
    if not u["hash"]:
        raise Errore("Entri con le credenziali Argo: la password si cambia sul portale Argo.")
    if not password_giusta(str(corpo.get("attuale", "")), u):
        raise Errore("La password attuale non è corretta.")
    nuova = str(corpo.get("nuova", ""))
    if len(nuova) < 8:
        raise Errore("La nuova password deve avere almeno 8 caratteri.")
    h, s = hash_password(nuova)
    c.execute("UPDATE utenti SET hash=?, sale=?, cambia_password=0 WHERE id=?", (h, s, u["id"]))
    c.execute("DELETE FROM sessioni WHERE utente_id=? AND token<>?", (u["id"], req.token))
    return {"ok": True}


@rotta("GET", "/api/home")
def api_home(c, u, m, corpo, q, req):
    cont = contatori(c, u)
    attive = c.execute("SELECT COUNT(*) FROM richieste WHERE utente_id=? AND stato IN ('inviata','verificata',"
                       "'da_integrare')", (u["id"],)).fetchone()[0]
    da_integrare = c.execute("SELECT COUNT(*) FROM richieste WHERE utente_id=? AND stato='da_integrare'",
                             (u["id"],)).fetchone()[0]
    circ = [ci for ci in c.execute("SELECT * FROM circolari ORDER BY data DESC, id DESC LIMIT 200")
            if circolare_visibile(u, ci) and ci["destinatari"] != "nessuno"]
    lette = {r[0] for r in c.execute("SELECT circolare_id FROM letture WHERE utente_id=?", (u["id"],))}
    da_leggere = [ci for ci in circ if ci["presa_visione"] and ci["id"] not in lette]
    prossime = [richiesta_pubblica(c, r, u) for r in c.execute(
        "SELECT * FROM richieste WHERE utente_id=? AND al>=? AND stato NOT IN ('annullata','respinta','revocata') "
        "ORDER BY dal LIMIT 4", (u["id"], oggi().isoformat()))]
    out = {"contatori": cont, "attive": attive, "da_integrare": da_integrare,
           "circolari_da_leggere": [dict(ci) for ci in da_leggere[:5]], "n_da_leggere": len(da_leggere),
           "ultime_circolari": [dict(ci) | {"letta": ci["id"] in lette} for ci in circ[:3]],
           "prossime": prossime}
    if timbrature_abilitate(c, u):
        tt = c.execute("SELECT * FROM timbrature WHERE utente_id=? AND quando>=? ORDER BY quando",
                       (u["id"], oggi().isoformat())).fetchall()
        out["oggi_timbrature"] = [dict(t) for t in tt]
    if u["ruolo"] in STAFF:
        out["da_lavorare"] = len(lista_da_lavorare(c, u))
        out["assenti_oggi"] = len(assenti(c, oggi()))
    return out


@rotta("GET", "/api/richieste")
def api_richieste(c, u, m, corpo, q, req):
    righe = c.execute("SELECT * FROM richieste WHERE utente_id=? ORDER BY creata DESC", (u["id"],)).fetchall()
    return [richiesta_pubblica(c, r, u) for r in righe]


@rotta("GET", "/api/contatori")
def api_contatori(c, u, m, corpo, q, req):
    target = u
    if q.get("utente") and u["ruolo"] in STAFF:
        target = c.execute("SELECT * FROM utenti WHERE id=?", (int(q["utente"]),)).fetchone() or u
    da, a = inizio_anno(), fine_anno(oggi())
    esterne = [dict(x) for x in c.execute(
        "SELECT id, tipo, inizio, fine, quantita, stato, descrizione, rif FROM assenze_argo WHERE utente_id=? AND inizio>=?"
        " AND inizio<=? ORDER BY inizio DESC", (target["id"], da.isoformat(), a.isoformat()))]
    for x in esterne:
        x["unita"] = TIPI[x["tipo"]]["unita"] if x["tipo"] in TIPI else "giorni"
        x["annullabile"] = bool(x.pop("rif"))  # c'è la richiesta da cui è nata: si annulla come in Unica
        rich = c.execute("SELECT id, stato, campi FROM richieste WHERE utente_id=? AND tipo=? AND dal=? AND al=? AND "
                         "campi LIKE '%\"origine\": \"segreteria\"%' ORDER BY id DESC",
                         (target["id"], x["tipo"] if x["tipo"] in TIPI else "generica", x["inizio"],
                          x["fine"])).fetchone()
        x["richiesta"] = {"id": rich["id"], "stato": rich["stato"],
                          "inviata": bool(json.loads(rich["campi"] or "{}").get("inviata_argo"))} if rich else None
    return {"utente": utente_pubblico(target), "anno": nome_anno(), "contatori": contatori(c, target),
            "segreteria": {"letto": target["argo_letto"] or "", "errore": target["argo_errore"] or "",
                           "assenze": esterne}}


@rotta("POST", "/api/richieste/anteprima")
def api_anteprima(c, u, m, corpo, q, req):
    try:
        v, avvisi = valida_richiesta(c, u, corpo, corpo.get("id"))
        return {"ok": True, "quantita": v["quantita"], "avvisi": avvisi}
    except Errore as e:
        return {"ok": False, "errore": str(e)}


@rotta("POST", "/api/richieste")
def api_nuova_richiesta(c, u, m, corpo, q, req):
    v, avvisi = valida_richiesta(c, u, corpo)
    t = TIPI[v["tipo"]]
    files = corpo.get("allegati") or []
    if t["allegato"] == "obbligatorio" and not files:
        raise Errore("Per questa richiesta serve un allegato.")
    if v["campi"].get("documentazione") == "Documentazione allegata" and not files:
        raise Errore("Hai indicato «Documentazione allegata»: aggiungi il file.")
    ora = adesso().isoformat()
    cur = c.execute("INSERT INTO richieste (utente_id,tipo,dal,al,ora_da,ora_a,quantita,campi,note,stato,creata,"
                    "aggiornata) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (u["id"], v["tipo"], v["dal"], v["al"], v["ora_da"], v["ora_a"], v["quantita"],
                     json.dumps(v["campi"], ensure_ascii=False), v["note"], "inviata", ora, ora))
    rid = cur.lastrowid
    for f in files[:10]:
        salva_allegato(c, "richiesta", rid, f, u["id"])
    c.execute("INSERT INTO storico (richiesta_id,quando,utente_id,azione) VALUES (?,?,?,?)",
              (rid, ora, u["id"], "inviata"))
    quando = f" dal {it_data(v['dal'])}" if v["dal"] else ""
    notifica_ruoli(c, ["segreteria"], f"Nuova richiesta di {nome_completo(u)}: {t['nome']}{quando}",
                   f"#/richiesta/{rid}", tranne=u["id"])
    return {"ok": True, "id": rid, "avvisi": avvisi}


@rotta("GET", r"/api/richieste/(\d+)")
def api_richiesta(c, u, m, corpo, q, req):
    r = leggi_richiesta(c, u, int(m[1]))
    d = richiesta_pubblica(c, r, u, dettaglio=True)
    if u["ruolo"] in STAFF and r["utente_id"] != u["id"]:
        rich = c.execute("SELECT * FROM utenti WHERE id=?", (r["utente_id"],)).fetchone()
        d["contatori_richiedente"] = [k for k in contatori(c, rich, data(r["dal"]) if r["dal"] else None)
                                      if k["tipo"] == r["tipo"]]
    return d


@rotta("POST", r"/api/richieste/(\d+)")
def api_modifica_richiesta(c, u, m, corpo, q, req):
    r = leggi_richiesta(c, u, int(m[1]))
    if r["utente_id"] != u["id"] or r["stato"] != "da_integrare":
        raise Errore("Si può modificare solo una propria richiesta da integrare.")
    corpo["tipo"] = r["tipo"]
    v, avvisi = valida_richiesta(c, u, corpo, r["id"])
    ora = adesso().isoformat()
    c.execute("UPDATE richieste SET dal=?,al=?,ora_da=?,ora_a=?,quantita=?,campi=?,note=?,stato='inviata',"
              "aggiornata=? WHERE id=?", (v["dal"], v["al"], v["ora_da"], v["ora_a"], v["quantita"],
                                          json.dumps(v["campi"], ensure_ascii=False), v["note"], ora, r["id"]))
    for f in (corpo.get("allegati") or [])[:10]:
        salva_allegato(c, "richiesta", r["id"], f, u["id"])
    c.execute("INSERT INTO storico (richiesta_id,quando,utente_id,azione,nota) VALUES (?,?,?,?,?)",
              (r["id"], ora, u["id"], "reinviata", str(corpo.get("nota_integrazione") or "")[:1000]))
    notifica_ruoli(c, ["segreteria"], f"{nome_completo(u)} ha integrato la richiesta n. {r['id']}",
                   f"#/richiesta/{r['id']}", tranne=u["id"])
    return {"ok": True, "avvisi": avvisi}


@rotta("POST", r"/api/richieste/(\d+)/allegati")
def api_allegato_richiesta(c, u, m, corpo, q, req):
    r = leggi_richiesta(c, u, int(m[1]))
    if r["stato"] in ("annullata",):
        raise Errore("La richiesta è annullata.")
    files = corpo.get("allegati") or []
    if not files:
        raise Errore("Scegli un file.")
    for f in files[:10]:
        salva_allegato(c, "richiesta", r["id"], f, u["id"])
    c.execute("INSERT INTO storico (richiesta_id,quando,utente_id,azione,nota) VALUES (?,?,?,?,?)",
              (r["id"], adesso().isoformat(), u["id"], "allegato", ", ".join(str(f.get("nome")) for f in files)))
    if r["utente_id"] == u["id"]:
        notifica_ruoli(c, ["segreteria"], f"{nome_completo(u)} ha aggiunto un allegato alla richiesta n. {r['id']}",
                       f"#/richiesta/{r['id']}", tranne=u["id"])
    return {"ok": True}


@rotta("POST", r"/api/richieste/(\d+)/azione")
def api_azione(c, u, m, corpo, q, req):
    r = leggi_richiesta(c, u, int(m[1]))
    rich = c.execute("SELECT * FROM utenti WHERE id=?", (r["utente_id"],)).fetchone()
    az = corpo.get("azione")
    if az not in azioni_possibili(u, r, rich) or az == "modifica":
        raise Errore("Azione non consentita in questo stato.")
    nota = str(corpo.get("nota") or "").strip()[:1000]
    if az in AZIONI_CON_NOTA and not nota:
        raise Errore("Scrivi una motivazione.")
    nuovo = {"verifica": "verificata", "integra": "da_integrare", "autorizza": "autorizzata",
             "respingi": "respinta", "registra": "registrata", "evadi": "evasa", "revoca": "revocata",
             "annulla": "annullata", "chiedi_annullamento": "annullamento", "conferma_annullamento": "annullata",
             "ritira_annullamento": None, "nega_annullamento": None}[az]
    if nuovo is None:  # si torna allo stato di prima della richiesta di annullamento
        nuovo = stato_prima_annullamento(c, r)
    ora = adesso().isoformat()
    c.execute("UPDATE richieste SET stato=?, aggiornata=? WHERE id=?", (nuovo, ora, r["id"]))
    c.execute("INSERT INTO storico (richiesta_id,quando,utente_id,azione,nota) VALUES (?,?,?,?,?)",
              (r["id"], ora, u["id"], az if az.endswith("_annullamento") else nuovo, nota))
    t = TIPI[r["tipo"]]
    link = f"#/richiesta/{r['id']}"
    if az in ("chiedi_annullamento", "ritira_annullamento"):
        testo = "chiede di annullare" if az == "chiedi_annullamento" else "non chiede più di annullare"
        notifica_ruoli(c, ["segreteria"], f"{nome_completo(u)} {testo} la richiesta n. {r['id']} ({t['nome']}, "
                       f"{it_data(r['dal'])})", link, tranne=u["id"])
        return {"ok": True, "stato": nuovo}
    if az in ("conferma_annullamento", "nega_annullamento"):
        esito = "annullamento confermato: i giorni tornano disponibili" if nuovo == "annullata" else \
            "annullamento non accolto"
        if r["utente_id"] != u["id"]:
            notifica(c, r["utente_id"], f"{t['nome']} (n. {r['id']}): {esito}" + (f" – {nota}" if nota else ""), link)
        return {"ok": True, "stato": nuovo}
    if r["utente_id"] != u["id"]:
        notifica(c, r["utente_id"], f"{t['nome']} (n. {r['id']}): {STATI[nuovo].lower()}"
                 + (f" – {nota}" if nota else ""), link)
    if nuovo == "verificata":
        ruoli = ["dirigente"] + (["dsga"] if t.get("approva_dsga") and categoria(rich) == "ata" else [])
        notifica_ruoli(c, ruoli, f"Da autorizzare: {t['nome']} di {nome_completo(rich)}", link, tranne=u["id"])
    if nuovo == "annullata":
        notifica_ruoli(c, ["segreteria"], f"{nome_completo(u)} ha annullato la richiesta n. {r['id']}", link,
                       tranne=u["id"])
    return {"ok": True, "stato": nuovo}


def stato_prima_annullamento(c, r):
    """Lo stato che la richiesta aveva prima della richiesta di annullamento."""
    for (a,) in c.execute("SELECT azione FROM storico WHERE richiesta_id=? ORDER BY id DESC", (r["id"],)):
        if a in ("autorizzata", "registrata"):
            return a
    return "autorizzata"


@rotta("POST", "/api/assenze-segreteria/annulla")
def api_annulla_assenza_segreteria(c, u, m, corpo, q, req):
    """Annullamento di un'assenza letta dal programma della segreteria: come il pulsante «Annulla» di Unica,
    la richiesta di annullamento (motivo e allegati) va al programma Personale. Si tiene anche una copia
    in SmartDesk, in stato «annullamento», per vederla tra le proprie richieste."""
    a = c.execute("SELECT * FROM assenze_argo WHERE id=? AND utente_id=?", (int(corpo.get("id") or 0), u["id"])).fetchone()
    if not a:
        raise Errore("Assenza non trovata: rientra con le credenziali Argo per aggiornare l'elenco.", 404)
    motivo = str(corpo.get("nota") or "").strip()
    if not motivo:
        raise Errore("Scrivi il motivo dell'annullamento.")
    if len(motivo) > 250:
        raise Errore(f"Il motivo può avere al massimo 250 caratteri (ne hai scritti {len(motivo)}).")
    rif = json.loads(a["rif"]) if a["rif"] else None
    if not rif:
        raise Errore("Questa assenza è stata inserita direttamente dalla segreteria, senza una tua richiesta: "
                     "nemmeno da Unica si può annullare. Chiedi alla segreteria di toglierla.")
    files = (corpo.get("allegati") or [])[:5]
    tipo = a["tipo"] if a["tipo"] in TIPI else "generica"
    gia = c.execute("SELECT * FROM richieste WHERE utente_id=? AND tipo=? AND dal=? AND al=? AND "
                    "campi LIKE '%\"origine\": \"segreteria\"%' ORDER BY id DESC",
                    (u["id"], tipo, a["inizio"], a["fine"])).fetchone()
    if gia and gia["stato"] == "annullamento" and json.loads(gia["campi"] or "{}").get("inviata_argo"):
        raise Errore(f"Hai già chiesto l'annullamento (richiesta n. {gia['id']}).")
    s = SESSIONI_PERSONALE.get(req.token)
    if not s or s.get("utente_id") != u["id"]:
        raise Errore("Per mandare l'annullamento alla segreteria entra con le credenziali Argo "
                     "(dopo un riavvio di SmartDesk serve un nuovo accesso).", 409)
    # prima si controllano gli allegati, poi si manda l'annullamento
    letti = []
    for f in files:
        nome = os.path.basename(str(f.get("nome") or "allegato"))[:120] or "allegato"
        try:
            dati = base64.b64decode(str(f.get("dati", "")).split(",")[-1], validate=False)
        except Exception:
            raise Errore(f"L'allegato «{nome}» non è leggibile.")
        if not dati or len(dati) > 10 * 1024 * 1024:
            raise Errore(f"L'allegato «{nome}» è vuoto o supera 10 MB.")
        letti.append((nome, dati, str(f.get("mime") or mimetypes.guess_type(nome)[0] or "application/octet-stream")))
    try:
        esito = argo.annulla_richiesta_personale(s, rif, motivo)
    except argo.ErroreArgo as e:
        if "scaduta" in str(e):
            SESSIONI_PERSONALE.pop(req.token, None)
        raise Errore(str(e), 502)
    non_caricati = []
    for nome, dati, mime in letti:
        try:
            argo.allega_richiesta_personale(s, rif["uid"], nome, dati, mime)
        except argo.ErroreArgo as e:
            non_caricati.append(str(e))
    ora = adesso().isoformat()
    campi = {"origine": "segreteria", "assenza": a["descrizione"] or TIPI[tipo]["nome"], "inviata_argo": True,
             "motivo": motivo}
    if gia:
        rid = gia["id"]
        c.execute("UPDATE richieste SET stato='annullamento', campi=?, aggiornata=? WHERE id=?",
                  (json.dumps(campi, ensure_ascii=False), ora, rid))
    else:
        rid = c.execute("INSERT INTO richieste (utente_id,tipo,dal,al,ora_da,ora_a,quantita,campi,note,stato,creata,"
                        "aggiornata) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (u["id"], tipo, a["inizio"], a["fine"], None, None, a["quantita"],
                         json.dumps(campi, ensure_ascii=False), "", "annullamento", ora, ora)).lastrowid
        c.execute("INSERT INTO storico (richiesta_id,quando,utente_id,azione,nota) VALUES (?,?,?,?,?)",
                  (rid, ora, None, "registrata", "Assenza registrata dalla segreteria"))
    for nome, dati, mime in letti:
        salva_allegato(c, "richiesta", rid, {"nome": nome, "mime": mime,
                                             "dati": base64.b64encode(dati).decode()}, u["id"])
    c.execute("INSERT INTO storico (richiesta_id,quando,utente_id,azione,nota) VALUES (?,?,?,?,?)",
              (rid, ora, u["id"], "chiedi_annullamento", motivo + "\n(inviata al programma della segreteria"
               + (f", con {len(letti) - len(non_caricati)} allegati" if letti else "") + ")"))
    return {"ok": True, "id": rid, "messaggio": esito, "allegati_non_caricati": non_caricati}


# ---- gestione (segreteria, DSGA, dirigente)
def lista_da_lavorare(c, u):
    out = []
    for r in c.execute("SELECT * FROM richieste WHERE stato IN ('inviata','verificata','annullamento') "
                       "ORDER BY dal IS NULL, dal"):
        rich = c.execute("SELECT * FROM utenti WHERE id=?", (r["utente_id"],)).fetchone()
        az = set(azioni_possibili(u, r, rich)) - {"annulla", "modifica"}
        if r["stato"] == "annullamento":
            if u["ruolo"] == "segreteria" and az:
                out.append(r)
            continue
        if u["ruolo"] == "segreteria":
            if r["stato"] == "inviata" and az:
                out.append(r)
        elif "autorizza" in az and r["stato"] == "verificata":
            out.append(r)
    return out


def assenti(c, giorno):
    iso = giorno.isoformat()
    righe = c.execute("SELECT r.*, u.nome, u.cognome, u.ruolo, u.plesso FROM richieste r JOIN utenti u ON "
                      "u.id=r.utente_id WHERE r.dal<=? AND r.al>=? AND r.tipo<>'generica' AND r.stato IN "
                      "('autorizzata','registrata','inviata','verificata','da_integrare','annullamento') ORDER BY u.cognome",
                      (iso, iso)).fetchall()
    return [dict(id=r["id"], nome=f"{r['cognome']} {r['nome']}", ruolo=RUOLI[r["ruolo"]], plesso=r["plesso"],
                 tipo=TIPI[r["tipo"]]["nome"], stato=r["stato"], stato_nome=STATI[r["stato"]],
                 orario=r["ora_da"] and f"{r['ora_da']}–{r['ora_a']}", dal=r["dal"], al=r["al"]) for r in righe]


def filtra_richieste(c, q):
    sql, par = "SELECT * FROM richieste WHERE 1=1", []
    if q.get("stato"):
        sql += " AND stato=?"; par.append(q["stato"])
    if q.get("tipo"):
        sql += " AND tipo=?"; par.append(q["tipo"])
    if q.get("utente"):
        sql += " AND utente_id=?"; par.append(int(q["utente"]))
    if q.get("dal"):
        sql += " AND (al>=? OR al IS NULL)"; par.append(q["dal"])
    if q.get("al"):
        sql += " AND (dal<=? OR dal IS NULL)"; par.append(q["al"])
    return c.execute(sql + " ORDER BY creata DESC LIMIT 1000", par).fetchall()


@rotta("GET", "/api/gestione/da-lavorare", ruoli=STAFF)
def api_da_lavorare(c, u, m, corpo, q, req):
    return [richiesta_pubblica(c, r, u) for r in lista_da_lavorare(c, u)]


@rotta("GET", "/api/gestione/richieste", ruoli=STAFF)
def api_tutte(c, u, m, corpo, q, req):
    return [richiesta_pubblica(c, r, u) for r in filtra_richieste(c, q)]


@rotta("GET", "/api/gestione/richieste.csv", ruoli=STAFF)
def api_tutte_csv(c, u, m, corpo, q, req):
    righe = []
    for r in filtra_richieste(c, q):
        d = richiesta_pubblica(c, r, u)
        righe.append([d["id"], d["richiedente"], d["richiedente_ruolo"], d["tipo_nome"], it_data(d["dal"]),
                      it_data(d["al"]), f"{d['ora_da'] or ''}{'-' + d['ora_a'] if d['ora_a'] else ''}",
                      fmt(d["quantita"]), d["unita"], d["stato_nome"], d["creata"][:16].replace("T", " "),
                      "; ".join(f"{k}: {v}" for k, v in d["campi"].items() if v), d["note"]])
    return csv_risposta(f"richieste-{oggi().isoformat()}.csv",
                        ["N.", "Dipendente", "Ruolo", "Tipo", "Dal", "Al", "Orario", "Quantità", "Unità", "Stato",
                         "Inviata", "Dettagli", "Note"], righe)


@rotta("GET", "/api/gestione/assenti", ruoli=STAFF)
def api_assenti(c, u, m, corpo, q, req):
    g = data(q.get("data") or oggi().isoformat())
    return {"data": g.isoformat(), "assenti": assenti(c, g)}


@rotta("GET", "/api/gestione/calendario", ruoli=STAFF)
def api_calendario(c, u, m, corpo, q, req):
    m0 = data((q.get("mese") or oggi().isoformat()[:7]) + "-01")
    m1 = (m0 + dt.timedelta(days=32)).replace(day=1)
    out = {}
    d = m0
    while d < m1:
        out[d.isoformat()] = len(assenti(c, d))
        d += dt.timedelta(days=1)
    return {"mese": m0.isoformat()[:7], "giorni": out}


@rotta("GET", "/api/utenti", ruoli=STAFF)
def api_utenti(c, u, m, corpo, q, req):
    out = []
    for x in c.execute("SELECT * FROM utenti ORDER BY attivo DESC, cognome, nome"):
        d = utente_pubblico(x)
        fer = contatori(c, x)[0]
        d["ferie_residue"] = fer["residuo"]
        out.append(d)
    return out


def valori_utente(corpo, nuovo):
    v = {}
    for k in ("nome", "cognome", "profilo", "plesso", "email"):
        if k in corpo or nuovo:
            v[k] = str(corpo.get(k) or "").strip()[:100]
    if nuovo or "username" in corpo:
        v["username"] = re.sub(r"[^a-z0-9._-]", "", str(corpo.get("username") or "").lower())[:40]
        if not v["username"]:
            raise Errore("Scegli un nome utente (lettere, numeri, punto).")
    if nuovo and (not v.get("nome") or not v.get("cognome")):
        raise Errore("Nome e cognome sono obbligatori.")
    if "ruolo" in corpo or nuovo:
        if corpo.get("ruolo") not in RUOLI:
            raise Errore("Scegli il ruolo.")
        v["ruolo"] = corpo["ruolo"]
    for k, lo, hi in (("ferie_spettanti", 0, 40), ("ferie_ap", 0, 40), ("ore_giornaliere", 0, 12)):
        if k in corpo:
            try:
                x = float(corpo[k])
            except (TypeError, ValueError):
                raise Errore(f"Valore non valido: {k}.")
            if not lo <= x <= hi:
                raise Errore(f"Valore fuori intervallo: {k}.")
            v[k] = x
    if "attivo" in corpo:
        v["attivo"] = 1 if corpo["attivo"] else 0
    if "argo_utente" in corpo:
        v["argo_utente"] = str(corpo.get("argo_utente") or "").strip().lower()[:80]
    return v


def controlla_argo_unico(c, v, escludi=None):
    if v.get("argo_utente") and c.execute("SELECT 1 FROM utenti WHERE lower(argo_utente)=? AND id IS NOT ?",
                                          (v["argo_utente"], escludi)).fetchone():
        raise Errore("Questo utente Argo è già collegato a un'altra persona.")


@rotta("POST", "/api/utenti", ruoli=STAFF)
def api_nuovo_utente(c, u, m, corpo, q, req):
    v = valori_utente(corpo, True)
    if v["ruolo"] == "dirigente" and u["ruolo"] != "dirigente":
        raise Errore("Solo il dirigente può creare un altro account dirigente.", 403)
    if c.execute("SELECT 1 FROM utenti WHERE username=?", (v["username"],)).fetchone():
        raise Errore("Nome utente già usato.")
    controlla_argo_unico(c, v)
    v.setdefault("ore_giornaliere", 6 if v["ruolo"] != "docente" else 0)
    if corpo.get("solo_argo") and v.get("argo_utente"):
        v["hash"] = v["sale"] = ""
        c.execute(f"INSERT INTO utenti ({','.join(v)}) VALUES ({','.join('?' * len(v))})", list(v.values()))
        return {"ok": True}
    pw = password_nuova()
    v["hash"], v["sale"] = hash_password(pw)
    v["cambia_password"] = 1
    c.execute(f"INSERT INTO utenti ({','.join(v)}) VALUES ({','.join('?' * len(v))})", list(v.values()))
    return {"ok": True, "password": pw}


@rotta("POST", r"/api/utenti/(\d+)", ruoli=STAFF)
def api_modifica_utente(c, u, m, corpo, q, req):
    x = c.execute("SELECT * FROM utenti WHERE id=?", (int(m[1]),)).fetchone()
    if not x:
        raise Errore("Utente non trovato.", 404)
    if (x["ruolo"] == "dirigente" or corpo.get("ruolo") == "dirigente") and u["ruolo"] != "dirigente":
        raise Errore("Solo il dirigente può modificare un account dirigente.", 403)
    v = valori_utente(corpo, False)
    if x["id"] == u["id"] and ("ruolo" in v and v["ruolo"] != u["ruolo"] or v.get("attivo") == 0):
        raise Errore("Non puoi cambiare il tuo ruolo o disattivarti.")
    if "username" in v and c.execute("SELECT 1 FROM utenti WHERE username=? AND id<>?",
                                     (v["username"], x["id"])).fetchone():
        raise Errore("Nome utente già usato.")
    controlla_argo_unico(c, v, x["id"])
    out = {"ok": True}
    if corpo.get("reimposta_password"):
        pw = password_nuova()
        v["hash"], v["sale"] = hash_password(pw)
        v["cambia_password"] = 1
        out["password"] = pw
        c.execute("DELETE FROM sessioni WHERE utente_id=?", (x["id"],))
    if v:
        c.execute(f"UPDATE utenti SET {','.join(k + '=?' for k in v)} WHERE id=?", list(v.values()) + [x["id"]])
    if v.get("attivo") == 0:
        c.execute("DELETE FROM sessioni WHERE utente_id=?", (x["id"],))
    return out


@rotta("POST", "/api/impostazioni", ruoli={"dsga", "dirigente"})
def api_impostazioni(c, u, m, corpo, q, req):
    for k in IMPOSTAZIONI_BASE:
        if k in corpo:
            val = str(corpo[k]).strip()[:120]
            if k == "patrono" and val and not re.fullmatch(r"\d{2}-\d{2}", val):
                raise Errore("Il patrono va scritto come MM-GG (es. 06-24).")
            if k == "argo_ruolo_nuovi" and val not in ("docente", "ata"):
                raise Errore("Gli account nuovi da Argo possono essere solo docente o ATA.")
            if k == "argo_codice_scuola":
                val = val.upper()
            if k == "argo_nuovi" and val == "1" and not str(corpo.get("argo_codice_scuola") or
                                                            impostazioni(c).get("argo_codice_scuola")).strip():
                raise Errore("Per creare gli account da Argo serve il codice della scuola (es. SC12345).")
            c.execute("UPDATE impostazioni SET valore=? WHERE chiave=?", (val, k))
    return {"ok": True}


# ---- bacheca
@rotta("GET", "/api/circolari")
def api_circolari(c, u, m, corpo, q, req):
    lette = {r["circolare_id"]: r["risposta"] for r in
             c.execute("SELECT circolare_id, risposta FROM letture WHERE utente_id=?", (u["id"],))}
    cerca = (q.get("q") or "").lower().strip()
    out = []
    for ci in c.execute("SELECT * FROM circolari ORDER BY data DESC, id DESC"):
        if not circolare_visibile(u, ci):
            continue
        if cerca and cerca not in (ci["titolo"] + " " + (ci["testo"] or "") + f" n. {ci['numero']}").lower():
            continue
        d = dict(ci)
        d["letta"] = ci["id"] in lette
        d["risposta"] = lette.get(ci["id"], "")
        d["n_allegati"] = c.execute("SELECT COUNT(*) FROM allegati WHERE proprietario='circolare' AND rif_id=?",
                                    (ci["id"],)).fetchone()[0] + len(json.loads(ci["link_esterni"] or "[]"))
        d.pop("link_esterni", None)
        if q.get("da_leggere") and (d["letta"] or not ci["presa_visione"]):
            continue
        out.append(d)
    return out


@rotta("GET", r"/api/circolari/(\d+)")
def api_circolare(c, u, m, corpo, q, req):
    ci = c.execute("SELECT * FROM circolari WHERE id=?", (int(m[1]),)).fetchone()
    if not ci or not circolare_visibile(u, ci):
        raise Errore("Circolare non trovata.", 404)
    d = dict(ci)
    let = c.execute("SELECT * FROM letture WHERE circolare_id=? AND utente_id=?", (ci["id"], u["id"])).fetchone()
    d["letta"] = bool(let)
    d["risposta"] = let["risposta"] if let else ""
    d["quando_letta"] = let["quando"] if let else ""
    d["allegati"] = elenco_allegati(c, "circolare", ci["id"])
    d["link_esterni"] = json.loads(ci["link_esterni"] or "[]")
    if u["ruolo"] in STAFF and ci["fonte"] != "argo":
        letture = {r["utente_id"]: r for r in c.execute("SELECT * FROM letture WHERE circolare_id=?", (ci["id"],))}
        dest = destinatari_circolare(c, ci)
        d["statistiche"] = {
            "destinatari": len(dest), "lette": sum(1 for x in dest if x["id"] in letture),
            "risposte": {k: sum(1 for x in dest if x["id"] in letture and letture[x["id"]]["risposta"] == k)
                         for k in ("Aderisco", "Non aderisco", "Non ho ancora deciso")} if ci["adesione"] else {},
            "elenco": [{"nome": nome_completo(x), "ruolo": RUOLI[x["ruolo"]],
                        "quando": letture[x["id"]]["quando"] if x["id"] in letture else "",
                        "risposta": letture[x["id"]]["risposta"] if x["id"] in letture else ""} for x in dest]}
    return d


@rotta("POST", "/api/circolari/aggiorna-argo", ruoli=STAFF)
def api_aggiorna_argo(c, u, m, corpo, q, req):
    imp = impostazioni(c)
    if imp.get("argo_bacheca") != "1" or not imp.get("argo_codice_scuola"):
        raise Errore("Manca il codice scuola Argo (Gestione › Impostazioni).")
    try:
        n = importa_bacheca_argo(c)
    except Exception as e:  # noqa: BLE001
        raise Errore(f"Argo non raggiungibile ({e.__class__.__name__}).", 502)
    return {"ok": True, "nuove": n}


@rotta("GET", r"/api/circolari/(\d+)/letture\.csv", ruoli=STAFF)
def api_circolare_csv(c, u, m, corpo, q, req):
    d = api_circolare(c, u, m, corpo, q, req)
    righe = [[x["nome"], x["ruolo"], "sì" if x["quando"] else "no", x["quando"][:16].replace("T", " "),
              x["risposta"]] for x in d["statistiche"]["elenco"]]
    return csv_risposta(f"circolare-{d['numero']}-letture.csv",
                        ["Nome", "Ruolo", "Presa visione", "Quando", "Risposta"], righe)


@rotta("POST", "/api/circolari", ruoli=STAFF)
def api_nuova_circolare(c, u, m, corpo, q, req):
    titolo = str(corpo.get("titolo") or "").strip()[:200]
    if not titolo:
        raise Errore("Scrivi il titolo.")
    dest = corpo.get("destinatari")
    if dest not in ("tutti", "docenti", "ata"):
        raise Errore("Scegli i destinatari.")
    anno = nome_anno()
    numero = (c.execute("SELECT MAX(numero) FROM circolari WHERE anno=?", (anno,)).fetchone()[0] or 0) + 1
    scad = corpo.get("scadenza") or None
    if scad:
        scad = data(scad, "scadenza").isoformat()
    cur = c.execute("INSERT INTO circolari (numero,anno,titolo,testo,destinatari,presa_visione,adesione,scadenza,"
                    "data,autore_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (numero, anno, titolo, str(corpo.get("testo") or "")[:20000], dest,
                     1 if corpo.get("presa_visione") or corpo.get("adesione") else 0,
                     1 if corpo.get("adesione") else 0, scad, adesso().isoformat(), u["id"]))
    cid = cur.lastrowid
    for f in (corpo.get("allegati") or [])[:10]:
        salva_allegato(c, "circolare", cid, f, u["id"])
    ci = c.execute("SELECT * FROM circolari WHERE id=?", (cid,)).fetchone()
    for x in destinatari_circolare(c, ci):
        if x["id"] != u["id"]:
            notifica(c, x["id"], f"Nuova circolare n. {numero}: {titolo}", f"#/circolare/{cid}")
    return {"ok": True, "id": cid, "numero": numero}


@rotta("POST", r"/api/circolari/(\d+)/leggi")
def api_leggi(c, u, m, corpo, q, req):
    ci = c.execute("SELECT * FROM circolari WHERE id=?", (int(m[1]),)).fetchone()
    if not ci or not circolare_visibile(u, ci):
        raise Errore("Circolare non trovata.", 404)
    risp = str(corpo.get("risposta") or "")
    if ci["adesione"]:
        if risp not in ("Aderisco", "Non aderisco", "Non ho ancora deciso"):
            raise Errore("Scegli una risposta.")
        if ci["scadenza"] and ci["scadenza"] < oggi().isoformat():
            raise Errore("Il termine per rispondere è scaduto.")
    else:
        risp = ""
    c.execute("INSERT INTO letture VALUES (?,?,?,?) ON CONFLICT(circolare_id,utente_id) DO UPDATE SET "
              "risposta=excluded.risposta, quando=excluded.quando", (ci["id"], u["id"], adesso().isoformat(), risp))
    return {"ok": True}


# ---- presenze
@rotta("POST", "/api/timbra")
def api_timbra(c, u, m, corpo, q, req):
    if not timbrature_abilitate(c, u):
        raise Errore("Le timbrature non sono attive per il tuo profilo.", 403)
    verso = corpo.get("verso")
    if verso not in ("E", "U"):
        raise Errore("Scegli entrata o uscita.")
    ultima = c.execute("SELECT * FROM timbrature WHERE utente_id=? AND quando>=? ORDER BY quando DESC LIMIT 1",
                       (u["id"], oggi().isoformat())).fetchone()
    if ultima and ultima["verso"] == verso:
        raise Errore("Hai già timbrato l'" + ("entrata" if verso == "E" else "uscita") + ": manca la timbratura "
                     "opposta. Se è un errore, chiedi la correzione alla segreteria.")
    if not ultima and verso == "U":
        raise Errore("Oggi non risulta un'entrata.")
    if ultima and (adesso() - dt.datetime.fromisoformat(ultima["quando"])).total_seconds() < 60:
        raise Errore("Hai appena timbrato.")
    c.execute("INSERT INTO timbrature (utente_id,quando,verso) VALUES (?,?,?)", (u["id"], adesso().isoformat(), verso))
    return {"ok": True}


@rotta("GET", "/api/cartellino")
def api_cartellino(c, u, m, corpo, q, req):
    target = u
    if q.get("utente") and not q["utente"].isdigit():
        raise Errore("Dipendente non valido.")
    if q.get("utente") and int(q["utente"]) != u["id"]:
        if u["ruolo"] not in STAFF:
            raise Errore("Non autorizzato.", 403)
        target = c.execute("SELECT * FROM utenti WHERE id=?", (int(q["utente"]),)).fetchone()
        if not target:
            raise Errore("Utente non trovato.", 404)
    mese = q.get("mese") or oggi().isoformat()[:7]
    if not re.fullmatch(r"\d{4}-\d{2}", mese):
        raise Errore("Mese non valido.")
    return cartellino(c, target, int(mese[:4]), int(mese[5:]))


@rotta("GET", "/api/cartellino.csv")
def api_cartellino_csv(c, u, m, corpo, q, req):
    k = api_cartellino(c, u, m, corpo, q, req)
    righe = []
    for g in k["giorni"]:
        righe.append([it_data(g["data"]), " ".join(("E " if t["verso"] == "E" else "U ") + t["quando"][11:16]
                                                   for t in g["timbrature"]),
                      fmt(g["ore"]), fmt(g["teorico"]), "" if g["saldo"] is None else fmt(g["saldo"]),
                      ", ".join(a["tipo"] for a in g["assenze"])])
    nome = k["utente"]["cognome"].lower().replace(" ", "-")
    return csv_risposta(f"cartellino-{nome}-{k['anno']}-{k['mese']:02d}.csv",
                        ["Giorno", "Timbrature", "Ore", "Ore dovute", "Saldo", "Assenze"], righe)


@rotta("POST", "/api/timbrature", ruoli=STAFF)
def api_timbratura_manuale(c, u, m, corpo, q, req):
    x = c.execute("SELECT * FROM utenti WHERE id=?", (int(corpo.get("utente_id") or 0),)).fetchone()
    if not x:
        raise Errore("Utente non trovato.")
    if x["id"] == u["id"] and u["ruolo"] != "dirigente":
        raise Errore("Le correzioni alle proprie timbrature le fa un collega.", 403)
    try:
        quando = dt.datetime.fromisoformat(str(corpo.get("quando"))).replace(second=0, microsecond=0)
    except ValueError:
        raise Errore("Data e ora non valide.")
    if corpo.get("verso") not in ("E", "U"):
        raise Errore("Scegli entrata o uscita.")
    nota = str(corpo.get("nota") or "").strip()[:200]
    if not nota:
        raise Errore("Scrivi il motivo della correzione.")
    c.execute("INSERT INTO timbrature (utente_id,quando,verso,fonte,nota) VALUES (?,?,?,?,?)",
              (x["id"], quando.isoformat(), corpo["verso"], f"manuale ({u['cognome']})", nota))
    notifica(c, x["id"], f"Timbratura aggiunta dalla segreteria: {quando.strftime('%d/%m %H:%M')} – {nota}",
             "#/presenze")
    return {"ok": True}


@rotta("POST", r"/api/timbrature/(\d+)/elimina", ruoli=STAFF)
def api_elimina_timbratura(c, u, m, corpo, q, req):
    t = c.execute("SELECT * FROM timbrature WHERE id=?", (int(m[1]),)).fetchone()
    if not t:
        raise Errore("Timbratura non trovata.", 404)
    if t["utente_id"] == u["id"] and u["ruolo"] != "dirigente":
        raise Errore("Le correzioni alle proprie timbrature le fa un collega.", 403)
    c.execute("DELETE FROM timbrature WHERE id=?", (t["id"],))
    notifica(c, t["utente_id"], f"Timbratura del {t['quando'][:16].replace('T', ' ')} eliminata dalla segreteria",
             "#/presenze")
    return {"ok": True}


# ---- documenti personali
@rotta("GET", "/api/documenti")
def api_documenti(c, u, m, corpo, q, req):
    if q.get("utente") and u["ruolo"] in STAFF:
        righe = c.execute("SELECT d.*, u.nome, u.cognome FROM documenti d JOIN utenti u ON u.id=d.utente_id "
                          "WHERE d.utente_id=? ORDER BY creato DESC", (int(q["utente"]),))
    elif q.get("tutti") and u["ruolo"] in STAFF:
        righe = c.execute("SELECT d.*, u.nome, u.cognome FROM documenti d JOIN utenti u ON u.id=d.utente_id "
                          "ORDER BY creato DESC LIMIT 300")
    else:
        righe = c.execute("SELECT d.*, u.nome, u.cognome FROM documenti d JOIN utenti u ON u.id=d.utente_id "
                          "WHERE d.utente_id=? ORDER BY creato DESC", (u["id"],))
    out = []
    for d in righe:
        x = dict(d)
        x["allegati"] = elenco_allegati(c, "documento", d["id"])
        out.append(x)
    return out


@rotta("POST", "/api/documenti", ruoli=STAFF)
def api_nuovo_documento(c, u, m, corpo, q, req):
    ids = corpo.get("utenti") or []
    files = corpo.get("allegati") or []
    titolo = str(corpo.get("titolo") or "").strip()[:150]
    tipo = corpo.get("tipo")
    if tipo not in ("Cedolino", "Certificazione Unica", "Contratto", "Decreto", "Altro"):
        raise Errore("Scegli il tipo di documento.")
    if not titolo or not files or not ids:
        raise Errore("Servono titolo, file e almeno un destinatario.")
    if len(ids) > 1 and len(files) > 1:
        raise Errore("Con più destinatari si invia un solo file (lo stesso per tutti).")
    n = 0
    for i in ids:
        x = c.execute("SELECT * FROM utenti WHERE id=?", (int(i),)).fetchone()
        if not x:
            continue
        cur = c.execute("INSERT INTO documenti (utente_id,tipo,titolo,periodo,creato) VALUES (?,?,?,?,?)",
                        (x["id"], tipo, titolo, str(corpo.get("periodo") or "")[:40], adesso().isoformat()))
        for f in files[:5]:
            salva_allegato(c, "documento", cur.lastrowid, f, u["id"])
        notifica(c, x["id"], f"Nuovo documento: {titolo}", "#/documenti")
        n += 1
    return {"ok": True, "inviati": n}


@rotta("GET", r"/api/allegati/([0-9a-f]{32})")
def api_allegato(c, u, m, corpo, q, req):
    a = c.execute("SELECT * FROM allegati WHERE id=?", (m[1],)).fetchone()
    if not a:
        raise Errore("File non trovato.", 404)
    ok = u["ruolo"] in STAFF
    if a["proprietario"] == "richiesta":
        r = c.execute("SELECT utente_id FROM richieste WHERE id=?", (a["rif_id"],)).fetchone()
        ok = ok or (r and r["utente_id"] == u["id"])
    elif a["proprietario"] == "circolare":
        ci = c.execute("SELECT * FROM circolari WHERE id=?", (a["rif_id"],)).fetchone()
        ok = ok or (ci and circolare_visibile(u, ci))
    elif a["proprietario"] == "documento":
        d = c.execute("SELECT * FROM documenti WHERE id=?", (a["rif_id"],)).fetchone()
        mio = d and d["utente_id"] == u["id"]
        ok = ok or mio
        if mio and not d["letto"]:
            c.execute("UPDATE documenti SET letto=? WHERE id=?", (adesso().isoformat(), d["id"]))
    if not ok:
        raise Errore("Non autorizzato.", 403)
    with open(os.path.join(DATI, "allegati", a["id"]), "rb") as f:
        dati = f.read()
    sicuro = a["mime"] in ("application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp", "text/plain")
    return file_da_scaricare(dati, a["nome"], a["mime"] if sicuro else "application/octet-stream",
                             inline=sicuro and not q.get("scarica"))


# ---- notifiche
@rotta("GET", "/api/notifiche")
def api_notifiche(c, u, m, corpo, q, req):
    righe = c.execute("SELECT * FROM notifiche WHERE utente_id=? ORDER BY id DESC LIMIT 40", (u["id"],))
    elenco = [dict(r) for r in righe]
    return {"non_lette": sum(1 for n in elenco if not n["letta"]), "elenco": elenco}


@rotta("POST", "/api/notifiche/lette")
def api_notifiche_lette(c, u, m, corpo, q, req):
    c.execute("UPDATE notifiche SET letta=1 WHERE utente_id=?", (u["id"],))
    return {"ok": True}


# ---------------------------------------------------------------- server HTTP
class Gestore(BaseHTTPRequestHandler):
    server_version = "SportelloPersonale/1.0"

    def log_message(self, fmt_, *args):
        if os.environ.get("SPORTELLO_LOG"):
            super().log_message(fmt_, *args)

    def do_GET(self):
        self.gestisci("GET")

    def do_POST(self):
        self.gestisci("POST")

    def invia(self, r):
        self.send_response(r.codice)
        self.send_header("Content-Type", r.tipo)
        self.send_header("Content-Length", str(len(r.corpo)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        if r.tipo.startswith("application/json") or r.tipo.startswith("text/csv"):
            self.send_header("Cache-Control", "no-store")
        for k, v in r.intestazioni.items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(r.corpo)

    def errore(self, codice, msg):
        self.invia(Risposta(json.dumps({"errore": msg}).encode(), codice=codice))

    def gestisci(self, metodo):
        url = urlparse(self.path)
        if not url.path.startswith("/api/"):
            return self.statico(url.path) if metodo == "GET" else self.errore(405, "Metodo non consentito")
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if "utente" in q and not q["utente"].isdigit():
            return self.errore(400, "Dipendente non valido.")
        corpo = {}
        if metodo == "POST":
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_CORPO:
                return self.errore(413, "File troppo grandi (massimo 25 MB in tutto).")
            if "application/json" not in (self.headers.get("Content-Type") or ""):
                return self.errore(415, "Formato non supportato.")
            try:
                corpo = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                return self.errore(400, "Dati non validi.")
            if not isinstance(corpo, dict):
                return self.errore(400, "Dati non validi.")
        for met, schema, f, ruoli, pubblica in ROTTE:
            mm = schema.match(url.path)
            if met != metodo or not mm:
                continue
            c = db()
            try:
                with c:
                    u = None
                    self.token = self.leggi_cookie()
                    if self.token:
                        u = c.execute("SELECT u.* FROM sessioni s JOIN utenti u ON u.id=s.utente_id WHERE "
                                      "s.token=? AND s.scade>? AND u.attivo=1", (self.token, time.time())).fetchone()
                    if not pubblica and not u:
                        raise Errore("Accesso scaduto: entra di nuovo.", 401)
                    if ruoli and u["ruolo"] not in ruoli:
                        raise Errore("Funzione riservata alla segreteria e alla dirigenza.", 403)
                    out = f(c, u, mm, corpo, q, self)
                r = out if isinstance(out, Risposta) else Risposta(
                    json.dumps(out, ensure_ascii=False, default=str).encode())
                return self.invia(r)
            except Errore as e:
                return self.errore(e.codice, str(e))
            except Exception as e:  # noqa: BLE001
                import traceback
                traceback.print_exc()
                return self.errore(500, f"Errore interno: {e.__class__.__name__}")
            finally:
                c.close()
        self.errore(404, "Funzione non trovata.")

    def leggi_cookie(self):
        for parte in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = parte.strip().partition("=")
            if k == "sp_sessione":
                return v
        return None

    def statico(self, percorso):
        if percorso in ("/", ""):
            percorso = "/index.html"
        pieno = os.path.normpath(os.path.join(STATIC, percorso.lstrip("/")))
        if not pieno.startswith(STATIC) or not os.path.isfile(pieno):
            pieno = os.path.join(STATIC, "index.html")
        with open(pieno, "rb") as f:
            dati = f.read()
        tipo = mimetypes.guess_type(pieno)[0] or "application/octet-stream"
        if tipo.startswith("text/") or tipo in ("application/javascript", "application/json"):
            tipo += "; charset=utf-8"
        if pieno.endswith(".webmanifest"):
            tipo = "application/manifest+json"
        self.invia(Risposta(dati, tipo, intestazioni={"Cache-Control": "no-cache"}))


# ---------------------------------------------------------------- dati di prova
def crea_demo():
    """Popola un database vuoto con personale, richieste, circolari e timbrature inventate."""
    c = db()
    if c.execute("SELECT COUNT(*) FROM utenti").fetchone()[0]:
        c.close()
        return None
    pw = password_nuova()
    h, s = hash_password(pw)
    persone = [
        ("dirigente", "Paola", "Ferraris", "dirigente", "Dirigente scolastico", "Sede", 32, 0, 0),
        ("dsga", "Marco", "Bellini", "dsga", "Direttore SGA", "Sede", 32, 4, 7.2),
        ("segreteria", "Laura", "Gallo", "segreteria", "Assistente amministrativa – Ufficio personale", "Sede",
         32, 2, 7.2),
        ("g.rinaldi", "Giulia", "Rinaldi", "docente", "Docente scuola primaria", "Primaria Almese", 32, 5, 0),
        ("s.conti", "Stefano", "Conti", "docente", "Docente di matematica e scienze", "Secondaria", 32, 0, 0),
        ("e.marino", "Elena", "Marino", "docente", "Docente di sostegno", "Secondaria", 30, 0, 0),
        ("f.colombo", "Francesca", "Colombo", "docente", "Docente scuola dell'infanzia", "Infanzia", 32, 3, 0),
        ("a.ricci", "Antonio", "Ricci", "ata", "Collaboratore scolastico", "Primaria Almese", 32, 6, 7.2),
        ("r.greco", "Rosa", "Greco", "ata", "Collaboratrice scolastica", "Secondaria", 32, 1, 7.2),
        ("d.fontana", "Davide", "Fontana", "ata", "Assistente tecnico", "Secondaria", 30, 0, 7.2),
    ]
    ids = {}
    for un, no, co, ru, pr, pl, fs, fa, og in persone:
        cur = c.execute("INSERT INTO utenti (username,nome,cognome,ruolo,profilo,plesso,hash,sale,ferie_spettanti,"
                        "ferie_ap,ore_giornaliere) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (un, no, co, ru, pr, pl, h, s, fs, fa, og))
        ids[un] = cur.lastrowid
    c.execute("UPDATE impostazioni SET valore=? WHERE chiave='scuola'", ("I.C. di prova",))
    c.execute("UPDATE impostazioni SET valore='1' WHERE chiave='settimana_corta'")
    imp = impostazioni(c)

    def prossimo_lav(d, n=0):
        while not lavorativo(d, imp) or n > 0:
            if lavorativo(d, imp):
                n -= 1
            d += dt.timedelta(days=1)
        return d

    o = oggi()
    ora = adesso()

    def richiesta(un, tipo, dal, al=None, ore=None, stato="inviata", campi=None, note="", passi=()):
        t = TIPI[tipo]
        al = al or dal
        q = (ora_min(ore[1]) - ora_min(ore[0])) / 60 if ore else (giorni_lavorativi(dal, al, imp) if dal else 0)
        crea = (ora - dt.timedelta(days=len(passi) + 1, hours=3)).isoformat()
        cur = c.execute("INSERT INTO richieste (utente_id,tipo,dal,al,ora_da,ora_a,quantita,campi,note,stato,creata,"
                        "aggiornata) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (ids[un], tipo, dal and dal.isoformat(), al and al.isoformat(), ore and ore[0],
                         ore and ore[1], q if t["unita"] != "nessuna" else 0,
                         json.dumps(campi or {}, ensure_ascii=False), note, stato, crea, ora.isoformat()))
        rid = cur.lastrowid
        c.execute("INSERT INTO storico (richiesta_id,quando,utente_id,azione) VALUES (?,?,?,?)",
                  (rid, crea, ids[un], "inviata"))
        for i, (chi, az, nota) in enumerate(passi):
            c.execute("INSERT INTO storico (richiesta_id,quando,utente_id,azione,nota) VALUES (?,?,?,?,?)",
                      (rid, (ora - dt.timedelta(days=len(passi) - i)).isoformat(), ids[chi], az, nota))
        return rid

    ver = ("segreteria", "verificata", "")
    richiesta("g.rinaldi", "ferie", prossimo_lav(o, 6), prossimo_lav(o, 7), stato="inviata")
    richiesta("s.conti", "motivi_personali", prossimo_lav(o, 3), stato="verificata",
              campi={"documentazione": "Autocertificazione"}, note="Trasloco", passi=[ver])
    richiesta("a.ricci", "permesso_breve", prossimo_lav(o, 2), ore=("11:00", "13:00"), stato="verificata",
              passi=[ver])
    richiesta("e.marino", "l104", prossimo_lav(o, 4), stato="inviata",
              campi={"per_chi": "Per assistenza a un familiare", "assistito": "Madre"})
    ultimo_lav = o
    while not lavorativo(ultimo_lav, imp):
        ultimo_lav -= dt.timedelta(days=1)
    richiesta("r.greco", "malattia", ultimo_lav, stato="inviata", campi={"tipo_malattia": "Malattia ordinaria",
                                                                 "protocollo": "1234567890"})
    richiesta("f.colombo", "formazione", prossimo_lav(o, 9), stato="da_integrare",
              campi={"corso": "Corso di coding unplugged"},
              passi=[("segreteria", "da_integrare", "Allega il programma del corso con l'attestato di iscrizione.")])
    richiesta("d.fontana", "generica", None, stato="inviata",
              campi={"tipologia": "Certificato di servizio", "oggetto": "Certificato per graduatoria"})
    passati = prossimo_lav(o - dt.timedelta(days=30))
    richiesta("g.rinaldi", "festivita", passati, stato="autorizzata",
              passi=[ver, ("dirigente", "autorizzata", "")])
    richiesta("a.ricci", "ferie", passati, prossimo_lav(passati, 1), stato="autorizzata",
              passi=[ver, ("dsga", "autorizzata", "")])
    richiesta("s.conti", "permesso_breve", prossimo_lav(o - dt.timedelta(days=20)), ore=("08:00", "10:00"),
              stato="autorizzata", passi=[ver, ("dirigente", "autorizzata", "")])
    richiesta("g.rinaldi", "motivi_personali", prossimo_lav(o - dt.timedelta(days=12)), stato="respinta",
              campi={"documentazione": "Autocertificazione"},
              passi=[ver, ("dirigente", "respinta", "Coincide con lo scrutinio: concordiamo un'altra data.")])
    richiesta("e.marino", "ferie", prossimo_lav(o, 1), stato="autorizzata", passi=[ver, ("dirigente", "autorizzata", "")])
    # circolari
    anno = nome_anno()
    circolari = [
        ("Sciopero del comparto scuola – comunicazione di adesione",
         "Le organizzazioni sindacali hanno proclamato uno sciopero per l'intera giornata.\n\nAi sensi dell'Accordo "
         "sulle norme di garanzia, il personale è invitato a comunicare entro la scadenza la propria intenzione di "
         "aderire, di non aderire o di non aver ancora maturato una decisione.", "tutti", 1, 1,
         (o + dt.timedelta(days=4)).isoformat()),
        ("Convocazione del Collegio dei docenti",
         "Il Collegio dei docenti è convocato in seduta ordinaria in aula magna con il seguente ordine del giorno:\n"
         "1. Approvazione del verbale della seduta precedente\n2. Piano annuale delle attività\n3. Progetti PTOF\n"
         "4. Varie ed eventuali", "docenti", 1, 0, None),
        ("Piano ferie estive del personale ATA",
         "Il personale ATA è invitato a presentare la richiesta di ferie estive tramite SmartDesk entro la fine "
         "del mese, per permettere la stesura del piano di servizio.", "ata", 1, 0, None),
        ("Orario di ricevimento della segreteria",
         "La segreteria del personale riceve dal lunedì al venerdì dalle 10:00 alle 12:00 e il martedì anche dalle "
         "14:30 alle 16:30.", "tutti", 0, 0, None),
    ]
    for i, (ti, te, de, pv, ad, sc) in enumerate(circolari, 1):
        cur = c.execute("INSERT INTO circolari (numero,anno,titolo,testo,destinatari,presa_visione,adesione,scadenza,"
                        "data,autore_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (i, anno, ti, te, de, pv, ad, sc, (ora - dt.timedelta(days=len(circolari) - i)).isoformat(),
                         ids["dirigente"]))
        if i == 2:
            aid = uuid.uuid4().hex
            pdf = pdf_semplice(["Convocazione del Collegio dei docenti", "", "Ordine del giorno allegato.",
                                "(documento di prova generato da SmartDesk)"])
            with open(os.path.join(DATI, "allegati", aid), "wb") as f:
                f.write(pdf)
            c.execute("INSERT INTO allegati VALUES (?,?,?,?,?,?,?,?)", (aid, "circolare", cur.lastrowid,
                      "convocazione-collegio.pdf", "application/pdf", len(pdf), ora.isoformat(), ids["dirigente"]))
        if i == 1:
            for un, rr in (("s.conti", "Non aderisco"), ("a.ricci", "Non ho ancora deciso")):
                c.execute("INSERT INTO letture VALUES (?,?,?,?)", (cur.lastrowid, ids[un], ora.isoformat(), rr))
    # timbrature delle ultime 3 settimane per l'ATA
    for un in ("a.ricci", "r.greco", "d.fontana", "segreteria", "dsga"):
        d = o - dt.timedelta(days=21)
        while d < o:
            if lavorativo(d, imp) and not (un == "a.ricci" and passati <= d <= prossimo_lav(passati, 1)):
                e = dt.datetime.combine(d, dt.time(7, 30)) + dt.timedelta(minutes=secrets.randbelow(15))
                us = e + dt.timedelta(hours=7, minutes=12 + secrets.randbelow(30) - 10)
                c.execute("INSERT INTO timbrature (utente_id,quando,verso) VALUES (?,?,?)", (ids[un], e.isoformat(), "E"))
                c.execute("INSERT INTO timbrature (utente_id,quando,verso) VALUES (?,?,?)", (ids[un], us.isoformat(), "U"))
            d += dt.timedelta(days=1)
    # cedolini
    mese_prec = (o.replace(day=1) - dt.timedelta(days=1))
    for un, uid in ids.items():
        if un == "dirigente":
            continue
        cur = c.execute("INSERT INTO documenti (utente_id,tipo,titolo,periodo,creato) VALUES (?,?,?,?,?)",
                        (uid, "Cedolino", f"Cedolino {mese_prec.strftime('%m/%Y')}", mese_prec.strftime("%Y-%m"),
                         ora.isoformat()))
        aid = uuid.uuid4().hex
        pdf = pdf_semplice([f"Cedolino {mese_prec.strftime('%m/%Y')} - documento di prova",
                            f"Dipendente: {un}", "", "Questo file serve solo a provare SmartDesk."])
        with open(os.path.join(DATI, "allegati", aid), "wb") as f:
            f.write(pdf)
        c.execute("INSERT INTO allegati VALUES (?,?,?,?,?,?,?,?)", (aid, "documento", cur.lastrowid,
                  f"cedolino-{mese_prec.strftime('%Y-%m')}.pdf", "application/pdf", len(pdf), ora.isoformat(),
                  ids["segreteria"]))
    for un in ("segreteria",):
        notifica(c, ids[un], "Ci sono richieste nuove da verificare", "#/gestione")
    c.commit()
    c.close()
    return pw


def main():
    global DATI
    p = argparse.ArgumentParser(description="SmartDesk - sportello del personale")
    p.add_argument("--host", default="127.0.0.1", help="0.0.0.0 per accettare i telefoni della rete")
    p.add_argument("--porta", type=int, default=8850)
    p.add_argument("--dati", help="cartella dei dati (database e allegati)")
    p.add_argument("--demo", action="store_true", help="se il database è vuoto, crea personale e dati di prova")
    p.add_argument("--crea-dirigente", metavar="USERNAME",
                   help="crea il primo account dirigente e scrive la password in dati/primo-accesso.txt")
    p.add_argument("--attiva-argo", metavar="CODICE_SCUOLA", nargs="?", const="",
                   help="attiva l'accesso con le credenziali Argo (con il codice scuola, es. SC12345)")
    p.add_argument("--collega-argo", metavar="UTENTE_ARGO",
                   help="crea un account che entra con questo utente Argo (vedi --ruolo)")
    p.add_argument("--ruolo", default="dirigente", choices=list(RUOLI), help="ruolo per --collega-argo")
    p.add_argument("--argo-nuovi", action="store_true",
                   help="chi entra con Argo e non ha ancora un account lo riceve subito (serve --attiva-argo CODICE)")
    a = p.parse_args()
    if a.dati:
        DATI = os.path.abspath(a.dati)
    prepara_db()
    if a.attiva_argo is not None:
        with db() as c:
            c.execute("UPDATE impostazioni SET valore='1' WHERE chiave='argo_attivo'")
            if a.attiva_argo:
                c.execute("UPDATE impostazioni SET valore=? WHERE chiave='argo_codice_scuola'", (a.attiva_argo.upper(),))
            if a.argo_nuovi:
                c.execute("UPDATE impostazioni SET valore='1' WHERE chiave='argo_nuovi'")
        print("Accesso con Argo attivato.")
    if a.collega_argo:
        with db() as c:
            ua = a.collega_argo.strip().lower()
            x = c.execute("SELECT * FROM utenti WHERE lower(argo_utente)=?", (ua,)).fetchone()
            if x:
                c.execute("UPDATE utenti SET ruolo=?, attivo=1 WHERE id=?", (a.ruolo, x["id"]))
                print(f"Utente Argo già collegato a {x['cognome']} {x['nome']}: ruolo impostato a {a.ruolo}.")
            else:
                base = re.sub(r"[^a-z0-9._-]", "", ua)[:36] or "utente"
                un, i = base, 1
                while c.execute("SELECT 1 FROM utenti WHERE username=?", (un,)).fetchone():
                    i += 1
                    un = f"{base}-{i}"
                c.execute("INSERT INTO utenti (username,nome,cognome,ruolo,hash,sale,ore_giornaliere,argo_utente) "
                          "VALUES (?,?,?,?,?,?,?,?)", (un, ua, "(da completare)", a.ruolo, "", "", 0, ua))
                print(f"Creato l'account per l'utente Argo «{ua}» con ruolo {a.ruolo}: "
                      "nome e cognome arrivano da Argo al primo accesso.")
            c.execute("UPDATE impostazioni SET valore='1' WHERE chiave='argo_attivo'")
    if a.demo:
        pw = crea_demo()
        if pw:
            with open(os.path.join(DATI, "credenziali-demo.txt"), "w", encoding="utf-8") as f:
                f.write("Account di prova di SmartDesk (tutti con la stessa password)\n\n"
                        "Utenti: dirigente, dsga, segreteria, g.rinaldi, s.conti, e.marino, f.colombo (docenti),\n"
                        "        a.ricci, r.greco, d.fontana (ATA)\n\n"
                        f"Password: {pw}\n")
            print(f"Dati di prova creati. Utenti e password in {os.path.join(DATI, 'credenziali-demo.txt')}")
    if a.crea_dirigente:
        with db() as c:
            un = a.crea_dirigente.lower()
            if c.execute("SELECT 1 FROM utenti WHERE username=?", (un,)).fetchone():
                sys.exit("Esiste già un utente con questo nome.")
            pw = password_nuova()
            h, s = hash_password(pw)
            c.execute("INSERT INTO utenti (username,nome,cognome,ruolo,profilo,hash,sale,cambia_password,"
                      "ore_giornaliere) VALUES (?,?,?,?,?,?,?,1,0)",
                      (un, "Dirigente", "Scolastico", "dirigente", "Dirigente scolastico", h, s))
        with open(os.path.join(DATI, "primo-accesso.txt"), "w", encoding="utf-8") as f:
            f.write(f"Utente: {un}\nPassword provvisoria: {pw}\n(al primo accesso verrà chiesto di cambiarla)\n")
        print(f"Account creato. Password provvisoria in {os.path.join(DATI, 'primo-accesso.txt')}")
    if not a.demo:
        threading.Thread(target=ciclo_bacheca_argo, daemon=True).start()
    srv = ThreadingHTTPServer((a.host, a.porta), Gestore)
    print(f"SmartDesk in ascolto su http://{'localhost' if a.host in ('127.0.0.1', '0.0.0.0') else a.host}"
          f":{a.porta}  (Ctrl+C per fermare)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
