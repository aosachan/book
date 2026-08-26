@echo off
setlocal
cd /d "%~dp0"
if not exist "runtime\pythonw.exe" (
  echo Bundled runtime was not found.
  pause
  exit /b 1
)
set "LRA_RUNTIME=%CD:\=/%/runtime"
set "TCL_LIBRARY=%LRA_RUNTIME%/tcl/tcl8.6"
set "TK_LIBRARY=%LRA_RUNTIME%/tcl/tk8.6"
start "LRA Sample Reader" "runtime\pythonw.exe" "tools\sample_reader.py"
