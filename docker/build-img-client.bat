@echo off
setlocal
pushd "%~dp0.."
docker build -t client-img -f client\Dockerfile client
set "result=%ERRORLEVEL%"
popd
exit /b %result%