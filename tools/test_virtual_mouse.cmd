@echo off
setlocal
set VCVARS=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars32.bat
if not exist "%VCVARS%" set VCVARS=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars32.bat
call "%VCVARS%" >nul || exit /b 1
cd /d "%~dp0.."
if not exist work\checks mkdir work\checks
cl /nologo /O2 /W4 /GS- /MT tools\test_virtual_mouse.c /Fowork\checks\test_virtual_mouse.obj /Fework\checks\test_virtual_mouse.exe /link kernel32.lib user32.lib ole32.lib uuid.lib || exit /b 1
.venv\Scripts\python.exe -c "import subprocess,sys; result=subprocess.run([r'work\checks\test_virtual_mouse.exe'],creationflags=subprocess.CREATE_NO_WINDOW,capture_output=True,text=True); sys.stdout.write(result.stdout); sys.stderr.write(result.stderr); sys.exit(result.returncode)"
exit /b %errorlevel%
