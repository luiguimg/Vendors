/* Portal de Proveedores — SPA conectada a la API del backend. */

const API = "/api/v1";
let token = localStorage.getItem("pp_token");
let vendorName = localStorage.getItem("pp_vendor") || "";

const STATUS_LABELS = {
  enviada:                  ["Enviada", "badge-info"],
  en_revision:              ["En Revisión", "badge-warn"],
  confirmada:               ["Confirmada", "badge-ok"],
  rechazada:                ["Rechazada", "badge-err"],
  modificacion_solicitada:  ["Modificación Solicitada", "badge-info"],
  en_produccion:            ["En Producción", "badge-ok"],
  embarcada:                ["Embarcada", "badge-ok"],
  recibida:                 ["Recibida", "badge-ok"],
  cancelada:                ["Cancelada", "badge-err"],
  borrador:                 ["Borrador", "badge-warn"],
  enviado:                  ["Enviado", "badge-info"],
  en_transito:              ["En Tránsito", "badge-warn"],
  recibido:                 ["Recibido", "badge-ok"],
  timbrada:                 ["Timbrada", "badge-ok"],
  en_validacion:            ["En Validación", "badge-info"],
  aprobado:                 ["Aprobado", "badge-ok"],
  aprobada:                 ["Aprobada", "badge-ok"],
  rechazado:                ["Rechazado", "badge-err"],
  programada:               ["Programada", "badge-warn"],
  pagada:                   ["Pagada", "badge-ok"],
  pago_parcial:             ["Pago Parcial", "badge-warn"],
};

const badge = (s) => {
  const [label, cls] = STATUS_LABELS[s] || [s, "badge-info"];
  return `<span class="badge ${cls}">${label}</span>`;
};
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const money = (n, cur = "MXN") =>
  Number(n).toLocaleString("es-MX", { style: "currency", currency: cur });
const fdate = (d) => (d ? new Date(d + (d.length === 10 ? "T00:00:00" : "")).toLocaleDateString("es-MX") : "—");

function toast(msg, isError = false) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.className = isError ? "show error" : "show";
  setTimeout(() => (el.className = ""), 4000);
}

async function api(path, options = {}) {
  const headers = options.headers || {};
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (options.body && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.body);
  }
  const resp = await fetch(API + path, { ...options, headers });
  if (resp.status === 401) { logout(); throw new Error("Sesión expirada"); }
  if (!resp.ok) {
    const data = await resp.json().catch(() => ({}));
    throw new Error(typeof data.detail === "string" ? data.detail : "Error en la solicitud");
  }
  return resp.status === 204 ? null : resp.json();
}

/* ─── Sesión ─────────────────────────────────────────────────────────── */

function showLogin() {
  document.getElementById("login-view").style.display = "grid";
  document.getElementById("app-view").style.display = "none";
}

function showApp() {
  document.getElementById("login-view").style.display = "none";
  document.getElementById("app-view").style.display = "flex";
  document.getElementById("hdr-vendor").textContent = vendorName;
  refreshAll();
}

document.getElementById("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errEl = document.getElementById("login-error");
  errEl.style.display = "none";
  try {
    const resp = await fetch(API + "/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: document.getElementById("login-email").value,
        password: document.getElementById("login-password").value,
      }),
    });
    if (!resp.ok) throw new Error("Credenciales inválidas");
    const data = await resp.json();
    token = data.token;
    vendorName = `${data.vendor_name} (${data.vendor_code})`;
    localStorage.setItem("pp_token", token);
    localStorage.setItem("pp_vendor", vendorName);
    showApp();
  } catch (err) {
    errEl.textContent = err.message;
    errEl.style.display = "block";
  }
});

function logout() {
  if (token) fetch(API + "/auth/logout", { method: "POST", headers: { Authorization: `Bearer ${token}` } }).catch(() => {});
  token = null;
  localStorage.removeItem("pp_token");
  localStorage.removeItem("pp_vendor");
  showLogin();
}

/* ─── Navegación ─────────────────────────────────────────────────────── */

function showSection(id) {
  document.querySelectorAll(".section").forEach((s) => s.classList.remove("active"));
  document.getElementById(id).classList.add("active");
  document.querySelectorAll(".nav-item[data-section]").forEach((n) => n.classList.remove("active"));
  const nav = document.querySelector(`.nav-item[data-section="${id}"]`);
  if (nav) nav.classList.add("active");
  document.querySelector("main").scrollTo(0, 0);
}

