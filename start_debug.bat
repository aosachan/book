@echo off
setlocal
cd /d "%~dp0"
if exist "runtime\python.exe" (
  set "LRA_RUNTIME=%CD:\=/%/runtime"
  set "TCL_LIBRARY=%LRA_RUNTIME%/tcl/tcl8.6"
  set "TK_LIBRARY=%LRA_RUNTIME%/tcl/tk8.6"
  "runtime\python.exe" -m reading_assistant
  if errorlevel 1 pause
  exit /b %errorlevel%
)
if not exist ".venv\Scripts\python.exe" (
  echo Run start.bat once to create .venv first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m reading_assistant
if errorlevel 1 pause
