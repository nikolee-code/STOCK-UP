/* Funciones comunes de Stock Up. Las pantallas se cargan desde index.html. */
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const money = n => "S/ " + Number(n || 0).toFixed(2);
const num = n => Number(n || 0).toLocaleString("es-PE", { maximumFractionDigits: 3 });
const round3 = n => Math.round((Number(n) + Number.EPSILON) * 1000) / 1000;
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[c]));
const sum = (a, fn = x => x) => a.reduce((s, x) => s + Number(fn(x) || 0), 0);
const UNIT = { und:"unidad", kg:"kg", g:"g", lt:"litro", m:"metro", paquete:"paquete", caja:"caja", bolsa:"bolsa", botella:"botella", docena:"docena" };
const ROLE = { admin:"Administrador", almacen:"Almacén", cajero:"Cajero", supervisor:"Supervisor", contador:"Contador" };
function parseDateValue(value) {
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value;
  if (typeof value !== "string" || !value.trim()) return null;
  const text=value.trim(),local=text.match(/^(\d{2})\/(\d{2})\/(\d{4})(?:\s+(\d{2}):(\d{2})(?::(\d{2}))?)?$/);
  if(local){const [,day,month,year,hour="00",minute="00",second="00"]=local;const y=Number(year),m=Number(month),d=Number(day),hh=Number(hour),mm=Number(minute),ss=Number(second);if(m<1||m>12||d<1||d>31||hh>23||mm>59||ss>59)return null;const instant=new Date(Date.UTC(y,m-1,d,hh,mm,ss)+5*3600000);const check=new Date(Date.UTC(y,m-1,d));if(check.getUTCFullYear()!==y||check.getUTCMonth()!==m-1||check.getUTCDate()!==d)return null;return instant;}
  const isoDay=text.match(/^(\d{4})-(\d{2})-(\d{2})$/);if(isoDay)return parseDateValue(`${isoDay[3]}/${isoDay[2]}/${isoDay[1]} 12:00`);
  const parsed=new Date(text);return Number.isNaN(parsed.getTime())?null:parsed;
}
function limaDate(value,options=null) {const date=parseDateValue(value);if(!date)return "—";try{return new Intl.DateTimeFormat("es-PE",{timeZone:"America/Lima",...(options||{dateStyle:"short",timeStyle:"short"})}).format(date);}catch{return "—";}}
const limaDateParts = date => Object.fromEntries(new Intl.DateTimeFormat("en-CA",{timeZone:"America/Lima",year:"numeric",month:"2-digit",day:"2-digit"}).formatToParts(date).map(x=>[x.type,x.value]));
const todayStr = () => {const p=limaDateParts(new Date());return `${p.year}-${p.month}-${p.day}`;};
const debounce = (fn, ms=250) => { let t; return (...a) => { clearTimeout(t); t=setTimeout(() => fn(...a), ms); }; };
const qs = o => Object.entries(o).filter(([,v]) => v !== "" && v != null).map(([k,v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join("&");
let token = localStorage.getItem("su_token"), me = null;
let META = { units:[], decimal_units:["kg","g","lt","m"], payments:{}, expense_cats:[], motives:[], boleta_limit:700, lookup_enabled:false, electronic_invoicing_enabled:false };
const VIEWS = {};
const API_SERVER = (document.querySelector('meta[name="stockup-api-url"]')?.content || "").trim().replace(/\/+$/,"");
const API_SERVER_INVALID = !!API_SERVER && !/^https:\/\//i.test(API_SERVER);
const STATIC_PAGES = location.hostname.endsWith(".github.io") && (!API_SERVER || API_SERVER_INVALID);
const has = p => !!me && (me.perms?.includes("*") || me.perms?.includes(p));
const hasAny = (...ps) => ps.some(has);

function toast(message, error=false) {
  const el=$("#toast"); if(!el) return;
  el.textContent=message; el.className="toast"+(error?" err":"");
  clearTimeout(toast.timer); toast.timer=setTimeout(()=>el.classList.add("hidden"),4000);
}
async function api(path, method="GET", body) {
  if(STATIC_PAGES) throw new Error(API_SERVER_INVALID ? "La dirección del servidor debe comenzar con https://." : "GitHub Pages publica la interfaz, pero falta conectar el servidor de Stock Up.");
  const response=await fetch((API_SERVER?API_SERVER+"/api":"/api")+path, { method, headers:{"Content-Type":"application/json", ...(token?{Authorization:"Bearer "+token}:{})}, body:body===undefined?undefined:JSON.stringify(body) });
  const data=await response.json().catch(()=>({}));
  if(!response.ok){ if(response.status===401 && token) logout(); throw new Error(typeof data.detail==="string"?data.detail:`Error ${response.status} en la solicitud`); }
  return data;
}
function fld(label, inner, hint="") { return `<label class="fld">${esc(label)}${inner}${hint?`<small class="muted">${esc(hint)}</small>`:""}</label>`; }
function opts(items, selected="") { return items.map(([v,t])=>`<option value="${esc(v)}" ${String(v)===String(selected)?"selected":""}>${esc(t)}</option>`).join(""); }
function badge(text, kind="soft") { return `<span class="badge ${esc(kind)}">${esc(text)}</span>`; }
function kpi(label,value,kind="",icon="",sub="") { return `<div class="kpi ${esc(kind)}"><span>${icon?esc(icon)+" · ":""}${esc(label)}</span><b>${esc(value)}</b>${sub?`<small>${esc(sub)}</small>`:""}</div>`; }
function stockState(p) { return Number(p.stock)<=0?"bad":Number(p.stock)<=Number(p.min_stock)?"warn":"ok"; }
function stockBadge(p) { const s=stockState(p); return badge(`${num(p.stock)} ${UNIT[p.unit]||p.unit}`,s==="bad"?"bad":s==="warn"?"warn":"ok"); }
function stockMeter(stock,min) { const pct=min>0?Math.min(100,Math.max(0,stock/min*100)):100; const kind=stock<=0?"bad":stock<=min?"warn":"ok"; return `<div class="meter ${kind}"><i style="width:${pct}%"></i></div>`; }
function stockEq(stock,unit) { return `${num(stock)} ${UNIT[unit]||unit}`; }
function chipsHtml(values, current="") { return `<div class="chips">${values.map(v=>`<button type="button" class="chip ${v===current?"on":""}" data-value="${esc(v)}">${esc(v||"Todas")}</button>`).join("")}</div>`; }
function bindChips(root, fn) { $$(root+" .chip").forEach(b=>b.onclick=()=>fn(b.dataset.value)); }
function rangeHtml(id="range",extra="",days=7) { const from=new Date(Date.now()-((days-1)*86400000)),p=limaDateParts(from),f=`${p.year}-${p.month}-${p.day}`; return `<div class="filters"><label>Desde<input id="${id}-from" type="date" value="${f}"></label><label>Hasta<input id="${id}-to" type="date" value="${todayStr()}"></label>${extra}</div>`; }
function bindRange(id,fn) { [`${id}-from`,`${id}-to`].forEach(x=>$("#"+x)?.addEventListener("change",fn)); }
function rangeVals(id) { return {date_from:$("#"+id+"-from")?.value||"",date_to:$("#"+id+"-to")?.value||""}; }

function modal({title,html,submit="Guardar",cancel="Cancelar",onSubmit,onClose,wide=false,danger=false,noButtons=false}={}) {
  closeModal(); const root=$("#modal-root");
  root.innerHTML=`<div class="overlay" role="presentation"><section class="modal ${wide?"wide":""}" role="dialog" aria-modal="true" aria-labelledby="modal-title"><header class="row-between"><h2 id="modal-title">${esc(title||"")}</h2><button type="button" class="btn ghost sm" data-close aria-label="Cerrar">×</button></header><div class="modal-body">${html||""}</div>${noButtons?"":`<footer class="actions"><button type="button" class="btn ghost" data-cancel>${esc(cancel)}</button><button type="button" class="btn ${danger?"bad":""}" data-submit>${esc(submit)}</button></footer>`}</section></div>`;
  const overlay=root.firstElementChild; const close=()=>{root.innerHTML="";document.removeEventListener("keydown",key);onClose?.();};
  const key=e=>{if(e.key==="Escape")close();}; document.addEventListener("keydown",key);
  overlay.addEventListener("click",e=>{if(e.target===overlay||e.target.closest("[data-close],[data-cancel]"))close();});
  overlay.querySelector("[data-submit]")?.addEventListener("click",async e=>{const b=e.currentTarget;b.disabled=true;try{const keep=await onSubmit?.(overlay.querySelector(".modal-body"));if(keep!==false)close();}catch(err){toast(err.message,true);}finally{b.disabled=false;}});
  return {close,element:overlay};
}
function closeModal(){const r=$("#modal-root");if(r)r.innerHTML="";}
function confirmBox(message,yes=()=>{}) { modal({title:"Confirmar",html:`<p>${esc(message)}</p>`,submit:"Confirmar",danger:true,onSubmit:yes}); }

async function scanBarcode({onScan,title="Escanear código de barras"}={}) {
  const html=`<div class="qr-reader"><video autoplay playsinline></video><p class="muted">Centra el código frente a la cámara. También puedes escribirlo manualmente.</p><div class="row-gap"><input class="manual-code" placeholder="Código de barras" inputmode="numeric"><button class="btn manual-submit">Usar código</button></div><p class="scan-status muted" role="status"></p></div>`;
  let stream=null, frame=0, detector=null;
  const stop=()=>{cancelAnimationFrame(frame);stream?.getTracks().forEach(t=>t.stop());stream=null;};
  const m=modal({title,html,noButtons:true,onClose:stop}); const video=m.element.querySelector("video"), status=m.element.querySelector(".scan-status");
  const close=m.close;
  const accept=value=>{const v=String(value||"").trim();if(!v)return;stop();close();onScan?.(v);};
  m.element.querySelector(".manual-submit").onclick=()=>accept(m.element.querySelector(".manual-code").value);
  m.element.querySelector(".manual-code").onkeydown=e=>{if(e.key==="Enter"){e.preventDefault();accept(e.target.value);}};
  try {
    if(!("BarcodeDetector" in window)) throw new Error("Este navegador no permite leer códigos con la cámara. Escribe el código manualmente.");
    detector=new BarcodeDetector({formats:["ean_13","ean_8","upc_a","upc_e","code_128","code_39","itf","qr_code"]});
    stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:"environment"}},audio:false}); video.srcObject=stream;
    const scan=async()=>{if(!video.srcObject)return;try{const hits=await detector.detect(video);if(hits.length)return accept(hits[0].rawValue);}catch{}frame=requestAnimationFrame(scan);};
    video.onloadedmetadata=scan;
  } catch(e) { status.textContent=e.message||"No se pudo abrir la cámara."; }
}

