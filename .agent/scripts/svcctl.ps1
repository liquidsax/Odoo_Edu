<#
svcctl.ps1 - start/stop/restart/status/logs/check for the local Odoo + PostgreSQL stack.
Self-elevates for mutating actions (Windows requires admin to control services).
All output is buffered and flushed once, so an elevated child can hand results back to
the non-elevated caller through a temp file.
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('start', 'stop', 'restart', 'status', 'logs', 'check')]
    [string]$Action = 'status',

    [Parameter(Position = 1)]
    [ValidateSet('odoo', 'pg', 'all')]
    [string]$Target = 'all',

    [Parameter(Position = 2)]
    [ValidateRange(1, 500)]
    [int]$Lines = 30,

    [switch]$Elevated,
    [string]$OutFile
)

$ErrorActionPreference = 'Stop'
$script:Buf = New-Object System.Collections.ArrayList
$OdooSvc = 'odoo-server-19.0'
$PgSvc = 'postgresql-x64-18'

function Say([string]$m) { [void]$script:Buf.Add($m) }

function Flush {
    $script:Buf | ForEach-Object { Write-Output $_ }
    if ($OutFile) { $script:Buf | Out-File -Encoding ascii -FilePath $OutFile }
}

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-ServicePath([string]$Name) {
    $c = Get-CimInstance Win32_Service -Filter "Name='$Name'" -ErrorAction SilentlyContinue
    if ($c) { return $c.PathName } else { return '' }
}

function Get-PgBin {
    $m = [regex]::Match((Get-ServicePath $PgSvc), '-D\s+"([^"]+)"')
    if (-not $m.Success) { return $null }
    $dataDir = $m.Groups[1].Value
    return @{ DataDir = $dataDir; Bin = (Split-Path $dataDir -Parent); Psql = (Join-Path (Split-Path $dataDir -Parent) 'bin\psql.exe') }
}

function Get-OdooConf {
    $m = [regex]::Match((Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Services\odoo-server-19.0\Parameters' -ErrorAction SilentlyContinue).AppParameters, '"([^"]+\.conf)"')
    if ($m.Success) { return $m.Groups[1].Value }
    return 'E:\Odoo\server\odoo.conf'
}

function Read-Conf([string]$Path) {
    $h = @{}
    if (-not (Test-Path $Path)) { return $h }
    foreach ($l in Get-Content $Path) {
        $p = [regex]::Match($l, '^\s*([A-Za-z0-9_]+)\s*=\s*(.*?)\s*$')
        if ($p.Success) { $h[$p.Groups[1].Value] = $p.Groups[2].Value }
    }
    return $h
}

function Get-PortInfo([int]$Port) {
    $conns = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    if (-not $conns) { return 'not listening' }
    $addrs = ($conns | ForEach-Object { $_.LocalAddress + ':' + [string]$Port }) | Select-Object -Unique
    $procId = ($conns | Select-Object -First 1).OwningProcess
    $pname = (Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue).Name
    return ($addrs -join ', ') + '  pid=' + [string]$procId + ' (' + $pname + ')'
}

function Wait-State([string]$Name, [string]$Want, [int]$TimeoutSec) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        $s = (Get-Service -Name $Name -ErrorAction SilentlyContinue).Status
        if ($s -eq $Want) { return $true }
        Start-Sleep -Milliseconds 700
    }
    return $false
}

function Invoke-One([string]$Name, [string]$Act) {
    $before = (Get-Service -Name $Name).Status
    try {
        switch ($Act) {
            'start' {
                if ($before -ne 'Running') { Start-Service -Name $Name; if (-not (Wait-State $Name 'Running' 60)) { throw 'did not reach Running within 60s' } }
            }
            'stop' {
                if ($before -ne 'Stopped') { Stop-Service -Name $Name -Force; if (-not (Wait-State $Name 'Stopped' 60)) { throw 'did not reach Stopped within 60s' } }
            }
            'restart' {
                Restart-Service -Name $Name -Force; if (-not (Wait-State $Name 'Running' 90)) { throw 'did not come back within 90s' }
            }
        }
        $after = (Get-Service -Name $Name).Status
        Say ('[OK]   ' + $Name + '  ' + $before + ' -> ' + $after)
    }
    catch {
        Say ('[FAIL] ' + $Name + '  ' + $Act + ' : ' + $_.Exception.Message)
        Say ('       current status: ' + (Get-Service -Name $Name).Status)
    }
}

