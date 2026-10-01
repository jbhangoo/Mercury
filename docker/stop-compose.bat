@echo off
setlocal
pushd "%~dp0.."
docker compose -f docker\compose.yaml --project-directory . stop
set "result=%ERRORLEVEL%"
popd
exit /b %result%