Add-Type -AssemblyName System.Device
$watcher = New-Object System.Device.Location.GeoCoordinateWatcher
$null = $watcher.TryStart($false, [TimeSpan]::FromSeconds(10))
$deadline = (Get-Date).AddSeconds(10)
while ($watcher.Status -ne 'Ready' -and (Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 200
}
if ($watcher.Status -eq 'Ready') {
    $loc = $watcher.Position.Location
    Write-Output "OK $($loc.Latitude) $($loc.Longitude)"
} else {
    Write-Output "FAILED $($watcher.Status)"
}