function Show-Status {
    Say '=== services ==='
    foreach ($n in @($PgSvc, $OdooSvc)) {
        $svc = Get-Service -Name $n -ErrorAction SilentlyContinue
        if (-not $svc) { Say ('[FAIL] ' + $n + ' : service not installed'); continue }
        $start = (Get-CimInstance Win32_Service -Filter "Name='$n'" -ErrorAction SilentlyContinue).StartMode
        $st = [string]$svc.Status
        $tag = 'WARN'
        if ($st -eq 'Running') { $tag = 'OK' }
        Say ('[' + $tag + ']   ' + $n.PadRight(20) + $st.PadRight(10) + 'startup=' + $start)
    }
    Say '=== ports ==='
    Say ('  5432 postgres : ' + (Get-PortInfo 5432))
    Say ('  8069 odoo http : ' + (Get-PortInfo 8069))
}

function Show-Logs {
    if ($Target -eq 'odoo' -or $Target -eq 'all') {
        $log = Join-Path (Split-Path (Get-OdooConf) -Parent) 'odoo.log'
        Say ('=== odoo log (last ' + $Lines + ' of ' + $log + ', UTC timestamps) ===')
        if (Test-Path $log) { Get-Content $log -Tail $Lines | Where-Object { $_.Trim() } | ForEach-Object { Say ('  ' + $_.Substring(0, [Math]::Min(240, $_.Length))) } }
        else { Say '  [WARN] log file not found' }
    }
    if ($Target -eq 'pg' -or $Target -eq 'all') {
        $pg = Get-PgBin
        Say ('=== postgres log (last ' + $Lines + ') ===')
        if ($pg -and (Test-Path (Join-Path $pg.DataDir 'log'))) {
            $f = Get-ChildItem (Join-Path $pg.DataDir 'log') -Filter '*.log' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
            if ($f) { Say ('  file: ' + $f.Name); Get-Content $f.FullName -Tail $Lines | Where-Object { $_.Trim() } | ForEach-Object { Say ('  ' + $_.Substring(0, [Math]::Min(240, $_.Length))) } }
        }
        else { Say '  [WARN] no log directory under ' + $(if ($pg) { $pg.DataDir } else { 'unknown data dir' }) }
    }
}

