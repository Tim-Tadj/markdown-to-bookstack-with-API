@echo off
setlocal EnableExtensions EnableDelayedExpansion

echo === Python + uv bootstrap ===

rem Detect an existing Python
set "PYTHON="
where python >nul 2>&1 && set "PYTHON=python"
if not defined PYTHON (
    where py >nul 2>&1 && set "PYTHON=py -3"
)

if not defined PYTHON (
    echo [i] Python not found. Attempting installation via winget...
    where winget >nul 2>&1
    if %errorlevel%==0 (
        rem Prefer a recent Python 3.12 line; winget handles architecture
        winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
        if %errorlevel% neq 0 (
            echo [!] winget install failed. Falling back to direct download.
            goto :install_python_direct
        )
    ) else (
        echo [i] winget not available. Falling back to direct download.
        goto :install_python_direct
    )

    rem Re-detect Python after winget install
    where python >nul 2>&1 && set "PYTHON=python"
    if not defined PYTHON (
        where py >nul 2>&1 && set "PYTHON=py -3"
    )
)

if not defined PYTHON (
    echo [!] Python still not found after installation. Please restart your terminal and rerun.
    exit /b 1
)

echo [=] Using Python: %PYTHON%

rem Ensure pip is present and current
%PYTHON% -m ensurepip --upgrade >nul 2>&1
%PYTHON% -m pip install --upgrade pip setuptools wheel
if %errorlevel% neq 0 (
    echo [!] Failed to upgrade pip/setuptools/wheel. Continuing.
)

rem Check/install uv
set "UVCMD="
where uv >nul 2>&1 && set "UVCMD=uv"
if not defined UVCMD (
    echo [i] uv not found. Installing via pip...
    %PYTHON% -m pip install -U uv
    if %errorlevel% neq 0 (
        echo [!] pip install uv failed.
    )
    where uv >nul 2>&1 && set "UVCMD=uv"
)

if not defined UVCMD (
    rem Fallback to module invocation if console script not on PATH
    %PYTHON% -m uv --version >nul 2>&1
    if %errorlevel%==0 (
        set "UVCMD=%PYTHON% -m uv"
    ) else (
        echo [!] uv is not available after installation attempts. Aborting.
        exit /b 1
    )
)

echo [=] Using uv: %UVCMD%

rem Install dependencies via uv if a requirements.txt is present
if exist requirements.txt (
    echo [i] Installing dependencies from requirements.txt with uv...
    %UVCMD% pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo [!] Dependency installation failed.
        exit /b 1
    )
    echo [✓] Dependencies installed.
 ) else (
    echo [i] No requirements.txt found. Skipping dependency install.
)

echo [✓] Bootstrap complete.
exit /b 0

:install_python_direct
set "PY_TMP=%TEMP%\python-installer.exe"
echo [i] Downloading Python installer...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Uri https://www.python.org/ftp/python/3.12.6/python-3.12.6-amd64.exe -OutFile '%PY_TMP%'; exit 0 } catch { exit 1 }"
if %errorlevel% neq 0 (
    echo [!] Failed to download Python installer. Please install Python manually from https://www.python.org/downloads/windows/
    exit /b 1
)
echo [i] Running Python installer (quiet)...
"%PY_TMP%" /quiet PrependPath=1 Include_pip=1
set "_inst_err=%errorlevel%"
del /f /q "%PY_TMP%" >nul 2>&1
if not "%_inst_err%"=="0" (
    echo [!] Python installer returned error %_inst_err%.
    exit /b %_inst_err%
)

rem Re-detect Python after direct install
where python >nul 2>&1 && set "PYTHON=python"
if not defined PYTHON (
    where py >nul 2>&1 && set "PYTHON=py -3"
)
goto :eof

