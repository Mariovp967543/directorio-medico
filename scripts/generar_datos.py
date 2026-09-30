#!/usr/bin/env python3
"""
Directorio Médico — genera data/directorio.enc (CIFRADO) para publicar en GitHub.

Flujo:
  matrices de SharePoint (carpeta sincronizada con OneDrive)  ─┐
  ó  La Matrix.xlsm                                           ─┴─► limpieza ─► JSON (solo en memoria)
      ─► gzip ─► AES-256-GCM (llave de 256 bits) ─► data/directorio.enc

El JSON en texto plano NUNCA se escribe en el repositorio. Solo se publican
campos aptos para un directorio: jamás cédula, fecha de nacimiento, teléfonos,
correos, dirección, pólizas ni datos de contratación.

La llave se lee, en este orden:
  1. variable de entorno DIRECTORIO_KEY (64 caracteres hexadecimales)
  2. archivo --llave (por defecto: ~/.directorio-medico/llave.txt), FUERA del repo

Uso:
  pip install pandas openpyxl cryptography
  python scripts/generar_datos.py --origen "C:/.../Proyecto Directorio - Documentos"
  python scripts/generar_datos.py --origen "C:/.../La Matrix.xlsm"

Formato de directorio.enc (binario, sin Base64):
  bytes 0-3   "DMC1"  identificador y versión
  byte  4     banderas (bit 0 = contenido comprimido con gzip)
  bytes 5-16  IV/nonce aleatorio de 12 bytes (nuevo en cada ejecución)
  bytes 17-   texto cifrado AES-256-GCM + etiqueta de autenticación de 16 bytes
  Los bytes 0-4 van como "datos adicionales autenticados" (AAD): si alguien
  altera el archivo, el descifrado falla en lugar de mostrar datos falsos.
"""
import argparse, gzip, json, os, re, secrets, sys, unicodedata
from datetime import date
from pathlib import Path

import pandas as pd

HOJA = "Datos por completar"
ESTADOS_PUBLICABLES = {"Laborando", "Nuevo ingreso"}
DIR_LOCAL = Path.home() / ".directorio-medico"
MAGIC, FLAG_GZIP = b"DMC1", 0x01

# Archivos de la biblioteca que no son matrices (igual que la consulta ArchivosExcluidos)
EXCLUIDOS = {
    "Cronograma de Trabajo.xlsx", "Información de entrada 1ER REPORTE.xlsx",
    "Información de entrada del Proyecto.xlsx", "LISTADO DE SKUS CHEQUEOS 2026.xlsx",
    "Preparaciones  Radiologia.xlsx", "Sesiones de revisión por unidad.xlsx",
    "Tabla de Parámetros - Directorio Corporativo.xlsx", "CMM Cartago.xlsx",
    "CMM Yoses.xlsx", "Pendientes.xlsx",
}

# ================================================================ limpieza
def limpiar(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, str):
        v = re.sub(r"[\s\u00a0]+", " ", v).strip()
        return v or None
    return v

def clave(v):
    s = str(v).lower()
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")

def canonico(v, oficiales):
    if v is None:
        return None
    k = clave(v)
    for o in oficiales:
        if clave(o) == k:
            return o
    return v

CORRECCIONES = {
    "Especialidad": {
        "Medicina Genral": "Medicina General",
        "Odontólogo General": "Odontología General",
        "Odontologia general": "Odontología General",
        "Pediatria general": "Pediatría General",
        "Pediatria": "Pediatría",
        "Imágenes medicas": "Imágenes Médicas",
        "Técnica en Imágenes Medicas": "Técnico en Imágenes Médicas",
        "Técnico de imágenes médicas": "Técnico en Imágenes Médicas",
        "Otorrinoralingología": "Otorrinolaringología",
        "Psicopedagodía": "Psicopedagogía",
        "Cirujía": "Cirugía",
        "Terapia del lenguaje": "Terapia de Lenguaje",
    },
    "Modalidad": {
        "Presencial y Virtual": "Presencial y Telemedicina",
        "Ambas": "Presencial y Telemedicina",
    },
    "Planes": {"MediSmart": "Medismart"},
    "FormaPago": {
        "tarjeta / efectivo / compra click": "Tarjeta / Efectivo / Compra Click",
        "Tarjeta/Efectivo/CompraClick": "Tarjeta / Efectivo / Compra Click",
        "Tarjeta/efectivo/Compra Click": "Tarjeta / Efectivo / Compra Click",
        "EFECTIVO/TARJETA/CRÉDITO/COMPRA CLICK": "Tarjeta / Efectivo / Crédito / Compra Click",
    },
    "Secretarias": {"Personal de admision y cajas": "Admisión y Cajas"},
}

