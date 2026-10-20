const $ = s => document.querySelector(s);
const money = n => "S/ " + Number(n || 0).toFixed(2);
const num = n => Number(n || 0).toLocaleString("es-PE", { maximumFractionDigits: 3 });
const round3 = n => Math.round(n * 1000) / 1000;
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
let token = localStorage.getItem("su_token");
let me = null;
let cart = [], catalog = [], productsCache = [];
let META = { units: [], decimal_units: [], payments: {}, boleta_limit: 700 };

const UNIT = { und: "Unidad", kg: "Kilogramo (kg)", g: "Gramo (g)", lt: "Litro (lt)", m: "Metro (m)", paquete: "Paquete", caja: "Caja", bolsa: "Bolsa", botella: "Botella", docena: "Docena" };

const MENU = [
  { id: "dashboard", label: "Inicio", perm: "dashboard" },
  { id: "pos", label: "Ventas", perm: "sales.create" },
  { id: "products", label: "Productos e inventario", perm: "products.read" },
  { id: "cash", label: "Caja", perm: "cash.own" },
  { id: "cashreview", label: "Cierres de caja", perm: "cash.review" },
  { id: "users", label: "Usuarios y permisos", perm: "users.manage" },
  { id: "audit", label: "Auditoría", perm: "audit.read" },
  { id: "account", label: "Mi cuenta", perm: "users.manage" },
];

const has = p => me && (me.perms.includes("*") || me.perms.includes(p));

function toast(msg, err = false) {
  const t = $("#toast");
  t.textContent = msg; t.className = "toast" + (err ? " err" : "");
  setTimeout(() => t.classList.add("hidden"), 3500);
}

async function api(path, method = "GET", body) {
  const r = await fetch("/api" + path, {
    method,
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: "Bearer " + token } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    if (r.status === 401 && token) logout();
    throw new Error(typeof data.detail === "string" ? data.detail : "Error en la solicitud");
  }
  return data;
}

/* ---------- Ver / ocultar contraseña (en todos los campos de contraseña) ---------- */
const EYE = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>';
const EYE_OFF = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>';

function addEyes() {
  document.querySelectorAll('input[type="password"]:not([data-eye])').forEach(inp => {
    inp.dataset.eye = "1";
    const wrap = document.createElement("div");
    wrap.className = "pw-wrap";
    inp.parentNode.insertBefore(wrap, inp);
    wrap.appendChild(inp);
    const b = document.createElement("button");
    b.type = "button"; b.className = "pw-eye"; b.title = "Mostrar u ocultar contraseña"; b.innerHTML = EYE;
    b.onclick = () => {
      const show = inp.type === "password";
      inp.type = show ? "text" : "password";
      b.innerHTML = show ? EYE_OFF : EYE;
    };
    wrap.appendChild(b);
  });
}
new MutationObserver(addEyes).observe(document.body, { childList: true, subtree: true });

/* ---------- Sesión ---------- */
async function doLogin(e) {
  e.preventDefault();
  try {
    const r = await api("/login", "POST", { username: $("#lu").value, password: $("#lp").value });
    token = r.token; localStorage.setItem("su_token", token);
    me = r.user; start();
  } catch (err) { toast(err.message, true); }
}
function logout() { localStorage.removeItem("su_token"); token = null; me = null; location.reload(); }

async function start() {
  try { META = await api("/meta"); } catch (e) {}
  $("#login").classList.add("hidden"); $("#app").classList.remove("hidden");
  $("#who").innerHTML = `<b>${esc(me.full_name)}</b><small>${esc(me.role)}</small>`;
  const items = MENU.filter(m => has(m.perm));
  $("#menu").innerHTML = items.map(m => `<button id="m-${m.id}" onclick="go('${m.id}')">${m.label}</button>`).join("");
  go(items[0].id);
}

const VIEWS = { dashboard: vDashboard, pos: vPos, products: vProducts, cash: vCash, cashreview: vCashReview, users: vUsers, audit: vAudit, account: vAccount };

async function go(id) {
  document.querySelectorAll("nav button").forEach(b => b.classList.toggle("active", b.id === "m-" + id));
  $("#title").textContent = MENU.find(m => m.id === id).label;
  $("#view").innerHTML = '<p class="muted">Cargando…</p>';
  try { await VIEWS[id](); } catch (e) { $("#view").innerHTML = `<div class="alert">${esc(e.message)}</div>`; }
}