function Show-Check {
    Say '=== 1. services / ports ==='
    Show-Status
    $conf = Read-Conf (Get-OdooConf)
    Say '=== 2. odoo.conf database keys ==='
    Say ('  file    : ' + (Get-OdooConf))
    Say ('  db_user : ' + $conf['db_user'] + '   db_host:port: ' + $conf['db_host'] + ':' + $conf['db_port'])
    Say ('  db_password set: ' + $(if ($conf['db_password']) { 'yes' } else { 'NO - Odoo cannot authenticate' }))
    Say ('  db_template: ' + $conf['db_template'])
    Say '=== 3. psql as the Odoo role ==='
    $pg = Get-PgBin
    if (-not $pg -or -not (Test-Path $pg.Psql)) { Say '  [FAIL] psql.exe not found'; return }
    $env:PGPASSWORD = $conf['db_password']
    $q = "select 'role=' || current_user"
    $who = (& $pg.Psql -h $conf['db_host'] -p $conf['db_port'] -U $conf['db_user'] -d postgres -Atc $q 2>&1)
    if ($LASTEXITCODE -ne 0) { Say ('  [FAIL] cannot connect as ' + $conf['db_user'] + ' -> ' + (($who | Out-String).Trim())); return }
    Say ('  [OK]   ' + ($who | Out-String).Trim())
    Say '=== 4. database collate/ctype (Windows rejects any mismatch) ==='
    $rows = & $pg.Psql -h $conf['db_host'] -p $conf['db_port'] -U $conf['db_user'] -d postgres -Atc "select datname || '|' || datcollate || '|' || datctype || '|template=' || datistemplate from pg_database order by 1" 2>&1
    $bad = 0
    foreach ($r in $rows) {
        $c = $r.Split('|')
        if ($c.Length -lt 4) { continue }
        if ($c[1] -ne $c[2]) { $bad++; Say ('  [FAIL] ' + $r + '   <-- unusable on Windows') }
        else { Say ('  [OK]   ' + $r) }
    }
    if ($bad -eq 0) { Say '  no collate/ctype mismatch' }
    if ($conf['db_template'] -and $conf['db_template'] -ne 'template0') {
        $t = $rows | Where-Object { $_ -like ($conf['db_template'] + '|*') }
        if ($t) { Say ('  [OK]   configured db_template is usable: ' + $t) }
        else { Say ('  [FAIL] db_template = ' + $conf['db_template'] + ' does not exist') }
    }
    Say '=== 5. HTTP on port 8069 ==='
    try {
        $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8069/web/database/list' -Method Post -ContentType 'application/json' `
            -Body '{"jsonrpc":"2.0","method":"call","params":{}}' -UseBasicParsing -TimeoutSec 90
        $j = $r.Content | ConvertFrom-Json
        Say ('  [OK]   database manager reachable, dbs: ' + (($j.result) -join ', '))
        if ($conf['db_name'] -and $j.result -notcontains $conf['db_name']) { Say ('  [WARN] db_name = ' + $conf['db_name'] + ' is not in that list') }
    }
    catch {
        Say ('  [FAIL] ' + $_.Exception.Message)
        Say '         (if services are up but this fails, Odoo still cannot reach PostgreSQL)'
    }
    Say '=== 6. errors in odoo.log since the running process started ==='
    $log = Join-Path (Split-Path (Get-OdooConf) -Parent) 'odoo.log'
    if (-not (Test-Path $log)) { Say '  [WARN] log file not found'; return }
    $httpPid = (Get-NetTCPConnection -State Listen -LocalPort 8069 -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess
    $since = $null
    if ($httpPid) {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$httpPid" -ErrorAction SilentlyContinue
        if ($proc) { $since = $proc.CreationDate.ToUniversalTime() }
    }
    if ($since) { Say ('  window: ' + $since.ToString('yyyy-MM-dd HH:mm') + ' UTC -> now (log stamps are UTC, local = UTC+8)') }
    else { Say '  [WARN] no process owns port 8069, scanning the last 400 lines instead' }
    $recent = @()
    foreach ($l in (Get-Content $log -Tail 400)) {
        if (-not $since) { $recent += $l; continue }
        $m = [regex]::Match($l, '^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})')
        if ($m.Success) {
            try { if ([DateTime]::Parse($m.Groups[1].Value, [Globalization.CultureInfo]::InvariantCulture).ToUniversalTime() -lt $since) { continue } }
            catch { continue }
        }
        $recent += $l
    }
    $dbfail = (@($recent | Where-Object { $_ -match 'Connection to the database failed' })).Count
    if ($dbfail -eq 0) { Say '  [OK]   no database connection failures' }
    else { Say ('  [FAIL] database connection failures: ' + $dbfail) }
    $errs = @($recent | Where-Object { $_ -match ' ERROR | CRITICAL |ParseError' })
    if ($errs.Count -eq 0) { Say '  [OK]   no ERROR/CRITICAL lines' }
    else {
        Say ('  [WARN] ' + $errs.Count + ' error line(s), last 5:')
        $errs | Select-Object -Last 5 | ForEach-Object { Say ('    ' + $_.Substring(0, [Math]::Min(240, $_.Length))) }
    }
}

# ---- elevation hand-off -------------------------------------------------------
$mutating = $Action -in @('start', 'stop', 'restart')
if ($mutating -and -not $Elevated) {
    if (Test-Admin) {
        $Elevated = $true
    }
    else {
        $tmp = Join-Path $env:TEMP ('svcctl-' + [guid]::NewGuid().ToString('N') + '.txt')
        $argLine = '-NoProfile -ExecutionPolicy Bypass -File "' + $PSCommandPath + '" -Action ' + $Action + ' -Target ' + $Target + ' -Lines ' + $Lines + ' -Elevated -OutFile "' + $tmp + '"'
        Say ('[INFO] "' + $Action + ' ' + $Target + '" needs admin rights - a UAC prompt is opening, please click Yes')
        $script:Buf | ForEach-Object { Write-Output $_ }
        try {
            Start-Process -FilePath 'powershell.exe' -ArgumentList $argLine -Verb RunAs -Wait
        }
        catch {
            Write-Output '[FAIL] UAC was declined or the elevated process could not start: ' + $_.Exception.Message
            exit 1
        }
        if (Test-Path $tmp) {
            Get-Content $tmp | ForEach-Object { Write-Output $_ }
            Remove-Item $tmp -Force
        }
        else { Write-Output '[FAIL] the elevated process produced no result file (it may have crashed early)' }
        exit 0
    }
}

# ---- ordering: dependents stop first, dependencies start first ----------------
$order = switch ($Action) {
    'stop' { @($OdooSvc, $PgSvc) }
    default { @($PgSvc, $OdooSvc) }
}
$wanted = switch ($Target) {
    'odoo' { @($OdooSvc) }
    'pg' { @($PgSvc) }
    'all' { $order }
}
$queue = @($order | Where-Object { $wanted -contains $_ })

switch ($Action) {
    'status' { Show-Status }
    'logs' { Show-Logs }
    'check' { Show-Check }
    default {
        Say ('[INFO] action=' + $Action + ' target=' + $Target + ' admin=' + (Test-Admin))
        foreach ($n in $queue) { Invoke-One $n $Action }
        Show-Status
    }
}
Flush
