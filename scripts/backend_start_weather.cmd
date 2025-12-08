@echo off
REM Lancer le scheduler depuis la racine du projet
cd /d "%~dp0\.."
py -m app.scheduler
pause
