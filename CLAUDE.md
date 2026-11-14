# Note per Claude: Sportello Personale

App web per le esigenze del personale scolastico, modello Argo Unica (richieste di assenza con verifica
segreteria -> autorizzazione dirigente/DSGA, bacheca con presa visione/adesione, timbrature e cartellino,
documenti personali, gestione). Creata il 14/11/2026 per Andrea Giorda. Si lavora **in italiano**.

- Solo libreria standard Python: `server.py` (API + SQLite + dati di prova), `static/` (index.html, app.js, style.css).
- Porte: 8850 uso vero, 8851 demo (`--dati dati-demo --demo`). Voce "sportello-personale" nel launch.json del progetto audio.
- Collaudo: `python prova_api.py` (deve dire TUTTO OK).
- Password: mai in chat. Demo in `dati-demo\credenziali-demo.txt`, primo dirigente in `dati\primo-accesso.txt`.
- **Niente push su GitHub** (regola dell'utente per i progetti nuovi): solo commit locali.
- Non usare nomi o marchi Argo nell'interfaccia (a parte "Credenziali Argo" per l'accesso).
- Accesso Argo (14/11): `argo.py` (OIDC come Documents\assenze-argo, solo stdlib, password mai salvata), impostazioni
  `argo_*`, colonna `utenti.argo_utente`, account "solo Argo" = hash vuoto. Collaudato con un finto Argo in prova_api.py
  e verificato che la pagina vera di Argo ha ancora il modulo `loginForm`. **Provato con credenziali vere il 14/11: funziona**
  (`avvia.bat`: Argo attivo, SC15290, account creati al primo accesso; il primo, Andrea, è dirigente). Claims ricevuti:
  given_name, family_name, full_name, email, preferred_username, cod_min (10), customer_code (7 = SC...), user_type,
  roles, licenses, tenancy, birthdate. Non ancora usati: email, user_type/roles (potrebbero dare docente/ATA). OTP non gestito.
  Non fare tentativi di accesso ad Argo con credenziali dell'utente: rischio di blocco dell'account.
- Assenze dalla segreteria (14/11): all'accesso Argo, `argo.leggi_personale` usa la stessa sessione SSO per entrare
  nel programma Personale (client OIDC `ad175860-...`, ritorno `/argopersonale/oidc-callback.html`), poi
  `POST personale.portaleargo.it/personale/rest/login` (Bearer) -> `uid` (= x-auth-token) e `uidSubAnagrafe`, e in sola
  lettura `assenza/search` (assenze registrate, numGiorni) e `richiestascodip/search` (richieste, codStato FWD/DAU/AUT...).
  Salvate in tabella `assenze_argo` (tipo mappato da `codParticolarita`, es. MOTPERS -> motivi_personali, FERIE -> ferie);
  `utilizzo()` le conta per prime e aggiunge le richieste dello Sportello solo se non si sovrappongono. Se la lettura
  fallisce l'accesso vale lo stesso (`utenti.argo_errore`, mostrato in Situazione). Endpoint verificati dal browser
  sulla pagina vera; il passaggio `login` è ricavato dal codice di argopersonale (app.js V.1.50.2).