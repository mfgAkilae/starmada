param([string]$Run = 'play1', [int]$DumpEvery = 100, [int]$ExitAfter = 160000)
# Start two active human slots with the test-only virtual input device.
$ErrorActionPreference = 'Stop'
$base = Split-Path -Parent $PSScriptRoot
$py = Join-Path $base '.venv\Scripts\python.exe'
$gameA = Join-Path $base 'work\play_clients\live\A'
$gameB = Join-Path $base 'work\play_clients\live\B'
if ($Run -notmatch '^[A-Za-z0-9_-]+$') { throw 'Invalid run name.' }
if (!(Test-Path -LiteralPath "$gameA\Armada.exe") -or !(Test-Path -LiteralPath "$gameB\Armada.exe")) {
    throw 'Prepare the fixed game copies with: python tools\prepare_play_test.py live'
}
$ownedPaths = @("$gameA\Armada.exe", "$gameB\Armada.exe")
if (Get-Process Armada -ErrorAction SilentlyContinue | Where-Object { $_.Path -in $ownedPaths }) {
    throw 'A live test fixture is already running. Close that run before starting another.'
}
$runDir = Join-Path $base "work\det\$Run"
if (Test-Path -LiteralPath $runDir) { throw 'Run already exists; choose a new run name.' }
New-Item -ItemType Directory $runDir | Out-Null
$request = Join-Path $runDir 'firewall_request.json'
@{programs=$ownedPaths; result=(Join-Path $runDir 'firewall_result.json')} |
    ConvertTo-Json | Set-Content -LiteralPath $request -Encoding UTF8
& powershell.exe -NoProfile -File (Join-Path $PSScriptRoot 'configure_game_firewall.ps1') -Request $request
if ($LASTEXITCODE -ne 0) { throw 'Game firewall preflight failed; no game started.' }
foreach ($game in @($gameA, $gameB)) {
    Copy-Item -LiteralPath (Join-Path $base 'src\strlkup_proxy\build_test\Strlkup.dll') -Destination (Join-Path $game 'Strlkup.dll') -Force
}
Start-Process -FilePath $py -ArgumentList @((Join-Path $PSScriptRoot 'mouse_watchdog.py'), '45', (Join-Path $base "work\watchdog_$Run.log"), $runDir) -WindowStyle Hidden | Out-Null
$env:ARMADA_TEST_INPUT = '1'
$env:ARMADA_TEST_NATIVE_MODE_INIT = '1'
& (Join-Path $PSScriptRoot 'mp_match.ps1') -Run $Run -DumpEvery $DumpEvery -ExitAfter $ExitAfter -AiSlots 0 -GameDirA $gameA -GameDirB $gameB -NativeWindow
foreach ($tag in @('A','B')) {
    & $py (Join-Path $PSScriptRoot 'test_window_render.py') $Run $tag --live-only
    if ($LASTEXITCODE -ne 0) {
        foreach ($owned in @('A','B')) { & $py (Join-Path $PSScriptRoot 'play_input.py') $Run $owned close }
        throw "Native-window rendering failed on client $tag; stopped this test run."
    }
}
"native-window rendering checked on both clients: $Run"
