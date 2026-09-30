#!/usr/bin/env python3
"""
Descarga las matrices del sitio de SharePoint usando Microsoft Graph con un
"registro de aplicación" de Entra ID (sin usuario ni contraseña de nadie).

Pensado para GitHub Actions: los archivos se bajan a una carpeta TEMPORAL del
runner, se procesan y se descartan. Nunca se guardan en el repositorio.

Variables de entorno (en GitHub: Settings → Secrets and variables → Actions):
  AZURE_TENANT_ID      Id. del inquilino (directorio) de Microsoft 365
  AZURE_CLIENT_ID      Id. de la aplicación registrada
  AZURE_CLIENT_SECRET  Secreto de la aplicación
  SP_HOST              grupomontecristo1.sharepoint.com
  SP_SITE_PATH         /sites/ProyectoDirectorioCorporativoGrupoMontecristo
  SP_ARCHIVO           (opcional) p. ej. "La Matrix.xlsm": descarga SOLO ese libro consolidado.
                       Si se deja vacío se descargan las matrices de cada unidad (recomendado:
                       siempre están al día aunque nadie actualice La Matrix en Excel).

Permiso mínimo que TI debe dar a la aplicación: Sites.Selected (aplicación)
con acceso de solo LECTURA a ESE sitio únicamente.

Uso:
  python scripts/descargar_sharepoint.py --destino /tmp/matrices
"""
import argparse, os, sys, time
from pathlib import Path
from urllib.parse import quote

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generar_datos import es_matriz  # mismas reglas de exclusión que el generador

GRAPH = os.environ.get("GRAPH_URL", "https://graph.microsoft.com/v1.0")
LOGIN = os.environ.get("LOGIN_URL", "https://login.microsoftonline.com")


def env(nombre):
    v = os.environ.get(nombre, "").strip()
    if not v:
        sys.exit(f"ERROR: falta la variable {nombre}")
    return v


def token():
    r = requests.post(f"{LOGIN}/{env('AZURE_TENANT_ID')}/oauth2/v2.0/token", data={
        "grant_type": "client_credentials",
        "client_id": env("AZURE_CLIENT_ID"),
        "client_secret": env("AZURE_CLIENT_SECRET"),
        "scope": "https://graph.microsoft.com/.default",
    }, timeout=30)
    if r.status_code != 200:
        # Se muestra solo el código de error de Entra, nunca el secreto
        err = r.json().get("error_description", r.text)[:300] if r.headers.get("content-type", "").startswith("application/json") else r.text[:300]
        sys.exit(f"ERROR al autenticar con Entra ID (HTTP {r.status_code}): {err}")
    return r.json()["access_token"]


class Graph:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers["Authorization"] = f"Bearer {token()}"

    def get(self, url, stream=False):
        url = url if url.startswith("http") else GRAPH + url
        for intento in range(6):
            r = self.s.get(url, timeout=120, stream=stream)
            if r.status_code in (429, 500, 502, 503, 504):          # limitación o falla temporal
                espera = int(r.headers.get("Retry-After", 2 ** intento))
                time.sleep(min(espera, 60)); continue
            if r.status_code == 403:
                sys.exit("ERROR 403: la aplicación no tiene permiso sobre el sitio. "
                         "TI debe concederle 'read' en el sitio (Sites.Selected).")
            r.raise_for_status()
            return r
        r.raise_for_status()

    def paginas(self, url):
        while url:
            data = self.get(url).json()
            yield from data.get("value", [])
            url = data.get("@odata.nextLink")


def recorrer(g, drive_id, item_id, ruta=""):
    """Recorre carpetas recursivamente (equivale a SharePoint.Files de Power Query)."""
    base = f"/drives/{drive_id}/root" if item_id == "root" else f"/drives/{drive_id}/items/{item_id}"
    for it in g.paginas(f"{base}/children?$select=id,name,file,folder&$top=999"):
        if "folder" in it:
            yield from recorrer(g, drive_id, it["id"], f"{ruta}{it['name']}/")
        elif "file" in it:
            yield ruta, it


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--destino", required=True, help="Carpeta temporal (FUERA del repositorio)")
    a = ap.parse_args()

    destino = Path(a.destino).resolve()
    repo = Path(__file__).resolve().parent.parent
    if destino == repo or repo in destino.parents:
        sys.exit("ERROR: el destino no puede estar dentro del repositorio.")
    destino.mkdir(parents=True, exist_ok=True)

    g = Graph()
    host, ruta_sitio = env("SP_HOST"), env("SP_SITE_PATH")
    sitio = g.get(f"/sites/{host}:{quote(ruta_sitio)}").json()
    print(f"Sitio: {sitio.get('displayName', ruta_sitio)}")

    solo = os.environ.get("SP_ARCHIVO", "").strip()
    quiero = (lambda n: n == solo) if solo else es_matriz
    print("Modo: " + (f"solo el libro '{solo}'" if solo else "matrices de cada unidad"))

    total = 0
    for drive in g.paginas(f"/sites/{sitio['id']}/drives?$select=id,name"):
        for ruta, it in recorrer(g, drive["id"], "root"):
            if not quiero(it["name"]):
                continue
            archivo = destino / drive["name"] / ruta / it["name"]
            archivo.parent.mkdir(parents=True, exist_ok=True)
            with g.get(f"/drives/{drive['id']}/items/{it['id']}/content", stream=True) as r:
                with open(archivo, "wb") as f:
                    for trozo in r.iter_content(1 << 16):
                        f.write(trozo)
            total += 1
            print(f"  ↓ {drive['name']}/{ruta}{it['name']}")
    if total == 0:
        sys.exit(f"ERROR: no se encontró {'el archivo ' + repr(solo) if solo else 'ninguna matriz'} en el sitio.")
    print(f"{total} archivos descargados.")


if __name__ == "__main__":
    main()
