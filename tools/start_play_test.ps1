param([string]$Run = 'play1', [int]$DumpEvery = 100, [int]$ExitAfter = 160000,
      [ValidateRange(0,6)][int]$AiSlots = 0,
      [ValidateRange(1,1440)][int]$WatchdogMinutes = 180, [switch]$LobbyOnly, [switch]$LateGame,
      [ValidatePattern('^[A-Za-z0-9_-]+$')][string]$Fixture = 'live',
      [string]$GameName = '', [switch]$SessionListOnly)
# Start two active human slots with the test-only virtual input device.
$ErrorActionPreference = 'Stop'
if ($LateGame) {
    if (!$PSBoundParameters.ContainsKey('DumpEvery')) { $DumpEvery = 1000 }
    if (!$PSBoundParameters.ContainsKey('ExitAfter')) { $ExitAfter = 800000 }
    if (!$PSBoundParameters.ContainsKey('WatchdogMinutes')) { $WatchdogMinutes = 240 }
}
if ($DumpEvery -lt 1 -or $ExitAfter -lt 0) { throw 'Invalid dump interval or step limit.' }
$base = Split-Path -Parent $PSScriptRoot
$py = Join-Path $base '.venv\Scripts\python.exe'
$gameA = Join-Path $base "work\play_clients\$Fixture\A"
$gameB = Join-Path $base "work\play_clients\$Fixture\B"
if ($Run -notmatch '^[A-Za-z0-9_-]+$') { throw 'Invalid run name.' }
if (!$GameName) { $GameName = "Armada-$Run" }
if (!(Test-Path -LiteralPath "$gameA\Armada.exe") -or !(Test-Path -LiteralPath "$gameB\Armada.exe")) {
    throw "Prepare the game copies with: python tools\prepare_play_test.py $Fixture"
}
$ownedPaths = @("$gameA\Armada.exe", "$gameB\Armada.exe")
if (Get-Process Armada -ErrorAction SilentlyContinue | Where-Object { $_.Path -in $ownedPaths }) {
    throw 'A live test fixture is already running. Close that run before starting another.'
}
if (Get-Process Armada -ErrorAction SilentlyContinue) {
    throw 'Another Armada process is running. Close that match before starting a test pair; concurrent matches can fail GOG display initialization.'
}
$runDir = Join-Path $base "work\det\$Run"
if (Test-Path -LiteralPath $runDir) { throw 'Run already exists; choose a new run name.' }
New-Item -ItemType Directory $runDir | Out-Null
@{fixture=$Fixture; programs=$ownedPaths; late_game=[bool]$LateGame} |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runDir 'launch.json') -Encoding UTF8
$request = Join-Path $runDir 'firewall_request.json'
@{programs=$ownedPaths; result=(Join-Path $runDir 'firewall_result.json')} |
    ConvertTo-Json | Set-Content -LiteralPath $request -Encoding UTF8
& powershell.exe -NoProfile -File (Join-Path $PSScriptRoot 'configure_game_firewall.ps1') -Request $request
if ($LASTEXITCODE -ne 0) { throw 'Game firewall preflight failed; no game started.' }
foreach ($game in @($gameA, $gameB)) {
    Copy-Item -LiteralPath (Join-Path $base 'src\strlkup_proxy\build_test\Strlkup.dll') -Destination (Join-Path $game 'Strlkup.dll') -Force
}
Start-Process -FilePath $py -ArgumentList @((Join-Path $PSScriptRoot 'mouse_watchdog.py'), "$WatchdogMinutes", (Join-Path $base "work\watchdog_$Run.log"), $runDir) -WindowStyle Hidden | Out-Null
$env:ARMADA_TEST_INPUT = '1'
$env:ARMADA_TEST_NATIVE_MODE_INIT = '1'
try {
    & (Join-Path $PSScriptRoot 'mp_match.ps1') -Run $Run -DumpEvery $DumpEvery -ExitAfter $ExitAfter -AiSlots $AiSlots -GameDirA $gameA -GameDirB $gameB -NativeWindow -LobbyOnly:$LobbyOnly -LateGame:$LateGame -Fixture $Fixture -GameName $GameName -SessionListOnly:$SessionListOnly
    if ($LobbyOnly -or $SessionListOnly) { return }
    foreach ($tag in @('A','B')) {
        & $py (Join-Path $PSScriptRoot 'test_window_render.py') $Run $tag --live-only
        if ($LASTEXITCODE -ne 0) { throw "Native-window rendering failed on client $tag." }
        & $py (Join-Path $PSScriptRoot 'game_window_positions.py') restore $Run $tag
        if ($LASTEXITCODE -ne 0) { throw "Window position restore failed on client $tag." }
    }
} catch {
    foreach ($tag in @('A','B')) {
        $pidFile = Join-Path $runDir "pid_$tag.txt"
        if (Test-Path -LiteralPath $pidFile) {
            $gameProcess = Get-Process -Id ([int](Get-Content -LiteralPath $pidFile -Raw)) -ErrorAction SilentlyContinue
            if ($gameProcess -and $gameProcess.Path -in $ownedPaths) {
                & $py (Join-Path $PSScriptRoot 'play_input.py') $Run $tag close
            }
        }
    }
    throw
}
"native-window rendering checked on both clients: $Run"
