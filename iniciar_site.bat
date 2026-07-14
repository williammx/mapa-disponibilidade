@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo   Mapa de Disponibilidade - iniciando o site
echo ============================================================
echo.
echo [1/3] Encerrando qualquer servidor antigo na porta 8000...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1
echo.
echo [2/3] Instalando dependencias (pode demorar na primeira vez)...
py -3.13 -m pip install -r requirements.txt || python3.13 -m pip install -r requirements.txt
echo.
echo [3/3] Site no ar. Abra no navegador:  http://localhost:8000
echo Deixe esta janela aberta. Para parar, feche-a.
echo.
py -3.13 -m uvicorn api:app --port 8000 || python3.13 -m uvicorn api:app --port 8000
pause
