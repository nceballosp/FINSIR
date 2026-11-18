<#
.SYNOPSIS
  Muestra la URL pública actual de la API FINSIR en ECS Fargate.
.DESCRIPTION
  La API no tiene balanceador: su IP pública cambia en cada redespliegue.
  Este script la resuelve con AWS CLI y, si lo pides, actualiza API_BASE_URL
  en .streamlit/secrets.toml. En Streamlit Community Cloud hay que pegarla a
  mano en Settings -> Secrets.
.EXAMPLE
  .\dashboard\get_api_url.ps1
  .\dashboard\get_api_url.ps1 -Profile terraform -UpdateSecrets
#>
param(
  [string]$Profile = "terraform",
  [string]$Region = "us-east-1",
  [string]$Cluster = "finsir-api-cluster",
  [string]$Service = "finsir-api",
  [switch]$UpdateSecrets
)
$ErrorActionPreference = "Stop"
$env:AWS_PROFILE = $Profile

$task = (aws ecs list-tasks --cluster $Cluster --service-name $Service --desired-status RUNNING `
  --region $Region --query 'taskArns[0]' --output text)
if (-not $task -or $task -eq "None") {
  throw "No hay ninguna tarea RUNNING en $Cluster/$Service. ¿La API está desplegada?"
}
$eni = (aws ecs describe-tasks --cluster $Cluster --tasks $task --region $Region `
  --query 'tasks[0].attachments[0].details[?name==`networkInterfaceId`].value | [0]' --output text)
$ip = (aws ec2 describe-network-interfaces --network-interface-ids $eni --region $Region `
  --query 'NetworkInterfaces[0].Association.PublicIp' --output text)
if (-not $ip -or $ip -eq "None") { throw "La tarea aún no tiene IP pública. Intenta en unos segundos." }

$url = "http://${ip}:8080"
Write-Host "API_BASE_URL = `"$url`""
try {
  $health = Invoke-RestMethod -Uri "$url/health" -TimeoutSec 10
  Write-Host "Health: $($health.status)"
} catch {
  Write-Host "Aviso: /health no respondió todavía."
}

if ($UpdateSecrets) {
  $secrets = Join-Path (Split-Path $PSScriptRoot -Parent) ".streamlit\secrets.toml"
  if (-not (Test-Path $secrets)) { throw "No existe $secrets. Copia .streamlit\secrets.toml.example." }
  $content = [System.IO.File]::ReadAllText($secrets)
  $content = [regex]::Replace($content, '(?m)^API_BASE_URL\s*=.*$', "API_BASE_URL = `"$url`"")
  [System.IO.File]::WriteAllText($secrets, $content, [System.Text.UTF8Encoding]::new($false))
  Write-Host "Actualizado $secrets"
}
