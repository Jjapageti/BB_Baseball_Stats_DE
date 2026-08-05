@echo off
cd /d "%~dp0"
start "" http://localhost:8000/dashboard.html
py -m http.server 8000
pause