/* ---------- Dashboard ---------- */
async function vDashboard() {
  const d = await api("/dashboard");
  const max = Math.max(...d.days.map(x => x.total), 1);
  $("#view").innerHTML = `
    <div class="kpis">
      <div class="kpi"><span>Ventas de hoy</span><b>${money(d.sales_today)}</b></div>
      <div class="kpi"><span>Operaciones de hoy</span><b>${d.count_today}</b></div>
      <div class="kpi"><span>Productos activos</span><b>${d.products}</b></div>
      <div class="kpi ${d.low_count ? "warn" : ""}"><span>Alertas de stock</span><b>${d.low_count}</b></div>
    </div>
    <div class="card"><h3>Ventas de los últimos 7 días</h3>
      <div class="bars">${d.days.map(x => `<div class="bar"><em>${x.total ? x.total.toFixed(0) : ""}</em><div style="height:${(x.total / max) * 130}px"></div><span>${x.label}</span></div>`).join("")}</div>
    </div>
    <div class="two">
      <div class="card"><h3>Productos por reponer</h3>
        ${d.low.length ? `<div class="tablewrap"><table><tr><th>Producto</th><th>Stock</th><th>Mínimo</th></tr>
        ${d.low.map(p => `<tr><td>${esc(p.name)}</td><td><span class="badge red">${num(p.stock)} ${esc(p.unit)}</span></td><td>${num(p.min_stock)}</td></tr>`).join("")}</table></div>` : '<p class="muted">Todo en orden.</p>'}
      </div>
      <div class="card"><h3>Ventas recientes</h3>
        ${d.recent.length ? `<div class="tablewrap"><table><tr><th>Comprobante</th><th>Fecha</th><th>Pago</th><th>Total</th></tr>
        ${d.recent.map(s => `<tr><td>${esc(s.doc)}</td><td>${s.date}</td><td>${esc(s.pay)}</td><td>${money(s.total)}</td></tr>`).join("")}</table></div>` : '<p class="muted">Aún no hay ventas.</p>'}
      </div>
    </div>`;
}

