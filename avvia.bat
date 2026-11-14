@echo off
rem Sportello Personale - avvio sul PC della segreteria.
rem Per farlo usare anche dai telefoni della rete della scuola, togliere "rem" dalla riga con 0.0.0.0
cd /d "%~dp0"
start "" http://localhost:8850
python server.py --porta 8850
rem python server.py --porta 8850 --host 0.0.0.0
pause
