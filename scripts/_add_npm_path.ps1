$npmPath = 'C:\Users\0000250059\AppData\Roaming\npm'
$currentPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if ($currentPath -notlike "*$npmPath*") {
    [Environment]::SetEnvironmentVariable('Path', "$currentPath;$npmPath", 'User')
    Write-Host 'Added npm path'
} else {
    Write-Host 'Already in PATH'
}