/* ─── Estado compartido ──────────────────────────────────────────────── */

let purchaseOrders = [];
let asns = [];

async function refreshAll() {
  try {
    [purchaseOrders, asns] = await Promise.all([api("/purchase-orders"), api("/asn")]);
    renderOverview();
    renderPOList();
    renderASNSection();
    await Promise.all([renderCPSection(), renderDocuments(), renderCFDIs(), renderStatement()]);
  } catch (err) {
    if (err.message !== "Sesión expirada") toast(err.message, true);
  }
}

/* ─── Resumen ────────────────────────────────────────────────────────── */

function renderOverview() {
  const counts = {};
  purchaseOrders.forEach((po) => (counts[po.status] = (counts[po.status] || 0) + 1));
  const kpis = [
    ["&#128203;", "OC por responder", (counts.enviada || 0) + (counts.en_revision || 0), "oc"],
    ["&#9989;", "OC confirmadas", (counts.confirmada || 0) + (counts.en_produccion || 0), "oc"],
    ["&#128674;", "Embarques activos", asns.filter((a) => a.status !== "recibido").length, "asn"],
    ["&#128196;", "Total de órdenes", purchaseOrders.length, "oc"],
  ];
  document.getElementById("ov-kpis").innerHTML = kpis.map(
    ([icon, label, value, target]) => `
    <div class="ov-card" onclick="showSection('${target}')">
      <div class="ov-icon">${icon}</div>
      <h3>${label}</h3>
      <div class="ov-kpi">${value}</div>
    </div>`).join("");

  const pending = purchaseOrders.filter((po) => ["enviada", "en_revision"].includes(po.status));
  document.getElementById("ov-pending").innerHTML = pending.length
    ? poTable(pending)
    : '<div class="empty">No tienes órdenes pendientes de respuesta. &#127881;</div>';
}

/* ─── Órdenes de compra ──────────────────────────────────────────────── */

function poTable(list) {
  return `<table class="status-table">
    <thead><tr><th>OC</th><th>Estatus</th><th>Fecha solicitada</th><th>Fecha confirmada</th><th>Total</th><th></th></tr></thead>
    <tbody>${list.map((po) => `
      <tr class="clickable" onclick="openPO(${po.id})">
        <td><strong>${esc(po.number)}</strong></td>
        <td>${badge(po.status)}</td>
        <td>${fdate(po.requested_date)}</td>
        <td>${fdate(po.confirmed_date)}</td>
        <td>${money(po.total, po.currency)}</td>
        <td><button class="btn btn-secondary btn-sm">Abrir</button></td>
      </tr>`).join("")}</tbody></table>`;
}

function renderPOList() {
  document.getElementById("oc-list").innerHTML = purchaseOrders.length
    ? poTable(purchaseOrders)
    : '<div class="empty">Sin órdenes de compra publicadas.</div>';
}

