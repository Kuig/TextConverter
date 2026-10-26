@echo off
REM Called by the Explorer context menu entries (see generate_registry_files.ps1):
REM   convert.cmd <source file> <target extension> [textconverter convert options]
REM Writes the result next to the source, with the target extension, through the
REM project's CLI. On failure the window stays open so the error can be read.
setlocal
set "EXE=%~dp0..\.venv\Scripts\textconverter.exe"
set "SOURCE=%~1"
set "OUTPUT=%~dpn1%~2"
set "OPTIONS="
shift
shift
:collect
if "%~1"=="" goto run
set "OPTIONS=%OPTIONS% %1"
shift
goto collect

:run
if not exist "%EXE%" (
    echo Error: %EXE% not found. Create the virtual environment and install the project first.
    pause
    exit /b 1
)
"%EXE%" convert "%SOURCE%" "%OUTPUT%"%OPTIONS%
if errorlevel 1 pause
