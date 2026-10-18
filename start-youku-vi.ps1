$root = $PSScriptRoot
$client = $null

foreach ($base in @("C:\Program Files (x86)\Youku", "C:\Program Files\Youku")) {
    if (-not (Test-Path -LiteralPath $base)) { continue }
    $client = Get-ChildItem -LiteralPath $base -Directory -ErrorAction SilentlyContinue |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName "YOUKU.exe") } |
        Sort-Object { [version]($_.Name -replace '[^0-9.].*$', '') } -Descending |
        ForEach-Object { Join-Path $_.FullName "YOUKU.exe" } |
        Select-Object -First 1
    if ($client) { break }
}
if (-not $client) { throw "Không tìm thấy YOUKU.exe trong Program Files." }

$managerPattern = [regex]::Escape($root) + '[\\/]subtitle_app\.py(?=["\s]|$)'
$managerProcesses = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -in @("python.exe", "pythonw.exe") -and $_.CommandLine -match $managerPattern })
if ($managerProcesses.Count -gt 0) {
    $busy = $true
    try {
        $health = Invoke-RestMethod -TimeoutSec 2 'http://127.0.0.1:18766/health'
        if ($health.app -in @('iqiyi-subtitles', 'subtitle-manager') -and $null -ne $health.busy) {
            $busy = [bool]$health.busy
        }
    } catch {}
    if ($busy) {
        Write-Warning 'App phụ đề đang dịch hoặc chưa xác nhận được trạng thái. Chờ dịch xong rồi chạy lại launcher Youku.'
        exit 1
    }
    $managerProcesses | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

Start-Process -FilePath $client -WorkingDirectory (Split-Path -Parent $client) `
    -ArgumentList "--remote-debugging-port=9224"

$python = @(
    (Join-Path $root ".venv\Scripts\pythonw.exe"),
    (Join-Path $root ".venv\Scripts\python.exe")
) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $python) {
    $command = Get-Command pythonw, python, py -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($command) { $python = $command.Source }
}
if ($python) {
    Start-Process -FilePath $python -ArgumentList (Join-Path $root "watch-youku-vi.py") `
        -WorkingDirectory $root -WindowStyle Hidden
}
$manager = $false
for ($i = 0; $i -lt 20; $i++) {
    try {
        $null = Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 "http://127.0.0.1:18766/"
        $manager = $true
        break
    } catch { Start-Sleep -Milliseconds 500 }
}
if ($manager) {
    Start-Process "http://127.0.0.1:18766/"
    Write-Host "Xong. Youku đã mở; app quản lý phụ đề đang chạy trong trình duyệt."
} else {
    Write-Warning "Youku đã mở nhưng app phụ đề chưa sẵn sàng. Chạy lại launcher để khởi động watcher."
}
