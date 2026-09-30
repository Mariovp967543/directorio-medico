/* ==========================================================================
   Directorio Médico — componente embebible (JS puro, sin dependencias)

   1. Descarga data/directorio.enc (cifrado AES-256-GCM) desde GitHub.
   2. Obtiene la llave desde la INTRANET, nunca desde GitHub:
        <iframe src=".../#k=<64 hex>">                        ← la pone el iframe del CMS (lo normal)
        window.DIRECTORIO_CONFIG = { key: "<64 hex>" }      ← inyectada por un servidor
        window.DIRECTORIO_CONFIG = { keyUrl: "/api/..." }    ← o pedida a un endpoint autenticado
        window.DIRECTORIO_CONFIG = { ingresoManual: true }   ← solo para la página de prueba
   3. Descifra en el navegador con Web Crypto (requiere HTTPS) y muestra el directorio.

   Montaje: <div id="directorio-medico"></div> (o cualquier elemento con
   data-directorio-medico). Opciones extra en DIRECTORIO_CONFIG:
     dataUrl   URL del .enc (por defecto: ../data/directorio.enc junto a este script)
     usarURL   true/false  guarda búsqueda y filtros en el #hash (por defecto true)
     titulo    texto del encabezado (por defecto "Directorio Médico")
   ========================================================================== */
