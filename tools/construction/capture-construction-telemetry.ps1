param(
    [Parameter(Mandatory = $true)]
    [string]$OutputPath,

    [Parameter(Mandatory = $true)]
    [string]$StopFile,

    [double]$IntervalSeconds = 2.0
)

$ErrorActionPreference = "SilentlyContinue"
Set-StrictMode -Version Latest

$OutputDirectory = Split-Path -Parent ([System.IO.Path]::GetFullPath($OutputPath))
if (-not (Test-Path -LiteralPath $OutputDirectory -PathType Container)) {
    New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
}

$NvidiaCommand = Get-Command nvidia-smi -ErrorAction SilentlyContinue
$NvidiaSmi = if ($null -eq $NvidiaCommand) { $null } else { $NvidiaCommand.Source }
$First = $true

while (Test-Path -LiteralPath $StopFile -PathType Leaf) {
    $Timestamp = (Get-Date).ToUniversalTime().ToString("o")

    $CpuPercent = $null
    $MemoryAvailableBytes = $null
    $MemoryTotalBytes = $null

    try {
        $Cpu = Get-CimInstance Win32_PerfFormattedData_PerfOS_Processor -Filter "Name='_Total'"
        if ($null -ne $Cpu.PercentProcessorTime) {
            $CpuPercent = [double]$Cpu.PercentProcessorTime
        }
    }
    catch {}

    try {
        $OperatingSystem = Get-CimInstance Win32_OperatingSystem
        if ($null -ne $OperatingSystem.FreePhysicalMemory) {
            $MemoryAvailableBytes = [int64]$OperatingSystem.FreePhysicalMemory * 1024
        }
        if ($null -ne $OperatingSystem.TotalVisibleMemorySize) {
            $MemoryTotalBytes = [int64]$OperatingSystem.TotalVisibleMemorySize * 1024
        }
    }
    catch {}

    $GpuUtilizationPercent = $null
    $GpuMemoryUsedMiB = $null
    $GpuMemoryTotalMiB = $null
    $GpuPowerDrawWatts = $null
    $GpuTemperatureC = $null

    if ($null -ne $NvidiaSmi) {
        try {
            $GpuLine = & $NvidiaSmi `
                --query-gpu=utilization.gpu,memory.used,memory.total,power.draw,temperature.gpu `
                --format=csv,noheader,nounits 2>$null |
                Select-Object -First 1

            if (-not [string]::IsNullOrWhiteSpace($GpuLine)) {
                $Parts = @($GpuLine -split ',' | ForEach-Object { $_.Trim() })
                if ($Parts.Count -ge 5) {
                    [double]$Parsed = 0
                    if ([double]::TryParse($Parts[0], [ref]$Parsed)) { $GpuUtilizationPercent = $Parsed }
                    if ([double]::TryParse($Parts[1], [ref]$Parsed)) { $GpuMemoryUsedMiB = $Parsed }
                    if ([double]::TryParse($Parts[2], [ref]$Parsed)) { $GpuMemoryTotalMiB = $Parsed }
                    if ([double]::TryParse($Parts[3], [ref]$Parsed)) { $GpuPowerDrawWatts = $Parsed }
                    if ([double]::TryParse($Parts[4], [ref]$Parsed)) { $GpuTemperatureC = $Parsed }
                }
            }
        }
        catch {}
    }

    $Row = [pscustomobject]@{
        timestamp_utc = $Timestamp
        cpu_percent = $CpuPercent
        memory_available_bytes = $MemoryAvailableBytes
        memory_total_bytes = $MemoryTotalBytes
        gpu_utilization_percent = $GpuUtilizationPercent
        gpu_memory_used_mib = $GpuMemoryUsedMiB
        gpu_memory_total_mib = $GpuMemoryTotalMiB
        gpu_power_draw_watts = $GpuPowerDrawWatts
        gpu_temperature_c = $GpuTemperatureC
    }

    if ($First) {
        $Row | Export-Csv -LiteralPath $OutputPath -NoTypeInformation -Encoding utf8
        $First = $false
    }
    else {
        $Row | Export-Csv -LiteralPath $OutputPath -NoTypeInformation -Encoding utf8 -Append
    }

    Start-Sleep -Milliseconds ([Math]::Max(250, [int]($IntervalSeconds * 1000)))
}
