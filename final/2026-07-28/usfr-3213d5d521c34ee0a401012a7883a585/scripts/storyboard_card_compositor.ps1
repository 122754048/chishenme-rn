param(
    [Parameter(Mandatory = $true)][string]$BasePath,
    [Parameter(Mandatory = $true)][string]$CardsPath,
    [Parameter(Mandatory = $true)][string]$OutputPath
)

Add-Type -AssemblyName System.Drawing

function Get-Sha256([string]$Path) {
    (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

$base = [System.Drawing.Bitmap]::new($BasePath)
$cards = (Get-Content -Raw -LiteralPath $CardsPath | ConvertFrom-Json).cards

try {
    $output = [System.Drawing.Bitmap]::new($base)
    try {
        $graphics = [System.Drawing.Graphics]::FromImage($output)
        try {
            $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
            foreach ($card in $cards) {
                $cardImage = [System.Drawing.Bitmap]::new($card.source_path)
                try {
                    $x, $y, $width, $height = $card.rect
                    $scale = [Math]::Min($width / $cardImage.Width, $height / $cardImage.Height)
                    $drawWidth = [int][Math]::Round($cardImage.Width * $scale)
                    $drawHeight = [int][Math]::Round($cardImage.Height * $scale)
                    $drawX = $x + [int][Math]::Floor(($width - $drawWidth) / 2)
                    $drawY = $y + [int][Math]::Floor(($height - $drawHeight) / 2)
                    $graphics.DrawImage($cardImage, $drawX, $drawY, $drawWidth, $drawHeight)
                } finally {
                    $cardImage.Dispose()
                }
            }
        } finally {
            $graphics.Dispose()
        }

        $output.Save($OutputPath, [System.Drawing.Imaging.ImageFormat]::Png)
    } finally {
        $output.Dispose()
    }
} finally {
    $base.Dispose()
}

$receipt = [ordered]@{
    schema_version = 'usfr-storyboard-source-ui-cards/v1'
    base_path = $BasePath
    base_sha256 = Get-Sha256 $BasePath
    cards_path = $CardsPath
    cards_sha256 = Get-Sha256 $CardsPath
    output_path = $OutputPath
    output_sha256 = Get-Sha256 $OutputPath
    card_count = @($cards).Count
    render_mode = 'deterministic_source_ui_card_composition'
}
$receipt | ConvertTo-Json -Depth 4 | Set-Content -Encoding utf8 -LiteralPath ($OutputPath.Replace('.png', '.receipt.json'))
