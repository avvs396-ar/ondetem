@echo off
chcp 65001 >nul
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  set "PYTHON_CMD=.venv\Scripts\python.exe"
) else (
  py --version >nul 2>&1
  if errorlevel 1 (
    set "PYTHON_CMD=python"
  ) else (
    set "PYTHON_CMD=py"
  )
)

%PYTHON_CMD% -c "import fastapi, uvicorn" >nul 2>&1
if errorlevel 1 (
  echo Instalando dependencias do OndeTem 3.0...
  %PYTHON_CMD% -m pip install -r requirements.txt
  if errorlevel 1 goto erro
)

echo ==================================================
echo   OndeTem 3.0 - FastAPI + PostgreSQL/SQLite
echo   Site: http://127.0.0.1:8001
echo   API Docs: http://127.0.0.1:8001/docs
echo ==================================================
start "" "http://127.0.0.1:8001"
%PYTHON_CMD% app.py
goto fim

:erro
echo Erro ao iniciar o OndeTem. Verifique se o Python 3.10+ esta instalado.
pause

:fim
