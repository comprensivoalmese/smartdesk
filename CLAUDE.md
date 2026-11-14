# Note per Claude: Sportello Personale

App web per le esigenze del personale scolastico, modello Argo Unica (richieste di assenza con verifica
segreteria -> autorizzazione dirigente/DSGA, bacheca con presa visione/adesione, timbrature e cartellino,
documenti personali, gestione). Creata il 14/11/2026 per Andrea Giorda. Si lavora **in italiano**.

- Solo libreria standard Python: `server.py` (API + SQLite + dati di prova), `static/` (index.html, app.js, style.css).
- Porte: 8850 uso vero, 8851 demo (`--dati dati-demo --demo`). Voce "sportello-personale" nel launch.json del progetto audio.
- Collaudo: `python prova_api.py` (deve dire TUTTO OK).
- Password: mai in chat. Demo in `dati-demo\credenziali-demo.txt`, primo dirigente in `dati\primo-accesso.txt`.
- **Niente push su GitHub** (regola dell'utente per i progetti nuovi): solo commit locali.
- Non usare nomi o marchi Argo nell'interfaccia.
