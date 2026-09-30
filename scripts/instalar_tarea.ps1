<#
  Registra la tarea programada de Windows que ejecuta actualizar_directorio.ps1
  de lunes a sábado a las 06:45 y 12:45 (ajuste las horas si lo necesita).
  La tarea corre con SU usuario, así usa la sincronización de OneDrive y las
  credenciales de Git ya guardadas en el Administrador de credenciales de Windows.

  Uso (PowerShell normal, no hace falta administrador):
    powershell -ExecutionPolicy Bypass -File scripts\instalar_tarea.ps1 -Origen "C:\Users\...\Proyecto Directorio - Documentos"
#>
param(
    [Parameter(Mandatory = $true)][string]$Origen,
    [string[]]$Horas = @("06:45", "12:45")
)
$ErrorActionPreference = "Stop"
$script = Join-Path $PSScriptRoot "actualizar_directorio.ps1"
if (-not (Test-Path $Origen)) { throw "No existe el origen: $Origen" }

# Guardar el origen como variable de entorno del usuario (no es un secreto)
[Environment]::SetEnvironmentVariable("DIRECTORIO_ORIGEN", $Origen, "User")

$accion = New-ScheduledTaskAction -Execute "powershell.exe" `
          -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`" -Origen `"$Origen`""
$dias = @("Monday","Tuesday","Wednesday","Thursday","Friday","Saturday")
$disparadores = $Horas | ForEach-Object { New-ScheduledTaskTrigger -Weekly -DaysOfWeek $dias -At $_ }
$config = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable `
          -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName "Directorio Medico - Actualizar" -Action $accion `
    -Trigger $disparadores -Settings $config -Description "Consolida, cifra y publica el directorio médico" -Force | Out-Null

Write-Host "Tarea 'Directorio Medico - Actualizar' registrada ($($Horas -join ', ')). Registros en $env:USERPROFILE\.directorio-medico\logs"
Write-Host "Probarla ahora:  Start-ScheduledTask -TaskName 'Directorio Medico - Actualizar'"
