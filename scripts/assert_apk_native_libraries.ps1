[CmdletBinding()]
param([Parameter(Mandatory=$true)][IO.Compression.ZipArchive]$Archive)

$ErrorActionPreference='Stop'
$architectures=@($Archive.Entries | ForEach-Object {
    if($_.FullName -match '^lib/([^/]+)/[^/]+\.so$'){$matches[1]}
} | Sort-Object -Unique)
if($architectures.Count -eq 0){throw 'APK has no native libraries'}
foreach($architecture in $architectures){
    foreach($library in @('libexpo-av.so','libexpo-modules-core.so','libhermes.so','libreactnativejni.so')){
        $entry=$Archive.GetEntry("lib/$architecture/$library")
        if(-not $entry -or $entry.Length -eq 0){
            throw "APK is missing $library for declared architecture $architecture; release refused"
        }
    }
}