async function openPO(id) {
  try {
    const po = await api(`/purchase-orders/${id}`);
    const i = purchaseOrders.findIndex((p) => p.id === id);
    if (i >= 0) purchaseOrders[i] = po;
    renderPOList();
    renderOverview();

    const canRespond = ["enviada", "en_revision", "modificacion_solicitada"].includes(po.status);
    const canDate = ["confirmada", "en_produccion"].includes(po.status);
    const canProduce = po.status === "confirmada";

    document.getElementById("oc-detail").innerHTML = `
    <div class="card">
      <div class="card-hdr">
        <div class="card-icon">&#128196;</div>
        <div>
          <div class="card-title">Orden ${esc(po.number)} &nbsp;${badge(po.status)}</div>
          <div class="card-sub">${esc(po.notes || "")}</div>
        </div>
      </div>
      <div class="po-meta">
        <div><strong>Fecha solicitada</strong>${fdate(po.requested_date)}</div>
        <div><strong>Fecha confirmada</strong>${fdate(po.confirmed_date)}</div>
        ${po.proposed_date ? `<div><strong>Fecha propuesta</strong>${fdate(po.proposed_date)} — ${esc(po.proposed_date_reason || "")}</div>` : ""}
        <div><strong>Total</strong>${money(po.total, po.currency)}</div>
        ${po.rejection_reason ? `<div><strong>Motivo rechazo</strong>${esc(po.rejection_reason)}</div>` : ""}
        ${po.change_request ? `<div><strong>Cambio solicitado</strong>${esc(po.change_request)}</div>` : ""}
      </div>
      <table class="status-table">
        <thead><tr><th>#</th><th>SKU</th><th>Descripción</th><th>Cantidad</th><th>Precio unit.</th><th>Importe</th></tr></thead>
        <tbody>${po.lines.map((l) => `
          <tr><td>${l.line_no}</td><td>${esc(l.sku)}</td><td>${esc(l.description)}</td>
          <td>${l.quantity} ${esc(l.unit)}</td><td>${money(l.unit_price, po.currency)}</td>
          <td>${money(l.quantity * l.unit_price, po.currency)}</td></tr>`).join("")}</tbody>
      </table>
      ${canRespond ? `
      <div class="form-actions" style="margin-top:18px">
        <button class="btn btn-primary" onclick="respondPO(${po.id}, 'aceptar')">Aceptar OC</button>
        <button class="btn btn-secondary" onclick="respondPO(${po.id}, 'solicitar_cambio')">Solicitar modificación</button>
        <button class="btn btn-danger" onclick="respondPO(${po.id}, 'rechazar')">Rechazar</button>
      </div>` : ""}
      ${canDate ? `
      <div class="form-grid" style="margin-top:18px">
        <div class="form-field"><label>Confirmar fecha de entrega</label><input type="date" id="po-date-${po.id}" value="${po.confirmed_date || ""}" /></div>
        <div class="form-actions" style="align-self:end">
          <button class="btn btn-primary" onclick="confirmDate(${po.id})">Confirmar fecha</button>
          <button class="btn btn-secondary" onclick="proposeDate(${po.id})">Proponer otra fecha</button>
          ${canProduce ? `<button class="btn btn-secondary" onclick="markProduction(${po.id})">Marcar en producción</button>` : ""}
        </div>
      </div>` : ""}
    </div>`;
    document.getElementById("oc-detail").scrollIntoView({ behavior: "smooth" });
  } catch (err) { toast(err.message, true); }
}

async function respondPO(id, action) {
  const payload = { action };
  if (action === "aceptar") {
    const date = prompt("Fecha de entrega comprometida (AAAA-MM-DD), vacío = fecha solicitada:");
    if (date === null) return;
    if (date.trim()) payload.confirmed_date = date.trim();
  } else {
    const reason = prompt(action === "rechazar" ? "Motivo del rechazo:" : "Describe la modificación solicitada:");
    if (!reason) return;
    payload.reason = reason;
  }
  try {
    await api(`/purchase-orders/${id}/respond`, { method: "POST", body: payload });
    toast("Respuesta enviada a Natureganix");
    await refreshAll();
    openPO(id);
  } catch (err) { toast(err.message, true); }
}

async function confirmDate(id) {
  const date = document.getElementById(`po-date-${id}`).value;
  if (!date) return toast("Selecciona una fecha", true);
  try {
    await api(`/purchase-orders/${id}/confirm-date`, { method: "POST", body: { action: "confirmar", confirmed_date: date } });
    toast("Fecha confirmada y registrada en BC");
    await refreshAll(); openPO(id);
  } catch (err) { toast(err.message, true); }
}

async function proposeDate(id) {
  const date = prompt("Nueva fecha propuesta (AAAA-MM-DD):");
  if (!date) return;
  const reason = prompt("Justificación de la nueva fecha:");
  if (!reason) return;
  try {
    await api(`/purchase-orders/${id}/confirm-date`, { method: "POST", body: { action: "proponer", proposed_date: date, reason } });
    toast("Propuesta enviada al comprador");
    await refreshAll(); openPO(id);
  } catch (err) { toast(err.message, true); }
}

async function markProduction(id) {
  try {
    await api(`/purchase-orders/${id}/status`, { method: "POST", body: { status: "en_produccion" } });
    toast("OC marcada en producción");
    await refreshAll(); openPO(id);
  } catch (err) { toast(err.message, true); }
}

/* ─── ASN ────────────────────────────────────────────────────────────── */

