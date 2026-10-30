@echo off
setlocal enabledelayedexpansion

echo ========================================================
echo   EdgeRAM-Optimizer - Standalone Executable Builder
echo ========================================================
echo.

cd /d "%~dp0"

:: 1. Locate PyInstaller
where pyinstaller >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    set "PYINSTALLER_CMD=pyinstaller"
) else if exist "%USERPROFILE%\anaconda3\Scripts\pyinstaller.exe" (
    set "PYINSTALLER_CMD=%USERPROFILE%\anaconda3\Scripts\pyinstaller.exe"
) else if exist "%LOCALAPPDATA%\Programs\Python\Python311\Scripts\pyinstaller.exe" (
    set "PYINSTALLER_CMD=%LOCALAPPDATA%\Programs\Python\Python311\Scripts\pyinstaller.exe"
) else (
    echo [ERROR] pyinstaller.exe was not found in PATH or standard python directories.
    echo Please install it using: pip install pyinstaller
    pause
    exit /b 1
)

:: 2. Ensure icon exists
if not exist "icon.ico" (
    echo [INFO] Generating icon.ico from Python script...
    python -c "from PIL import Image, ImageDraw; img = Image.new('RGBA', (64, 64), color=(0,0,0,0)); d = ImageDraw.Draw(img); d.ellipse([4, 4, 60, 60], fill='#0f172a', outline='#0ea5e9', width=3); d.polygon([(32, 12), (20, 36), (30, 36), (26, 52), (44, 28), (34, 28)], fill='#38bdf8'); img.save('icon.ico', sizes=[(16,16),(32,32),(48,48),(64,64)])" 2>nul
)

echo [INFO] Bundling standalone executable via PyInstaller...
echo [INFO] Including CustomTkinter assets, Win32 bindings, and Tray daemon...
echo.

"%PYINSTALLER_CMD%" ^
    --noconsole ^
    --onefile ^
    --icon=icon.ico ^
    --name="EdgeRAM-Optimizer" ^
    --collect-all customtkinter ^
    --hidden-import win32com.client ^
    --hidden-import pystray ^
    --hidden-import PIL ^
    main.py

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ========================================================
    echo [SUCCESS] EdgeRAM-Optimizer built successfully!
    echo Portable Executable Location:
    echo   %~dp0dist\EdgeRAM-Optimizer.exe
    echo ========================================================
) else (
    echo.
    echo [ERROR] Build failed with exit code %ERRORLEVEL%.
)

endlocal
if not "%CI%"=="true" if not "%NONINTERACTIVE%"=="1" pause
