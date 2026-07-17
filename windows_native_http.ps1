param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("GET", "POST")]
    [string]$Method,

    [Parameter(Mandatory = $true)]
    [string]$Url,

    [ValidateRange(1, 120)]
    [int]$TimeoutSec = 30
)

$ErrorActionPreference = "Stop"
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

function Write-Envelope {
    param([hashtable]$Value, [int]$ExitCode)
    [Console]::Out.WriteLine(($Value | ConvertTo-Json -Compress -Depth 5))
    exit $ExitCode
}

try {
    $uri = [Uri]$Url
} catch {
    Write-Envelope @{ ok = $false; status = 0; error = "invalid_url" } 64
}

if (
    $uri.Scheme -ne "https" -or
    $uri.DnsSafeHost -ne "generativelanguage.googleapis.com" -or
    -not $uri.AbsolutePath.StartsWith("/v1beta/models", [StringComparison]::Ordinal)
) {
    Write-Envelope @{ ok = $false; status = 0; error = "destination_not_allowed" } 64
}

$apiKey = $env:GEMINI_API_KEY
if ([string]::IsNullOrWhiteSpace($apiKey)) {
    Write-Envelope @{ ok = $false; status = 0; error = "key_missing" } 65
}

# Google documents REST generation authentication using the `key` query
# parameter. Construct it only inside this child process so the credential is
# absent from Python argv, shell history, project files, and helper output.
$uriBuilder = [UriBuilder]::new($uri)
$existingQuery = $uriBuilder.Query.TrimStart("?")
$keyQuery = "key=" + [Uri]::EscapeDataString($apiKey)
$uriBuilder.Query = if ($existingQuery) { $existingQuery + "&" + $keyQuery } else { $keyQuery }
$requestUri = $uriBuilder.Uri

$requestBody = [Console]::In.ReadToEnd()
Add-Type -AssemblyName System.Net.Http
$handler = [Net.Http.HttpClientHandler]::new()
$handler.AllowAutoRedirect = $false
$client = [Net.Http.HttpClient]::new($handler)
$client.Timeout = [TimeSpan]::FromSeconds($TimeoutSec)
$httpMethod = if ($Method -eq "GET") { [Net.Http.HttpMethod]::Get } else { [Net.Http.HttpMethod]::Post }
$request = [Net.Http.HttpRequestMessage]::new($httpMethod, $requestUri)
if ($Method -eq "POST") {
    $request.Content = [Net.Http.StringContent]::new(
        $requestBody,
        [Text.Encoding]::UTF8,
        "application/json"
    )
}

try {
    $response = $client.SendAsync($request).GetAwaiter().GetResult()
    $responseBody = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
    $status = [int]$response.StatusCode
    if ($response.IsSuccessStatusCode) {
        Write-Envelope @{ ok = $true; status = $status; body = $responseBody } 0
    }
    $apiStatus = ""
    try {
        $candidate = [string](($responseBody | ConvertFrom-Json).error.status)
        if ($candidate -match "^[A-Z_]{1,64}$") { $apiStatus = $candidate }
    } catch { $apiStatus = "" }
    Write-Envelope @{
        ok = $false
        status = $status
        api_status = $apiStatus
        error = "http_error"
    } 22
} catch {
    Write-Envelope @{ ok = $false; status = 0; error = "transport_error" } 23
} finally {
    if ($null -ne $response) { $response.Dispose() }
    $request.Dispose()
    $client.Dispose()
    $handler.Dispose()
}