function renderASNSection() {
  const eligible = purchaseOrders.filter((po) => ["confirmada", "en_produccion"].includes(po.status));
  const sel = document.getElementById("asn-po");
  sel.innerHTML = eligible.length
    ? eligible.map((po) => `<option value="${po.id}">${esc(po.number)} — ${money(po.total, po.currency)}</option>`).join("")
    : '<option value="">(sin OC elegibles)</option>';
  sel.onchange = renderASNLines;
  renderASNLines();

  document.getElementById("asn-list").innerHTML = asns.length
    ? `<table class="status-table">
        <thead><tr><th>ASN</th><th>OC</th><th>Tipo</th><th>Transportista</th><th>ETA</th><th>Estatus</th><th>WMS</th></tr></thead>
        <tbody>${asns.map((a) => `
          <tr><td><strong>${esc(a.number)}</strong></td><td>${esc(a.po_number)}</td>
          <td>${esc(a.shipment_type)}</td><td>${esc(a.carrier_name)}</td>
          <td>${a.eta ? new Date(a.eta).toLocaleString("es-MX") : "—"}</td>
          <td>${badge(a.status)}</td>
          <td>${a.erp_acknowledged ? badge("recibido") : '<span class="badge badge-warn">Pendiente</span>'}</td></tr>`).join("")}
        </tbody></table>`
    : '<div class="empty">Aún no has creado embarques.</div>';
}

function renderASNLines() {
  const poId = Number(document.getElementById("asn-po").value);
  const po = purchaseOrders.find((p) => p.id === poId);
  document.getElementById("asn-lines").innerHTML = po
    ? `<table class="status-table"><thead><tr><th>SKU</th><th>Descripción</th><th>Ordenado</th><th>A embarcar</th></tr></thead>
       <tbody>${po.lines.map((l, i) => `
         <tr><td>${esc(l.sku)}</td><td>${esc(l.description)}</td><td>${l.quantity} ${esc(l.unit)}</td>
         <td><input type="number" min="0" max="${l.quantity}" step="0.01" value="${l.quantity}"
              data-line="${i}" style="width:90px;padding:4px 8px;border:1px solid #c8c6c4;border-radius:2px"/></td></tr>`).join("")}
       </tbody></table>`
    : '<div class="empty">Selecciona una orden de compra confirmada.</div>';
}

document.getElementById("asn-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const poId = Number(document.getElementById("asn-po").value);
  const po = purchaseOrders.find((p) => p.id === poId);
  if (!po) return toast("Selecciona una OC elegible", true);

  const lines = [...document.querySelectorAll("#asn-lines input[data-line]")]
    .map((input) => {
      const l = po.lines[Number(input.dataset.line)];
      return { sku: l.sku, description: l.description, quantity: Number(input.value), unit: l.unit };
    })
    .filter((l) => l.quantity > 0);
  if (!lines.length) return toast("Indica cantidades a embarcar", true);

  try {
    await api("/asn", { method: "POST", body: {
      po_number: po.number,
      shipment_type: document.getElementById("asn-type").value,
      carrier_name: document.getElementById("asn-carrier").value,
      carrier_rfc: document.getElementById("asn-carrier-rfc").value || null,
      vehicle_plate: document.getElementById("asn-plate").value || null,
      driver_name: document.getElementById("asn-driver").value || null,
      pallets: Number(document.getElementById("asn-pallets").value || 0),
      weight_kg: Number(document.getElementById("asn-weight").value || 0),
      ship_datetime: document.getElementById("asn-ship").value || null,
      eta: document.getElementById("asn-eta").value || null,
      tracking_number: document.getElementById("asn-tracking").value || null,
      lines,
    }});
    toast("ASN enviado — Natureganix preparará la recepción");
    e.target.reset();
    await refreshAll();
  } catch (err) { toast(err.message, true); }
});

/* ─── Carta Porte (carga de XML timbrado externamente) ──────────────── */

async function renderCPSection() {
  // Pedidos activos que pueden requerir Carta Porte
  const eligible = purchaseOrders.filter((po) =>
    ["confirmada", "en_produccion", "embarcada", "recibida"].includes(po.status));
  document.getElementById("cp-pos").innerHTML = eligible
    .map((po) => `<option value="${esc(po.number)}">${esc(po.number)} — ${badgeText(po.status)}</option>`).join("");

  const cps = await api("/documents?doc_type=carta_porte");
  document.getElementById("cp-list").innerHTML = cps.length
    ? `<table class="status-table">
        <thead><tr><th>Archivo</th><th>Pedidos que ampara</th><th>Folio fiscal (UUID)</th><th>Cargada</th><th>Estatus</th><th></th></tr></thead>
        <tbody>${cps.map((d) => `
          <tr><td>${esc(d.filename)}</td>
          <td>${d.po_numbers.map((n) => `<code class="inline">${esc(n)}</code>`).join(" ")}</td>
          <td>${d.cfdi_uuid ? `<code class="inline">${esc(d.cfdi_uuid)}</code>` : "—"}</td>
          <td>${new Date(d.uploaded_at).toLocaleString("es-MX")}</td>
          <td>${badge(d.status)}${d.rejection_reason ? `<div style="font-size:11px;color:var(--red)">${esc(d.rejection_reason)}</div>` : ""}</td>
          <td><a class="btn btn-secondary btn-sm" href="#" onclick="return downloadDoc(event, ${d.id}, '${esc(d.filename)}')">Descargar</a></td></tr>`).join("")}
        </tbody></table>`
    : '<div class="empty">Sin Cartas Porte cargadas.</div>';
}

