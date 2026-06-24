@echo off
setlocal

cd /d "%~dp0\.."

if not exist ".venv\Scripts\python.exe" (
    echo Missing .venv. Create it first with:
    echo py -3.11 -m venv .venv
    exit /b 1
)

call ".venv\Scripts\activate.bat"

python -m pip install --upgrade pip setuptools wheel
if errorlevel 1 exit /b %errorlevel%

python -m pip install -r prim_app\requirements.txt
if errorlevel 1 exit /b %errorlevel%

python -m pip install pyinstaller
if errorlevel 1 exit /b %errorlevel%

python -m PyInstaller PRIMAcquisition.spec --clean --noconfirm
if errorlevel 1 exit /b %errorlevel%

set "ISCC="

for %%I in (ISCC.exe) do if not "%%~$PATH:I"=="" set "ISCC=%%~$PATH:I"

if not exist "%ISCC%" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%USERPROFILE%\AppData\Local\Programs\Inno Setup 6\ISCC.exe"

if not exist "%ISCC%" (
    echo Inno Setup Compiler not found.
    echo Install it with:
    echo winget install -e --id JRSoftware.InnoSetup
    echo.
    echo If winget says it is already installed, locate ISCC.exe with:
    echo dir /s /b "%LOCALAPPDATA%\Programs\ISCC.exe"
    exit /b 1
)

"%ISCC%" installer\PRIMA.iss
if errorlevel 1 exit /b %errorlevel%

echo.
echo Installer created in installer\output
