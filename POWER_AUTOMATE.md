# Flujo de Power Automate — actualización diaria sin PC y sin administradores

El flujo corre en la nube de Microsoft con **su** cuenta de Microsoft 365. Todos los días:

1. Lista las matrices de la biblioteca de SharePoint.
2. Pide a SharePoint un **enlace de descarga temporal** por archivo (vence en ~1 hora).
3. Dispara GitHub Actions con esos enlaces. GitHub descarga, limpia, **cifra** y publica.

Solo usa conectores **estándar** (incluidos en la licencia de Microsoft 365): *Periodicidad*,
*SharePoint* y *GitHub*. No requiere Power Automate Premium ni permisos de administrador.

> **Antes de empezar:** el repositorio `directorio-medico` ya debe existir en GitHub con el
> secreto `DIRECTORIO_KEY` cargado (ver README, pasos 2 a 4).

---

## Crear el flujo (15-20 min)

Entre a **make.powerautomate.com → Crear → Flujo de nube programado**.

- Nombre: `Directorio Médico - Publicar`
- Inicio: hoy · Repetir cada: **1 Día** → **Crear**

### Paso 1 · Periodicidad (el disparador)

Abra la tarjeta *Periodicidad* → **Mostrar opciones avanzadas**:

| Campo | Valor |
|---|---|
| Intervalo / Frecuencia | `1` / `Día` |
| Zona horaria | `(UTC-06:00) Centroamérica` |
| A estas horas | `6`, `12`, `17` |
| En estos minutos | `30` |

### Paso 2 · Inicializar variable

**+ Nueva acción → "Inicializar variable"**

| Campo | Valor |
|---|---|
| Nombre | `archivos` |
| Tipo | `Matriz` |
| Valor | `[]` |

### Paso 3 · Obtener archivos (solo propiedades) — SharePoint

**+ Nueva acción → SharePoint → "Obtener archivos (solo propiedades)"**

| Campo | Valor |
|---|---|
| Dirección del sitio | `https://grupomontecristo1.sharepoint.com/sites/ProyectoDirectorioCorporativoGrupoMontecristo` |
| Nombre de la biblioteca | `Documentos` (la biblioteca donde están las matrices) |
| Limitar entradas a la carpeta | *(recomendado)* la carpeta donde están las matrices |
| Incluir elementos anidados | `Sí` |

En los **…** de la acción → **Configuración** → *Paginación*: **Activada**, umbral `5000`.

### Paso 4 · Filtrar matriz

**+ Nueva acción → "Filtrar matriz"**

- **De:** contenido dinámico → *value* (de *Obtener archivos*).
- Clic en **Editar en modo avanzado** y pegue:
  ```
  @and(endsWith(toLower(item()?['{FilenameWithExtension}']), '.xlsx'), not(startsWith(item()?['{FilenameWithExtension}'], '~$')), equals(item()?['{IsFolder}'], false))
  ```

(Los reportes y archivos que no son matrices se descartan después en GitHub, con las mismas
reglas de La Matrix.)

### Paso 5 · Aplicar a cada uno

**+ Nueva acción → "Aplicar a cada uno"** → seleccione *Cuerpo* de **Filtrar matriz**.

Renombre esta acción exactamente como **`Cada archivo`** (en los **…** → *Cambiar nombre*),
porque las expresiones siguientes usan ese nombre.

Dentro del bucle agregue dos acciones:

**5a · SharePoint → "Enviar una solicitud HTTP a SharePoint"** — renómbrela **`Obtener enlace`**

| Campo | Valor |
|---|---|
| Dirección del sitio | la misma del paso 3 |
| Método | `GET` |
| Identificador URI | *(expresión, pestaña **fx**)* ver abajo |
| Encabezados | `Accept` = `application/json` |

Expresión del **Identificador URI**:
```
concat('_api/v2.0/drive/root:/', replace(uriComponent(substring(items('Cada_archivo')?['{FullPath}'], add(indexOf(items('Cada_archivo')?['{FullPath}'], '/'), 1))), '%2F', '/'))
```
*(Toma la ruta del archivo dentro de la biblioteca y le pide a SharePoint sus datos, que incluyen
`@content.downloadUrl`: el enlace de descarga temporal.)*