def unificar_variantes(serie, campo):
    corr = {clave(k): v for k, v in CORRECCIONES.get(campo, {}).items()}
    s = serie.map(lambda v: None if v is None else corr.get(clave(v), v))
    conteo = s.dropna().value_counts()
    mejor = {}
    # Preferir la escritura que NO está toda en mayúsculas; luego la más usada.
    for valor, n in sorted(conteo.items(), key=lambda kv: (str(kv[0]).isupper(), -kv[1], kv[0])):
        mejor.setdefault(clave(valor), valor)
    return s.map(lambda v: None if v is None else mejor.get(clave(v), v))

def nombre_propio(t):
    """Solo corrige nombres escritos TODO EN MAYÚSCULAS o todo en minúsculas."""
    if not t or not (t.isupper() or t.islower()):
        return t
    menores = {"de", "del", "la", "las", "los", "y"}
    pal = t.lower().split(" ")
    return " ".join(p if (i and p in menores) else p[:1].upper() + p[1:] for i, p in enumerate(pal))

def norm_col(c):
    return re.sub(r"[\s\u00a0]+", " ", str(c)).strip()

def col(df, prefijo):
    for c in df.columns:
        if norm_col(c).lower().startswith(prefijo.lower()):
            return c
    raise KeyError(f"No se encontró la columna que empieza con: {prefijo!r}")

# ================================================================ lectura
def es_matriz(nombre):
    return (nombre.lower().endswith(".xlsx") and not nombre.startswith("~$")
            and "Matriz Cumplimiento" not in nombre and not nombre.startswith("Directorio medico")
            and nombre not in EXCLUIDOS)

def leer_carpeta(carpeta):
    """Equivalente a la consulta Unificacion, pero sobre la carpeta sincronizada."""
    from openpyxl import load_workbook
    tablas, omitidos = [], []
    for f in sorted(Path(carpeta).rglob("*.xlsx")):
        if not es_matriz(f.name):
            continue
        try:
            wb = load_workbook(f, read_only=True)
            tiene = HOJA in wb.sheetnames
            wb.close()
            if not tiene:
                omitidos.append(f.name); continue
            t = pd.read_excel(f, sheet_name=HOJA, dtype=object, engine="openpyxl")
        except Exception as e:  # archivo abierto/corrupto: se omite y se informa
            omitidos.append(f"{f.name} ({type(e).__name__})"); continue
        t.columns = [norm_col(c) for c in t.columns]
        t = t.loc[:, ~t.columns.duplicated()]
        t.insert(0, "Source.Name", f.name)
        tablas.append(t)
    if not tablas:
        sys.exit(f"ERROR: no se encontraron matrices con la hoja '{HOJA}' en {carpeta}")
    print(f"  {len(tablas)} matrices leídas" + (f"; omitidos: {', '.join(omitidos)}" if omitidos else ""))
    return pd.concat(tablas, ignore_index=True, sort=False)

def leer_origen(origen):
    p = Path(origen)
    if p.is_dir():
        libros = sorted(p.rglob("*.xlsm"))
        if libros and not any(es_matriz(f.name) for f in p.rglob("*.xlsx")):
            p = libros[0]                     # modo "La Matrix": un solo libro consolidado
        else:
            return leer_carpeta(p)
    if p.suffix.lower() in (".xlsm", ".xlsx"):
        print(f"  Libro consolidado: {p.name}")
        df = pd.read_excel(p, sheet_name=HOJA, dtype=object, engine="openpyxl")
        df.columns = [norm_col(c) for c in df.columns]
        return df
    sys.exit(f"ERROR: origen no válido: {origen}")

