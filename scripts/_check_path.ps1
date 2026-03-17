$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$entries = $userPath -split ';'
$npmEntries = $entries | Where-Object { $_ -like '*npm*' }
if ($npmEntries) {
    Write-Host "FOUND in User PATH:"
    $npmEntries | ForEach-Object { Write-Host "  $_" }
} else {
    Write-Host "NOT in User PATH"
    Write-Host "Adding now..."
    $npmPath = 'C:\Users\0000250059\AppData\Roaming\npm'
    [Environment]::SetEnvironmentVariable('Path', "$userPath;$npmPath", 'User')
    Write-Host "Added: $npmPath"
}
