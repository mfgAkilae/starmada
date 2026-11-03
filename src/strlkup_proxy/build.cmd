@echo off
rem Builds the 32-bit Strlkup.dll runtime proxy (cursor fix, GOG wrapper mapping isolation).
rem Needs Visual Studio 2022 Build Tools with the x86 toolset. Output: build\Strlkup.dll
rem "build.cmd test" builds the test bed variant with ARMADA_TESTHOOKS into build_test\.
setlocal
set VCVARS=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars32.bat
if not exist "%VCVARS%" set VCVARS=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars32.bat
call "%VCVARS%" >nul || exit /b 1
cd /d "%~dp0"
set OUT=build
set DEFS=
if /i "%1"=="test" (
  set OUT=build_test
  set DEFS=/DARMADA_TESTHOOKS
)
if not exist %OUT% mkdir %OUT%
cl /nologo /O2 /W4 /GS- /MT /LD %DEFS% strlkup_proxy.c /Fo%OUT%\ /Fe%OUT%\Strlkup.dll /link /NODEFAULTLIB:libcmt /ENTRY:DllMain /SUBSYSTEM:WINDOWS kernel32.lib user32.lib || exit /b 1
echo built %~dp0%OUT%\Strlkup.dll
