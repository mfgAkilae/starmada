@echo off
setlocal
set VCVARS=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars32.bat
if not exist "%VCVARS%" set VCVARS=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars32.bat
call "%VCVARS%" >nul || exit /b 1
cd /d "%~dp0.."
if not exist work\checks mkdir work\checks
cl /nologo /O2 /W4 /GS- /MT tools\test_render_mutex.c /Fowork\checks\test_render_mutex.obj /Fework\checks\test_render_mutex.exe /link kernel32.lib user32.lib || exit /b 1
work\checks\test_render_mutex.exe --legacy
set LEGACY_EXIT=%errorlevel%
if not "%LEGACY_EXIT%"=="42" (
  echo FAIL: legacy collision check returned %LEGACY_EXIT%, expected 42
  exit /b 1
)
work\checks\test_render_mutex.exe --legacy-wait
set WAIT_EXIT=%errorlevel%
if not "%WAIT_EXIT%"=="44" (
  echo FAIL: legacy wait cleanup check returned %WAIT_EXIT%, expected 44
  exit /b 1
)
work\checks\test_render_mutex.exe
exit /b %errorlevel%
