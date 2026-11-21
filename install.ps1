# Download and verify a Foundry client release using Windows tools.
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$AllowedSigners,
  [string]$Repository = 'kekxv/foundry',
  [string]$Version,
  [string]$InstallDir,
  [string]$ReleaseBaseUrl
)

$ErrorActionPreference = 'Stop'
$work = $null
$created = $false
$names = @('foundry.exe', 'foundry-worker.exe')
$stableVersion = '(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)'

function Receive-Asset([string]$Url, [string]$OutputFile, [long]$Limit) {
  $curlArgs = @('-q', '-fsSL', '--proto', '=https', '--proto-redir', '=https',
    '--globoff', '--connect-timeout', '15', '--max-time', '180',
    '--max-filesize', "$Limit", '--output', $OutputFile)
  if ($env:FOUNDRY_CA_CERT) { $curlArgs += @('--cacert', $env:FOUNDRY_CA_CERT) }
  & $curl @curlArgs -- $Url
  if ($LASTEXITCODE -ne 0) { throw "Download failed for $Url" }
  if ((Get-Item -LiteralPath $OutputFile).Length -gt $Limit) {
    throw 'Download exceeds size limit'
  }
}

try {
  if ([System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture -ne 'X64' -or
      [Environment]::OSVersion.Platform -ne 'Win32NT') {
    throw 'This installer requires Windows x64'
  }
  $system = [Environment]::SystemDirectory
  $curl = Join-Path $system 'curl.exe'
  $ssh = Join-Path $system 'OpenSSH/ssh-keygen.exe'
  if (-not [IO.File]::Exists($curl) -or -not [IO.File]::Exists($ssh)) {
    throw 'Windows curl and OpenSSH Client with ssh-keygen -Y verify are required'
  }

  if (-not $ReleaseBaseUrl) {
    if ($Repository -cnotmatch '\A[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+\z' -or
        $Repository -match '/\.{1,2}$') {
      throw 'Provide the GitHub repository with -Repository OWNER/REPO'
    }
    $ReleaseBaseUrl = "https://github.com/$Repository/releases"
  }
  $ReleaseBaseUrl = $ReleaseBaseUrl.TrimEnd('/')
  $uri = [Uri]$ReleaseBaseUrl
  if (-not $uri.IsAbsoluteUri -or $uri.Scheme -ne 'https' -or -not $uri.Host -or
      $uri.UserInfo -or $uri.Query -or $uri.Fragment) {
    throw 'Release downloads require a valid HTTPS base URL'
  }
  $endpoint = "$ReleaseBaseUrl/latest/download"
  if ($Version) {
    if ($Version -cnotmatch "\A$stableVersion\z") { throw 'Expected version x.y.z' }
    $endpoint = "$ReleaseBaseUrl/download/v$Version"
  }
  $trustedFile = Get-Item -LiteralPath $AllowedSigners
  if ($trustedFile.PSIsContainer) { throw 'Supply a trusted allowed-signers file' }
  $work = Join-Path ([IO.Path]::GetTempPath()) ("foundry-install-" + [Guid]::NewGuid())
  New-Item -ItemType Directory -Path $work | Out-Null
  $manifest = Join-Path $work 'install-manifest.txt'
  $signature = Join-Path $work 'install-manifest.txt.sig'
  $signers = Join-Path $work 'allowed_signers'
  Copy-Item -LiteralPath $trustedFile.FullName -Destination $signers
  $cutoff = Get-Content -LiteralPath $signers -TotalCount 1
  if ($cutoff -cnotmatch '\A# foundry-install-v1 expires-at ([0-9]{1,20})\z' -or
      [UInt64]$Matches[1] -le [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()) {
    throw 'invalid or expired allowed-signers file'
  }
  $trustExpiry = [UInt64]$Matches[1]
  Receive-Asset "$endpoint/install-manifest.txt" $manifest 16384
  Receive-Asset "$endpoint/install-manifest.txt.sig" $signature 16384
  # Redirect the original bytes into OpenSSH without PowerShell's text pipeline.
  $start = New-Object System.Diagnostics.ProcessStartInfo
  $start.FileName = $ssh
  $start.WorkingDirectory = $work
  $start.Arguments = '-Y verify -I foundry-release -n foundry-install-v1 -f allowed_signers -s install-manifest.txt.sig'
  $start.UseShellExecute = $false
  $start.RedirectStandardInput = $true
  $verify = [Diagnostics.Process]::Start($start)
  try {
    $bytes = [IO.File]::ReadAllBytes($manifest)
    $stdin = $verify.StandardInput.BaseStream
    $stdin.Write($bytes, 0, $bytes.Length)
    $stdin.Close()
    $verify.WaitForExit()
    if ($verify.ExitCode -ne 0) { throw 'release signature verification failed' }
  } finally { $verify.Dispose() }

  $lines = [IO.File]::ReadAllLines($manifest)
  if ($lines.Length -lt 2 -or $lines[0] -cnotmatch "\Afoundry-install-v1 ($stableVersion) ([0-9]{1,20})\z") {
    throw 'Invalid installation manifest'
  }
  $release = $Matches[1]
  $expires = [UInt64]$Matches[2]
  if ($expires -le [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() -or $expires -gt $trustExpiry -or
      ($Version -and $Version -cne $release)) {
    throw 'Expired or mismatched installation manifest'
  }
  $name = "foundry-$release-windows-x64.zip"
  $records = @($lines | Select-Object -Skip 1 | Where-Object { $_.EndsWith(" $name") })
  if ($records.Count -ne 1 -or
      $records[0] -cnotmatch ('\A([0-9a-f]{64}) ([1-9][0-9]{0,8}) ' + [regex]::Escape($name) + '\z')) {
    throw 'Invalid or missing Windows ZIP record'
  }
  $expected = $Matches[1]
  $size = [long]$Matches[2]
  if ($size -gt 134217728) { throw 'ZIP exceeds size limit' }
  $archive = Join-Path $work $name
  Receive-Asset "$ReleaseBaseUrl/download/v$release/$name" $archive $size
  if ((Get-Item -LiteralPath $archive).Length -ne $size) { throw 'ZIP size mismatch' }
  if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ine $expected) {
    throw 'ZIP SHA-256 mismatch'
  }

  Add-Type -AssemblyName System.IO.Compression.FileSystem
  $zip = [IO.Compression.ZipFile]::OpenRead($archive)
  try {
    foreach ($binary in $names) {
      $entries = @($zip.Entries | Where-Object { $_.FullName -ceq $binary })
      if ($entries.Count -ne 1 -or $entries[0].Length -le 0 -or $entries[0].Length -gt 134217728) {
        throw "Invalid ZIP entry $binary"
      }
      [IO.Compression.ZipFileExtensions]::ExtractToFile(
        $entries[0], (Join-Path $work $binary), $false)
    }
  } finally { $zip.Dispose() }

  if (-not $InstallDir) { $InstallDir = Join-Path $env:LOCALAPPDATA "foundry/clients/$release" }
  $destination = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($InstallDir)
  if (Test-Path -LiteralPath $destination) { throw "install directory already exists: $destination" }
  New-Item -ItemType Directory -Path $destination | Out-Null
  $created = $true
  foreach ($binary in $names) {
    [IO.File]::Copy((Join-Path $work $binary), (Join-Path $destination $binary), $false)
  }
  $created = $false
  Write-Output "Installed Foundry $release in $destination"
} catch {
  [Console]::Error.WriteLine("Foundry installation failed: " + $_.Exception.Message)
  exit 1
} finally {
  if ($created) {
    foreach ($binary in $names) {
      Remove-Item -LiteralPath (Join-Path $destination $binary) -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $destination -ErrorAction SilentlyContinue
  }
  if ($work) { Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue }
}
