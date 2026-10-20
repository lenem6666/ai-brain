@echo off
rem Portable launcher: works from any install path (%~dp0 = ...\ai-brain\bin\)
rem Note: do NOT force PYTHONIOENCODING=utf-8 here - it makes Chinese output
rem unreadable in Windows PowerShell consoles (GBK). Python follows the console.
setlocal
set "BRAIN_HOME=%~dp0.."
for %%I in ("%BRAIN_HOME%") do set "BRAIN_HOME=%%~fI"
"%BRAIN_HOME%\runtime\python.exe" "%BRAIN_HOME%\brain.py" %*
