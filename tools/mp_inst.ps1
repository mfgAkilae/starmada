param([string]$Tag = 'A', [string]$Run = 'mp1', [int]$DumpEvery = 50, [int]$ExitAfter = 0,
      [string]$GameDir = 'E:\dev\starmada\work\testrun')
# Starts one test instance for the two-instance multiplayer test bed (test proxy required).
$out = "E:\dev\starmada\work\det\$Run\$Tag"
New-Item -ItemType Directory -Force $out | Out-Null
Get-ChildItem $out -Filter 'step_*.txt' -ErrorAction SilentlyContinue | ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force -Confirm:$false }
$env:ARMADA_TEST_DUMP_EVERY = "$DumpEvery"
$env:ARMADA_TEST_DUMP_DIR = $out
$env:ARMADA_TEST_EXIT_AFTER = "$ExitAfter"
$env:ARMADA_TEST_MULTI = '1'
$p = Start-Process -FilePath "$GameDir\Armada.exe" -ArgumentList '-nointro' -WorkingDirectory $GameDir -PassThru
$p.Id | Out-File -Encoding ascii "E:\dev\starmada\work\pid_$Tag.txt"
"$Tag pid $($p.Id)"
