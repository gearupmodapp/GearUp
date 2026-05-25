echo off
cd /d %~dp0
technyx_toolset hdr_to_wav %*
if %errorlevel% NEQ 0 pause
