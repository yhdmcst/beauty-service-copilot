param(
    [Parameter(Mandatory)]
    [string]$Presentation,
    [Parameter(Mandatory)]
    [string]$Output
)

$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$inputPath = [IO.Path]::GetFullPath((Join-Path $root $Presentation))
$outputPath = [IO.Path]::GetFullPath((Join-Path $root $Output))
if (-not $outputPath.StartsWith($root + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Output must stay in the project.'
}
if (Test-Path -LiteralPath $outputPath) {
    throw 'Render directory already exists. Choose another path.'
}
$beforeHash = (Get-FileHash -LiteralPath $inputPath -Algorithm SHA256).Hash
$existing = @(Get-Process POWERPNT -ErrorAction SilentlyContinue)
$application = $null
$presentationObject = $null
$rows = [Collections.Generic.List[object]]::new()
try {
    $application = New-Object -ComObject PowerPoint.Application
    $application.AutomationSecurity = 3
    $application.DisplayAlerts = 1
    $presentationObject = $application.Presentations.Open($inputPath, -1, 0, 0)
    New-Item -ItemType Directory -Path $outputPath | Out-Null
    for ($i = 1; $i -le $presentationObject.Slides.Count; $i++) {
        $slide = $presentationObject.Slides.Item($i)
        try {
            $image = Join-Path $outputPath ('slide-{0:d2}.png' -f $i)
            $slide.Export($image, 'PNG', 1600, 900)
            for ($j = 1; $j -le $slide.Shapes.Count; $j++) {
                $shape = $slide.Shapes.Item($j)
                try {
                    if ($shape.HasTextFrame -ne -1 -or $shape.TextFrame.HasText -ne -1) { continue }
                    $frame = $shape.TextFrame2
                    $range = $frame.TextRange
                    $text = $range.Text
                    if (-not $text.Trim()) { continue }
                    $availableHeight = $shape.Height - $frame.MarginTop - $frame.MarginBottom
                    $availableWidth = $shape.Width - $frame.MarginLeft - $frame.MarginRight
                    $rows.Add([ordered]@{
                        slide = $i
                        text = $text
                        box_height_pt = [Math]::Round($availableHeight, 3)
                        bound_height_pt = [Math]::Round($range.BoundHeight, 3)
                        box_width_pt = [Math]::Round($availableWidth, 3)
                        bound_width_pt = [Math]::Round($range.BoundWidth, 3)
                        overflow = $range.BoundHeight -gt $availableHeight + 1 -or $range.BoundWidth -gt $availableWidth + 1
                    })
                } finally {
                    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($shape)
                }
            }
        } finally {
            [void][Runtime.InteropServices.Marshal]::ReleaseComObject($slide)
        }
    }
    $presentationObject.SaveAs((Join-Path $outputPath 'presentation.pdf'), 32)
    $result = [ordered]@{
        rendered_at = (Get-Date).ToString('o')
        scope = 'PowerPoint read-only opening, native PNG/PDF export and text bounds; not manual visual review'
        presentation = $Presentation
        source_sha256 = $beforeHash
        slide_n = $presentationObject.Slides.Count
        text_box_n = $rows.Count
        overflow_n = @($rows | Where-Object { $_.overflow }).Count
        rows = @($rows.ToArray())
    }
    $result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $outputPath 'powerpoint_bounds.json') -Encoding utf8
    $rows | Where-Object { $_.overflow } | ConvertTo-Json -Depth 5
    Write-Output "PowerPoint rendered $($result.slide_n) slides; text bounds flagged $($result.overflow_n) boxes."
} finally {
    if ($null -ne $presentationObject) {
        $presentationObject.Close()
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($presentationObject)
    }
    if ($null -ne $application) {
        if ($existing.Count -eq 0 -and $application.Presentations.Count -eq 0) { $application.Quit() }
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($application)
    }
}
$afterHash = (Get-FileHash -LiteralPath $inputPath -Algorithm SHA256).Hash
if ($afterHash -ne $beforeHash) { throw 'Input presentation changed during read-only export.' }