(() => {
  "use strict";

  const SCRIPT_SRC = document.currentScript && document.currentScript.src;
  const PAGE = 48;
  const MAGIC = "DMC1";

  /* ====================================================== criptografía */
  class ErrorDMC extends Error { constructor(tipo, msg) { super(msg); this.tipo = tipo; } }

  function hexABytes(hex) {
    const limpio = String(hex || "").trim();
    if (!/^[0-9a-fA-F]{64}$/.test(limpio)) throw new ErrorDMC("llave", "La llave debe tener 64 caracteres hexadecimales.");
    const out = new Uint8Array(32);
    for (let i = 0; i < 32; i++) out[i] = parseInt(limpio.substr(i * 2, 2), 16);
    return out;
  }

  /** Importa la llave como NO extraíble: el código ya no puede volver a leerla. */
  async function importarLlave(hex) {
    const bytes = hexABytes(hex);
    try {
      return await crypto.subtle.importKey("raw", bytes, { name: "AES-GCM" }, false, ["decrypt"]);
    } finally {
      bytes.fill(0);
    }
  }

  async function descifrar(buffer, llave) {
    const u8 = new Uint8Array(buffer);
    if (u8.length < 34 || String.fromCharCode(...u8.subarray(0, 4)) !== MAGIC) {
      throw new ErrorDMC("formato", "El archivo de datos no tiene el formato esperado.");
    }
    const cabecera = u8.slice(0, 5), iv = u8.slice(5, 17), cifrado = u8.slice(17);
    let plano;
    try {
      plano = await crypto.subtle.decrypt({ name: "AES-GCM", iv, additionalData: cabecera, tagLength: 128 }, llave, cifrado);
    } catch (_) {
      throw new ErrorDMC("descifrado", "No se pudo descifrar: la llave no corresponde o el archivo fue alterado.");
    }
    if (cabecera[4] & 1) {
      const flujo = new Blob([plano]).stream().pipeThrough(new DecompressionStream("gzip"));
      plano = await new Response(flujo).arrayBuffer();
    }
    return JSON.parse(new TextDecoder().decode(plano));
  }

  async function obtenerLlaveDeConfig(cfg) {
    // Lo normal: el iframe de la intranet trae la llave en #k=... (nunca viaja a ningún servidor).
    const h = new URLSearchParams(location.hash.slice(1));
    const hk = h.get("k");
    if (hk) {
      h.delete("k");
      const resto = h.toString();
      history.replaceState(null, "", location.pathname + location.search + (resto ? "#" + resto : ""));
      return importarLlave(hk);
    }
    if (cfg.key) {
      const k = cfg.key;
      try { delete cfg.key; } catch (_) { cfg.key = undefined; }   // no dejarla en memoria global
      return importarLlave(k);
    }
    if (cfg.keyUrl) {
      const r = await fetch(cfg.keyUrl, { credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json, text/plain" } });
      if (r.status === 401 || r.status === 403) throw new ErrorDMC("acceso", "Su usuario no tiene acceso al directorio.");
      if (!r.ok) throw new ErrorDMC("llave", `No se pudo obtener la llave (HTTP ${r.status}).`);
      const txt = (await r.text()).trim();
      let hex = txt;
      if (txt.startsWith("{")) { try { hex = JSON.parse(txt).key; } catch (_) {} }
      return importarLlave(hex);
    }
    return null;
  }

  async function descargarDatos(url) {
    let r;
    try {
      // ?_= evita que GitHub Pages o el navegador entreguen una versión vieja
      r = await fetch(url + (url.includes("?") ? "&" : "?") + "_=" + Date.now(), { cache: "no-store" });
    } catch (_) {
      throw new ErrorDMC("red", "No se pudo conectar con el servidor de datos (GitHub). Revise la red o el proxy.");
    }
    if (!r.ok) throw new ErrorDMC("red", `No se pudo descargar el directorio (HTTP ${r.status}).`);
    return r.arrayBuffer();
  }

  /** Convierte las filas (una por médico + sede) en profesionales con todas sus sedes. */
  function adaptar(D) {
    if (D.profesionales) return D;
    const porPersona = new Map();
    const SERV = D.servicios || {};
    for (const f of D.filas || []) {
      let p = porPersona.get(f.pid);
      if (!p) {
        p = { id: f.pid, nombre: f.nombre, estado: f.estado, unidades: [], seguros: [], sedes: [], servicios: [] };
        porPersona.set(f.pid, p);
      }
      for (const k of ["codigo", "especialidad", "subespecialidad", "enfoque", "planes", "web", "convenios", "ingreso", "medismart"]) {
        if (!p[k] && f[k]) p[k] = f[k];
      }
      if (f.medismart === "Si") p.medismart = "Si";
      if (f.estado === "Laborando") p.estado = "Laborando";
      if (f.unidad && !p.unidades.includes(f.unidad)) p.unidades.push(f.unidad);
      for (const s of f.seguros || []) if (!p.seguros.includes(s)) p.seguros.push(s);
      p.sedes.push({
        sede: f.sede || "Sede no registrada", unidad: f.unidad, piso: f.piso, consultorio: f.consultorio,
        horario: f.horario, modalidad: f.modalidad, agenda: f.agenda, callcenter: f.callcenter === "Si",
        espera: f.espera, cobro: f.cobro, cortesias: f.cortesias, honorarios: f.honorarios, mixta: f.mixta,
        pago: f.pago, secretarias: f.secretarias,
      });
      // [nombre, precio, idx_preparación, sku, cpt, sede]
      for (const s of SERV[String(f.id)] || []) p.servicios.push([s[0], s[2], s[3], s[1], s[4], f.sede]);
    }
    return { generado: D.generado, preparaciones: D.preparaciones || [], profesionales: [...porPersona.values()] };
  }

  /* ====================================================== utilidades */
  const norm = (s) => (s ?? "").toString().normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const esc = (s) => (s ?? "").toString().replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const iniciales = (n) => n.split(" ").filter(Boolean).slice(0, 2).map((p) => p[0]).join("").toUpperCase();
  const esTele = (p) => (p.sedes || []).some((s) => /telemedicina/i.test(s.modalidad || ""));
  const esPres = (p) => (p.sedes || []).some((s) => /presencial/i.test(s.modalidad || "")) || !(p.sedes || []).some((s) => s.modalidad);
  const crc = new Intl.NumberFormat("es-CR", { style: "currency", currency: "CRC", maximumFractionDigits: 0 });
  const fecha = (iso) => new Date(iso + "T12:00:00").toLocaleDateString("es-CR", { day: "numeric", month: "long", year: "numeric" });
  const urlSegura = (u) => { try { const x = new URL(u); return /^https?:$/.test(x.protocol) ? x.href : null; } catch (_) { return null; } };

  /** Resalta los términos buscados respetando tildes (busca "jose" y marca "José"). */
  function resaltar(texto, terminos) {
    if (!texto) return "";
    if (!terminos.length) return esc(texto);
    let n = "";
    const map = [];
    for (let i = 0; i < texto.length; i++) {
      const c = norm(texto[i]);
      for (let k = 0; k < c.length; k++) { n += c[k]; map.push(i); }
    }
    const marcas = new Array(texto.length).fill(false);
    for (const t of terminos) {
      let pos = n.indexOf(t);
      while (pos !== -1) {
        for (let k = pos; k < pos + t.length; k++) marcas[map[k]] = true;
        pos = n.indexOf(t, pos + t.length);
      }
    }
    let out = "", abierto = false;
    for (let i = 0; i < texto.length; i++) {
      if (marcas[i] && !abierto) { out += "<mark>"; abierto = true; }
      if (!marcas[i] && abierto) { out += "</mark>"; abierto = false; }
      out += esc(texto[i]);
    }
    return out + (abierto ? "</mark>" : "");
  }

  const ICON = {
    logo: `<svg viewBox="0 0 32 32" aria-hidden="true"><path d="M13 7h6v6h6v6h-6v6h-6v-6H7v-6h6z"/></svg>`,
    luna: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3a9 9 0 1 0 9 9 7 7 0 0 1-9-9z"/></svg>`,
    lupa: `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>`,
    x: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>`,
    candado: `<svg viewBox="0 0 24 24" aria-hidden="true" style="width:36px;height:36px"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>`,
  };

  /* ====================================================== componente */
  function montar(root, cfg) {
    const uid = "dmc" + Math.random().toString(36).slice(2, 8);
    const $ = (r) => root.querySelector(`[data-r="${r}"]`);
    root.classList.add("dmc");
    try { const t = localStorage.getItem("dmc-tema"); if (t) root.dataset.theme = t; } catch (_) {}

    const titulo = esc(cfg.titulo || "Directorio Médico");
    const estado = (clase, html) => { root.innerHTML = `<div class="dmc-state ${clase}"><div class="dmc-state__box">${html}</div></div>`; };

    function mostrarError(e) {
      const tipo = e && e.tipo;
      const ayuda = {
        https: "Abra la intranet con https:// — el navegador solo permite descifrar en conexiones seguras.",
        descifrado: "La llave configurada en la intranet no coincide con la usada al publicar. Avise al administrador.",
        acceso: "Si cree que debería tener acceso, contacte a TI.",
      }[tipo] || "Intente de nuevo en unos minutos. Si el problema continúa, avise al administrador.";
      estado("dmc-state--error", `<h2>${esc(e && e.message || "Error inesperado")}</h2><p>${ayuda}</p>`);
      if (!(e instanceof ErrorDMC)) console.error("[Directorio Médico]", e);
    }

    async function iniciar() {
      if (!window.isSecureContext || !(window.crypto && crypto.subtle)) {
        return mostrarError(new ErrorDMC("https", "Este navegador no permite descifrar los datos en esta página."));
      }
      estado("", `<div class="dmc-spinner" role="status" aria-label="Cargando"></div><p>Cargando directorio…</p>`);
      const dataUrl = cfg.dataUrl || (SCRIPT_SRC ? new URL("../data/directorio.enc", SCRIPT_SRC).href : "data/directorio.enc");
      try {
        const [llave, buffer] = await Promise.all([obtenerLlaveDeConfig(cfg), descargarDatos(dataUrl)]);
        if (llave) return renderizar(await descifrar(buffer, llave));
        if (!cfg.ingresoManual) throw new ErrorDMC("llave", "La intranet no entregó la llave de descifrado.");
        pedirLlave(buffer);
      } catch (e) { mostrarError(e); }
    }

    /** Solo para la página de prueba: la llave se escribe a mano y no se guarda. */
    function pedirLlave(buffer, error) {
      estado("", `${ICON.candado}<h2>Datos cifrados</h2>
        <p>Pegue la llave de 64 caracteres para ver el directorio. No se guarda en ningún lado.</p>
        <form class="dmc-keyform" data-r="kf">
          <input data-r="k" type="password" autocomplete="off" spellcheck="false" aria-label="Llave de descifrado" placeholder="Llave (64 caracteres hexadecimales)">
          <button class="dmc-btn" type="submit">Abrir</button>
        </form>
        ${error ? `<p style="color:var(--dmc-danger)">${esc(error)}</p>` : ""}`);
      $("k").focus();
      $("kf").addEventListener("submit", async (ev) => {
        ev.preventDefault();
        const btn = ev.submitter; if (btn) btn.disabled = true;
        const valor = $("k").value; $("k").value = "";
        try { renderizar(await descifrar(buffer, await importarLlave(valor))); }
        catch (e) { pedirLlave(buffer, e.message); }
      });
    }

    /* ---------------------------------------------------- interfaz */
    function renderizar(DATOS) {
      const DATA = adaptar(DATOS);
      const P = DATA.profesionales || [];
      for (const p of P) {
        p._idx = norm([p.nombre, p.especialidad, p.subespecialidad, p.codigo, p.enfoque,
          (p.sedes || []).map((s) => s.sede).join(" "), (p.unidades || []).join(" "),
          (p.servicios || []).map((s) => s[0]).join(" ")].join(" · "));
        p._sedes = [...new Set((p.sedes || []).map((s) => s.sede))];
      }

      root.innerHTML = `
        <header class="dmc-top"><div class="dmc-wrap dmc-top__inner">
          <div class="dmc-brand">
            <span class="dmc-brand__mark" aria-hidden="true">${ICON.logo}</span>
            <div><h1 class="dmc-brand__title">${titulo}</h1>
              <p class="dmc-brand__sub">${P.length.toLocaleString("es-CR")} profesionales · actualizado ${fecha(DATA.generado)}</p></div>
          </div>
          <button class="dmc-icon-btn" data-r="tema" type="button" aria-label="Cambiar tema claro/oscuro" title="Cambiar tema">${ICON.luna}</button>
        </div></header>

        <section class="dmc-hero"><div class="dmc-wrap">
          <label class="dmc-search">${ICON.lupa}
            <input data-r="q" type="search" autocomplete="off" spellcheck="false" aria-label="Buscar"
                   placeholder="Buscar por nombre, especialidad, servicio o código profesional">
            <kbd aria-hidden="true">/</kbd>
          </label>
          <div class="dmc-filters" role="group" aria-label="Filtros">
            <label class="dmc-field"><span>Especialidad</span><select data-r="esp"><option value="">Todas</option></select></label>
            <label class="dmc-field"><span>Sede</span><select data-r="sede"><option value="">Todas</option></select></label>
            <label class="dmc-field"><span>Unidad</span><select data-r="unidad"><option value="">Todas</option></select></label>
            <label class="dmc-field"><span>Modalidad</span><select data-r="mod">
              <option value="">Todas</option><option value="Presencial">Presencial</option><option value="Telemedicina">Telemedicina</option></select></label>
            <label class="dmc-field"><span>Orden</span><select data-r="orden">
              <option value="nombre">Nombre A–Z</option><option value="especialidad">Especialidad</option><option value="servicios">Más servicios</option></select></label>
          </div>
          <div class="dmc-chips">
            <label class="dmc-toggle"><input type="checkbox" data-r="serv"><span>Con servicios y precios</span></label>
            <label class="dmc-toggle"><input type="checkbox" data-r="cc"><span>Agenda por call center</span></label>
            <label class="dmc-toggle"><input type="checkbox" data-r="ms"><span>Acepta Medismart</span></label>
            <button type="button" class="dmc-link-btn" data-r="limpiar" hidden>Limpiar filtros</button>
          </div>
        </div></section>

        <main class="dmc-wrap dmc-main">
          <p class="dmc-count" data-r="count" aria-live="polite"></p>
          <ul class="dmc-grid" data-r="grid"></ul>
          <div class="dmc-empty" data-r="empty" hidden>${ICON.lupa}<p><strong>Sin resultados.</strong> Pruebe con otra palabra o quite algún filtro.</p></div>
          <div class="dmc-more"><button type="button" class="dmc-btn" data-r="mas" hidden>Mostrar más</button></div>
        </main>

        <footer class="dmc-foot"><div class="dmc-wrap">Información consolidada desde las matrices de cada unidad. Para reportar un dato incorrecto, contacte al equipo de Calidad.</div></footer>

        <dialog class="dmc-modal" data-r="modal" aria-labelledby="${uid}-n">
          <header class="dmc-modal__head">
            <div class="dmc-avatar dmc-avatar--lg" data-r="m-av" aria-hidden="true"></div>
            <div class="dmc-modal__id"><h2 id="${uid}-n" data-r="m-n"></h2><p data-r="m-e"></p><div class="dmc-tags" data-r="m-t"></div></div>
            <button class="dmc-icon-btn" type="button" data-r="cerrar" aria-label="Cerrar">${ICON.x}</button>
          </header>
          <div class="dmc-modal__body" data-r="m-b"></div>
        </dialog>`;

      /* combos */
      const llenar = (sel, valores) => {
        const c = new Map();
        valores.forEach((v) => v && c.set(v, (c.get(v) || 0) + 1));
        [...c.entries()].sort((a, b) => a[0].localeCompare(b[0], "es")).forEach(([v, n]) => sel.add(new Option(`${v} (${n})`, v)));
      };
      llenar($("esp"), P.map((p) => p.especialidad));
      llenar($("sede"), P.flatMap((p) => p._sedes));
      llenar($("unidad"), P.flatMap((p) => p.unidades || []));

      /* estado ↔ URL */
      const CTRL = ["q", "esp", "sede", "unidad", "mod", "orden", "serv", "cc", "ms"];
      const leer = () => Object.fromEntries(CTRL.map((k) => { const el = $(k); return [k, el.type === "checkbox" ? el.checked : el.value]; }));
      const usarURL = cfg.usarURL !== false;
      function aURL(st) {
        if (!usarURL) return;
        const u = new URLSearchParams();
        for (const [k, v] of Object.entries(st)) if (v && !(k === "orden" && v === "nombre")) u.set(k, v === true ? "1" : v);
        const h = u.toString();
        history.replaceState(history.state, "", h ? "#" + h : location.pathname + location.search);
      }
      if (usarURL) {
        const u = new URLSearchParams(location.hash.slice(1));
        CTRL.forEach((k) => { if (!u.has(k)) return; const el = $(k); if (el.type === "checkbox") el.checked = u.get(k) === "1"; else el.value = u.get(k); });
      }

      let resultado = [], mostrados = 0, terminos = [];

      function filtrar() {
        const st = leer();
        terminos = norm(st.q).split(/\s+/).filter(Boolean);
        resultado = P.filter((p) =>
          terminos.every((t) => p._idx.includes(t)) &&
          (!st.esp || p.especialidad === st.esp) &&
          (!st.sede || p._sedes.includes(st.sede)) &&
          (!st.unidad || (p.unidades || []).includes(st.unidad)) &&
          (!st.mod || (st.mod === "Telemedicina" ? esTele(p) : esPres(p))) &&
          (!st.serv || (p.servicios || []).some((s) => s[1])) &&
          (!st.cc || (p.sedes || []).some((s) => s.callcenter)) &&
          (!st.ms || p.medismart === "Si"));
        const porNombre = (a, b) => a.nombre.localeCompare(b.nombre, "es");
        resultado.sort({
          nombre: porNombre,
          especialidad: (a, b) => (a.especialidad || "~").localeCompare(b.especialidad || "~", "es") || porNombre(a, b),
          servicios: (a, b) => (b.servicios || []).length - (a.servicios || []).length || porNombre(a, b),
        }[st.orden] || porNombre);
        $("limpiar").hidden = !Object.entries(st).some(([k, v]) => v && !(k === "orden" && v === "nombre"));
        aURL(st);
        mostrados = 0;
        $("grid").innerHTML = "";
        pintar();
      }

      function tarjeta(p) {
        const li = document.createElement("li");
        const s = p._sedes, nServ = (p.servicios || []).length;
        li.innerHTML = `
          <button class="dmc-card" type="button" data-id="${p.id}">
            <div class="dmc-card__top">
              <span class="dmc-avatar" aria-hidden="true">${esc(iniciales(p.nombre))}</span>
              <div>
                <p class="dmc-card__name">${resaltar(p.nombre, terminos)}</p>
                <p class="dmc-card__esp ${p.especialidad ? "" : "is-empty"}">${p.especialidad ? resaltar(p.especialidad, terminos) : "Especialidad no registrada"}</p>
              </div>
            </div>
            ${p.subespecialidad ? `<p class="dmc-card__sub">${resaltar(p.subespecialidad, terminos)}</p>` : ""}
            <div class="dmc-card__foot">
              ${p.estado === "Nuevo ingreso" ? `<span class="dmc-tag dmc-tag--new">Nuevo</span>` : ""}
              ${esTele(p) ? `<span class="dmc-tag dmc-tag--tele">Telemedicina</span>` : ""}
              ${p.medismart === "Si" ? `<span class="dmc-tag dmc-tag--ms">Medismart</span>` : ""}
              ${s.slice(0, 2).map((x) => `<span class="dmc-tag">${esc(x)}</span>`).join("")}
              ${s.length > 2 ? `<span class="dmc-tag">+${s.length - 2}</span>` : ""}
              ${nServ ? `<span class="dmc-tag">${nServ} servicio${nServ > 1 ? "s" : ""}</span>` : ""}
            </div>
          </button>`;
        return li;
      }

      function pintar() {
        const frag = document.createDocumentFragment();
        resultado.slice(mostrados, mostrados + PAGE).forEach((p) => frag.appendChild(tarjeta(p)));
        mostrados = Math.min(mostrados + PAGE, resultado.length);
        $("grid").appendChild(frag);
        const n = resultado.length;
        $("count").textContent = n ? `${n.toLocaleString("es-CR")} profesional${n === 1 ? "" : "es"}${n > mostrados ? ` · mostrando ${mostrados}` : ""}` : "";
        $("empty").hidden = n > 0;
        $("mas").hidden = mostrados >= n;
      }

      const modal = $("modal");
      function abrir(p) {
        $("m-av").textContent = iniciales(p.nombre);
        $("m-n").textContent = p.nombre;
        $("m-e").textContent = [p.especialidad, p.subespecialidad].filter(Boolean).join(" · ") || "Especialidad no registrada";
        $("m-t").innerHTML = [
          p.estado === "Nuevo ingreso" ? `<span class="dmc-tag dmc-tag--new">Nuevo ingreso</span>` : "",
          esTele(p) ? `<span class="dmc-tag dmc-tag--tele">Telemedicina</span>` : "",
          ...(p.unidades || []).map((u) => `<span class="dmc-tag">${esc(u)}</span>`),
        ].join("");
        const siNo = (v) => v === "Si" ? "Sí" : v;
        const info = [["Código profesional", p.codigo], ["Enfoque", p.enfoque], ["Método de ingreso", p.ingreso],
                      ["Acepta Medismart", siNo(p.medismart)], ["Planes", p.planes]].filter(([, v]) => v);
        const web = p.web && urlSegura(p.web);
        const serv = p.servicios || [];
        const variasSedes = new Set(serv.map((s) => s[5])).size > 1;
        const kv = (pares) => pares.filter(([, v]) => v).map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");
        $("m-b").innerHTML = `
          ${info.length || web ? `<h3>Información</h3><dl class="dmc-kv">${info.map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join("")}
            ${web ? `<dt>Perfil</dt><dd><a class="dmc-ext" href="${esc(web)}" target="_blank" rel="noopener noreferrer">Ver perfil en línea ↗</a></dd>` : ""}</dl>` : ""}
          ${(p.sedes || []).length ? `<h3>Dónde atiende</h3>${p.sedes.map((s) => `
            <div class="dmc-sede">
              <p class="dmc-sede__name">${esc(s.sede)} ${s.modalidad ? `<span class="dmc-tag ${/tele/i.test(s.modalidad) ? "dmc-tag--tele" : ""}">${esc(s.modalidad)}</span>` : ""}
                ${s.unidad ? `<span class="dmc-tag">${esc(s.unidad)}</span>` : ""}</p>
              <dl class="dmc-kv">${kv([
                ["Horario", esc(s.horario)],
                ["Ubicación", [s.piso && "Piso " + String(s.piso).replace(/^piso\s*/i, ""), s.consultorio].filter(Boolean).map(esc).join(" · ")],
                ["Agenda", s.agenda && esc(s.agenda) + (s.callcenter ? " · también por call center" : "")],
                ["Tiempo de espera", esc(s.espera)],
                ["Forma de pago", esc(s.pago)],
                ["Secretaría", esc(s.secretarias)],
                ["Condiciones", [["Cobro anticipado", s.cobro], ["Cortesías", s.cortesias], ["Honorarios médicos", s.honorarios], ["Medicina mixta", s.mixta]]
                    .filter(([, v]) => v).map(([k, v]) => `<span class="dmc-tag ${v === "Si" ? "dmc-tag--si" : ""}">${k}: ${esc(siNo(v))}</span>`).join(" ")],
              ])}</dl>
            </div>`).join("")}` : ""}
          ${(p.seguros || []).length ? `<h3>Seguros aceptados (${p.seguros.length})</h3><div class="dmc-tags">${p.seguros.map((x) => `<span class="dmc-tag">${esc(x)}</span>`).join("")}</div>` : ""}
          ${p.convenios ? `<h3>Convenios corporativos</h3><p class="dmc-text">${esc(p.convenios)}</p>` : ""}
          ${serv.length ? `<h3>Servicios y procedimientos (${serv.length})</h3>
            ${serv.length > 8 ? `<input class="dmc-serv-filter" data-r="sf" type="search" placeholder="Filtrar servicios…" aria-label="Filtrar servicios">` : ""}
            <table class="dmc-serv"><thead><tr><th>Servicio</th><th>SKU</th><th class="dmc-num">Precio sin IVA</th></tr></thead>
            <tbody>${serv.map(([n, precio, ip, sku, cpt, sede]) => `
              <tr data-n="${esc(norm(n + " " + (sku || "")))}"><td>${resaltar(n, terminos)}
                ${variasSedes && sede ? `<small>Sede: ${esc(sede)}</small>` : ""}
                ${ip != null && DATA.preparaciones[ip] ? `<small>Preparación: ${esc(DATA.preparaciones[ip])}</small>` : ""}
                ${cpt ? `<small>CPT: ${esc(cpt)}</small>` : ""}</td>
              <td class="dmc-sku">${esc(sku || "")}</td>
              <td class="dmc-num">${precio ? crc.format(precio) : "—"}</td></tr>`).join("")}</tbody></table>` : ""}`;
        const sf = $("sf");
        if (sf) sf.addEventListener("input", () => {
          const t = norm(sf.value);
          modal.querySelectorAll("tbody tr").forEach((tr) => { tr.hidden = !!t && !tr.dataset.n.includes(t); });
        });
        modal.showModal();
        $("m-b").scrollTop = 0;
      }

      /* eventos */
      let timer;
      $("q").addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(filtrar, 120); });
      ["esp", "sede", "unidad", "mod", "orden", "serv", "cc", "ms"].forEach((k) => $(k).addEventListener("change", filtrar));
      $("mas").addEventListener("click", pintar);
      $("limpiar").addEventListener("click", () => {
        CTRL.forEach((k) => { const el = $(k); if (el.type === "checkbox") el.checked = false; else el.value = k === "orden" ? "nombre" : ""; });
        filtrar(); $("q").focus();
      });
      $("grid").addEventListener("click", (e) => {
        const b = e.target.closest(".dmc-card"); if (!b) return;
        abrir(P.find((p) => p.id === +b.dataset.id));
      });
      $("cerrar").addEventListener("click", () => modal.close());
      modal.addEventListener("click", (e) => { if (e.target === modal) modal.close(); });
      modal.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); modal.close(); } });
      document.addEventListener("keydown", (e) => {
        const tag = (document.activeElement && document.activeElement.tagName) || "";
        if (e.key === "/" && !/INPUT|TEXTAREA|SELECT/.test(tag) && !modal.open && root.isConnected) { e.preventDefault(); $("q").focus(); }
      });
      $("tema").addEventListener("click", () => {
        const oscuro = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
        root.dataset.theme = oscuro ? "light" : "dark";
        try { localStorage.setItem("dmc-tema", root.dataset.theme); } catch (_) {}
      });

      filtrar();
    }

    iniciar();
  }

  /* ====================================================== arranque */
  function arrancar() {
    const cfg = window.DIRECTORIO_CONFIG || {};
    const nodos = document.querySelectorAll("#directorio-medico, [data-directorio-medico]");
    if (!nodos.length) { console.warn("[Directorio Médico] No se encontró <div id=\"directorio-medico\">."); return; }
    nodos.forEach((n) => montar(n, cfg));
  }
  window.DirectorioMedico = { montar: (el, cfg) => montar(el, cfg || window.DIRECTORIO_CONFIG || {}) };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", arrancar);
  else arrancar();
})();
