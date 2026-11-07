param(
  [string]$Proc = "WorkBuddy",
  [long]$Hwnd = 0,
  [int]$MaxDepth = 12
)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

if ($Hwnd -eq 0) {
  $proc = Get-Process -Name $Proc -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
  if (-not $proc) { Write-Output "NO PROCESS: $Proc"; exit 1 }
  $Hwnd = $proc.MainWindowHandle
}
Write-Output ("HWND: " + $Hwnd)

$root = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]$Hwnd)
if (-not $root) { Write-Output "NO ROOT ELEMENT"; exit 1 }
Write-Output ("ROOT: " + $root.Current.Name + " / " + $root.Current.ControlType.ProgrammaticName)

$all = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants,
  [System.Windows.Automation.Condition]::TrueCondition)

$out = @()
foreach ($el in $all) {
  $name = $el.Current.Name
  $type = $el.Current.ControlType.ProgrammaticName
  $rect = $el.Current.BoundingRectangle
  if (-not $rect -or $rect.IsEmpty) { continue }
  $w = $rect.Width; $h = $rect.Height
  if ($w -lt 5 -or $h -lt 5) { continue }
  # only keep interactive/meaningful elements
  if ($type -match 'Button|MenuItem|Hyperlink|ListItem|Text|Edit|Tab|CheckBox|RadioButton|ComboBox|Custom|Image') {
    $out += [PSCustomObject]@{
      Type = $type
      Name = $name
      X = [int]$rect.X
      Y = [int]$rect.Y
      W = [int]$w
      H = [int]$h
    }
  }
}
$out | Where-Object { $_.Name -or $_.Type -match 'Button|MenuItem' } |
  Sort-Object Y, X | Format-Table -AutoSize -Wrap