function ticketHtml(r) {
  const customer=(r.customer_name||r.customer_doc)?`<p><b>Cliente:</b> ${esc(r.customer_name||"—")} ${r.customer_doc?`· ${esc(r.customer_doc_type||"")} ${esc(r.customer_doc)}`:""}<br>${esc(r.customer_address||"")}</p>`:"";
  return `<article class="receipt"><header class="r-head"><img class="receipt-logo" src="./brand.png" alt="Stock Up"><h2>Stock Up</h2><b>${esc(r.doc_name||r.doc_type||"Comprobante")}</b><br>${esc(r.number||"")}</header><p><b>Fecha:</b> ${esc(r.date||"")}<br><b>Atendió:</b> ${esc(r.cashier||"")}</p>${customer}<table><thead><tr><th>Descripción</th><th>Cant.</th><th>Precio</th><th>Importe</th></tr></thead><tbody>${(r.items||[]).map(i=>`<tr><td>${esc(i.description)}</td><td>${num(i.qty)}</td><td>${money(i.price)}</td><td>${money(i.subtotal??i.qty*i.price)}</td></tr>`).join("")}</tbody></table>${r.doc_type==="nota_interna"?"":`<div class="r-tot"><span>Op. gravada</span><span>${money(r.base)}</span></div><div class="r-tot"><span>IGV (18%)</span><span>${money(r.igv)}</span></div>`}<div class="r-tot"><span>Subtotal</span><span>${money(r.subtotal)}</span></div>${Number(r.discount)?`<div class="r-tot"><span>Descuento ${esc(r.promo_name||"")}</span><span>− ${money(r.discount)}</span></div>`:""}<div class="r-tot big"><span>TOTAL</span><span>${money(r.total)}</span></div><p><b>Pago:</b> ${esc(r.payment||"")}${r.payment_ref?` · ${esc(r.payment_ref)}`:""}</p><div class="r-demo">${r.doc_type==="nota_interna"?"DOCUMENTO INTERNO":"DOCUMENTO DE PRUEBA · NO VÁLIDO ANTE SUNAT"}</div></article>`;
}
function printTickets(rows) { const w=window.open("","_blank","width=480,height=720"); if(!w)return toast("Permite las ventanas emergentes para imprimir",true);w.document.write(`<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Comprobantes Stock Up</title><style>body{font:12px Arial;color:#111}.receipt{width:76mm;margin:0 auto 10mm;page-break-after:always}.receipt:last-child{page-break-after:auto}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:3px;border-bottom:1px solid #ccc}.r-head{text-align:center;border-bottom:1px dashed #777;padding-bottom:8px;margin-bottom:8px}.r-tot{display:flex;justify-content:space-between}.big{font-size:16px;font-weight:bold}.r-demo{text-align:center;border:1px solid #777;padding:4px;margin-top:8px}</style></head><body>${rows.map(ticketHtml).join("")}<script>onload=()=>print()<\/script></body></html>`);w.document.close(); }
async function printSales(ids) { const w=window.open("","_blank","width=480,height=720");if(!w)return toast("Permite las ventanas emergentes para imprimir",true);w.document.write("Cargando comprobantes…");try{const rows=await Promise.all(ids.map(id=>api(`/sales/${id}`)));w.document.open();w.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>Comprobantes Stock Up</title><style>body{font:12px Arial}.receipt{width:76mm;margin:0 auto 10mm;page-break-after:always}.receipt:last-child{page-break-after:auto}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:3px;border-bottom:1px solid #ccc}.r-head{text-align:center}.r-tot{display:flex;justify-content:space-between}.big{font-weight:bold}</style></head><body>${rows.map(ticketHtml).join("")}<script>onload=()=>print()<\/script></body></html>`);w.document.close();}catch(e){w.close();toast(e.message,true);} }
function showReceipt(r,label="",after) { modal({title:label||"Venta registrada",html:ticketHtml(r),noButtons:true});const m=$("#modal-root");const foot=document.createElement("div");foot.className="r-actions noprint";foot.innerHTML='<button class="btn ghost" type="button">Imprimir</button><button class="btn" type="button">Nueva venta</button>';m.querySelector(".modal-body").append(foot);foot.children[0].onclick=()=>printTickets([r]);foot.children[1].onclick=()=>{closeModal();after?.();}; }
function payLabel(value) { return META.payments?.[value]||value||"—"; }
function MENU() { return [ {id:"dashboard",label:"Inicio",perm:"dashboard"},{id:"pos",label:"Ventas",perm:"sales.create",role:"cajero"},{id:"products",label:"Productos e Inventario",perm:"products.read"},{id:"cashreview",label:"Historial de cierres de caja",perm:"cash.review"},{id:"users",label:"Usuarios y permisos",perm:"users.manage"},{id:"expenses",label:"Egresos",perm:"expenses.create",any:["expenses.read","expenses.create"]},{id:"cash",label:"Mi caja",perm:"cash.own"},{id:"audit",label:"Auditoría",perm:"audit.read"},{id:"settings",label:"Configuración",perm:"settings.manage"},{id:"account",label:"Mi cuenta",public:true} ]; }

/* Mostrar u ocultar contraseña en el inicio y en los formularios futuros. */
const EYE_OPEN='<svg viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8Z"/><circle cx="12" cy="12" r="3"/></svg>';
const EYE_CLOSED='<svg viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor" stroke-width="2"><path d="m3 3 18 18M10.6 10.6a2 2 0 0 0 2.8 2.8M9.9 5.2A10.7 10.7 0 0 1 12 5c7 0 11 7 11 7a16.3 16.3 0 0 1-4 4.7M6.2 6.2C3 8.1 1 12 1 12s4 7 11 7a10.8 10.8 0 0 0 4-.8"/></svg>';
function addEyes(){document.querySelectorAll('input[type="password"]:not([data-eye])').forEach(input=>{input.dataset.eye="1";const wrap=document.createElement("span");wrap.className="pw-wrap";input.parentNode.insertBefore(wrap,input);wrap.append(input);const button=document.createElement("button");button.type="button";button.className="pw-eye";button.setAttribute("aria-label","Mostrar contraseña");button.innerHTML=EYE_OPEN;button.onclick=()=>{const visible=input.type==="password";input.type=visible?"text":"password";button.innerHTML=visible?EYE_CLOSED:EYE_OPEN;button.setAttribute("aria-label",visible?"Ocultar contraseña":"Mostrar contraseña");};wrap.append(button);});}
addEyes();new MutationObserver(addEyes).observe(document.body,{childList:true,subtree:true});