/* ---------- Productos ---------- */
async function vProducts() {
  const list = await api("/products");
  productsCache = list;
  const showCost = list.length && list[0].cost !== undefined;
  const canW = has("products.write"), canA = has("stock.adjust");
  const unitOpts = META.units.map(u => `<option value="${u}">${esc(UNIT[u] || u)}</option>`).join("");
  $("#view").innerHTML = `
    ${canW ? `<div class="card"><h3>Nuevo producto</h3>
      <form class="grid-form" onsubmit="addProduct(event)">
        <div><label>Código de barras (opcional)</label><input name="barcode" inputmode="numeric" autocomplete="off" placeholder="Escanéalo o escríbelo"></div>
        <div><label>Código interno (opcional)</label><input name="code" autocomplete="off" placeholder="Se genera solo"></div>
        <div><label>Nombre</label><input name="name" required></div>
        <div><label>Categoría</label><input name="category" value="General"></div>
        <div><label>Unidad de medida</label><select name="unit" onchange="unitChanged(this)">${unitOpts}</select></div>
        <div><label>Costo por unidad (S/)</label><input name="cost" type="number" step="0.01" min="0" value="0"></div>
        <div><label>Precio por unidad (S/)</label><input name="price" type="number" step="0.01" min="0" required></div>
        <div><label>Stock inicial</label><input name="stock" type="number" step="1" min="0" value="0"></div>
        <div><label>Stock mínimo</label><input name="min_stock" type="number" step="1" min="0" value="5"></div>
        <button class="btn" type="submit">Guardar</button>
      </form>
      <p class="muted hint">Si el producto no tiene código de barras, se identifica por su unidad de medida (kg, paquete, etc.). El precio y el stock se cuentan por esa unidad. Para venderlo también por docena, jaba o saco, usa el botón <b>+ Presentación</b> de la tabla.</p>
    </div>` : ""}
    <div class="card">
      <div class="row"><h3>Inventario</h3><input placeholder="Buscar por nombre o código…" oninput="filterRows(this.value)"></div>
      <div class="tablewrap"><table id="ptable"><thead><tr><th>Código</th><th>Cód. barras</th><th>Producto</th><th>Unidad</th>${showCost ? "<th>Costo</th>" : ""}<th>Precio</th><th>Stock</th><th>Presentaciones</th>${canW || canA ? "<th></th>" : ""}</tr></thead>
      <tbody>${list.map(p => `<tr><td>${esc(p.code)}</td><td>${esc(p.barcode || "—")}</td><td>${esc(p.name)}</td><td>${esc(UNIT[p.unit] || p.unit)}</td>${showCost ? `<td>${money(p.cost)}</td>` : ""}<td>${money(p.price)}</td>
        <td><span class="badge ${p.stock <= p.min_stock ? "red" : ""}">${num(p.stock)} ${esc(p.unit)}</span></td>
        <td>${p.presentations.map(x => `<span class="badge soft">${esc(x.name)} · ${num(x.factor)} ${esc(p.unit)} · ${money(x.price)}</span>`).join(" ") || "—"}</td>
        ${canW || canA ? `<td class="actions">${canA ? `<button class="btn ghost sm" onclick="adjust(${p.id})">Ajustar</button>` : ""}${canW ? `<button class="btn ghost sm" onclick="addPres(${p.id})">+ Presentación</button>` : ""}</td>` : ""}</tr>`).join("")}</tbody></table></div>
    </div>`;
}
function unitChanged(sel) {
  const dec = META.decimal_units.includes(sel.value);
  const f = sel.closest("form");
  ["stock", "min_stock"].forEach(n => f.elements[n].step = dec ? "0.001" : "1");
}
function filterRows(q) {
  q = q.toLowerCase();
  document.querySelectorAll("#ptable tbody tr").forEach(r => r.style.display = r.textContent.toLowerCase().includes(q) ? "" : "none");
}
async function addProduct(e) {
  e.preventDefault();
  const f = Object.fromEntries(new FormData(e.target));
  ["cost", "price", "stock", "min_stock"].forEach(k => f[k] = parseFloat(f[k] || 0));
  try { await api("/products", "POST", f); toast("Producto guardado"); vProducts(); } catch (er) { toast(er.message, true); }
}
async function adjust(id) {
  const raw = prompt("Cantidad a sumar (+) o restar (−). Ej: 10, -3 o 2.5");
  if (raw === null) return;
  const d = parseFloat(raw.replace(",", "."));
  if (isNaN(d)) return toast("Cantidad no válida", true);
  const r = prompt("Motivo del ajuste (obligatorio):");
  if (!r || !r.trim()) return toast("El motivo es obligatorio", true);
  try { await api(`/products/${id}/adjust`, "POST", { delta: d, reason: r }); toast("Stock actualizado"); vProducts(); }
  catch (e) { toast(e.message, true); }
}
async function addPres(id) {
  const p = productsCache.find(x => x.id === id);
  const name = prompt(`Nombre de la presentación para "${p.name}" (ej: Docena, Jaba, Caja, Saco):`);
  if (!name || !name.trim()) return;
  const factor = parseFloat((prompt(`¿Cuántas ${p.unit} trae "${name}"? (ej: 12)`) || "").replace(",", "."));
  if (!(factor > 0)) return toast("Cantidad no válida", true);
  const price = parseFloat((prompt(`Precio de venta de "${name}" (S/):`) || "").replace(",", "."));
  if (isNaN(price) || price < 0) return toast("Precio no válido", true);
  const barcode = prompt("Código de barras de la presentación (opcional, deja vacío si no tiene):") || "";
  try { await api(`/products/${id}/presentations`, "POST", { name, factor, price, barcode }); toast("Presentación guardada"); vProducts(); }
  catch (e) { toast(e.message, true); }
}

