@echo off
setlocal
set VCVARS=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars32.bat
if not exist "%VCVARS%" set VCVARS=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars32.bat
call "%VCVARS%" >nul || exit /b 1
cd /d "%~dp0.."
if not exist work\checks mkdir work\checks
cl /nologo /O2 /W4 /GS- /MT tools\test_ddraw_render_target.c /Fowork\checks\test_ddraw_render_target.obj /Fework\checks\test_ddraw_render_target.exe /link kernel32.lib user32.lib || exit /b 1
work\checks\test_ddraw_render_target.exe %*
if errorlevel 1 exit /b %errorlevel%
work\checks\test_ddraw_render_target.exe %* --relocate
exit /b %errorlevel%
