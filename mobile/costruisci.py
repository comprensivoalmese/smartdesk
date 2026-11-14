"""Prepara il sito per GitHub Pages: presentazione (mobile/sito), app per telefono e tablet (mobile/app) e
pacchetto della versione per PC. Uso: python mobile/costruisci.py [cartella_di_uscita]  (predefinita: _sito)."""
import os
import shutil
import sys
import zipfile

QUI = os.path.dirname(os.path.abspath(__file__))
RADICE = os.path.dirname(QUI)
OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(RADICE, "_sito"))

shutil.rmtree(OUT, ignore_errors=True)
shutil.copytree(os.path.join(QUI, "sito"), OUT)
shutil.copytree(os.path.join(QUI, "app"), os.path.join(OUT, "app"))
for f in ("style.css", "icona.svg"):  # stessa grafica dell'app per PC
    shutil.copy(os.path.join(RADICE, "static", f), os.path.join(OUT, "app", f))
open(os.path.join(OUT, ".nojekyll"), "w").close()

# versione completa per PC (server Python): solo i file del programma, mai i dati
with zipfile.ZipFile(os.path.join(OUT, "SmartDesk-server.zip"), "w", zipfile.ZIP_DEFLATED) as z:
    for f in ("server.py", "argo.py", "README.md", "avvia.bat", "avvia-demo.bat"):
        if os.path.exists(os.path.join(RADICE, f)):
            z.write(os.path.join(RADICE, f), "SmartDesk/" + f)
    for f in sorted(os.listdir(os.path.join(RADICE, "static"))):
        z.write(os.path.join(RADICE, "static", f), "SmartDesk/static/" + f)
print("Sito pronto in", OUT)
