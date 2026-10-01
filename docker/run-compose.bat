@echo off
setlocal
pushd "%~dp0.."
docker compose -f docker\compose.yaml --project-directory . up --build -d
set "result=%ERRORLEVEL%"
if not "%result%"=="0" goto finish
start "" "http://localhost:8080/"
:finish
popd
exit /b %result%