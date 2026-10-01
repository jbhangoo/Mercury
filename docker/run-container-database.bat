@echo off
setlocal

docker network inspect mercury >nul 2>&1
if errorlevel 1 (
    docker network create mercury >nul
    if errorlevel 1 exit /b 1
)

docker container inspect database >nul 2>&1
if not errorlevel 1 (
    docker start database
    exit /b
)

docker run -d --rm --name database --network mercury -p 5433:5432 -e POSTGRES_DB=mercury -e POSTGRES_USER=mercury -e POSTGRES_PASSWORD=mercury_dev_password -v mercury-db-data:/var/lib/postgresql database-img
exit /b %ERRORLEVEL%