/* ---------- Punto de venta ---------- */
async function vPos() {
  catalog = await api("/products"); cart = [];
  const payOpts = Object.entries(META.payments).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("");
  $("#view").innerHTML = `<div class="pos">
    <div class="card"><h3>Productos</h3>
      <input id="ps" placeholder="Escanea el código de barras o busca por nombre…" oninput="drawCatalog()" onkeydown="searchKey(event)" autocomplete="off">
      <div id="cat" class="catalog"></div></div>
    <div class="card"><h3>Venta actual</h3><div id="cart"></div>
      <label>Forma de pago</label><select id="pay" onchange="payChanged()">${payOpts}</select>
      <div id="refbox" class="hidden"><label>N.º de operación (opcional)</label><input id="pref" autocomplete="off"></div>
      <label>Comprobante</label><select id="doc" onchange="drawCustomer()"><option value="boleta">Boleta</option><option value="factura">Factura</option><option value="nota_interna">Nota de venta interna</option></select>
      <div id="cust"></div>
      <div class="total"><span>Total</span><b id="tot">S/ 0.00</b></div>
      <button class="btn big" onclick="confirmSale()">Confirmar venta</button></div></div>`;
  drawCatalog(); drawCart(); drawCustomer(); $("#ps").focus();
}
function payChanged() { $("#refbox").classList.toggle("hidden", $("#pay").value === "efectivo"); }
function drawCustomer() {
  const t = $("#doc").value;
  const digits = `oninput="this.value=this.value.replace(/\\D/g,'')"`;
  $("#cust").innerHTML = t === "factura"
    ? `<div class="custbox"><label>RUC del cliente *</label><input id="cdoc" inputmode="numeric" maxlength="11" placeholder="11 dígitos" autocomplete="off" ${digits}>
       <label>Razón social *</label><input id="cname" autocomplete="off">
       <label>Dirección (opcional)</label><input id="caddr" autocomplete="off">
       <p class="muted hint">La factura exige el RUC y la razón social del cliente.</p></div>`
    : t === "boleta"
    ? `<div class="custbox"><label>DNI del cliente (opcional)</label><input id="cdoc" inputmode="numeric" maxlength="8" placeholder="8 dígitos" autocomplete="off" ${digits}>
       <label>Nombre del cliente (opcional)</label><input id="cname" autocomplete="off">
       <p class="muted hint">Si el total supera S/ ${META.boleta_limit}, el DNI y el nombre son obligatorios.</p></div>`
    : "";
}
function matches(p, q) {
  if (!q) return true;
  const txt = p.name + " " + p.code + " " + (p.barcode || "") + p.presentations.map(x => " " + (x.barcode || "")).join("");
  return txt.toLowerCase().includes(q);
}
function drawCatalog() {
  const q = ($("#ps").value || "").toLowerCase();
  $("#cat").innerHTML = catalog.filter(p => matches(p, q)).map(p => {
    const pres = p.presentations.map(x => `<button class="pbtn" ${p.stock < x.factor ? "disabled" : ""} onclick="addToCart(${p.id},${x.id})">${esc(x.name)} · ${money(x.price)}</button>`).join("");
    return `<div class="pcard ${p.stock <= 0 ? "out" : ""}">
      <button class="pmain" ${p.stock <= 0 ? "disabled" : ""} onclick="addToCart(${p.id})"><b>${esc(p.name)}</b><small>${esc(p.barcode || p.code)} · stock ${num(p.stock)} ${esc(p.unit)}</small><span class="pr">${money(p.price)} / ${esc(p.unit)}</span></button>
      ${pres ? `<div class="pres">${pres}</div>` : ""}</div>`;
  }).join("");
}
function searchKey(e) {
  if (e.key !== "Enter") return;
  e.preventDefault();
  const q = e.target.value.trim();
  if (!q) return;
  const done = (pid, presId) => { addToCart(pid, presId); e.target.value = ""; drawCatalog(); };
  for (const p of catalog) {
    if (p.barcode === q || p.code.toLowerCase() === q.toLowerCase()) return done(p.id);
    const x = p.presentations.find(y => y.barcode === q);
    if (x) return done(p.id, x.id);
  }
  const found = catalog.filter(p => matches(p, q.toLowerCase()));
  if (found.length === 1) done(found[0].id);
  else toast(found.length ? "Hay varios resultados, elige uno de la lista" : "No se encontró el producto", true);
}
function unitsUsed(pid) { return cart.filter(l => l.pid === pid).reduce((s, l) => s + l.qty * l.factor, 0); }
function addToCart(pid, presId) {
  const p = catalog.find(x => x.id === pid);
  const x = presId ? p.presentations.find(y => y.id === presId) : null;
  const factor = x ? x.factor : 1;
  if (unitsUsed(pid) + factor > p.stock + 1e-9) return toast(`No hay más stock de ${p.name}`, true);
  const key = pid + "-" + (presId || 0);
  const l = cart.find(c => c.key === key);
  if (l) l.qty = round3(l.qty + 1);
  else cart.push({ key, pid, presId: presId || null, name: x ? `${p.name} (${x.name})` : p.name, unit: x ? x.name : p.unit, price: x ? x.price : p.price, qty: 1, factor, decimal: !x && p.decimal });
  drawCart();
}
function chQty(key, d) {
  const l = cart.find(c => c.key === key);
  const p = catalog.find(x => x.id === l.pid);
  if (d > 0 && unitsUsed(l.pid) + l.factor > p.stock + 1e-9) return toast("No hay más stock", true);
  l.qty += d;
  if (l.qty <= 0) cart = cart.filter(c => c.key !== key);
  drawCart();
}
function setQty(key, v) {
  const l = cart.find(c => c.key === key);
  const p = catalog.find(x => x.id === l.pid);
  let n = round3(parseFloat(String(v).replace(",", ".")));
  if (!(n > 0)) { cart = cart.filter(c => c.key !== key); return drawCart(); }
  const others = unitsUsed(l.pid) - l.qty * l.factor;
  if (others + n * l.factor > p.stock + 1e-9) {
    toast(`Stock máximo: ${num(p.stock)} ${p.unit}`, true);
    n = round3((p.stock - others) / l.factor);
  }
  if (n <= 0) cart = cart.filter(c => c.key !== key); else l.qty = n;
  drawCart();
}
function drawCart() {
  $("#cart").innerHTML = cart.length ? cart.map(l => `<div class="cartline"><div><b>${esc(l.name)}</b><br><small class="muted">${money(l.price)} / ${esc(l.unit)}</small></div>
    <div class="qty">${l.decimal
      ? `<input class="qin" type="number" step="0.001" min="0" value="${l.qty}" onchange="setQty('${l.key}', this.value)"> <small>${esc(l.unit)}</small>`
      : `<button onclick="chQty('${l.key}',-1)">−</button>${num(l.qty)}<button onclick="chQty('${l.key}',1)">+</button>`}</div>
    <b>${money(l.price * l.qty)}</b></div>`).join("")
    : '<p class="muted">Agrega productos desde la izquierda.</p>';
  $("#tot").textContent = money(cart.reduce((s, l) => s + l.price * l.qty, 0));
}
async function confirmSale() {
  if (!cart.length) return toast("El carrito está vacío", true);
  const val = id => ($(id) ? $(id).value.trim() : "");
  const body = {
    items: cart.map(l => ({ product_id: l.pid, qty: l.qty, presentation_id: l.presId })),
    payment_method: $("#pay").value, payment_ref: val("#pref"),
    doc_type: $("#doc").value, customer_doc: val("#cdoc"), customer_name: val("#cname"), customer_address: val("#caddr"),
  };
  try { const r = await api("/sales", "POST", body); showReceipt(r); }
  catch (e) { toast(e.message, true); }
}

