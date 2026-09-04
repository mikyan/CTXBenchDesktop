$ErrorActionPreference = "Continue"

function Test-Command([string]$Name) {
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

$cargoCommand = Get-Command "cargo" -ErrorAction SilentlyContinue
$rustupCargo = Join-Path $env:USERPROFILE ".cargo\bin\cargo.exe"
$cargoPath = if ($cargoCommand) { $cargoCommand.Source } elseif (Test-Path -LiteralPath $rustupCargo) { $rustupCargo } else { $null }

$checks = @()
$checks += [pscustomobject]@{ Check = "Node.js"; Ready = (Test-Command "node"); Detail = if (Test-Command "node") { node --version } else { "Install Node.js LTS" } }
$checks += [pscustomobject]@{ Check = "Rust"; Ready = ($null -ne $cargoPath); Detail = if ($cargoPath) { & $cargoPath --version } else { "Install Rust MSVC with rustup" } }
$vswhere = "C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
$msvcPath = if (Test-Path -LiteralPath $vswhere) { & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath } else { $null }
$msvcReady = (Test-Command "cl") -or -not [string]::IsNullOrWhiteSpace($msvcPath)
$checks += [pscustomobject]@{ Check = "MSVC"; Ready = $msvcReady; Detail = if ($msvcReady) { if ($msvcPath) { $msvcPath } else { "C++ compiler available" } } else { "Install Visual Studio Build Tools: Desktop development with C++" } }
$checks += [pscustomobject]@{ Check = "WSL"; Ready = (Test-Command "wsl"); Detail = if (Test-Command "wsl") { (wsl -d Ubuntu -- uname -r 2>$null) } else { "Install WSL2 and Ubuntu" } }
$dockerVersion = if (Test-Command "wsl") { wsl -d Ubuntu -- sh -lc "docker version --format '{{.Server.Version}}' 2>/dev/null" } else { $null }
$checks += [pscustomobject]@{ Check = "Docker in WSL"; Ready = ($LASTEXITCODE -eq 0 -and $null -ne $dockerVersion); Detail = if ($dockerVersion) { "Docker Engine $dockerVersion" } else { "Run scripts/wsl/install-docker.sh explicitly inside Ubuntu" } }

$checks | Format-Table -AutoSize
if ($checks.Ready -contains $false) { exit 1 }
