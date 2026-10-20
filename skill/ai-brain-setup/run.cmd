@echo off
rem ai-brain bootstrap launcher.
rem Finds a python interpreter, then runs scripts\ensure.py with the same args.
rem ASCII only: cmd reads this file in the console codepage (GBK on zh-CN),
rem Chinese comments here have broken the script before.
setlocal enabledelayedexpansion
set "HERE=%~dp0"
set "PYEXE="

if defined BRAIN_PY if exist "%BRAIN_PY%" set "PYEXE=%BRAIN_PY%"
if not defined PYEXE call :findpy

if not defined PYEXE (
  echo [FAIL] No python found.
  echo        Install Python 3.8+ or set BRAIN_PY to a python.exe path.
  echo        WorkBuddy ships one under .workbuddy\binaries\python\versions\
  exit /b 4
)

"%PYEXE%" "%HERE%scripts\ensure.py" %*
exit /b %ERRORLEVEL%

:findpy
for /f "delims=" %%I in ('where python 2^>nul') do (
  if not defined PYEXE set "PYEXE=%%I"
)
for /f "delims=" %%I in ('where python3 2^>nul') do (
  if not defined PYEXE set "PYEXE=%%I"
)
if not defined PYEXE if exist "D:\WorkBuddy\.workbuddy\binaries\python\versions" (
  for /d %%D in ("D:\WorkBuddy\.workbuddy\binaries\python\versions\*") do (
    if exist "%%D\python.exe" set "PYEXE=%%D\python.exe"
  )
)
if not defined PYEXE if exist "%LOCALAPPDATA%\Programs\Python" (
  for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
    if exist "%%D\python.exe" set "PYEXE=%%D\python.exe"
  )
)
goto :eof