/* ---------- Comprobante ---------- */
function showReceipt(r) {
  const banner = r.doc_type === "nota_interna" ? "Documento interno: no es comprobante tributario" : "DOCUMENTO DE PRUEBA · NO VÁLIDO ANTE SUNAT";
  const cust = (r.customer_name || r.customer_doc)
    ? `<p><b>Cliente:</b> ${esc(r.customer_name || "—")}<br>${r.customer_doc ? `<b>${esc(r.customer_doc_type)}:</b> ${esc(r.customer_doc)}<br>` : ""}${r.customer_address ? esc(r.customer_address) : ""}</p>` : "";
  const taxes = r.doc_type === "nota_interna" ? "" : `
    <div class="r-tot"><span>Op. gravada</span><span>${money(r.base)}</span></div>
    <div class="r-tot"><span>IGV (18%)</span><span>${money(r.igv)}</span></div>`;
  const div = document.createElement("div");
  div.className = "overlay"; div.id = "rcpt";
  div.innerHTML = `<div class="receipt" id="receipt">
    <div class="r-head"><h2>Stock Up</h2><div>${esc(r.doc_name)}</div><b>${esc(r.number)}</b></div>
    <p><b>Fecha:</b> ${esc(r.date)}<br><b>Atendió:</b> ${esc(r.cashier)}</p>
    ${cust}
    <table><tr><th>Descripción</th><th>Cant.</th><th>P. unit.</th><th>Importe</th></tr>
    ${r.items.map(i => `<tr><td>${esc(i.description)}</td><td>${num(i.qty)}</td><td>${money(i.price)}</td><td>${money(i.subtotal)}</td></tr>`).join("")}</table>
    <div style="margin-top:8px">${taxes}<div class="r-tot big"><span>TOTAL</span><span>${money(r.total)}</span></div></div>
    <p><b>Pago:</b> ${esc(r.payment)}${r.payment_ref ? ` · Operación ${esc(r.payment_ref)}` : ""}</p>
    <div class="r-demo">${banner}</div>
    <div class="r-actions noprint"><button class="btn ghost" onclick="window.print()">Imprimir</button><button class="btn" onclick="closeReceipt()">Nueva venta</button></div>
  </div>`;
  document.body.appendChild(div);
}
function closeReceipt() { const d = $("#rcpt"); if (d) d.remove(); vPos(); }

