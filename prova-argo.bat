@echo off
rem Prima prova sul campo con le credenziali Argo.
rem Crea il tuo account (ruolo dirigente, per vedere anche la Gestione), attiva Argo e avvia lo Sportello.
cd /d "%~dp0"
set /p UTENTE=Il tuo nome utente Argo: 
set /p CODICE=Codice scuola su Argo (invio = SC15290): 
if "%CODICE%"=="" set CODICE=SC15290
start "" http://localhost:8850
python server.py --porta 8850 --attiva-argo %CODICE% --collega-argo %UTENTE% --ruolo dirigente
pause
