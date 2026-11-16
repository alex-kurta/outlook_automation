@echo off
setlocal EnableExtensions

REM ============================================================
REM  MailPlus Automation - one-shot setup
REM  Creates the .venv, installs Playwright + Chromium,
REM  creates .env from the template, and sets MAILPLUS_HOME.
REM ============================================================

set "PROJECT_DIR=%~dp0"
REM %~dp0 ends with a backslash; strip it for a clean path
set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

echo ============================================
echo  MailPlus Automation - Setup
echo  Project folder: %PROJECT_DIR%
echo ============================================
echo.

REM --- 0. Verify Python is available ----------------------
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python was not found on PATH.
    echo         Install Python 3.x, then run setup again.
    echo.
    pause
    exit /b 1
)

REM --- 1. Create virtual environment -------------------------
if exist ".venv\Scripts\python.exe" (
    echo [1/5] Virtual environment already exists.
) else (
    echo [1/5] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 goto :error
)

REM --- 2. Upgrade pip ----------------------------------------
echo [2/5] Upgrading pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error

REM --- 3. Install Playwright --------------------------------
echo [3/5] Installing Playwright...
".venv\Scripts\python.exe" -m pip install playwright
if errorlevel 1 goto :error

REM --- 4. Install Chromium browser --------------------------
echo [4/5] Installing Chromium browser...
".venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 goto :error

REM --- 5. Create .env from template if missing --------------
if exist ".env" (
    echo [5/5] .env already exists - leaving it untouched.
) else (
    echo [5/5] Creating .env from .env.example...
    copy ".env.example" ".env" >nul
    echo        Edit .env and fill in your DSM credentials.
)

REM --- 6. Set MAILPLUS_HOME for the VBA macros --------------
echo.
echo Setting MAILPLUS_HOME=%PROJECT_DIR%
setx MAILPLUS_HOME "%PROJECT_DIR%" >nul
if errorlevel 1 (
    echo [WARN] Could not set MAILPLUS_HOME automatically.
    echo        Set it manually, then restart Outlook:
    echo            setx MAILPLUS_HOME "%PROJECT_DIR%"
) else (
    echo [OK] MAILPLUS_HOME set. Restart Outlook for it to take effect.
)

echo.
echo ============================================
echo  Setup complete!
echo.
echo  Next steps:
echo   1. Edit .env with your DSM URL, username, password.
echo   2. Close and reopen Outlook.
echo   3. Import OutlookMacros.bas  (Alt+F11 ^> File ^> Import File).
echo   4. Run the TestConfig macro to verify everything.
echo ============================================
echo.
pause
exit /b 0

:error
echo.
echo [ERROR] Setup failed. See the messages above.
echo.
pause
exit /b 1