/* ---------- Caja ---------- */
function methodsTable(list, withTotal) {
  if (!list.length) return '<p class="muted">Aún no hay ventas en este turno.</p>';
  const total = list.reduce((s, m) => s + m.total, 0);
  return `<table><tr><th>Forma de pago</th><th>Ventas</th><th>Total</th></tr>
    ${list.map(m => `<tr><td>${esc(m.label)}</td><td>${m.count}</td><td>${money(m.total)}</td></tr>`).join("")}
    ${withTotal ? `<tr><td><b>Total vendido</b></td><td></td><td><b>${money(total)}</b></td></tr>` : ""}</table>`;
}
async function vCash() {
  const { session } = await api("/cash/current");
  if (!session) {
    $("#view").innerHTML = `<div class="card" style="max-width:520px"><h3>Abrir caja</h3>
      <label>Saldo inicial en efectivo (S/)</label><input id="op" type="number" step="0.01" min="0" value="0">
      <button class="btn big" onclick="openCash()">Abrir caja</button></div>`;
    return;
  }
  $("#view").innerHTML = `<div class="two"><div class="card"><h3>Cierre de caja a ciegas</h3>
      <p class="muted">Abierta desde ${session.opened_at} · Saldo inicial ${money(session.opening_amount)}</p><br>
      <label>Efectivo contado físicamente (S/)</label><input id="cnt" type="number" step="0.01" min="0">
      <label>Observación (opcional)</label><input id="nt">
      <button class="btn big" onclick="closeCash()">Cerrar caja</button>
      <p class="muted hint">El arqueo cuenta solo el efectivo. El monto esperado se mostrará recién después de guardar tu conteo.</p></div>
    <div class="card"><h3>Cobros digitales de este turno</h3>
      ${session.digital.length ? methodsTable(session.digital, false) : '<p class="muted">Aún no hay cobros por Yape, Plin, tarjeta ni transferencia.</p>'}</div></div>`;
}
async function openCash() {
  try { await api("/cash/open", "POST", { opening_amount: parseFloat($("#op").value || 0) }); toast("Caja abierta"); vCash(); } catch (e) { toast(e.message, true); }
}
async function closeCash() {
  const v = parseFloat($("#cnt").value);
  if (isNaN(v)) return toast("Ingresa el efectivo contado", true);
  try {
        const r = await api("/cash/close", "POST", { counted_amount: v, note: $("#nt").value });
            $("#view").innerHTML = `<div class="two"><div class="card"><h3>Caja cerrada · Efectivo</h3><table>
      <tr><td>Saldo inicial</td><td>${money(r.opening)}</td></tr>
      <tr><td>Contado</td><td>${money(r.counted)}</td></tr>
      <tr><td>Esperado</td><td>${money(r.expected)}</td></tr>
      <tr><td><b>Diferencia</b></td><td><span class="badge ${r.difference ? "red" : ""}">${money(r.difference)}</span></td></tr></table></div>
      <div class="card"><h3>Ventas del turno por forma de pago</h3>${methodsTable(r.methods, true)}
      <p class="muted hint">Solo el efectivo entra en el arqueo. Los cobros digitales se concilian con tu banco o billetera.</p></div></div>`;
  } catch (e) { toast(e.message, true); }
}
async function vCashReview() {
  const rows = await api("/cash/sessions");
  $("#view").innerHTML = `<div class="card"><h3>Historial de cierres</h3><div class="tablewrap"><table>
    <tr><th>N.º</th><th>Cajero</th><th>Apertura</th><th>Cierre</th><th>Contado</th><th>Esperado</th><th>Diferencia</th><th>Por forma de pago</th><th>Estado</th></tr>
    ${rows.map(c => `<tr><td>${c.id}</td><td>${esc(c.user)}</td><td>${c.opened}</td><td>${c.closed || "—"}</td>
    <td>${c.counted == null ? "—" : money(c.counted)}</td><td>${c.expected == null ? "—" : money(c.expected)}</td>
    <td>${c.difference == null ? "—" : `<span class="badge ${c.difference ? "red" : ""}">${money(c.difference)}</span>`}</td>
    <td>${Object.entries(c.methods).map(([k, v]) => `<span class="badge soft">${esc(k)}: ${money(v)}</span>`).join(" ") || "—"}</td><td>${c.status}</td></tr>`).join("")}</table></div></div>`;
}

