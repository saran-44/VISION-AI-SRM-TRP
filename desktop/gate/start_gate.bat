@echo off
setlocal
cd /d "%~dp0\..\.."

rem Use gate virtual environment if available, else system python
if exist ".venv-gate\Scripts\python.exe" (
    set "PYTHON_EXE=.venv-gate\Scripts\python.exe"
) else if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

echo Starting VISION AI - SRM TRP Gate Portal...
"%PYTHON_EXE%" desktop\gate\launcher.py %*
endlocal
