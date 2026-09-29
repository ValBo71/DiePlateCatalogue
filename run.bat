@echo off
title Printing Catalog Server
echo Checking environment...

:: 0. Create a Desktop shortcut with a custom icon on first run
if not exist "%USERPROFILE%\Desktop\Printing Catalog.lnk" (
    if exist "%~dp0assets\icon.ico" (
        echo Creating Desktop shortcut...
        powershell -NoProfile -Command "$s = (New-Object -ComObject WScript.Shell).CreateShortcut('%USERPROFILE%\Desktop\Printing Catalog.lnk'); $s.TargetPath = '%~f0'; $s.WorkingDirectory = '%~dp0'; $s.IconLocation = '%~dp0assets\icon.ico'; $s.Save()"
    )
)

:: 1. Check if system python is available in PATH
python --version >nul 2>&1
if errorlevel 1 goto nopathpython
echo System Python found. Using system Python...
set PYTHON_EXE=python
goto setup_venv

:nopathpython
:: 2. If system Python is not in PATH, check if portable Python is already installed in the folder
if exist python_portable\python.exe (
    echo Portable Python found. Using portable Python...
    set PYTHON_EXE=python_portable\python.exe
    goto run_pip
)

echo System Python not found. Installing portable Python environment...
echo Downloading Python 3.11 Portable (this will take a moment)...

:: Download embedded Python 3.11.9 zip
powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip' -OutFile 'python_embed.zip'"
if errorlevel 1 goto downloaderror

echo Extracting Python...
powershell -Command "Expand-Archive -Path 'python_embed.zip' -DestinationPath 'python_portable' -Force"
if errorlevel 1 goto extracterror

echo Configuring Python paths...
:: Enable site-packages in embedded python (uncomment "import site" in the ._pth file)
powershell -Command "(Get-Content python_portable/python311._pth) -replace '#import site', 'import site' | Set-Content python_portable/python311._pth"

echo Installing Package Manager (pip)...
powershell -Command "Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile 'get-pip.py'"
python_portable\python.exe get-pip.py --no-warn-script-location --disable-pip-version-check

:: Clean up download files
if exist python_embed.zip del python_embed.zip
if exist get-pip.py del get-pip.py

set PYTHON_EXE=python_portable\python.exe
goto run_pip

:setup_venv
:: Create and use virtual environment for system Python
if exist .venv goto activate_venv
echo Creating virtual environment...
%PYTHON_EXE% -m venv .venv

:activate_venv
echo Activating virtual environment...
call .venv\Scripts\activate
set PYTHON_EXE=python
:: Fall through to run_pip

:run_pip
echo Installing/Verifying dependencies...
%PYTHON_EXE% -m pip install -r requirements.txt
if errorlevel 1 goto piperror

:: Ensure required directories exist
if not exist database mkdir database
if not exist uploads mkdir uploads

:: Clear any leftover exit marker from a previous crashed run
if exist database\.exit_requested del database\.exit_requested

echo Server is starting...
start "" "http://localhost:5050"
%PYTHON_EXE% app.py

:: The app's Exit button writes this marker just before shutting itself down,
:: so we can close the window automatically instead of pausing - a Ctrl+C or
:: crash leaves no marker, so the pause below still shows for those cases.
if exist database\.exit_requested goto clean_exit
goto end

:downloaderror
echo Error: Failed to download portable Python! Please check your internet connection.
pause
goto end

:extracterror
echo Error: Failed to extract Python files!
pause
goto end

:piperror
echo Error: Failed to install Python dependencies!
pause
goto end

:clean_exit
del database\.exit_requested
exit /b 0

:end
pause
