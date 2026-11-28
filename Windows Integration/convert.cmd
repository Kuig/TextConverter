@echo off
REM Called by the Explorer context menu entries (see generate_registry_files.ps1):
REM   convert.cmd <source file> <target extension> [textconverter convert options]
REM   convert.cmd --clipboard <folder> <target extension> [textconverter convert options]
REM Writes the result next to the source through the project's CLI, as
REM <name>_converted<ext>, or <name>_converted2<ext> and so on when such a file
REM exists (also as one of the <name>_converted_<sheet>.csv of a table per file):
REM no existing file is overwritten. The clipboard is written into the folder as
REM clipboard_converted<ext>, numbered the same way. On failure the window stays
REM open so the error can be read.
setlocal
set "EXE=%~dp0..\.venv\Scripts\textconverter.exe"
if /i "%~1"=="--clipboard" goto clipboard
set "SOURCE=%~1"
set "STEM=%~dpn1_converted"
goto extension

:clipboard
set "SOURCE="
set "STEM=%~f2\clipboard_converted"
shift

:extension
set "EXT=%~2"
set "NUMBER=1"
set "TAG="
:name
if not exist "%STEM%%TAG%*%EXT%" goto named
set /a NUMBER+=1
set "TAG=%NUMBER%"
goto name

:named
set "OUTPUT=%STEM%%TAG%%EXT%"
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
if not defined SOURCE goto paste
"%EXE%" convert "%SOURCE%" "%OUTPUT%"%OPTIONS%
goto done

:paste
"%EXE%" convert --clipboard "%OUTPUT%"%OPTIONS%

:done
if errorlevel 1 pause
