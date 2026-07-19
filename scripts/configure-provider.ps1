param(
    [string]$BaseUrl = "https://jianzhile.vip/v1"
)

$ErrorActionPreference = "Stop"

if (-not $BaseUrl.StartsWith("https://")) {
    throw "BaseUrl must use HTTPS."
}

$BaseUrl = $BaseUrl.TrimEnd("/")
$secureKey = Read-Host "Enter a newly generated API key" -AsSecureString
$apiKey = [System.Net.NetworkCredential]::new("", $secureKey).Password

try {
    $response = Invoke-RestMethod `
        -Uri "$BaseUrl/models" `
        -Headers @{ Authorization = "Bearer $apiKey" } `
        -Method Get

    $models = @($response.data | ForEach-Object { $_.id } | Sort-Object -Unique)
    if ($models.Count -eq 0) {
        throw "The provider returned no model IDs."
    }

    Write-Host "Available models:"
    for ($index = 0; $index -lt $models.Count; $index++) {
        Write-Host "[$($index + 1)] $($models[$index])"
    }

    $selection = Read-Host "Choose a model number"
    if ($selection -notmatch "^\d+$") {
        throw "Model selection must be a number."
    }

    $selectedIndex = [int]$selection - 1
    if ($selectedIndex -lt 0 -or $selectedIndex -ge $models.Count) {
        throw "Model selection is out of range."
    }

    $model = $models[$selectedIndex]
    if ($model -notmatch "^[A-Za-z0-9._:/-]+$") {
        throw "The selected model ID contains unsupported characters."
    }

    @(
        "MODEL=openai:$model"
        "OPENAI_API_KEY=$apiKey"
        "OPENAI_BASE_URL=$BaseUrl"
    ) | Set-Content -Path ".env" -Encoding ascii

    Write-Host "Configured model '$model' in ignored .env."
}
finally {
    $apiKey = $null
    $secureKey.Dispose()
}