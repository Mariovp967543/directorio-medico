#!/usr/bin/env python3
"""
Descarga las matrices usando los ENLACES TEMPORALES que envía el flujo de Power Automate.

El flujo (con la cuenta de quien lo creó) pide a SharePoint un enlace de descarga por archivo
("@content.downloadUrl", vence en ~1 hora) y dispara este workflow con:

    client_payload = { "archivos": [ { "n": "Sedes GAM.xlsx", "u": "https://...sharepoint.com/..." }, ... ] }

Seguridad:
  - El payload se lee del archivo del evento ($GITHUB_EVENT_PATH), nunca de variables de entorno,
    porque GitHub muestra las variables de entorno en los registros (que son públicos en un repo público).
  - Cada enlace se oculta con ::add-mask:: por si algún error lo mostrara.
  - Solo se aceptan enlaces https de *.sharepoint.com.
  - Los archivos se guardan en una carpeta temporal FUERA del repositorio.

Uso:
  python scripts/descargar_enlaces.py --destino "$RUNNER_TEMP/matrices"
"""
import argparse, json, os, re, sys, time
from pathlib import Path
from urllib.parse import urlparse

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generar_datos import es_matriz  # mismas reglas de exclusión que el generador


def cargar_archivos():
    ruta = os.environ.get("GITHUB_EVENT_PATH")
    if not ruta or not Path(ruta).exists():
        sys.exit("ERROR: no hay evento de GitHub (este script lo ejecuta el workflow).")
    evento = json.loads(Path(ruta).read_text(encoding="utf-8"))
    archivos = (evento.get("client_payload") or {}).get("archivos")
    if isinstance(archivos, str):              # por si Power Automate lo envía como texto
        archivos = json.loads(archivos)
    if not isinstance(archivos, list) or not archivos:
        sys.exit("ERROR: el flujo de Power Automate no envió la lista 'archivos'.")
    return archivos


def enlace_valido(u):
    try:
        p = urlparse(u)
    except Exception:
        return False
    return p.scheme == "https" and (p.hostname or "").endswith(".sharepoint.com")


def nombre_seguro(n):
    n = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", str(n)).strip() or "archivo.xlsx"
    return n[:150]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--destino", required=True)
    a = ap.parse_args()

    destino = Path(a.destino).resolve()
    repo = Path(__file__).resolve().parent.parent
    if destino == repo or repo in destino.parents:
        sys.exit("ERROR: el destino no puede estar dentro del repositorio.")
    destino.mkdir(parents=True, exist_ok=True)

    archivos = cargar_archivos()
    for x in archivos:                         # ocultar TODOS los enlaces antes de cualquier otra salida
        if isinstance(x, dict) and x.get("u"):
            print(f"::add-mask::{x['u']}")

    total, omitidos, usados = 0, [], set()
    for x in archivos:
        n, u = (x.get("n") or ""), (x.get("u") or "")
        if not es_matriz(n):
            continue
        if not enlace_valido(u):
            omitidos.append(f"{n} (enlace no válido)"); continue
        nombre = nombre_seguro(n)
        base, i = nombre, 2
        while nombre in usados:                # dos archivos con el mismo nombre en carpetas distintas
            nombre = f"{Path(base).stem} ({i}){Path(base).suffix}"; i += 1
        usados.add(nombre)
        for intento in range(4):
            try:
                r = requests.get(u, timeout=120, stream=True)
            except requests.RequestException:
                time.sleep(2 ** intento); continue
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(min(int(r.headers.get("Retry-After", 2 ** intento)), 30)); continue
            break
        else:
            omitidos.append(f"{n} (sin respuesta)"); continue
        if r.status_code != 200:
            omitidos.append(f"{n} (HTTP {r.status_code}; ¿enlace vencido?)"); continue
        with open(destino / nombre, "wb") as f:
            for trozo in r.iter_content(1 << 16):
                f.write(trozo)
        total += 1
        print(f"  ↓ {nombre}")

    if omitidos:
        print("Omitidos: " + "; ".join(omitidos))
    if total == 0:
        sys.exit("ERROR: no se descargó ninguna matriz. Revise el flujo de Power Automate.")
    print(f"{total} matrices descargadas.")


if __name__ == "__main__":
    main()
