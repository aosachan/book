@echo off
setlocal
cd /d "%~dp0"

if exist "runtime\pythonw.exe" goto run_bundled
if exist ".venv\Scripts\pythonw.exe" goto run

set "LRA_PYTHON="
where py >nul 2>nul
if not errorlevel 1 set "LRA_PYTHON=py -3"
if not defined LRA_PYTHON (
  where python >nul 2>nul
  if not errorlevel 1 set "LRA_PYTHON=python"
)
if not defined LRA_PYTHON if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" set "LRA_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if not defined LRA_PYTHON (
  echo Python 3.10 or newer was not found.
  echo Install Python from python.org, then double-click start.bat again.
  pause
  exit /b 1
)

echo Creating the private runtime on first launch...
%LRA_PYTHON% -c "import PIL" >nul 2>nul
if errorlevel 1 (
  %LRA_PYTHON% -m venv ".venv"
  if errorlevel 1 goto setup_error
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto setup_error
) else (
  %LRA_PYTHON% -m venv --system-site-packages ".venv"
  if errorlevel 1 goto setup_error
)

:run
if "%LRA_SMOKE_TEST%"=="1" (
  ".venv\Scripts\python.exe" -m reading_assistant --smoke-test
  exit /b %errorlevel%
)
start "Local Reading Assistant" ".venv\Scripts\pythonw.exe" -m reading_assistant
exit /b 0

:run_bundled
set "LRA_RUNTIME=%CD:\=/%/runtime"
set "TCL_LIBRARY=%LRA_RUNTIME%/tcl/tcl8.6"
set "TK_LIBRARY=%LRA_RUNTIME%/tcl/tk8.6"
if "%LRA_SMOKE_TEST%"=="1" (
  "runtime\python.exe" -m reading_assistant --smoke-test
  exit /b %errorlevel%
)
start "Local Reading Assistant" "runtime\pythonw.exe" -m reading_assistant
exit /b 0

:setup_error
echo.
echo Setup failed. Check your Python installation and network connection, then retry.
pause
exit /b 1
