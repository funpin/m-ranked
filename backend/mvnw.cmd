@echo off
setlocal
set BASE_DIR=%~dp0
set MAVEN_VERSION=3.9.11
if "%MAVEN_USER_HOME%"=="" (set WRAPPER_ROOT=%USERPROFILE%\.m2) else (set WRAPPER_ROOT=%MAVEN_USER_HOME%)
set WRAPPER_HOME=%WRAPPER_ROOT%\wrapper\dists\apache-maven-%MAVEN_VERSION%
set MAVEN_BIN=%WRAPPER_HOME%\apache-maven-%MAVEN_VERSION%\bin\mvn.cmd
if not exist "%MAVEN_BIN%" (
  if not exist "%WRAPPER_HOME%" mkdir "%WRAPPER_HOME%"
  set ARCHIVE=%WRAPPER_HOME%\apache-maven-%MAVEN_VERSION%-bin.tar.gz
  if not exist "%ARCHIVE%" powershell -NoProfile -Command "$u=(Select-String -Path '%BASE_DIR%.mvn\wrapper\maven-wrapper.properties' -Pattern '^distributionUrl=').Line.Substring(16); Invoke-WebRequest -Uri $u -OutFile '%ARCHIVE%'"
  powershell -NoProfile -Command "$e=(Select-String -Path '%BASE_DIR%.mvn\wrapper\maven-wrapper.properties' -Pattern '^distributionSha256Sum=').Line.Substring(22); $a=(Get-FileHash -Algorithm SHA256 -Path '%ARCHIVE%').Hash.ToLowerInvariant(); if ($a -ne $e) { throw 'Maven distribution checksum verification failed' }"
  if errorlevel 1 exit /b 1
  tar -xzf "%ARCHIVE%" -C "%WRAPPER_HOME%"
)
call "%MAVEN_BIN%" -f "%BASE_DIR%pom.xml" %*
