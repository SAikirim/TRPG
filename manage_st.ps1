# manage_st.ps1 - idempotent control for the SillyTavern/TRPG service set.
#
# Goal: prevent the recurring "duplicate process" problem. 'start' checks the port first and
#       SKIPS anything already listening -> duplicates are structurally impossible.
#       (English-only strings: PowerShell 5.1 misreads UTF-8-without-BOM, so no Korean here.)
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File manage_st.ps1 status
#   powershell -ExecutionPolicy Bypass -File manage_st.ps1 start            # all managed (skips UP)
#   powershell -ExecutionPolicy Bypass -File manage_st.ps1 start app.py
#   powershell -ExecutionPolicy Bypass -File manage_st.ps1 stop mechanics
#   powershell -ExecutionPolicy Bypass -File manage_st.ps1 restart st
#
# managed=$true  : we start/stop these (app.py, mechanics, st)
# managed=$false : heavy/global (SD/ollama/litellm) -> status only, never auto-touched (VRAM/global safety)
param(
  [ValidateSet('status','start','stop','restart')] [string]$Action = 'status',
  [string]$Service = 'all'
)

$SDPY  = 'C:\git\WebUI\stable-diffusion-webui\venv\Scripts\Python.exe'
$SYSPY = 'C:\Users\SAiki\AppData\Local\Programs\Python\Python310\python.exe'
$NODE  = 'C:\Program Files\nodejs\node.exe'

$Services = @(
  @{ name='app.py';    port=5000;  managed=$true;  exe=$SDPY;  args='app.py';             cwd='C:\git\TRPG';                  env=@{} },
  @{ name='mechanics'; port=5102;  managed=$true;  exe=$SYSPY; args='mechanics_server.py'; cwd='C:\git\trpg-st-bridge\tools';  env=@{} },
  @{ name='st';        port=8000;  managed=$true;  exe=$NODE;  args='server.js';           cwd='C:\git\SillyTavern';           env=@{ NODE_ENV='production' } },
  @{ name='sd';        port=7860;  managed=$false; exe=''; args=''; cwd=''; env=@{} },
  @{ name='ollama';    port=11434; managed=$false; exe=''; args=''; cwd=''; env=@{} },
  @{ name='litellm';   port=4000;  managed=$false; exe=''; args=''; cwd=''; env=@{} }
)

function PortPid([int]$port){
  $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  if($c){ $c.OwningProcess } else { $null }
}

function Show-Status {
  "=== SillyTavern/TRPG service status ==="
  foreach($s in $Services){
    $pp = PortPid $s.port
    $tag = if($s.managed){'[managed] '}else{'[external]'}
    if($pp){ "{0} {1,-10} UP    :{2,-5} PID {3}" -f $tag,$s.name,$s.port,$pp }
    else   { "{0} {1,-10} DOWN  :{2}" -f $tag,$s.name,$s.port }
  }
}

function Start-One($s){
  if(-not $s.managed){ "  $($s.name): external - not auto-managed"; return }
  $pp = PortPid $s.port
  if($pp){ "  $($s.name): already UP (PID $pp) - skip (no duplicate)"; return }
  foreach($k in $s.env.Keys){ Set-Item -Path "env:$k" -Value $s.env[$k] }
  Start-Process -FilePath $s.exe -ArgumentList $s.args -WorkingDirectory $s.cwd -WindowStyle Hidden | Out-Null
  $ok=$false; for($i=0;$i -lt 30;$i++){ Start-Sleep -Milliseconds 700; if(PortPid $s.port){$ok=$true;break} }
  if($ok){ "  $($s.name): started -> :$($s.port) UP" } else { "  $($s.name): started but port not up (check logs)" }
}

function Stop-One($s){
  if(-not $s.managed){ "  $($s.name): external - not stopped"; return }
  $pp = PortPid $s.port
  if(-not $pp){ "  $($s.name): already DOWN"; return }
  taskkill /F /T /PID $pp 2>&1 | Out-Null
  Start-Sleep -Milliseconds 900
  if(PortPid $s.port){ "  $($s.name): stop FAILED (still UP)" } else { "  $($s.name): stopped" }
}

if($Service -eq 'all'){ $sel = $Services | Where-Object { $_.managed } }
else { $sel = $Services | Where-Object { $_.name -eq $Service } }

switch($Action){
  'status'  { Show-Status }
  'start'   { "=== START ==="; foreach($s in $sel){ Start-One $s }; ""; Show-Status }
  'stop'    { "=== STOP ===";  foreach($s in $sel){ Stop-One  $s }; ""; Show-Status }
  'restart' { "=== RESTART ==="; foreach($s in $sel){ Stop-One $s; Start-One $s }; ""; Show-Status }
}
