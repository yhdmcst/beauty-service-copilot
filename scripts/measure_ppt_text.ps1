param(
    [Parameter(Mandatory)]
    [string]$Presentation,
    [Parameter(Mandatory)]
    [string]$Output
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$root = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$inputPath = [IO.Path]::GetFullPath((Join-Path $root $Presentation))
$outputPath = [IO.Path]::GetFullPath((Join-Path $root $Output))
if (-not $outputPath.StartsWith($root + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Output must stay in the project.'
}
if (Test-Path -LiteralPath $outputPath) {
    throw 'Existing measurement retained. Choose a new output path.'
}
$bitmap = [Drawing.Bitmap]::new(1, 1)
$bitmap.SetResolution(96, 96)
$graphics = [Drawing.Graphics]::FromImage($bitmap)
$zip = [IO.Compression.ZipFile]::OpenRead($inputPath)
$rows = [Collections.Generic.List[object]]::new()
try {
    $slides = $zip.Entries | Where-Object { $_.FullName -match '^ppt/slides/slide\d+\.xml$' }
    foreach ($entry in $slides) {
        $reader = [IO.StreamReader]::new($entry.Open())
        try { [xml]$doc = $reader.ReadToEnd() } finally { $reader.Dispose() }
        $ns = [Xml.XmlNamespaceManager]::new($doc.NameTable)
        $ns.AddNamespace('p', 'http://schemas.openxmlformats.org/presentationml/2006/main')
        $ns.AddNamespace('a', 'http://schemas.openxmlformats.org/drawingml/2006/main')
        foreach ($shape in $doc.SelectNodes('//p:sp[p:txBody]', $ns)) {
            $extent = $shape.SelectSingleNode('p:spPr/a:xfrm/a:ext', $ns)
            if ($null -eq $extent) { continue }
            $body = $shape.SelectSingleNode('p:txBody/a:bodyPr', $ns)
            $width = [double]$extent.GetAttribute('cx') / 914400 * 96
            $height = [double]$extent.GetAttribute('cy') / 914400 * 96
            $width -= ([double]$body.GetAttribute('lIns') + [double]$body.GetAttribute('rIns')) / 914400 * 96
            $height -= ([double]$body.GetAttribute('tIns') + [double]$body.GetAttribute('bIns')) / 914400 * 96
            $needed = 0.0
            $parts = [Collections.Generic.List[string]]::new()
            foreach ($paragraph in $shape.SelectNodes('p:txBody/a:p', $ns)) {
                $texts = @($paragraph.SelectNodes('.//a:t', $ns) | ForEach-Object { $_.InnerText })
                $text = $texts -join ''
                $parts.Add($text)
                $styleNode = $paragraph.SelectSingleNode('a:r/a:rPr', $ns)
                if ($null -eq $styleNode) { $styleNode = $paragraph.SelectSingleNode('a:endParaRPr', $ns) }
                $fontSize = if ($styleNode.HasAttribute('sz')) { [double]$styleNode.GetAttribute('sz') / 100 } else { 18 }
                $fontName = $styleNode.SelectSingleNode('a:latin', $ns)
                $family = if ($null -ne $fontName) { $fontName.GetAttribute('typeface') } else { 'Microsoft YaHei' }
                $weight = if ($styleNode.GetAttribute('b') -eq '1') { [Drawing.FontStyle]::Bold } else { [Drawing.FontStyle]::Regular }
                $font = [Drawing.Font]::new($family, [single]$fontSize, $weight, [Drawing.GraphicsUnit]::Point)
                $format = [Drawing.StringFormat]::GenericTypographic.Clone()
                try {
                    $sample = if ($text.Length) { $text } else { ' ' }
                    $size = $graphics.MeasureString($sample, $font, [Drawing.SizeF]::new([single]$width, 10000), $format)
                    $needed += [Math]::Max($size.Height, $font.GetHeight($graphics))
                } finally {
                    $format.Dispose()
                    $font.Dispose()
                }
            }
            $rows.Add([ordered]@{
                slide = $entry.FullName
                text = $parts -join "`n"
                width_px = [Math]::Round($width, 2)
                available_height_px = [Math]::Round($height, 2)
                measured_height_px = [Math]::Round($needed, 2)
                overflow_px = [Math]::Round([Math]::Max(0, $needed - $height), 2)
                risk = $needed -gt $height + 2
            })
        }
    }
} finally {
    $zip.Dispose()
    $graphics.Dispose()
    $bitmap.Dispose()
}
$report = [ordered]@{
    measured_at = (Get-Date).ToString('o')
    presentation = $Presentation
    scope = 'Windows GDI+ text-height estimate at 96 DPI; not PowerPoint rendering or visual review'
    text_box_n = $rows.Count
    risk_n = @($rows | Where-Object { $_.risk }).Count
    rows = @($rows.ToArray())
}
New-Item -ItemType Directory -Path (Split-Path -Parent $outputPath) -Force | Out-Null
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $outputPath -Encoding utf8
$report.rows | Where-Object { $_.risk } | ConvertTo-Json -Depth 5
Write-Output "Text boxes: $($report.text_box_n), estimated overflow risks: $($report.risk_n)"
