# Directorio Médico — cifrado y actualizado todos los días

Es el mismo esquema que ya funciona con `directorio-hm` (GitHub Pages + `<iframe>` en la
intranet), con tres cambios:

1. **La fuente es SharePoint** (La Matrix / matrices de cada unidad), no un archivo editado a mano.
2. **Se actualiza solo todos los días** con GitHub Actions, sin depender de ninguna PC.
3. **Los datos están cifrados** (AES-256-GCM). La llave **no está en GitHub**: la pone el iframe de la intranet.

```
SharePoint  (matrices que llena cada unidad  →  La Matrix)
    │  06:45 · 12:45 · 17:45 todos los días
    ▼
GitHub Actions  ── descarga → limpia → comprime → CIFRA con el secreto DIRECTORIO_KEY
    │  commit de data/directorio.enc (solo si algo cambió)
    ▼
GitHub Pages   ── index.html + assets/ + data/directorio.enc   (los datos van cifrados)
    ▲
    │  <iframe src="https://USUARIO.github.io/REPO/#k=LLAVE">
Intranet (CMS) ── el navegador descifra con la llave del iframe y muestra el directorio
```

### ¿Por qué la llave va en el iframe?

El editor del CMS de la intranet borra cualquier `<script>`, pero sí permite `<iframe>`.
Por eso la llave viaja en la dirección del iframe, **después del `#`**:

- Lo que va después de `#` **nunca se envía** a GitHub ni a ningún servidor. Solo lo lee el navegador.
- La página lo usa para descifrar y lo **borra de la barra de direcciones** en cuanto carga.
- Solo quien puede editar o ver el código de esa página de la intranet ve la llave.

---

## Archivos

| Ruta | Qué es |
|---|---|
| `index.html` | La página que carga el iframe. |
| `assets/directorio.js` / `.css` | El directorio (tarjetas, buscador, filtros, ficha con procedimientos, modo oscuro). Descifra en el navegador. |
| `data/directorio.enc` | Datos cifrados. Lo genera GitHub Actions; no se edita a mano. |
| `.github/workflows/actualizar-directorio.yml` | La automatización diaria. |
| `scripts/descargar_sharepoint.py` | Baja las matrices (o solo La Matrix) desde SharePoint con Microsoft Graph. |
| `scripts/generar_datos.py` | Limpia, arma la tabla y cifra. |
| `scripts/nueva_llave.py` | Crea o rota la llave. |
| `scripts/actualizar_directorio.ps1`, `instalar_tarea.ps1` | Plan B: publicar desde una PC con Windows. |

---

## Puesta en marcha

### 1. TI: permiso de solo lectura a SharePoint (una vez, ~15 min)

Es lo único que necesita a otra persona. Un administrador de Microsoft 365:

1. **Entra admin center → Registros de aplicaciones → Nuevo registro**: `Directorio Medico - GitHub`,
   cuentas de este directorio únicamente, sin URI de redirección.
2. **Permisos de API → Microsoft Graph → Permisos de aplicación → `Sites.Selected`** →
   *Conceder consentimiento de administrador*. (Por sí solo no da acceso a nada.)
3. **Certificados y secretos → Nuevo secreto** (24 meses) → copiar el *Valor*.
4. Dar **lectura** solo al sitio del proyecto:
   ```powershell
   Grant-PnPAzureADAppSitePermission -AppId "<Id. de aplicación>" -DisplayName "Directorio Medico - GitHub" `
     -Site "https://grupomontecristo1.sharepoint.com/sites/ProyectoDirectorioCorporativoGrupoMontecristo" -Permissions Read
   ```
   (o `POST https://graph.microsoft.com/v1.0/sites/{id-del-sitio}/permissions` con
   `{"roles":["read"],"grantedToIdentities":[{"application":{"id":"<Id. de aplicación>","displayName":"Directorio Medico - GitHub"}}]}`)
5. Entregar por canal seguro: **Id. de directorio (tenant)**, **Id. de aplicación** y **valor del secreto**.

