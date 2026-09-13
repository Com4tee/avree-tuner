@echo off
chcp 65001 >nul
title AVREE Tuner
cd /d "%~dp0"

where python >/dev/null 2>&1
if errorlevel 1 (
    echo.
    echo Nie znalazlem Pythona w PATH.
    echo Zainstaluj Python 3.13+ z python.org i zaznacz "Add to PATH".
    echo.
    pause
    exit /b 1
)

python avree_tuner.py %*

if errorlevel 1 (
    echo.
    pause
)
