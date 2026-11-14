# Sportello Personale

App web per le esigenze del personale scolastico (docenti e ATA). Fa le stesse cose di Argo Unica:
le richieste di assenza passano da un percorso di autorizzazione, la bacheca chiede presa visione o
adesione, il personale ha il cartellino delle presenze e riceve i suoi documenti.

Usa solo Python 3.10+ (libreria standard): niente da installare. I dati stanno in `dati\`
(database SQLite e allegati).

## Avvio

- **Prova con dati inventati**: doppio clic su `avvia-demo.bat` (porta 8851, cartella `dati-demo\`).
  Utenti e password di prova sono in `dati-demo\credenziali-demo.txt`.
- **Uso vero**: la prima volta crea l'account del dirigente
  ```
  python server.py --crea-dirigente dirigente
  ```
  La password provvisoria si trova in `dati\primo-accesso.txt` (al primo accesso si cambia; poi cancella il file).
  Dopo si avvia con `avvia.bat` (porta 8850). Gli altri account si creano da **Gestione › Personale**.
- Per usarla dai telefoni della rete della scuola: `python server.py --host 0.0.0.0` e aprire
  `http://<IP del PC>:8850` (serve una regola del firewall per la porta).

## Accesso con le credenziali Argo

Il personale entra con lo stesso nome utente e la stessa password del portale Argo. Lo Sportello fa lo stesso
accesso del sito Argo (auth.portaleargo.it), controlla che le credenziali siano giuste e **non salva la password**.
Il server deve avere internet.

- **Avvio**: doppio clic su `avvia.bat` (= `python server.py --porta 8850 --attiva-argo SC15290 --argo-nuovi`).
  Si entra con «Credenziali Argo» e il nome utente nel formato `nome.cognome.SC15290`: nome, cognome e scuola si leggono
  da lì. Chi ha credenziali Argo valide di SC15290 riceve l'account al primo accesso, senza registrazione.
  **Il primo in assoluto diventa amministratore** (ruolo dirigente, vede la Gestione); gli altri entrano come docenti e
  la segreteria corregge il ruolo in Gestione › Personale.
- Per collegare a mano un utente Argo con un ruolo: `python server.py --collega-argo nome.cognome.SC15290 --ruolo segreteria`.
- Come si riconosce chi entra: 1) dal campo «Utente Argo» della sua scheda in Gestione › Personale; 2) altrimenti da nome
  e cognome che arrivano da Argo (se c'è una sola persona con quel nome, la scheda si collega da sola); 3) altrimenti, se
  in Impostazioni è attiva «Crea l'account al primo accesso», si crea un account nuovo (docente o ATA) e la segreteria
  riceve una notifica. Per crearlo il codice scuola deve comparire nei dati che Argo restituisce.
- Si fa un solo tentativo verso Argo per ogni invio; dopo 3 password sbagliate si aspetta 15 minuti, così Argo non
  blocca l'account.
- Non gestito ancora: account Argo con secondo codice (OTP), scelta tra più profili, consensi da accettare.
  Il messaggio d'errore lo dice; chi è in questi casi usa l'account dello Sportello.
- Diagnosi: dopo ogni accesso Argo riuscito `dati\argo-campi.json` elenca i **nomi** dei campi ricevuti da Argo (senza i
  valori). Serve a capire se Argo manda nome, cognome e codice scuola.

## Che cosa fa

**Per tutto il personale**
- Richieste: ferie, festività soppresse, motivi personali/familiari, permesso breve, recupero ore (ATA),
  malattia, visita medica (oraria per ATA o giornata intera), Legge 104, congedo parentale, malattia del figlio,
  lutto, matrimonio, concorsi/esami, formazione (docenti), richiesta generica alla segreteria (certificati, IBAN...).
- Controlli automatici: giorni lavorativi (domeniche, festività nazionali, Pasquetta, patrono, sabato con settimana
  corta), preavviso minimo, limiti annui e mensili, ferie residue, sovrapposizioni. L'anteprima dice subito quanti
  giorni/ore conta la richiesta o perché non va.
- Allegati (anche dopo l'invio), cronologia di ogni passaggio, annullamento, integrazione su richiesta della segreteria.
- Situazione ferie e permessi con usati / in attesa / rimasti.
- Bacheca con ricerca, presa visione e adesione (es. sciopero: aderisco / non aderisco / non ho ancora deciso, con scadenza).
- Presenze (ATA, e docenti se attivato): timbratura entrata/uscita, cartellino mensile con saldo ore, CSV e stampa.
- Documenti personali (cedolini, CU, contratti) inviati dalla segreteria.
- Notifiche a ogni cambio di stato; funziona da telefono (menu in basso) e si può installare come app.

**Per segreteria, DSGA e dirigente** (menu Gestione)
- Da lavorare: la segreteria verifica (o registra le malattie, evade le richieste generiche); il dirigente autorizza;
  il DSGA autorizza ferie, festività, permessi brevi, recuperi e visite orarie del personale ATA.
- Tutte le richieste con filtri ed esportazione CSV.
- Calendario delle assenze con chi è assente ogni giorno.
- Personale: anagrafica, ruolo, ferie spettanti e residue dell'anno precedente, ore giornaliere, reimpostazione password.
- Bacheca: nuove circolari con allegati, chi ha letto e chi no, risposte di adesione, CSV.
- Correzione delle timbrature (con motivo; non sulle proprie).
- Impostazioni: nome scuola, settimana corta, patrono, timbrature per i docenti.

## Collaudo

```
python prova_api.py
```
Avvia il server su una porta libera con dati di prova in una cartella temporanea e prova tutto il giro
(richiesta, verifica, autorizzazione, limiti, bacheca, timbrature, documenti, permessi d'accesso).

## Limiti di questa versione

- Le regole contrattuali (limiti, preavvisi) sono quelle più comuni del CCNL scuola e stanno in `TIPOLOGIE`
  dentro `server.py`: vanno controllate con la segreteria.
- Non è collegata ad Argo (Personale Web, Presenze, Emolumenti): i dati si inseriscono qui.
- Niente firma con OTP, niente pagamenti PagoPA, niente notifiche email o push.
- Senza HTTPS: va bene in rete interna; per l'uso da fuori serve un dominio con certificato.
