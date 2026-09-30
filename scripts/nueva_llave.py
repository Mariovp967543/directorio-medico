#!/usr/bin/env python3
"""
Genera una llave AES-256 nueva (64 caracteres hexadecimales) con el generador
criptográfico del sistema y la guarda FUERA del repositorio:

    ~/.directorio-medico/llave.txt      (Windows: C:\\Users\\<usuario>\\.directorio-medico\\llave.txt)

Esa misma llave debe configurarse en el servidor de la intranet (variable de
entorno DIRECTORIO_KEY). Nunca la suba a GitHub, ni la pegue en correos o chats.

Uso:
    python scripts/nueva_llave.py            crea la llave si no existe
    python scripts/nueva_llave.py --rotar    reemplaza la llave actual (guarda copia .anterior)
"""
import secrets, sys
from pathlib import Path

ruta = Path.home() / ".directorio-medico" / "llave.txt"
rotar = "--rotar" in sys.argv

if ruta.exists() and not rotar:
    sys.exit(f"Ya existe una llave en {ruta}. Use --rotar para reemplazarla.")

ruta.parent.mkdir(parents=True, exist_ok=True)
if ruta.exists():
    ruta.replace(ruta.with_suffix(".anterior"))
llave = secrets.token_hex(32)          # 32 bytes = 256 bits
ruta.write_text(llave, encoding="utf-8")
try:
    ruta.chmod(0o600)                  # en Linux/macOS: solo el dueño puede leerla
except OSError:
    pass

print(f"Llave guardada en: {ruta}")
print("Cópiela al servidor de la intranet como variable de entorno DIRECTORIO_KEY.")
print("Después de rotarla, ejecute el generador con --forzar para volver a cifrar los datos.")