### 2. Repositorio nuevo

Use un repositorio **nuevo** (por ejemplo `directorio-medico`), **no** `directorio-hm`: el historial de
`directorio-hm` guarda todas las versiones anteriores de `directorio-data.js` **sin cifrar** y
cualquiera puede verlas. Ver el paso 7.

1. En GitHub: **New repository** → `directorio-medico` → **Public** → sin README.
2. Suba el contenido de esta carpeta (todo, incluida la carpeta oculta `.github`):
   ```powershell
   cd C:\Proyectos\directorio-medico
   git init
   git add .
   git commit -m "Directorio médico cifrado"
   git branch -M main
   git remote add origin https://github.com/Mariovp967543/directorio-medico.git
   git push -u origin main
   ```
   Alternativa sin comandos: *Add file → Upload files* y arrastrar todo. Si la carpeta `.github`
   no se sube así, cree el archivo con *Add file → Create new file*, nombre
   `.github/workflows/actualizar-directorio.yml`, y pegue su contenido.
3. **Settings → Pages → Build and deployment → Source: GitHub Actions**.

### 3. La llave

```powershell
pip install cryptography
python scripts\nueva_llave.py
```
Queda en `C:\Users\<usuario>\.directorio-medico\llave.txt` (64 caracteres). Guárdela también en un
gestor de contraseñas. **Nunca** la suba a GitHub ni la pegue en archivos del repositorio.

### 4. Secretos y variables en GitHub

**Settings → Secrets and variables → Actions**

| Pestaña | Nombre | Valor |
|---|---|---|
| Secrets | `DIRECTORIO_KEY` | contenido de `llave.txt` |
| Secrets | `AZURE_TENANT_ID` | Id. de directorio (de TI) |
| Secrets | `AZURE_CLIENT_ID` | Id. de aplicación (de TI) |
| Secrets | `AZURE_CLIENT_SECRET` | valor del secreto (de TI) |
| Variables | `SP_HOST` | `grupomontecristo1.sharepoint.com` |
| Variables | `SP_SITE_PATH` | `/sites/ProyectoDirectorioCorporativoGrupoMontecristo` |
| Variables | `SP_ARCHIVO` | *(opcional)* `La Matrix.xlsm` |

**Sobre `SP_ARCHIVO`:**
- **Vacío (recomendado):** lee directo las matrices de cada unidad, igual que lo hace La Matrix.
  Siempre está al día aunque nadie abra La Matrix.
- **`La Matrix.xlsm`:** lee solo ese libro. Solo trae datos nuevos si alguien lo abrió y le dio
  *Actualizar todo* en Excel.

### 5. Primera corrida

**Actions → Actualizar directorio → Run workflow**. En 2-3 minutos debe quedar en verde:
- hay un commit nuevo con `data/directorio.enc`;
- `https://mariovp967543.github.io/directorio-medico/` abre y **pide la llave** (así debe ser).
  Pegue la llave para comprobar que se ve el directorio.

### 6. El iframe en la intranet

En el editor del CMS, modo **Fuente HTML**, reemplace el iframe viejo por este (ponga su llave
después de `#k=`):

```html
<iframe src="https://mariovp967543.github.io/directorio-medico/#k=PEGUE_AQUI_LA_LLAVE_DE_64_CARACTERES" width="100%" height="900" frameborder="0" style="border:none;width:100%;min-height:900px;"></iframe>
```

Listo. A partir de aquí se actualiza solo. No hay que volver a tocar el CMS ni la versión
(`?v=`) porque la página siempre pide los datos frescos.

### 7. Cerrar lo anterior

Cuando confirme que el iframe nuevo funciona:

1. **Borre o haga privado el repositorio `directorio-hm`** (*Settings → Danger Zone*). Hoy
   `directorio-data.js` está público **sin cifrar**, con todo su historial.
