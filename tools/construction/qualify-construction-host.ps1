param(
    [string]$DockerImage = "python:3.12-slim",
    [string]$BaseUrl = "http://127.0.0.1:11434"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Write-Host "=== Construction Lab Host Qualification ===" -ForegroundColor Cyan

$Docker = Get-Command docker -ErrorAction Stop
$Git = Get-Command git -ErrorAction Stop
$Python = Get-Command python -ErrorAction Stop
$Ollama = Get-Command ollama -ErrorAction Stop

Write-Host "git:    $(& git --version)"
Write-Host "python: $(& python --version 2>&1)"
Write-Host "ollama: $(& ollama --version 2>&1)"
Write-Host "docker: $(& docker --version 2>&1)"

& docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker CLI is installed but the Docker engine is not available. Start Docker Desktop."
}

& docker image inspect $DockerImage *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Required image '$DockerImage' is not present. Run: docker pull $DockerImage"
}

$Smoke = & docker run --rm --pull never --network none --memory 256m --cpus 1 --pids-limit 64 --read-only `
    --tmpfs /tmp:rw,noexec,nosuid,size=32m $DockerImage `
    python -c "import sys; print(sys.version_info[:2])" 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "Bounded Docker smoke failed: $Smoke"
}
Write-Host "bounded container: PASS ($Smoke)"

try {
    $Tags = Invoke-RestMethod -Uri ($BaseUrl.TrimEnd('/') + "/api/tags") -Method Get -TimeoutSec 5
    Write-Host "ollama API: PASS ($($Tags.models.Count) model(s) visible)"
}
catch {
    throw "Ollama API qualification failed at $BaseUrl: $($_.Exception.Message)"
}

Write-Host "Construction Lab host qualification: PASS" -ForegroundColor Green
