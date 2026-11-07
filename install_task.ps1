# install_task.ps1 - register the daily auto check-in scheduled task.
# Run from an ELEVATED (Administrator) PowerShell:
#   powershell -NoProfile -ExecutionPolicy Bypass -File "D:\qiandao\sign in\install_task.ps1"
# To uninstall:
#   Unregister-ScheduledTask -TaskName "QiandaoAutoCheckin" -Confirm:$false

$ErrorActionPreference = "Stop"
$TaskName = "QiandaoAutoCheckin"
$Py      = "C:\Users\14976\AppData\Local\Programs\Python\Python312\pythonw.exe"
$Script  = Join-Path $PSScriptRoot "checkin.py"
$Work    = $PSScriptRoot

# Clean up leftover tasks from the old version.
foreach ($old in "QiandaoDaemon","QiandaoCatchup") {
    Unregister-ScheduledTask -TaskName $old -Confirm:$false -ErrorAction SilentlyContinue
}
Write-Host "Cleaned old tasks: QiandaoDaemon / QiandaoCatchup (if any)"

if (-not (Test-Path $Py)) { throw "pythonw.exe not found: $Py" }
if (-not (Test-Path $Script)) { throw "checkin.py not found: $Script" }

# Daily 10:05 (after Qoder's 10:00 claim window opens). Start boundary = tomorrow,
# so registering does not fire the task immediately.
$start = (Get-Date).Date.AddDays(1).AddHours(10).AddMinutes(5).ToString("yyyy-MM-ddTHH:mm:ss")

$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Daily auto check-in: TRAE CN / WorkBuddy / SenseRaccoon / Qoder CN (windowless via pythonw)</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
    </LogonTrigger>
    <CalendarTrigger>
      <StartBoundary>__START__</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
    </CalendarTrigger>
    <EventTrigger>
      <Enabled>true</Enabled>
      <Subscription>&lt;QueryList&gt;&lt;Query Id="0" Path="System"&gt;&lt;Select Path="System"&gt;*[System[Provider[@Name='Microsoft-Windows-Power-Troubleshooter'] and EventID=1]]&lt;/Select&gt;&lt;/Query&gt;&lt;/QueryList&gt;</Subscription>
    </EventTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT10M</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>$Py</Command>
      <Arguments>"$Script"</Arguments>
      <WorkingDirectory>$Work</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@

$xml = $xml.Replace('__START__', $start)

Register-ScheduledTask -TaskName $TaskName -Xml $xml -Force | Out-Null
Write-Host "Registered task: $TaskName"
Write-Host "  Triggers: logon / daily 10:05 / wake from sleep"
Write-Host "  Command: $Py"
Write-Host "  Args: $Script"
