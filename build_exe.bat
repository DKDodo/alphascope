@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv" (
    echo Virtual environment not found. Run run.bat once first, then re-run this script.
    exit /b 1
)

call ".venv\Scripts\activate.bat"

echo Installing PyInstaller...
pip install pyinstaller >nul

echo Building AlphaScope.exe (this can take several minutes)...
python -m PyInstaller --noconfirm --clean --onefile --name AlphaScope -d noarchive ^
    --collect-all uvicorn ^
    --collect-all yfinance ^
    --collect-all transformers ^
    --collect-all webview ^
    --collect-all clr_loader ^
    --copy-metadata torch --copy-metadata transformers --copy-metadata tokenizers ^
    --copy-metadata regex --copy-metadata requests --copy-metadata packaging ^
    --copy-metadata filelock --copy-metadata numpy --copy-metadata tqdm ^
    --copy-metadata huggingface-hub --copy-metadata safetensors --copy-metadata pyyaml ^
    --hidden-import app.market_data.providers.massive_provider ^
    --hidden-import winotify ^
    --add-data "app\web;app\web" ^
    --icon "app_icon.ico" ^
    desktop_launcher.py

if not exist "dist\AlphaScope.exe" (
    echo Build failed - dist\AlphaScope.exe was not created.
    pause
    exit /b 1
)

echo.
echo Build complete: dist\AlphaScope.exe
echo Creating a Desktop shortcut...

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ws = New-Object -ComObject WScript.Shell;" ^
    "$shortcut = $ws.CreateShortcut((Join-Path $ws.SpecialFolders('Desktop') 'AlphaScope.lnk'));" ^
    "$shortcut.TargetPath = (Resolve-Path 'dist\AlphaScope.exe').Path;" ^
    "$shortcut.WorkingDirectory = (Resolve-Path 'dist').Path;" ^
    "$shortcut.Description = 'AlphaScope - market scanner (paper trading only)';" ^
    "$shortcut.Save()"

echo Desktop shortcut created: AlphaScope.lnk
pause
