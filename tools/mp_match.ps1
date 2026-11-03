param([string]$Run = 'mp2', [int]$DumpEvery = 50, [int]$AiSlots = 2)
# Two-instance multiplayer test bed on one PC (test proxy from "src\strlkup_proxy\build.cmd test"
# installed as Strlkup.dll, dxcfg display=application). Instance A hosts a TCP/IP LAN game,
# instance B joins, A adds Hard AI players and both launch. The menus are driven with
# PostMessage (clk.py) and press-drag-release for the drop-down lists (drag.py).
$py = 'E:\dev\starmada\.venv\Scripts\python.exe'
$t = 'E:\dev\starmada\tools'
& "$t\mp_inst.ps1" -Tag A -Run $Run -DumpEvery $DumpEvery; Start-Sleep -Seconds 10
& $py "$t\clk.py" A 555 20;  Start-Sleep -Seconds 8      # Multiplayer
& $py "$t\clk.py" A 319 310; Start-Sleep -Seconds 6      # Local Area Network (TCP/IP)
& $py "$t\clk.py" A 292 215; Start-Sleep -Seconds 4      # Create Game
& $py "$t\clk.py" A 78 167;  Start-Sleep -Seconds 6      # OK (game name dialog)
& "$t\mp_inst.ps1" -Tag B -Run $Run -DumpEvery $DumpEvery; Start-Sleep -Seconds 10
& $py "$t\clk.py" B 555 20;  Start-Sleep -Seconds 8
& $py "$t\clk.py" B 319 310; Start-Sleep -Seconds 25     # session list fills
& $py "$t\clk.py" B 97 76;   Start-Sleep -Seconds 2      # select the first game
& $py "$t\clk.py" B 160 215; Start-Sleep -Seconds 12     # Join Game
& $py "$t\shot.py" B "E:\dev\starmada\work\det\$Run\B_joined.png" | Out-Null
for ($i = 0; $i -lt $AiSlots; $i++) {                    # slots 3.. -> Computer AI:Hard
  $y = 101 + 19 * $i
  & $py "$t\drag.py" A 79 $y 79 ($y + 76); Start-Sleep -Seconds 2
}
& $py "$t\clk.py" A 319 460; Start-Sleep -Seconds 5      # host: Launch
& $py "$t\clk.py" B 319 460; Start-Sleep -Seconds 5      # client: ready
& $py "$t\clk.py" A 319 460                              # host: Launch
"launched $Run"