# ================================================================ transformación
SI_NO = ["Si", "No"]

def si_no(v):
    """Si/No/Sí/SI/no → 'Si' | 'No'; cualquier otro texto se conserva."""
    if v is None:
        return None
    k = clave(v).strip()
    return "Si" if k == "si" else "No" if k == "no" else v

def lista_seguros(*textos):
    """Une los tipos de seguro nacionales e internacionales en una lista sin duplicados."""
    vistos, out = set(), []
    for t in textos:
        if not t or clave(t) in ("no", "n/a", "na", "no aplica"):
            continue
        for s in re.split(r"\s*[,;|/]\s*|\s+y\s+", str(t)):
            s = s.strip(" .")
            if len(s) > 1 and clave(s) not in vistos:
                vistos.add(clave(s)); out.append(s)
    return out

def construir(df):
    """
    Modelo de la tabla del directorio (una fila por médico + sede, como el directorio HM):
      filas      → lo que muestra la tabla principal
      servicios  → { id_fila: [[servicio, sku, precio_sin_iva, idx_preparacion, cpt], ...] }
    """
    df = df.map(limpiar)
    C = {k: col(df, p) for k, p in {
        "archivo": "Source.Name", "cedula": "Cédula", "nombre": "Nombre completo",
        "ap1": "Apellido 1", "ap2": "Apellido 2", "codigo": "Código Profesional",
        "esp": "Especialidad", "sub": "Subespecialidad", "enfoque": "Enfoque",
        "horario": "Atención por agenda", "cortesias": "Gestión de cortesías",
        "web": "Perfil de página WEB", "medismart": "Perfil de página Medismart",
        "sede": "Sede,", "piso": "Piso", "consultorio": "# de Consultorio",
        "herramienta": "Herramienta de agendamiento", "modalidad": "Modalidad de cita",
        "cobro": "Cobro Anticipado", "callcenter": "Agendamiento por call center",
        "secretarias": "Secretarias", "servicio": "Catálogo de servicios", "sku": "SKU",
        "prep": "Preparaciones", "precio": "Precio final", "pago": "Forma de pago",
        "honorarios": "Honorarios Médicos", "espera": "Tiempo de espera", "mixta": "Medicina mixta",
        "seg_nac": "Tipo de Seguro Nacional", "seg_int": "Tipo de Seguro internacional",
        "convenios": "Convenios corporativos", "planes": "Planes de beneficios",
        "cpt": "Lista de procedimientos por CPT", "ingreso": "Tipo de contratación",
        "estado": "Estado Actual",
    }.items()}

    df[C["cedula"]] = df[C["cedula"]].map(lambda v: None if v is None else re.sub(r"[\s\-.]", "", str(v).removesuffix(".0")))
    df = df[df[C["cedula"]].notna()].copy()
    df[C["estado"]] = df[C["estado"]].map(lambda v: canonico(v, ["Laborando", "Salida", "Nuevo ingreso"]))
    df[C["herramienta"]] = df[C["herramienta"]].map(lambda v: canonico(v, ["Blue", "Huli", "Siku", "Otro"]))
    for k in ("callcenter", "cobro", "cortesias", "honorarios", "mixta"):
        df[C[k]] = df[C[k]].map(si_no)
    df[C["ingreso"]] = df[C["ingreso"]].map(lambda v: canonico(v, [
        "Servicios profesionales", "Alquiler", "Planilla", "Proveedor externo", "Honorarios", "Participaciones", "Indefinido"]))
    for campo, k in [("Especialidad", "esp"), ("Subespecialidad", "sub"), ("Enfoque", "enfoque"),
                     ("Sede", "sede"), ("Modalidad", "modalidad"), ("Planes", "planes"),
                     ("FormaPago", "pago"), ("Secretarias", "secretarias")]:
        df[C[k]] = unificar_variantes(df[C[k]], campo)
    df[C["modalidad"]] = df[C["modalidad"]].map(lambda v: canonico(v, ["Presencial", "Telemedicina", "Presencial y Telemedicina"]))
    df[C["precio"]] = pd.to_numeric(df[C["precio"]], errors="coerce")

    # Desempate: Laborando > Nuevo ingreso > resto; luego la fila más completa; luego el archivo.
    prio = {"Laborando": 0, "Nuevo ingreso": 1}
    df["__prio"] = df[C["estado"]].map(lambda e: prio.get(e, 2))
    df["__vacios"] = df.isna().sum(axis=1)
    df = df.sort_values(["__prio", "__vacios", C["archivo"]], kind="stable")
    df = df.astype(object).where(df.notna(), None)

    # Nombre "oficial" de cada persona = el de su fila prioritaria (evita variantes entre matrices)
    nombres = {}
    for ced, g in df.groupby(C["cedula"], sort=False):
        p = g.iloc[0]
        nombres[ced] = nombre_propio(" ".join(str(x) for x in (p[C["nombre"]], p[C["ap1"]], p[C["ap2"]]) if x))

    txt = lambda v: None if v is None else str(v)
    preparaciones, idx_prep, filas, servicios, personas = [], {}, [], {}, set()
    for (ced, sede), g in df.groupby([C["cedula"], C["sede"]], sort=False, dropna=False):
        if not any(e in ESTADOS_PUBLICABLES for e in g[C["estado"]]):
            continue                                   # salió de esta sede/unidad
        p = g.iloc[0]
        if isinstance(sede, float) and pd.isna(sede):
            sede = None
        web = next((u for u in g[C["web"]].dropna().tolist() + g[C["medismart"]].dropna().tolist()
                    if str(u).startswith("http")), None)
        planes = txt(p[C["planes"]])
        fila = {k: v for k, v in {
            "nombre": nombres[ced],
            "codigo": txt(p[C["codigo"]]),
            "especialidad": p[C["esp"]],
            "subespecialidad": p[C["sub"]],
            "enfoque": p[C["enfoque"]],
            "sede": sede,
            "unidad": str(p[C["archivo"]]).removesuffix(".xlsx"),
            "piso": txt(p[C["piso"]]),
            "consultorio": txt(p[C["consultorio"]]),
            "horario": txt(p[C["horario"]]),
            "modalidad": p[C["modalidad"]],
            "agenda": p[C["herramienta"]],
            "callcenter": p[C["callcenter"]],
            "cobro": p[C["cobro"]],
            "cortesias": p[C["cortesias"]],
            "secretarias": p[C["secretarias"]],
            "espera": txt(p[C["espera"]]),
            "pago": p[C["pago"]],
            "honorarios": p[C["honorarios"]],
            "mixta": p[C["mixta"]],
            "ingreso": p[C["ingreso"]],
            "medismart": "Si" if planes and "medismart" in clave(planes) else ("No" if planes else None),
            "planes": planes,
            "seguros": lista_seguros(p[C["seg_nac"]], p[C["seg_int"]]),
            "convenios": txt(p[C["convenios"]]),
            "web": web,
            "estado": p[C["estado"]] if p[C["estado"]] in ESTADOS_PUBLICABLES else "Laborando",
        }.items() if v not in (None, "", [])}

        lista, vistos = [], set()
        for _, r in g.iterrows():
            s = r[C["servicio"]] and str(r[C["servicio"]])
            if not s or s in vistos or s.lower().startswith("servicio vinculado"):
                continue
            vistos.add(s)
            prep = r[C["prep"]] and str(r[C["prep"]])
            ip = None
            if prep and not prep.lower().startswith("ver adjunto"):
                ip = idx_prep.setdefault(prep, len(preparaciones))
                if ip == len(preparaciones):
                    preparaciones.append(prep)
            precio = r[C["precio"]]
            sku = txt(r[C["sku"]])
            if sku and sku.lower().startswith("servicio vinculado"):
                sku = None
            lista.append([s, sku, None if precio is None or precio <= 0 else round(float(precio)), ip, txt(r[C["cpt"]])])
        fila["_serv"] = lista
        fila["_ced"] = ced
        filas.append(fila)
        personas.add(ced)

    filas.sort(key=lambda x: (clave(x["nombre"]), clave(x.get("sede", ""))))
    pids = {}
    for i, f in enumerate(filas, 1):
        f["id"] = i
        f["pid"] = pids.setdefault(f.pop("_ced"), len(pids) + 1)   # agrupa las sedes de una misma persona
        lista = f.pop("_serv")
        f["nServ"] = len(lista)
        if lista:
            servicios[str(i)] = lista
    return {"medicos": len(personas),
            "filas": filas, "servicios": servicios, "preparaciones": preparaciones}

