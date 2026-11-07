$sh = New-Object -ComObject WScript.Shell
$paths = @(
  'C:\Users\14976\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Qoder\Qoder CN.lnk',
  'C:\Users\14976\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Qoder CN.lnk',
  'C:\Users\14976\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\TRAE CN\TRAE CN.lnk',
  'C:\Users\14976\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\WorkBuddy.lnk',
  'C:\ProgramData\Microsoft\Windows\Start Menu\Programs\商汤小浣熊.lnk'
)
foreach ($p in $paths) {
  if (Test-Path $p) {
    $s = $sh.CreateShortcut($p)
    Write-Output ("LNK: " + $p)
    Write-Output ("  Target: " + $s.TargetPath)
    Write-Output ("  Args:   " + $s.Arguments)
    Write-Output ("  WorkDir:" + $s.WorkingDirectory)
  } else {
    Write-Output ("MISSING: " + $p)
  }
}