2. El **admin local** (`directorio-admin`) y el **Ingreso Masivo** ya no se usan: los cambios se hacen en
   las matrices de SharePoint. Si se editara algo desde el admin, la corrida siguiente lo
   reemplazaría con lo que diga SharePoint.
3. Revoque el token de GitHub que usaba el admin (*Settings → Developer settings → Personal access tokens*).

---

## Mantenimiento

| Qué | Cuándo | Cómo |
|---|---|---|
| Secreto de TI | Vence a los 24 meses | TI crea uno nuevo; se reemplaza `AZURE_CLIENT_SECRET`. |
| Aviso de GitHub | Si pasan 60 días sin ningún cambio | GitHub pausa los horarios y avisa por correo; se reactiva con un clic en *Actions*. |
| Corrida fallida | GitHub envía correo | Ver el detalle en *Actions*. |
| Cambiar la llave | Si se filtra, o cada 6-12 meses | Ver abajo. |

**Cambiar la llave:**
1. `python scripts\nueva_llave.py --rotar`
2. Reemplace el secreto `DIRECTORIO_KEY` en GitHub y ejecute *Run workflow* (detecta la llave nueva
   y vuelve a cifrar).
3. Cambie la llave en el iframe del CMS. Hasta que lo haga, el directorio mostrará "la llave no corresponde".

## Qué muestra el directorio

Una tarjeta por profesional (1 542 con los datos actuales) con buscador sin tildes, filtros por
especialidad, sede, unidad y modalidad, y atajos para *Con servicios y precios*, *Agenda por call center*
y *Acepta Medismart*. Al abrir una tarjeta se ve la ficha completa: código profesional, enfoque,
método de ingreso, Medismart, **cada sede** con horario, piso/consultorio, agenda, tiempo de espera,
forma de pago, secretaría y condiciones (cobro anticipado, cortesías, honorarios, medicina mixta),
seguros aceptados, convenios y la lista de **servicios y procedimientos** con SKU, precio sin IVA,
preparación y CPT. Los filtros quedan en la dirección, y tiene modo claro/oscuro.

Solo se incluyen personas con estado *Laborando* o *Nuevo ingreso*. **Nunca** se publican cédula,
fecha de nacimiento, teléfonos, correos personales, dirección, pólizas, sociedad ni comisiones.

## Seguridad: qué protege y qué no

- **Protege:** el repositorio, la URL de GitHub Pages y cualquier copia de `directorio.enc` son
  ilegibles sin la llave. Si alguien altera el archivo, el descifrado falla en lugar de mostrar datos falsos.
- **No es Base64:** es AES-256-GCM con llave aleatoria de 256 bits y un valor nuevo en cada publicación.
- **No protege de alguien con acceso a la intranet:** esa persona puede ver la llave en el código del
  iframe. Es el límite de cualquier cifrado que se descifra en el navegador. Si la dirección del iframe
  (con la llave) se comparte fuera, cambie la llave.

## Solución de problemas

| Síntoma | Causa probable |
|---|---|
| La página pide la llave dentro de la intranet | El iframe no tiene `#k=...` o se cortó al pegar. |
| "La llave no corresponde" | La llave del iframe es distinta al secreto `DIRECTORIO_KEY`. |
| Actions: `ERROR al autenticar con Entra ID` | El secreto de TI venció o se copió mal. |
| Actions: `ERROR 403` | TI no dio lectura del sitio a la aplicación (paso 1.4). |
| Actions: `no se encontró el archivo 'La Matrix.xlsm'` | El nombre en `SP_ARCHIVO` no coincide exactamente. |
| Un dato no cambia | Revise que el cambio esté en la matriz de SharePoint y que la última corrida esté en verde. |

## Plan B: publicar desde una PC

Si TI no puede crear la aplicación: sincronice la biblioteca con OneDrive y use
`scripts\instalar_tarea.ps1 -Origen "<carpeta sincronizada>"`. Queda programado en Windows y
publica con sus credenciales de Git. No configure los secretos `AZURE_*`: el workflow lo detecta y
solo publica el sitio. Requiere la PC encendida.
