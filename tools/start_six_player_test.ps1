param(
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_-]*$')][string]$Run = 'agents6_1',
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_-]*$')][string]$Fixture = 'agents6_stock1',
    [ValidateRange(1,100000)][int]$DumpEvery = 1000,
    [ValidateRange(0,2000000)][int]$ExitAfter = 800000,
    [ValidateRange(1,1440)][int]$WatchdogMinutes = 240,
    [switch]$LobbyOnly
)
# One real LAN match: six human clients, no native AI or injected gameplay orders.
$ErrorActionPreference = 'Stop'
$base = Split-Path -Parent $PSScriptRoot
$py = Join-Path $base '.venv\Scripts\python.exe'
$tags = @('A','B','C','D','E','F')
$fixtureRoot = Join-Path $base "work\play_clients\$Fixture"
$runDir = Join-Path $base "work\det\$Run"
$gameName = "Armada-$Run"
$programs = @($tags | ForEach-Object { Join-Path $fixtureRoot "$_\Armada.exe" })
if (Get-Process Armada -ErrorAction SilentlyContinue) {
    throw 'Another Armada match is running. Preserve it and close it before starting this six-player match.'
}
if (Test-Path -LiteralPath $runDir) { throw 'Run already exists; choose a new Run name.' }
$fixtureInfo = Get-Content -LiteralPath (Join-Path $fixtureRoot 'fixture.json') -Raw | ConvertFrom-Json
if ((@($fixtureInfo.tags) -join ',') -ne ($tags -join ',')) {
    throw 'Prepare exactly six clients: python tools\prepare_play_test.py <fixture> --players 6'
}
foreach ($tag in $tags) {
    foreach ($name in @('Armada.exe','Strlkup.dll','ddraw.dll','dxcfg.ini','label.map')) {
        $file = Join-Path $fixtureRoot "$tag\$name"
        if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -ne $fixtureInfo.clients.$tag.$name) {
            throw "Fixture artifact changed before launch: $tag/$name"
        }
    }
}
New-Item -ItemType Directory -Path $runDir | Out-Null
function Write-JsonFile([string]$Path, $Value) {
    $json = $Value | ConvertTo-Json -Depth 10
    [IO.File]::WriteAllText($Path, $json + "`n", (New-Object Text.UTF8Encoding($false)))
}
function Invoke-GameTool([string]$Script, [string[]]$ToolArguments) {
    & $py (Join-Path $PSScriptRoot $Script) @ToolArguments
    if ($LASTEXITCODE -ne 0) { throw "Game tool failed: $Script" }
}
function Write-Phase([string]$Phase) {
    Write-JsonFile (Join-Path $runDir 'phase.json') @{utc=[DateTime]::UtcNow.ToString('o'); phase=$Phase}
    Write-Output $Phase
}
Write-JsonFile (Join-Path $runDir 'launch.json') @{
    schema=2; fixture=$Fixture; peers=$tags; programs=$programs
    human_clients=6; native_ai=0; gameplay='UI economy, fleet control and special abilities'
    gameplay_order_injection=@{step=0; order=0; repeat=0}
    created_utc=[DateTime]::UtcNow.ToString('o')
}
$firewallRequest = Join-Path $runDir 'firewall_request.json'
Write-JsonFile $firewallRequest @{programs=$programs; result=(Join-Path $runDir 'firewall_result.json')}
Write-Phase 'Checking six program-specific firewall rules'
& powershell.exe -NoProfile -File (Join-Path $PSScriptRoot 'configure_game_firewall.ps1') -Request $firewallRequest
if ($LASTEXITCODE -ne 0) { throw 'Firewall preflight failed; no clients started.' }
Write-Phase 'Installing test proxy in six verified fixtures'
$testProxy = Join-Path $base 'src\strlkup_proxy\build_test\Strlkup.dll'
foreach ($tag in $tags) {
    Copy-Item -LiteralPath $testProxy -Destination (Join-Path $fixtureRoot "$tag\Strlkup.dll") -Force
}
$prelaunch = @{}
foreach ($tag in $tags) {
    $hashes = @{}
    foreach ($name in @('Armada.exe','Strlkup.dll','Strlkup_orig.dll','ddraw.dll','dxcfg.ini','label.map')) {
        $hashes[$name] = (Get-FileHash -LiteralPath (Join-Path $fixtureRoot "$tag\$name") -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $prelaunch[$tag] = @{
        hashes=$hashes; command_line=@((Join-Path $fixtureRoot "$tag\Armada.exe"),'-nointro','-window')
        configuration=[IO.File]::ReadAllText((Join-Path $fixtureRoot "$tag\dxcfg.ini"))
    }
}
Write-JsonFile (Join-Path $runDir 'prelaunch.json') $prelaunch
Write-Phase 'Artifact hashes saved'
Start-Process -FilePath $py -ArgumentList @((Join-Path $PSScriptRoot 'mouse_watchdog.py'), "$WatchdogMinutes", (Join-Path $base "work\watchdog_$Run.log"), $runDir) -WindowStyle Hidden | Out-Null
$env:ARMADA_TEST_INPUT = '1'
$env:ARMADA_TEST_NATIVE_MODE_INIT = '1'
$env:ARMADA_RUN_DIR = $runDir
function Start-Peer([string]$Tag) {
    $prelaunch[$Tag].start_utc = [DateTime]::UtcNow.ToString('o')
    Write-JsonFile (Join-Path $runDir 'prelaunch.json') $prelaunch
    & (Join-Path $PSScriptRoot 'mp_inst.ps1') -Tag $Tag -Run $Run -GameDir (Join-Path $fixtureRoot $Tag) -NativeWindow -DumpEvery $DumpEvery -ExitAfter $ExitAfter
    $pidFile = Join-Path $runDir "pid_$Tag.txt"
    if (!(Test-Path -LiteralPath $pidFile)) { throw "No PID for client $Tag" }
    $prelaunch[$Tag].pid = [int](Get-Content -LiteralPath $pidFile -Raw)
    Write-JsonFile (Join-Path $runDir 'prelaunch.json') $prelaunch
    Start-Sleep -Seconds 10
}
try {
    Write-Phase 'Starting host A'
    Start-Peer 'A'
    Invoke-GameTool 'clk.py' @('A','555','20'); Start-Sleep -Seconds 8
    Invoke-GameTool 'clk.py' @('A','319','310'); Start-Sleep -Seconds 6
    Invoke-GameTool 'clk.py' @('A','292','215'); Start-Sleep -Seconds 4
    Invoke-GameTool 'set_game_name.py' @($Run,$gameName,'--fixture',$Fixture)
    Start-Sleep -Seconds 6
    Invoke-GameTool 'set_game_name.py' @($Run,$gameName,'--fixture',$Fixture,'--verify')
    Invoke-GameTool 'setup_six_player_lobby.py' @($Run,'--fixture',$Fixture,'--inspect')
    Invoke-GameTool 'setup_six_player_lobby.py' @($Run,'--fixture',$Fixture,'--host-only')
    foreach ($tag in $tags[1..5]) {
        Start-Peer $tag
        Invoke-GameTool 'clk.py' @($tag,'555','20'); Start-Sleep -Seconds 8
        Invoke-GameTool 'clk.py' @($tag,'319','310'); Start-Sleep -Seconds 25
        Invoke-GameTool 'select_lan_session.py' @($Run,$gameName,'--fixture',$Fixture,'--tag',$tag)
        Invoke-GameTool 'clk.py' @($tag,'160','215'); Start-Sleep -Seconds 12
        Invoke-GameTool 'shot.py' @($tag,(Join-Path $runDir "${tag}_joined.png"))
    }
    if ($LobbyOnly) { "All six clients joined: $Run"; return }
    Invoke-GameTool 'setup_six_player_lobby.py' @($Run,'--fixture',$Fixture)
    Invoke-GameTool 'clk.py' @('A','319','460'); Start-Sleep -Seconds 3
    foreach ($tag in $tags[1..5]) { Invoke-GameTool 'clk.py' @($tag,'319','460'); Start-Sleep -Seconds 2 }
    Invoke-GameTool 'clk.py' @('A','319','460')
    $deadline = (Get-Date).AddSeconds(150)
    $ready = $false
    while ((Get-Date) -lt $deadline) {
        $complete = @($tags | Where-Object { Get-ChildItem (Join-Path $runDir $_) -Filter 'step_*.txt' -ErrorAction SilentlyContinue })
        if ($complete.Count -eq 6) { $ready = $true; break }
        foreach ($tag in $tags) {
            if (!(Get-Process -Id $prelaunch[$tag].pid -ErrorAction SilentlyContinue)) { throw "Client $tag exited during initialization." }
        }
        Start-Sleep -Milliseconds 500
    }
    if (!$ready) { throw 'Not all six clients produced simulation captures.' }
    foreach ($tag in $tags) { Invoke-GameTool 'test_window_render.py' @($Run,$tag,'--live-only') }
    Invoke-GameTool 'bind_match_identity.py' @($Run)
    Invoke-GameTool 'game_window_positions.py' (@('restore',$Run) + $tags)
    "Six owned UI clients running, rendering checked: $Run"
} catch {
    $alive = @{}
    foreach ($tag in $tags) {
        $pidFile = Join-Path $runDir "pid_$tag.txt"
        if (Test-Path -LiteralPath $pidFile) {
            $owned = Get-Process -Id ([int](Get-Content -LiteralPath $pidFile -Raw)) -ErrorAction SilentlyContinue
            if ($owned -and $owned.Path -in $programs) {
                $alive[$tag] = $owned.Id
            }
        }
    }
    Write-JsonFile (Join-Path $runDir 'failure.json') @{
        utc=[DateTime]::UtcNow.ToString('o'); error=$_.Exception.Message
        preserved_owned_clients=$alive
    }
    throw
}
