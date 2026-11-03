param([string]$Ini, [int]$Seconds = 12, [string]$Shot = "", [string]$GameArgs = "")
# Writes dxcfg.ini, starts the test game, reports crash or windows, then stops the game.
$dir = "E:\dev\starmada\work\testrun"
Set-Content -Path "$dir\dxcfg.ini" -Value $Ini -Encoding ascii
$log = "$dir\Logs\logfile.txt"
if (Test-Path $log) { Move-Item $log "$dir\Logs\logfile_$(Get-Date -Format HHmmss).txt" -Force }
if ($GameArgs) { $p = Start-Process -FilePath "$dir\Armada.exe" -ArgumentList $GameArgs -WorkingDirectory $dir -PassThru }
else { $p = Start-Process -FilePath "$dir\Armada.exe" -WorkingDirectory $dir -PassThru }
Start-Sleep -Seconds $Seconds
if ($p.HasExited) {
  "EXITED code=$($p.ExitCode)"
  Get-Content $log -ErrorAction SilentlyContinue | Select-String 'EXCEPTION|EIP' | Select-Object -First 3
} else {
  & E:\dev\starmada\.venv\Scripts\python.exe E:\dev\starmada\tools\probe.py windows $p.Id | Select-String "'visible': True"
  if ($Shot) { & E:\dev\starmada\.venv\Scripts\python.exe E:\dev\starmada\tools\probe.py shot $p.Id $Shot }
  Stop-Process -Id $p.Id -Force
  "RUNNING (stopped)"
}