# ================================================================ cifrado
def cargar_llave(ruta):
    hexa = os.environ.get("DIRECTORIO_KEY")
    if not hexa:
        ruta = Path(ruta)
        if not ruta.exists():
            sys.exit(f"ERROR: no hay llave. Genere una con:  python scripts/nueva_llave.py\n       (se esperaba en {ruta})")
        hexa = ruta.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[0-9a-fA-F]{64}", hexa):
        sys.exit("ERROR: la llave debe tener 64 caracteres hexadecimales (256 bits).")
    return bytes.fromhex(hexa)

def cifrar(texto: bytes, llave: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    cabecera = MAGIC + bytes([FLAG_GZIP])
    iv = secrets.token_bytes(12)                       # nonce único por ejecución
    comprimido = gzip.compress(texto, compresslevel=9, mtime=0)
    return cabecera + iv + AESGCM(llave).encrypt(iv, comprimido, cabecera)

def descifrar(blob: bytes, llave: bytes) -> bytes:
    """Para pruebas: el navegador hace lo mismo con Web Crypto."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    cab, iv, ct = blob[:5], blob[5:17], blob[17:]
    if cab[:4] != MAGIC:
        raise ValueError("Archivo no reconocido")
    plano = AESGCM(llave).decrypt(iv, ct, cab)
    return gzip.decompress(plano) if cab[4] & FLAG_GZIP else plano

# ================================================================ main
def main():
    ap = argparse.ArgumentParser(description="Genera el directorio médico cifrado.")
    ap.add_argument("--origen", required=True, help="Carpeta sincronizada con las matrices, o La Matrix.xlsm")
    ap.add_argument("--salida", default=str(Path(__file__).resolve().parent.parent / "data" / "directorio.enc"))
    ap.add_argument("--llave", default=str(DIR_LOCAL / "llave.txt"))
    ap.add_argument("--forzar", action="store_true", help="Cifra y escribe aunque no haya cambios")
    ap.add_argument("--json-prueba", help="(Solo diagnóstico) escribe el JSON en claro FUERA del repositorio")
    a = ap.parse_args()

    llave = cargar_llave(a.llave)
    print(f"Leyendo {a.origen} …")
    datos = construir(leer_origen(a.origen))

    # ¿Cambió algo? Se descifra el .enc publicado y se compara el contenido (sin la fecha).
    # Así no hace falta guardar estado en ningún lado y funciona igual en la PC o en GitHub Actions.
    salida = Path(a.salida)
    if not a.forzar and salida.exists():
        try:
            anterior = json.loads(descifrar(salida.read_bytes(), llave))
            if {k: anterior.get(k) for k in datos} == datos:
                print(f"SIN_CAMBIOS: {len(datos['filas'])} filas, nada que publicar.")
                return
        except Exception:
            print("  El archivo publicado no se pudo descifrar con la llave actual (¿llave rotada?); se regenera.")

    datos = {"generado": date.today().isoformat(), **datos}
    final = json.dumps(datos, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")

    if a.json_prueba:
        repo = Path(__file__).resolve().parent.parent
        destino = Path(a.json_prueba).resolve()
        if repo in destino.parents:
            sys.exit("ERROR: --json-prueba no puede quedar dentro del repositorio (se publicaría en claro).")
        destino.write_bytes(final)

    blob = cifrar(final, llave)
    assert descifrar(blob, llave) == final             # verificación de ida y vuelta
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_bytes(blob)
    print(f"ACTUALIZADO: {datos['medicos']} médicos en {len(datos['filas'])} filas → {salida} ({len(blob)/1024:.0f} KB cifrados)")

if __name__ == "__main__":
    main()
