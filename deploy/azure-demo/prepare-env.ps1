param(
    [Parameter(Mandatory=$true)][string]$VerifyFlowDomain,
    [Parameter(Mandatory=$true)][string]$PortalDomain
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$vfPath = Join-Path $repo 'backend/.env'
$portalPath = Join-Path $repo 'mock-aicte-portal/.env'
if (-not (Test-Path -LiteralPath $vfPath) -or -not (Test-Path -LiteralPath $portalPath)) {
    throw 'The existing local backend/.env and mock-aicte-portal/.env are required.'
}
foreach ($domain in @($VerifyFlowDomain, $PortalDomain)) {
    if ($domain -notmatch '^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])$' -or $domain -notmatch '\.') {
        throw "Invalid domain name: $domain"
    }
}

function Read-Env([string]$path) {
    $values = @{}
    foreach ($line in [System.IO.File]::ReadAllLines($path)) {
        if ($line -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') { $values[$Matches[1]] = $Matches[2] }
    }
    return $values
}

$vf = Read-Env $vfPath
$portal = Read-Env $portalPath
if (-not $vf['VERIFYFLOW_PORTAL_SHARED_SECRET'] -or
    $vf['VERIFYFLOW_PORTAL_SHARED_SECRET'] -ne $portal['VERIFYFLOW_INTAKE_SECRET']) {
    throw 'Local portal and VerifyFlow intake secrets are missing or differ.'
}
if (-not $portal['SECRET_KEY']) { throw 'Portal SECRET_KEY is missing.' }

$template = Read-Env (Join-Path $PSScriptRoot '.env.example')
$template['VERIFYFLOW_DOMAIN'] = $VerifyFlowDomain
$template['PORTAL_DOMAIN'] = $PortalDomain
$template['VERIFYFLOW_CORS_ORIGINS'] = '["https://' + $VerifyFlowDomain + '"]'
$template['VERIFYFLOW_PORTAL_SHARED_SECRET'] = $vf['VERIFYFLOW_PORTAL_SHARED_SECRET']
$template['VERIFYFLOW_INTAKE_SECRET'] = $vf['VERIFYFLOW_PORTAL_SHARED_SECRET']
$template['VERIFYFLOW_PORTAL_OWNER_EMAIL'] = $vf['VERIFYFLOW_PORTAL_OWNER_EMAIL']
$template['VERIFYFLOW_PORTAL_REVIEWER_EMAIL'] = $vf['VERIFYFLOW_PORTAL_REVIEWER_EMAIL']
$template['SECRET_KEY'] = $portal['SECRET_KEY']
foreach ($key in @('VERIFYFLOW_AI_PROVIDER', 'VERIFYFLOW_AI_API_KEY', 'VERIFYFLOW_AI_MODEL',
    'VERIFYFLOW_AI_INPUT_USD_PER_MTOK', 'VERIFYFLOW_AI_OUTPUT_USD_PER_MTOK',
    'VERIFYFLOW_AI_DOCUMENT_EGRESS', 'VERIFYFLOW_AI_DAILY_BUDGET_USD')) {
    if ($vf[$key]) { $template[$key] = $vf[$key] }
}

$out = Join-Path $PSScriptRoot '.env'
if (Test-Path -LiteralPath $out) { throw 'Deployment .env already exists. Edit it directly to preserve existing secrets.' }
$lines = foreach ($key in ($template.Keys | Sort-Object)) { "$key=$($template[$key])" }
[System.IO.File]::WriteAllLines($out, [string[]]$lines)
Write-Host 'Created private deploy/azure-demo/.env. Keep it out of Git.'
