param([string]$Run = 'mp2', [int]$DumpEvery = 50, [int]$AiSlots = 2, [int]$ExitAfter = 0,
      [string]$GameDirA = 'E:\dev\starmada\work\testrun', [string]$GameDirB = 'E:\dev\starmada\work\testrun',
      [int]$InjectStep = 0, [int]$InjectOrder = 0, [int]$InjectRepeat = 0, [switch]$NativeWindow,
      [switch]$LobbyOnly, [switch]$LateGame, [string]$Fixture = 'live',
      [string]$GameName = '', [switch]$SessionListOnly)
$ErrorActionPreference = 'Stop'
if ($Run -notmatch '^[A-Za-z0-9_-]+$') { throw 'Invalid run name.' }
# Two-instance multiplayer test bed on one PC (test proxy from "src\strlkup_proxy\build.cmd test"
# installed as Strlkup.dll, dxcfg display=application). Instance A hosts a TCP/IP LAN game,
# instance B joins, A adds Hard AI players and both launch. The menus are driven with
# PostMessage (clk.py) and press-drag-release for the drop-down lists (drag.py).
# The instances start without activation (start_bg.py) and the test proxy keeps them in the
# background; run tools\mouse_watchdog.py alongside to stop them if one takes the mouse or focus.
$py = 'E:\dev\starmada\.venv\Scripts\python.exe'
$t = 'E:\dev\starmada\tools'
$env:ARMADA_RUN_DIR = "E:\dev\starmada\work\det\$Run"
& "$t\mp_inst.ps1" -Tag A -Run $Run -GameDir $GameDirA -NativeWindow:$NativeWindow -DumpEvery $DumpEvery -ExitAfter $ExitAfter -InjectStep $InjectStep -InjectOrder $InjectOrder -InjectRepeat $InjectRepeat; Start-Sleep -Seconds 10
& $py "$t\clk.py" A 555 20;  Start-Sleep -Seconds 8      # Multiplayer
& $py "$t\clk.py" A 319 310; Start-Sleep -Seconds 6      # Local Area Network (TCP/IP)
& $py "$t\clk.py" A 292 215; Start-Sleep -Seconds 4      # Create Game
if ($GameName) {
  & $py "$t\set_game_name.py" $Run $GameName --fixture $Fixture
  if ($LASTEXITCODE -ne 0) { throw 'Could not set unique game name.' }
} else {
  & $py "$t\clk.py" A 78 167
}
Start-Sleep -Seconds 6                                # host lobby opens
if ($GameName) {
  & $py "$t\set_game_name.py" $Run $GameName --fixture $Fixture --verify
  if ($LASTEXITCODE -ne 0) { throw 'Unique host game name was not applied.' }
}
& "$t\mp_inst.ps1" -Tag B -Run $Run -GameDir $GameDirB -NativeWindow:$NativeWindow -DumpEvery $DumpEvery -ExitAfter $ExitAfter -InjectStep $InjectStep -InjectOrder $InjectOrder -InjectRepeat $InjectRepeat; Start-Sleep -Seconds 10
& $py "$t\clk.py" B 555 20;  Start-Sleep -Seconds 8
& $py "$t\clk.py" B 319 310; Start-Sleep -Seconds 25     # session list fills
if ($SessionListOnly) { "client session list ready: $Run"; return }
if ($GameName) {
  & $py "$t\select_lan_session.py" $Run $GameName --fixture $Fixture
  if ($LASTEXITCODE -ne 0) { throw 'Could not select the exact waiting host session.' }
} else {
  & $py "$t\clk.py" B 97 76
}
Start-Sleep -Seconds 2
& $py "$t\clk.py" B 160 215; Start-Sleep -Seconds 12     # Join Game
& $py "$t\shot.py" B "E:\dev\starmada\work\det\$Run\B_joined.png" | Out-Null
if ($LobbyOnly) { "both clients joined lobby: $Run"; return }
if ($LateGame) {
  & $py "$t\setup_late_game_lobby.py" $Run --fixture $Fixture
  if ($LASTEXITCODE -ne 0) { throw 'Late-Game lobby configuration failed.' }
}
for ($i = 0; !$LateGame -and $i -lt $AiSlots; $i++) {     # slots 3.. -> Computer AI:Hard
  $y = 101 + 19 * $i
  $targetY = if ($y -ge 149) { $y - 76 } else { $y + 76 }
  & $py "$t\drag.py" A 79 $y 79 $targetY; Start-Sleep -Seconds 2
}
& $py "$t\clk.py" A 319 460; Start-Sleep -Seconds 5      # host: Launch
& $py "$t\clk.py" B 319 460; Start-Sleep -Seconds 5      # client: ready
& $py "$t\clk.py" A 319 460                              # host: Launch
"lobby launch commands sent for $Run"
$deadline = (Get-Date).AddSeconds(90)
while ((Get-Date) -lt $deadline) {
    if ((Get-ChildItem "$env:ARMADA_RUN_DIR\A" -Filter 'step_*.txt' -ErrorAction SilentlyContinue) -and
        (Get-ChildItem "$env:ARMADA_RUN_DIR\B" -Filter 'step_*.txt' -ErrorAction SilentlyContinue)) {
        "simulation running on both clients: $Run"
        return
    }
    foreach ($tag in @('A','B')) {
        $pidPath = Join-Path $env:ARMADA_RUN_DIR "pid_$tag.txt"
        $gamePid = [int](Get-Content -LiteralPath $pidPath -Raw)
        if (!(Get-Process -Id $gamePid -ErrorAction SilentlyContinue)) {
            throw "Client $tag exited before the simulation started."
        }
    }
    Start-Sleep -Milliseconds 500
}
throw "No state dumps from both clients; inspect $env:ARMADA_RUN_DIR."
