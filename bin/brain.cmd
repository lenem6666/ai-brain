@echo off
rem Portable launcher: works from any install path (%~dp0 = ...\ai-brain\bin\)
setlocal
set "BRAIN_HOME=%~dp0.."
for %%I in ("%BRAIN_HOME%") do set "BRAIN_HOME=%%~fI"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
"%BRAIN_HOME%\runtime\python.exe" "%BRAIN_HOME%\brain.py" %*
