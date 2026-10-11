# Builds the CurseForge upload zip.
#
# The zip MUST contain a single top-level folder named exactly TransmogPalette,
# because that is the folder WoW loads and the .toc inside must match its name.
# Zipping the *contents* instead produces an addon the client silently ignores.
#
# Only .lua and .toc ship. The ColorData.lua.bak-* files in the addon folder are
# development leftovers and are excluded explicitly -- a -Recurse copy once put
# them into the live AddOns directory.
param(
    [string]$OutDir = "$PSScriptRoot\..\dist"
)

$ErrorActionPreference = "Stop"

$root    = Split-Path $PSScriptRoot -Parent
$addon   = Join-Path $root "TransmogPalette"
$tocPath = Join-Path $addon "TransmogPalette.toc"

if (-not (Test-Path $tocPath)) { throw "no .toc at $tocPath" }

# Version comes from the .toc so there is one source of truth.
$toc = Get-Content $tocPath
$version = ($toc | Select-String '^## Version:\s*(.+)$').Matches.Groups[1].Value.Trim()
$iface   = ($toc | Select-String '^## Interface:\s*(.+)$').Matches.Groups[1].Value.Trim()
if (-not $version) { throw "no '## Version:' line in the .toc" }

# Every file listed in the .toc must exist, or the addon errors on load for
# everyone who installs it.
$listed = $toc | Where-Object { $_ -match '\.lua\s*$' } | ForEach-Object { $_.Trim() }
$missing = $listed | Where-Object { -not (Test-Path (Join-Path $addon $_)) }
if ($missing) { throw "listed in .toc but missing: $($missing -join ', ')" }

$stage = Join-Path ([IO.Path]::GetTempPath()) ("tmpalette-" + [Guid]::NewGuid().ToString("N"))
$dest  = Join-Path $stage "TransmogPalette"
New-Item -ItemType Directory -Force -Path $dest | Out-Null

# Development-only files stay in the .toc for the live junctioned copy but are
# dropped from the release, .toc line included.
$devOnly = @("Capture.lua")
$listed = $listed | Where-Object { $devOnly -notcontains $_ }
$toc | Where-Object { $devOnly -notcontains $_.Trim() } | Set-Content (Join-Path $dest "TransmogPalette.toc") -Encoding ASCII
foreach ($f in $listed) { Copy-Item (Join-Path $addon $f) $dest }
foreach ($extra in @("LICENSE", "CHANGELOG.md")) {
    $p = Join-Path $root $extra
    if (Test-Path $p) { Copy-Item $p $dest }
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$zip = Join-Path $OutDir "TransmogPalette-$version.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
# Not Compress-Archive: on Windows PowerShell 5.1 it writes entry names with
# backslashes, which the zip format forbids. Windows copes; macOS and Linux
# extractors can produce a flat file literally named "TransmogPalette\Core.lua".
Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
$out = [IO.Compression.ZipFile]::Open($zip, [IO.Compression.ZipArchiveMode]::Create)
try {
    Get-ChildItem $dest -File | Sort-Object Name | ForEach-Object {
        [IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $out, $_.FullName, "TransmogPalette/$($_.Name)",
            [IO.Compression.CompressionLevel]::Optimal) | Out-Null
    }
} finally { $out.Dispose() }
Remove-Item $stage -Recurse -Force

$size = (Get-Item $zip).Length / 1MB
"built  $zip"
"        version $version, interface $iface, {0:N2} MB" -f $size
""
"contents:"
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [IO.Compression.ZipFile]::OpenRead($zip)
$archive.Entries | ForEach-Object { "  {0,-46} {1,10:N0}" -f $_.FullName, $_.Length }
$archive.Dispose()