function badgeText(s) {
  return (STATUS_LABELS[s] || [s])[0];
}

document.getElementById("cp-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const selected = [...document.getElementById("cp-pos").selectedOptions].map((o) => o.value);
  const fileInput = document.getElementById("cp-file");
  if (!selected.length) return toast("Selecciona el pedido o grupo de pedidos que ampara", true);
  if (!fileInput.files.length) return toast("Adjunta el XML timbrado", true);

  const form = new FormData();
  form.append("po_numbers", selected.join(","));
  form.append("doc_type", "carta_porte");
  form.append("file", fileInput.files[0]);
  try {
    const doc = await api("/documents", { method: "POST", body: form });
    toast(doc.cfdi_uuid
      ? `Carta Porte validada — Folio fiscal: ${doc.cfdi_uuid}`
      : "Carta Porte cargada; en validación por Natureganix");
    e.target.reset();
    renderCPSection();
    renderDocuments();
  } catch (err) { toast(err.message, true); }
});

/* ─── Documentos ─────────────────────────────────────────────────────── */

async function renderDocuments() {
  document.getElementById("doc-po").innerHTML = purchaseOrders
    .map((po) => `<option value="${esc(po.number)}">${esc(po.number)}</option>`).join("");
  const docs = await api("/documents");
  document.getElementById("doc-list").innerHTML = docs.length
    ? `<table class="status-table">
        <thead><tr><th>Pedido(s)</th><th>Tipo</th><th>Archivo</th><th>Folio fiscal</th><th>Cargado</th><th>Estatus</th><th></th></tr></thead>
        <tbody>${docs.map((d) => `
          <tr><td>${d.po_numbers.map((n) => `<code class="inline">${esc(n)}</code>`).join(" ")}</td>
          <td>${esc(d.doc_type.replace(/_/g, " "))}</td>
          <td>${esc(d.filename)}</td>
          <td>${d.cfdi_uuid ? `<code class="inline" title="${esc(d.cfdi_uuid)}">${esc(d.cfdi_uuid.slice(0, 8))}…</code>` : "—"}</td>
          <td>${new Date(d.uploaded_at).toLocaleString("es-MX")}</td>
          <td>${badge(d.status)}${d.rejection_reason ? `<div style="font-size:11px;color:var(--red)">${esc(d.rejection_reason)}</div>` : ""}</td>
          <td><a class="btn btn-secondary btn-sm" href="${API}/documents/${d.id}/download" onclick="return downloadDoc(event, ${d.id}, '${esc(d.filename)}')">Descargar</a></td></tr>`).join("")}
        </tbody></table>`
    : '<div class="empty">El expediente está vacío.</div>';
}

async function downloadDoc(e, id, filename) {
  e.preventDefault();
  try {
    const resp = await fetch(`${API}/documents/${id}/download`, { headers: { Authorization: `Bearer ${token}` } });
    if (!resp.ok) throw new Error("No se pudo descargar");
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = Object.assign(document.createElement("a"), { href: url, download: filename });
    a.click();
    URL.revokeObjectURL(url);
  } catch (err) { toast(err.message, true); }
  return false;
}

document.getElementById("doc-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fileInput = document.getElementById("doc-file");
  if (!fileInput.files.length) return;
  const selectedPOs = [...document.getElementById("doc-po").selectedOptions].map((o) => o.value);
  if (!selectedPOs.length) return toast("Selecciona al menos un pedido", true);
  const form = new FormData();
  form.append("po_numbers", selectedPOs.join(","));
  form.append("doc_type", document.getElementById("doc-type").value);
  form.append("file", fileInput.files[0]);
  try {
    await api("/documents", { method: "POST", body: form });
    toast("Documento cargado al expediente");
    e.target.reset();
    renderDocuments();
  } catch (err) { toast(err.message, true); }
});

