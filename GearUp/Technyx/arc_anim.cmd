echo off
cd /d %~dp0
technyx_toolset arc_anim %*
if %errorlevel% NEQ 0 pause
