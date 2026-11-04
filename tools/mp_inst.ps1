param([string]$Tag = 'A', [string]$Run = 'mp1', [int]$DumpEvery = 50, [int]$ExitAfter = 0,
      [string]$GameDir = 'E:\dev\starmada\work\testrun',
      [int]$InjectStep = 0, [int]$InjectOrder = 0, [int]$InjectRepeat = 0, [switch]$NativeWindow)
# Starts one test instance for the two-instance multiplayer test bed (test proxy required).
$out = "E:\dev\starmada\work\det\$Run\$Tag"
New-Item -ItemType Directory -Force $out | Out-Null
Get-ChildItem $out -Filter 'step_*.txt' -ErrorAction SilentlyContinue | ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force -Confirm:$false }
$env:ARMADA_TEST_DUMP_EVERY = "$DumpEvery"
$env:ARMADA_TEST_DUMP_DIR = $out
$env:ARMADA_TEST_EXIT_AFTER = "$ExitAfter"
$env:ARMADA_TEST_MULTI = '1'
$env:ARMADA_TEST_INJECT_STEP = "$InjectStep"
$env:ARMADA_TEST_INJECT_ORDER = "$InjectOrder"
$env:ARMADA_TEST_INJECT_REPEAT = "$InjectRepeat"
# started without activation; the test proxy keeps the game in the background
$gameArguments = @('-nointro')
if ($NativeWindow) { $gameArguments += '-window' }
$id = & 'E:\dev\starmada\.venv\Scripts\python.exe' 'E:\dev\starmada\tools\start_bg.py' "$GameDir\Armada.exe" $GameDir @gameArguments
if ($LASTEXITCODE -ne 0 -or "$id" -notmatch '^\d+$') { throw 'Game process failed to start.' }
$id | Out-File -Encoding ascii "E:\dev\starmada\work\pid_$Tag.txt"
$id | Out-File -Encoding ascii "E:\dev\starmada\work\det\$Run\pid_$Tag.txt"
& 'E:\dev\starmada\.venv\Scripts\python.exe' (Join-Path $PSScriptRoot 'game_window_positions.py') restore $Run $Tag --timeout 20 --executable "$GameDir\Armada.exe"
if ($LASTEXITCODE -ne 0) { throw "Window position restore failed for client $Tag." }
"$Tag pid $id"
