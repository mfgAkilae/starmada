@echo off
rem Builds the 32-bit Strlkup.dll runtime proxy (cursor fix, GOG wrapper mapping isolation).
rem Needs Visual Studio 2022 Build Tools with the x86 toolset. Output: build\Strlkup.dll
setlocal
set VCVARS=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars32.bat
if not exist "%VCVARS%" set VCVARS=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars32.bat
call "%VCVARS%" >nul || exit /b 1
cd /d "%~dp0"
if not exist build mkdir build
cl /nologo /O2 /W4 /GS- /MT /LD strlkup_proxy.c /Fobuild\ /Febuild\Strlkup.dll /link /NODEFAULTLIB:libcmt /ENTRY:DllMain /SUBSYSTEM:WINDOWS kernel32.lib user32.lib || exit /b 1
echo built %~dp0build\Strlkup.dll
