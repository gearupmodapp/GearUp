echo off
cd /d %~dp0
technyx_toolset arc_extract %*
if %errorlevel% NEQ 0 pause
