@echo off
rem ai-brain hourly sync, called by scheduled task ai-brain-sync
rem Portable: the install root is derived from this file's location.
setlocal
set "BRAIN_HOME=%~dp0.."
for %%I in ("%BRAIN_HOME%") do set "BRAIN_HOME=%%~fI"
if not exist "%BRAIN_HOME%\logs" mkdir "%BRAIN_HOME%\logs"

rem Task Scheduler starts with a minimal PATH that often has no git.
rem Without this the hourly sync fails silently and machines never converge.
set "GITDIR="
if exist "D:\Program Files (x86)\WorkBuddy\resources\vendor\PortableGit\cmd\git.exe" set "GITDIR=D:\Program Files (x86)\WorkBuddy\resources\vendor\PortableGit\cmd"
if not defined GITDIR if exist "C:\Program Files\Git\cmd\git.exe" set "GITDIR=C:\Program Files\Git\cmd"
if not defined GITDIR if exist "%LOCALAPPDATA%\Programs\Git\cmd\git.exe" set "GITDIR=%LOCALAPPDATA%\Programs\Git\cmd"
if defined GITDIR set "PATH=%GITDIR%;%PATH%"

echo [%date% %time%] sync start>> "%BRAIN_HOME%\logs\sync.log"
"%BRAIN_HOME%\bin\brain.cmd" sync -m "auto-sync">> "%BRAIN_HOME%\logs\sync.log" 2>&1
echo [%date% %time%] exit=%ERRORLEVEL%>> "%BRAIN_HOME%\logs\sync.log"
endlocal
