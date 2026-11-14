@echo off
rem Sportello Personale - si entra con le credenziali Argo (nome.cognome.SC15290).
rem Il primo che entra diventa amministratore (ruolo dirigente); gli altri entrano come docenti e la segreteria corregge il ruolo.
rem Per farlo usare anche dai telefoni della rete della scuola aggiungere --host 0.0.0.0 (e aprire la porta 8850 nel firewall).
cd /d "%~dp0"
start "" http://localhost:8850
python server.py --porta 8850 --attiva-argo SC15290 --argo-nuovi
pause