**5b · "Anexar a variable de matriz"**

| Campo | Valor |
|---|---|
| Nombre | `archivos` |
| Valor | *(expresión **fx**)* ver abajo |

```
addProperty(addProperty(json('{}'), 'n', items('Cada_archivo')?['{FilenameWithExtension}']), 'u', body('Obtener_enlace')?['@content.downloadUrl'])
```
*(Arma un objeto `{ "n": nombre del archivo, "u": enlace temporal }` y lo agrega a la lista.)*

### Paso 6 · GitHub → "Create a repository dispatch event"

**Fuera del bucle** (debajo de *Cada archivo*): **+ Nueva acción → GitHub → "Create a repository
dispatch event"**. La primera vez pedirá **Iniciar sesión** con su cuenta de GitHub (Mariovp967543).

| Campo | Valor |
|---|---|
| Repository owner | `Mariovp967543` |
| Repository name | `directorio-medico` |
| event_type | `actualizar-directorio` |
| client_payload | *(expresión **fx**)* `addProperty(json('{}'), 'archivos', variables('archivos'))` |

*(Si el campo `client_payload` aparece dividido en propiedades, agregue una propiedad llamada
`archivos` con el valor `variables('archivos')`.)*

### Paso 7 · Guardar y probar

1. **Guardar**. Si aparece un error sobre **"directiva de prevención de pérdida de datos (DLP)"**,
   su empresa no permite combinar SharePoint con GitHub: **deténgase aquí** y use la opción de la PC
   (README, Plan B). No intente saltarse esa política.
2. **Probar → Manualmente → Probar → Ejecutar flujo**.
3. En Power Automate, todas las acciones deben quedar en verde.
4. En GitHub → **Actions** debe aparecer **"Actualizar directorio"** disparado por
   *repository_dispatch*. En 2-3 minutos: verde, con un commit de `data/directorio.enc`.

Desde ese momento corre solo a las 6:30, 12:30 y 17:30, todos los días.

---

## Seguridad del flujo

- Los enlaces temporales **no se muestran** en los registros públicos de GitHub: el workflow los lee
  del evento dentro del script y los oculta (`::add-mask::`). Solo se imprime el nombre de cada archivo.
- Cada enlace sirve para **un** archivo y **vence en ~1 hora**. GitHub los usa en el primer minuto.
- GitHub solo acepta enlaces `https://…sharepoint.com`.
- Las matrices se descargan en una carpeta temporal del servidor de GitHub, se cifran y se borran.
  **Nunca** se guardan en el repositorio.
- El flujo ve solo lo que ve su cuenta. Si cambia la contraseña, Power Automate le pedirá
  **reconectar** SharePoint (le llega un correo).

## Solución de problemas

| Dónde | Síntoma | Qué hacer |
|---|---|---|
| Power Automate, al guardar | Error de **DLP** | Su empresa bloquea SharePoint + GitHub en el mismo flujo. Use el Plan B (PC). |
| Paso 3 | No trae archivos | Revise el nombre de la biblioteca y la carpeta. |
| Paso 5a | `404` | El archivo no está en la biblioteca **predeterminada** del sitio. Cambie el URI a `_api/v2.0/drives/<id-de-la-biblioteca>/root:/…` (el id se obtiene con un GET a `_api/v2.0/drives`). |
| Paso 5b | Valor `u` vacío | Revise que la acción 5a se llame exactamente `Obtener enlace`. |
| Paso 6 | `404 Not Found` | Usuario o nombre del repositorio mal escritos, o la conexión de GitHub no tiene acceso a ese repo. |
| GitHub Actions | `no envió la lista 'archivos'` | Revise el `client_payload` del paso 6. |
| GitHub Actions | `HTTP 401/403 … ¿enlace vencido?` | Pasó más de una hora entre el flujo y GitHub; vuelva a ejecutar el flujo. |
| GitHub Actions | `la llave no corresponde` en la página | El secreto `DIRECTORIO_KEY` y la llave del iframe son distintos. |

**Para revisar un caso raro:** en el historial del flujo abra la ejecución → acción *Obtener enlace*
→ *Mostrar salidas*. Debe verse una propiedad `@content.downloadUrl`.