/* ---------- Usuarios ---------- */
async function vUsers() {
  const list = await api("/users");
  $("#view").innerHTML = `<div class="card"><h3>Nuevo usuario</h3>
    <form class="grid-form" onsubmit="addUser(event)">
      <div><label>Usuario</label><input name="username" required></div>
      <div><label>Nombre completo</label><input name="full_name" required></div>
      <div><label>Contraseña (mín. 8)</label><input name="password" type="password" minlength="8" required></div>
      <div><label>Rol</label><select name="role"><option value="cajero">Cajero</option><option value="almacen">Almacén</option><option value="supervisor">Supervisor</option><option value="contador">Contador</option><option value="admin">Administrador</option></select></div>
      <button class="btn" type="submit">Crear</button></form></div>
    <div class="card"><h3>Trabajadores</h3><div class="tablewrap"><table><tr><th>Usuario</th><th>Nombre</th><th>Rol</th><th>Estado</th><th></th></tr>
    ${list.map(u => `<tr><td>${esc(u.username)}</td><td>${esc(u.full_name)}</td><td><span class="badge">${esc(u.role)}</span></td><td>${u.active ? "Activo" : "Inactivo"}</td>
    <td><button class="btn ghost sm" onclick="resetPwd(${u.id}, '${esc(u.username)}')">Restablecer clave</button></td></tr>`).join("")}</table></div></div>`;
}
async function addUser(e) {
  e.preventDefault();
  try { await api("/users", "POST", Object.fromEntries(new FormData(e.target))); toast("Usuario creado"); vUsers(); } catch (er) { toast(er.message, true); }
}
async function resetPwd(id, name) {
  const p = prompt(`Nueva contraseña para ${name} (mínimo 8 caracteres):`);
  if (p === null) return;
  if (p.length < 8) return toast("Mínimo 8 caracteres", true);
  try { await api(`/users/${id}/reset-password`, "POST", { new_password: p }); toast("Contraseña restablecida"); }
  catch (e) { toast(e.message, true); }
}

/* ---------- Auditoría ---------- */
async function vAudit() {
  const rows = await api("/audit");
  $("#view").innerHTML = `<div class="card"><h3>Registro de actividades</h3><div class="tablewrap"><table>
    <tr><th>Fecha</th><th>Usuario</th><th>Acción</th><th>Detalle</th></tr>
    ${rows.map(a => `<tr><td>${a.date}</td><td>${esc(a.user)}</td><td><span class="badge ${a.action.includes("FALLIDO") ? "red" : ""}">${esc(a.action)}</span></td><td>${esc(a.detail)}</td></tr>`).join("")}</table></div></div>`;
}

/* ---------- Mi cuenta ---------- */
async function vAccount() {
  $("#view").innerHTML = `<div class="card" style="max-width:520px"><h3>Cambiar mi contraseña</h3>
    <form onsubmit="changePwd(event)" style="display:flex;flex-direction:column;gap:10px">
      <label>Contraseña actual</label><input name="current" type="password" autocomplete="current-password" required>
      <label>Nueva contraseña (mín. 8 caracteres)</label><input name="new1" type="password" minlength="8" autocomplete="new-password" required>
      <label>Repite la nueva contraseña</label><input name="new2" type="password" minlength="8" autocomplete="new-password" required>
      <button class="btn big" type="submit">Guardar nueva contraseña</button>
    </form></div>`;
}
async function changePwd(e) {
  e.preventDefault();
  const f = Object.fromEntries(new FormData(e.target));
  if (f.new1 !== f.new2) return toast("Las contraseñas nuevas no coinciden", true);
  try {
    await api("/me/password", "POST", { current_password: f.current, new_password: f.new1 });
    toast("Contraseña cambiada correctamente");
    e.target.reset();
  } catch (er) { toast(er.message, true); }
}

/* ---------- Arranque ---------- */
(async function init() {
  addEyes();
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
  if (token) { try { me = await api("/me"); return start(); } catch (e) {} }
  $("#login").classList.remove("hidden");
})();