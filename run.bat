@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv" (
    echo Creating virtual environment...
    py -3.12 -m venv .venv 2>nul
    if errorlevel 1 (
        python -m venv .venv
    )
)

call ".venv\Scripts\activate.bat"

echo Installing dependencies...
python -m pip install --upgrade pip >nul
pip install -r requirements.txt

if not exist ".env" (
    copy ".env.example" ".env" >nul
)

echo Starting AlphaScope on http://127.0.0.1:8000/ ...
start "" "http://127.0.0.1:8000/"
uvicorn app.main:app --host 127.0.0.1 --port 8000

pause
