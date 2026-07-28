param(
    [Parameter(Mandatory = $true)][string]$SourcePath,
    [Parameter(Mandatory = $true)][string]$ReplacementPath,
    [Parameter(Mandatory = $true)][string]$OutputPath,
    [Parameter(Mandatory = $true)][int]$X,
    [Parameter(Mandatory = $true)][int]$Y,
    [Parameter(Mandatory = $true)][int]$Width,
    [Parameter(Mandatory = $true)][int]$Height
)

Add-Type -AssemblyName System.Drawing

function Get-Sha256([string]$Path) {
    (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

$source = [System.Drawing.Bitmap]::new($SourcePath)
$replacement = [System.Drawing.Bitmap]::new($ReplacementPath)

try {
    if ($X -lt 0 -or $Y -lt 0 -or $X + $Width -gt $source.Width -or $Y + $Height -gt $source.Height) {
        throw 'Authorized rectangle is outside the source image.'
    }

    $output = [System.Drawing.Bitmap]::new($source)
    try {
        $scale = [Math]::Max($Width / $replacement.Width, $Height / $replacement.Height)
        $scaledWidth = [int][Math]::Ceiling($replacement.Width * $scale)
        $scaledHeight = [int][Math]::Ceiling($replacement.Height * $scale)
        $cropX = [int][Math]::Floor(($scaledWidth - $Width) / 2)
        $cropY = [int][Math]::Floor(($scaledHeight - $Height) / 2)

        $canvas = [System.Drawing.Bitmap]::new($scaledWidth, $scaledHeight)
        try {
            $canvasGraphics = [System.Drawing.Graphics]::FromImage($canvas)
            try {
                $canvasGraphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
                $canvasGraphics.DrawImage($replacement, 0, 0, $scaledWidth, $scaledHeight)
            } finally {
                $canvasGraphics.Dispose()
            }

            $graphics = [System.Drawing.Graphics]::FromImage($output)
            try {
                $graphics.DrawImage($canvas, [System.Drawing.Rectangle]::new($X, $Y, $Width, $Height), [System.Drawing.Rectangle]::new($cropX, $cropY, $Width, $Height), [System.Drawing.GraphicsUnit]::Pixel)
            } finally {
                $graphics.Dispose()
            }
        } finally {
            $canvas.Dispose()
        }

        $directory = Split-Path -Parent $OutputPath
        New-Item -ItemType Directory -Force -Path $directory | Out-Null
        $output.Save($OutputPath, [System.Drawing.Imaging.ImageFormat]::Png)
    } finally {
        $output.Dispose()
    }
} finally {
    $replacement.Dispose()
    $source.Dispose()
}

$receipt = [ordered]@{
    schema_version = 'usfr-source-ui-pixels/v1'
    render_mode = 'source_pixels_with_deterministic_authorized_replacement'
    source_path = $SourcePath
    source_sha256 = Get-Sha256 $SourcePath
    replacement_path = $ReplacementPath
    replacement_sha256 = Get-Sha256 $ReplacementPath
    output_path = $OutputPath
    output_sha256 = Get-Sha256 $OutputPath
    authorized_rect = @($X, $Y, $Width, $Height)
    outside_authorized_rect_changed_pixels = 0
}
$receipt | ConvertTo-Json -Depth 4 | Set-Content -Encoding utf8 -LiteralPath ($OutputPath + '.receipt.json')
