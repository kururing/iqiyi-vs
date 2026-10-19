$ErrorActionPreference = "Continue"
$root = $PSScriptRoot
Set-Location $root
$py = @(
    (Join-Path $root ".venv\Scripts\python.exe"),
    (Join-Path $root ".venv\Scripts\pythonw.exe")
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $py) {
    $cmd = Get-Command python, py, pythonw -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cmd) { $py = $cmd.Source }
}
if (-not $py) { throw "Khong tim thay Python de gan tieng Viet." }

function Start-Iqiyi([string]$FilePath, [string]$WorkingDirectory, [string]$ProxyUrl, [string]$BrowserFolder) {
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $FilePath
    $startInfo.WorkingDirectory = $WorkingDirectory
    $startInfo.UseShellExecute = $false
    $webViewArgs = "--remote-debugging-port=9223 --remote-debugging-address=127.0.0.1"
    if ($ProxyUrl) {
        $startInfo.EnvironmentVariables["HTTP_PROXY"] = $ProxyUrl
        $startInfo.EnvironmentVariables["HTTPS_PROXY"] = $ProxyUrl
        $startInfo.EnvironmentVariables["ALL_PROXY"] = $ProxyUrl
        $startInfo.EnvironmentVariables["NO_PROXY"] = "localhost,127.0.0.1,::1"
        $webViewArgs += " --proxy-server=$ProxyUrl --proxy-bypass-list=localhost;127.0.0.1;[::1]"
    }
    $startInfo.EnvironmentVariables["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = $webViewArgs
    if ($BrowserFolder) {
        $startInfo.EnvironmentVariables["WEBVIEW2_BROWSER_EXECUTABLE_FOLDER"] = $BrowserFolder
    }
    [void][System.Diagnostics.Process]::Start($startInfo)
}

$scriptPattern = [regex]::Escape($root) + '[\\/](watch-iqiyi-vi|inject-cdp|subtitle_app)\.py(?=["\s]|$)'
$scriptProcesses = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        $_.Name -in @("python.exe", "pythonw.exe") -and
        $_.CommandLine -match $scriptPattern
    })
$subtitleProcesses = @($scriptProcesses | Where-Object { $_.CommandLine -match 'subtitle_app\.py' })
if ($subtitleProcesses.Count -gt 0) {
    $busy = $true
    try {
        $health = Invoke-RestMethod -TimeoutSec 2 'http://127.0.0.1:18766/health'
        if ($health.app -in @('iqiyi-subtitles', 'subtitle-manager') -and $null -ne $health.busy) {
            $busy = [bool]$health.busy
        }
    } catch {
        try {
            # Older managers have no health endpoint or local authentication.
            $legacy = Invoke-RestMethod -TimeoutSec 2 'http://127.0.0.1:18766/api/episodes'
            if ($null -ne $legacy.PSObject.Properties['episodes']) {
                $busy = @($legacy.episodes | Where-Object { $_.progress.stage -eq 'translating' }).Count -gt 0
            }
        } catch {}
    }
    if ($busy) {
        Write-Warning 'App phu de dang dich hoac chua xac nhan duoc trang thai. Cho dich xong roi chay lai launcher de nap ban moi.'
        exit 1
    }
}
$scriptProcesses | ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }

Write-Host "Cai phu de Viet (chi can chay mot lan)..."
$applyScript = Join-Path $root "apply-vi.py"
& $py $applyScript
$applyExitCode = $LASTEXITCODE
if ($applyExitCode -eq 2) {
    Write-Host "Can quyen Administrator de Viet hoa giao dien cai dat native. Dang mo UAC..."
    $elevated = Start-Process -FilePath $py -ArgumentList ('"{0}"' -f $applyScript) -WorkingDirectory $root -Verb RunAs -Wait -PassThru
    $applyExitCode = $elevated.ExitCode
}
if ($applyExitCode -ne 0) {
    Write-Error "apply-vi.py loi (exit $applyExitCode)."
    exit 1
}

$playerProxy = $env:IQIYI_PLAYER_PROXY
if (-not $playerProxy) { $playerProxy = "" }
$webViewRoot = "C:\Program Files (x86)\Microsoft\EdgeWebView\Application"
$webViewRuntime = @(
    Get-ChildItem -LiteralPath $webViewRoot -Directory -ErrorAction SilentlyContinue |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName "msedgewebview2.exe") } |
        Sort-Object { try { [version]$_.Name } catch { [version]"0.0" } } -Descending
) | Select-Object -First 1
$webViewFolder = if ($webViewRuntime) { $webViewRuntime.FullName } else { "" }
$clientOutput = & $py $applyScript --client-path
if ($LASTEXITCODE -ne 0) {
    Write-Error "Khong tim thay QyClient.exe. Hay mo iQIYI mot lan hoac kiem tra duong dan cai dat."
    exit 1
}
$client = [string]($clientOutput | Select-Object -Last 1)
$client = $client.Trim()
if (-not (Test-Path -LiteralPath $client)) {
    Write-Error "Khong tim thay QyClient.exe tai: $client"
    exit 1
}
$installRoot = Split-Path $client
$qy = Get-Process QyClient,QyPlayer,QyKernel,QyFragment -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -like "$installRoot\*" }
if ($qy) {
    Write-Host "Khoi dong lai iQIYI de nap hook phu de moi..."
    $qy | Stop-Process -Force
    $qy | Wait-Process -Timeout 10 -ErrorAction SilentlyContinue
}
if ((Test-Path -LiteralPath $client) -and -not (Get-Process QyClient -ErrorAction SilentlyContinue)) {
    if ($playerProxy) {
        Write-Host "Mo iQIYI qua proxy da cau hinh (IQIYI_PLAYER_PROXY)..."
    } else {
        Write-Host "Mo iQIYI voi ket noi truc tiep (khong proxy)..."
    }
    if ($webViewFolder) { Write-Host "Dung WebView2 co san: $webViewFolder" }
    Start-Iqiyi -FilePath $client -WorkingDirectory $installRoot -ProxyUrl $playerProxy -BrowserFolder $webViewFolder
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
    Write-Host "Xong. iQIYI đã mở; app quản lý phụ đề đang chạy trong trình duyệt."
} else {
    Write-Warning "iQIYI đã mở nhưng app phụ đề chưa sẵn sàng. Chạy lại launcher để khởi động watcher."
}
