@echo off
setlocal

docker network inspect mercury >nul 2>&1
if errorlevel 1 (
    docker network create mercury >nul
    if errorlevel 1 exit /b 1
)

docker container inspect client >nul 2>&1
if not errorlevel 1 (
    docker start client
    exit /b
)

docker run -d --rm --name client --network mercury -p 8080:80 client-img
exit /b %ERRORLEVEL%