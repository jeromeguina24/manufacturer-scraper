@echo off
rem Scheduler-friendly wrapper: run the scraper from the repo directory
rem using the project venv. Logs land in logs\YYYY-MM-DD.log.
cd /d "%~dp0"
if not exist logs mkdir logs
for /f "tokens=2 delims==" %%a in ('wmic os get localdatetime /value') do set dt=%%a
set stamp=%dt:~0,4%-%dt:~4,2%-%dt:~6,2%
".venv\Scripts\python.exe" -m manufacturer_scraper run %* >> "logs\%stamp%.log" 2>&1
