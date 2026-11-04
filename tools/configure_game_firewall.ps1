param([Parameter(Mandatory=$true)][string]$Request, [switch]$CheckOnly)
# Idempotent, program-specific Private-LAN rules. Elevation is the normal Windows UAC flow.
$ErrorActionPreference = 'Stop'
$config = Get-Content -LiteralPath $Request -Raw | ConvertFrom-Json
$entries = @($config.programs | ForEach-Object {
    $path = (Resolve-Path -LiteralPath $_).Path
    if ([IO.Path]::GetFileName($path) -notin @('Armada.exe','Armada2.exe')) {
        throw ('Unexpected game executable: ' + $path)
    }
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $hash = $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($path.ToLowerInvariant())) }
    finally { $sha.Dispose() }
    $suffix = ([BitConverter]::ToString($hash)).Replace('-','').Substring(0,16)
    [PSCustomObject]@{path=$path; name=('Codex.Armada.LAN.' + $suffix); suffix=$suffix}
})
if (!$entries.Count) { throw 'No game programs supplied.' }
$blocked = @(Get-NetFirewallRule -PolicyStore ActiveStore -Enabled True -Action Block -Direction Inbound |
    Where-Object { $_.Profile -eq 'Any' -or ([int]$_.Profile -band 2) } |
    Get-NetFirewallApplicationFilter | Where-Object { $_.Program -in $entries.path })
if ($blocked.Count) {
    throw ('An existing Private block rule overrides the game allow rule: ' + ($blocked.Program -join ', '))
}

function Test-GameRule($entry) {
    $rule = Get-NetFirewallRule -PolicyStore ActiveStore -Name $entry.name -ErrorAction SilentlyContinue
    if (!$rule) { return $false }
    $application = $rule | Get-NetFirewallApplicationFilter
    $address = $rule | Get-NetFirewallAddressFilter
    $port = $rule | Get-NetFirewallPortFilter
    return ($rule.Enabled -eq 'True' -and $rule.Action -eq 'Allow' -and
            $rule.Direction -eq 'Inbound' -and $rule.Profile -eq 'Private' -and
            $application.Program -eq $entry.path -and
            @($address.RemoteAddress).Count -eq 1 -and $address.RemoteAddress -contains 'LocalSubnet' -and
            $port.Protocol -eq 'Any')
}

# Reading installed rules needs no UAC. Fixed paths make later starts elevation-free.
$missing = @($entries | Where-Object { !(Test-GameRule $_) })
if (!$missing.Count) {
    @{ok=$true; changed=$false; rules=@($entries | ForEach-Object {
        @{program=$_.path; rule=$_.name; profile='Private'; remote='LocalSubnet'; verified=$true}
    })} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $config.result -Encoding UTF8
    exit 0
}
if ($CheckOnly) { exit 1 }
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (!$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    $arguments = @('-NoProfile', '-File', ('"' + $PSCommandPath + '"'), '-Request', ('"' + (Resolve-Path -LiteralPath $Request).Path + '"'))
    $process = Start-Process -FilePath powershell.exe -ArgumentList $arguments -Verb RunAs -WindowStyle Hidden -PassThru
    $process.WaitForExit()
    exit $process.ExitCode
}
try {
    $results = @()
    foreach ($entry in $entries) {
        $path = $entry.path; $name = $entry.name; $suffix = $entry.suffix
        if (Get-NetFirewallRule -Name $name -ErrorAction SilentlyContinue) {
            Set-NetFirewallRule -Name $name -Enabled True -Direction Inbound -Action Allow -Profile Private
            Get-NetFirewallRule -Name $name | Get-NetFirewallApplicationFilter | Set-NetFirewallApplicationFilter -Program $path
            Get-NetFirewallRule -Name $name | Get-NetFirewallAddressFilter | Set-NetFirewallAddressFilter -RemoteAddress LocalSubnet
            Get-NetFirewallRule -Name $name | Get-NetFirewallPortFilter | Set-NetFirewallPortFilter -Protocol Any
        } else {
            New-NetFirewallRule -Name $name -DisplayName ('Armada LAN test - ' + $suffix) -Group 'Armada multiplayer tests' -Program $path -Direction Inbound -Action Allow -Profile Private -RemoteAddress LocalSubnet -Protocol Any | Out-Null
        }
        if (!(Test-GameRule $entry)) {
            throw ('Firewall rule verification failed: ' + $path)
        }
        $results += [PSCustomObject]@{program=$path; rule=$name; profile='Private'; remote='LocalSubnet'; verified=$true}
    }
    @{ok=$true; changed=$true; rules=$results} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $config.result -Encoding UTF8
} catch {
    @{ok=$false; error=$_.Exception.Message} | ConvertTo-Json | Set-Content -LiteralPath $config.result -Encoding UTF8
    exit 1
}
