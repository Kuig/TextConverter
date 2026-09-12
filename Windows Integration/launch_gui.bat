@echo off
REM Launch TextConverter GUI via Streamlit.
REM Activates the venv and opens the web interface.
cd /d "%~dp0.."

if not exist ".venv\Scripts\activate.bat" (
    echo Error: virtual environment not found at .venv\Scripts\activate.bat
    echo Create it first with: python -m venv .venv
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
textconverter gui
