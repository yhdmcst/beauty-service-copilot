@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -NoExit -ExecutionPolicy Bypass -File "%~dp0scripts\connect_remote_model.ps1"
