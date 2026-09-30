<#
  Directorio Médico — actualización automática
  1. Lee las matrices desde la biblioteca de SharePoint sincronizada con OneDrive
  2. Limpia, comprime y CIFRA (AES-256-GCM) -> data\directorio.enc
  3. Si hubo cambios, hace commit y push a GitHub con las credenciales de Git del usuario

  Uso manual:
    powershell -ExecutionPolicy Bypass -File scripts\actualizar_directorio.ps1 -Origen "C:\Users\...\Proyecto Directorio - Documentos"
  El origen también puede venir de la variable de entorno DIRECTORIO_ORIGEN.
#>
param(
    [string]$Origen = $env:DIRECTORIO_ORIGEN,
    [string]$Python = "python"
)
$ErrorActionPreference = "Stop"
$Repo   = Split-Path -Parent $PSScriptRoot
$Casa   = if ($env:USERPROFILE) { $env:USERPROFILE } else { $HOME }
$LogDir = Join-Path $Casa (Join-Path ".directorio-medico" "logs")
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir ("actualizacion_{0:yyyy-MM-dd}.log" -f (Get-Date))
function Log($m) { $l = "{0:HH:mm:ss}  {1}" -f (Get-Date), $m; Write-Host $l; Add-Content -Path $Log -Value $l -Encoding UTF8 }

# Ejecuta un programa externo (git, python) sin que sus mensajes por stderr
# se traten como errores de PowerShell; devuelve el código de salida real.
function Invoke-Externo([string]$Exe, [string[]]$Argumentos, [string]$Prefijo = "") {
    $ErrorActionPreference = "Continue"
    & $Exe @Argumentos 2>&1 | ForEach-Object { Log ("$Prefijo" + "$_") }
    return $LASTEXITCODE
}

try {
    if (-not $Origen) { throw "Indique -Origen o defina la variable de entorno DIRECTORIO_ORIGEN." }
    if (-not (Test-Path $Origen)) { throw "No existe el origen: $Origen" }
    Set-Location $Repo
    Log "=== Inicio · origen: $Origen"

    # 0. Traer cambios de código que otros hayan subido
    if ((Invoke-Externo git @("pull", "--rebase", "--quiet") "git: ") -ne 0) { throw "git pull falló." }

    # 1-2. Generar y cifrar (el JSON en claro nunca toca el disco)
    $cod = Invoke-Externo $Python @("-W", "ignore", (Join-Path "scripts" "generar_datos.py"), "--origen", $Origen)
    if ($cod -ne 0) { throw "El generador terminó con error (código $cod)." }

    # Salvaguarda: jamás publicar datos en claro (archivos no ignorados o ya versionados)
    $prohibidos = & git ls-files --others --cached --exclude-standard -- "data/*.json" "data/*.js" "*.xlsx" "*.xlsm" "*.csv"
    if ($prohibidos) { throw "Hay archivos en claro que se subirían al repo: $prohibidos" }

    # 3. Publicar solo si cambió
    [void](Invoke-Externo git @("add", "--", "data/directorio.enc"))
    if ((Invoke-Externo git @("diff", "--cached", "--quiet", "--", "data/directorio.enc")) -eq 0) {
        Log "Sin cambios en los datos. Nada que publicar."; exit 0
    }
    $msg = "Actualiza directorio ({0:yyyy-MM-dd HH:mm})" -f (Get-Date)
    if ((Invoke-Externo git @("commit", "--quiet", "-m", $msg, "--", "data/directorio.enc") "git: ") -ne 0) { throw "git commit falló." }
    if ((Invoke-Externo git @("push", "--quiet") "git: ") -ne 0) { throw "git push falló (¿credenciales vencidas o sin red?)." }
    Log "Publicado en GitHub."
}
catch {
    Log "ERROR: $($_.Exception.Message)"
    exit 1
}
