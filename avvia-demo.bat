@echo off
rem Sportello Personale con personale e dati di prova (cartella dati-demo)
cd /d "%~dp0"
start "" http://localhost:8851
python server.py --porta 8851 --dati dati-demo --demo
pause
