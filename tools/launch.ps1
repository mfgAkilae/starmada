param([string]$GameArgs = "-nointro", [string]$Display = "application")
# Starts the test game windowed and leaves it running; writes the pid to work\pid.txt.
$dir = "E:\dev\starmada\work\testrun"
Set-Content -Path "$dir\dxcfg.ini" -Encoding ascii -Value "[dxcfg]`r`ndisplay=$Display`r`npresentation=windowed`r`naspect=enabled`r`nscaling=fit`r`nvsync=application`r`ngamma=1.0`r`nanisotropic=application`r`nantialiasing=application`r`n"
$log = "$dir\Logs\logfile.txt"
if (Test-Path $log) { Move-Item $log "$dir\Logs\logfile_$(Get-Date -Format HHmmss).txt" -Force }
$p = Start-Process -FilePath "$dir\Armada.exe" -ArgumentList $GameArgs -WorkingDirectory $dir -PassThru
$p.Id | Out-File -Encoding ascii E:\dev\starmada\work\pid.txt
"pid=$($p.Id)"