/* ─── CFDI ───────────────────────────────────────────────────────────── */

async function renderCFDIs() {
  document.getElementById("cfdi-po").innerHTML =
    '<option value="">(sin OC)</option>' +
    purchaseOrders.map((po) => `<option value="${esc(po.number)}">${esc(po.number)}</option>`).join("");
  const cfdis = await api("/cfdi");
  document.getElementById("cfdi-list").innerHTML = cfdis.length
    ? `<table class="status-table">
        <thead><tr><th>UUID</th><th>Tipo</th><th>OC</th><th>Total</th><th>Estatus</th><th>CxP BC</th></tr></thead>
        <tbody>${cfdis.map((c) => `
          <tr><td><code class="inline">${esc(c.uuid)}</code></td><td>${esc(c.cfdi_type)}</td>
          <td>${esc(c.po_number || "—")}</td><td>${money(c.total, c.currency)}</td>
          <td>${badge(c.status)}${c.rejection_reason ? `<div style="font-size:11px;color:var(--red)">${esc(c.rejection_reason)}</div>` : ""}</td>
          <td>${c.erp_synced ? badge("aprobada") : '<span class="badge badge-warn">Pendiente</span>'}</td></tr>`).join("")}
        </tbody></table>`
    : '<div class="empty">No has cargado CFDIs.</div>';
}

document.getElementById("cfdi-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const cfdi = await api("/cfdi", { method: "POST", body: {
      uuid: document.getElementById("cfdi-uuid").value.trim(),
      cfdi_type: document.getElementById("cfdi-type").value,
      po_number: document.getElementById("cfdi-po").value || null,
      serie_folio: document.getElementById("cfdi-folio").value || null,
      total: Number(document.getElementById("cfdi-total").value),
      payment_method: document.getElementById("cfdi-method").value,
    }});
    toast(cfdi.status === "aprobada"
      ? "CFDI aprobado — registrado en CxP"
      : cfdi.status === "rechazada"
        ? `CFDI rechazado: ${cfdi.rejection_reason}`
        : "CFDI en validación");
    e.target.reset();
    renderCFDIs(); renderStatement();
  } catch (err) { toast(err.message, true); }
});

/* ─── Estado de cuenta ───────────────────────────────────────────────── */

async function renderStatement() {
  const st = await api("/account-statement");
  document.getElementById("cxp-kpis").innerHTML = [
    ["&#9203;", "Saldo pendiente", money(st.total_pendiente)],
    ["&#128197;", "Programado a pago", money(st.total_programado)],
    ["&#9989;", "Pagado", money(st.total_pagado)],
    ["&#128196;", "Condiciones", st.vendor.payment_terms],
  ].map(([icon, label, value]) => `
    <div class="ov-card" style="cursor:default">
      <div class="ov-icon">${icon}</div><h3>${label}</h3>
      <div class="ov-kpi" style="font-size:18px">${value}</div>
    </div>`).join("");

  document.getElementById("cxp-list").innerHTML = st.cfdis.length
    ? `<table class="status-table">
        <thead><tr><th>UUID</th><th>OC</th><th>Total</th><th>Pagado</th><th>Vence</th><th>Estatus</th><th>REP</th></tr></thead>
        <tbody>${st.cfdis.map((c) => `
          <tr><td><code class="inline">${esc(c.uuid.slice(0, 13))}…</code></td>
          <td>${esc(c.po_number || "—")}</td><td>${money(c.total, c.currency)}</td>
          <td>${money(c.paid_amount, c.currency)}</td><td>${fdate(c.due_date)}</td>
          <td>${badge(c.status)}</td>
          <td>${c.payments.filter((p) => p.rep_uuid).map((p) =>
            `<code class="inline" title="REP ${esc(p.rep_uuid)}">${esc(p.rep_uuid.slice(0, 8))}…</code>`).join(" ") || "—"}</td></tr>`).join("")}
        </tbody></table>`
    : '<div class="empty">Sin facturas registradas.</div>';
}

/* ─── Arranque ───────────────────────────────────────────────────────── */

if (token) {
  api("/auth/me").then((v) => {
    vendorName = `${v.name} (${v.code})`;
    showApp();
  }).catch(() => showLogin());
} else {
  showLogin();
}
