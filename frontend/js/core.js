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
  const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),20000);
  let response;
  try {
    response=await fetch((API_SERVER?API_SERVER+"/api":"/api")+path,{method,headers:{"Content-Type":"application/json",...(token?{Authorization:"Bearer "+token}:{})},body:body===undefined?undefined:JSON.stringify(body),signal:controller.signal});
  } catch(error) {
    if(error.name==="AbortError") throw new Error("La solicitud tardó demasiado. Revisa la conexión e inténtalo de nuevo.");
    throw new Error("No se pudo conectar con Stock Up. Comprueba internet y vuelve a intentar; los datos del formulario siguen aquí.");
  } finally { clearTimeout(timeout); }
  const data=await response.json().catch(()=>({}));
  if(!response.ok){if(response.status===401&&token)logout();throw new Error(typeof data.detail==="string"?data.detail:`Error ${response.status} en la solicitud`);}
  return data;
}
function downloadCsv(filename, columns, rows) {
  const quote=value=>"\""+String(value??"").replace(/\"/g, "\"\"")+"\"";
  const content=String.fromCharCode(0xFEFF)+[columns.map(x=>quote(x.label)).join(";"),...rows.map(row=>columns.map(x=>quote(typeof x.value==="function"?x.value(row):row[x.value])).join(";"))].join("\r\n");
  const url=URL.createObjectURL(new Blob([content],{type:"text/csv;charset=utf-8"}));
  const a=document.createElement("a");a.href=url;a.download=filename;a.click();URL.revokeObjectURL(url);
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

let activeModalClose=null;
function modal({title,html,submit="Guardar",cancel="Cancelar",onSubmit,onClose,wide=false,danger=false,noButtons=false}={}) {
  closeModal(); const root=$("#modal-root");
  root.innerHTML=`<div class="overlay" role="presentation"><section class="modal ${wide?"wide":""}" role="dialog" aria-modal="true" aria-labelledby="modal-title"><header class="row-between"><h2 id="modal-title">${esc(title||"")}</h2><button type="button" class="btn ghost sm" data-close aria-label="Cerrar">×</button></header><div class="modal-body">${html||""}</div>${noButtons?"":`<footer class="actions"><button type="button" class="btn ghost" data-cancel>${esc(cancel)}</button><button type="button" class="btn ${danger?"bad":""}" data-submit>${esc(submit)}</button></footer>`}</section></div>`;
  const overlay=root.firstElementChild; let opened=true; const close=()=>{if(!opened)return;opened=false;root.innerHTML="";document.removeEventListener("keydown",key);if(activeModalClose===close)activeModalClose=null;onClose?.();};activeModalClose=close;
  const key=e=>{if(e.key==="Escape")close();}; document.addEventListener("keydown",key);
  overlay.addEventListener("click",e=>{if(e.target===overlay||e.target.closest("[data-close],[data-cancel]"))close();});
  overlay.querySelector("[data-submit]")?.addEventListener("click",async e=>{const b=e.currentTarget;b.disabled=true;try{const keep=await onSubmit?.(overlay.querySelector(".modal-body"));if(keep!==false)close();}catch(err){toast(err.message,true);}finally{b.disabled=false;}});
  return {close,element:overlay};
}
function closeModal(){if(activeModalClose){activeModalClose();return;}const r=$("#modal-root");if(r)r.innerHTML="";}
function confirmBox(message,yes=()=>{}) { modal({title:"Confirmar",html:`<p>${esc(message)}</p>`,submit:"Confirmar",danger:true,onSubmit:yes}); }

const SCANNER_FORMATS=["ean_13","ean_8","upc_a","upc_e","code_128","code_39","itf","codabar","qr_code"];
const ZXING_BROWSER_URL="https://unpkg.com/@zxing/browser@0.2.1/umd/zxing-browser.min.js";
let zxingBrowserPromise=null;
function loadZXingBrowser(){
  if(window.ZXingBrowser)return Promise.resolve(window.ZXingBrowser);
  if(zxingBrowserPromise)return zxingBrowserPromise;
  zxingBrowserPromise=new Promise((resolve,reject)=>{
    const script=document.createElement("script");script.src=ZXING_BROWSER_URL;script.async=true;
    script.onload=()=>window.ZXingBrowser?resolve(window.ZXingBrowser):reject(new Error("No se pudo iniciar ZXing."));
    script.onerror=()=>reject(new Error("No se pudo cargar el lector automático. Puedes escribir el código manualmente."));
    document.head.appendChild(script);
  }).catch(error=>{zxingBrowserPromise=null;throw error;});
  return zxingBrowserPromise;
}
function cameraErrorMessage(error){
  if(error?.name==="NotAllowedError"||error?.name==="PermissionDeniedError"||error?.name==="SecurityError")return "No se autorizó el acceso a la cámara. Habilita el permiso del sitio y vuelve a intentar; también puedes escribir el código manualmente.";
  if(error?.name==="NotFoundError"||error?.name==="DevicesNotFoundError")return "No hay una cámara disponible en este dispositivo. Puedes escribir el código manualmente.";
  if(error?.name==="NotReadableError"||error?.name==="TrackStartError")return "La cámara está ocupada o no se pudo iniciar. Ciérrala en otras aplicaciones e inténtalo de nuevo.";
  if(error?.name==="OverconstrainedError")return "La cámara no admite la configuración solicitada. Puedes escribir el código manualmente.";
  return error?.message||"No se pudo iniciar la cámara. Puedes escribir el código manualmente.";
}
function validScannedCode(value){return typeof value==="string"&&value.trim().length>0&&value.trim().length<=128&&!/[\u0000-\u001f\u007f]/.test(value);}
async function scanBarcode({onScan,title="Escanear código"}={}) {
  const html=`<div class="qr-reader"><video autoplay playsinline muted aria-label="Vista en directo de la cámara"></video><p class="muted">Centra el código frente a la cámara. También puedes escribirlo manualmente.</p><div class="row-gap"><input class="manual-code" placeholder="Código de barras" autocomplete="off"><button type="button" class="btn manual-submit">Usar código</button></div><p class="scan-status muted" role="status" aria-live="polite">Solicitando acceso a la cámara…</p></div>`;
  let stream=null,frame=null,detector=null,controls=null,active=true,accepted=false,detecting=false;
  const m=modal({title,html,noButtons:true,onClose:stop});const video=m.element.querySelector("video"),status=m.element.querySelector(".scan-status"),input=m.element.querySelector(".manual-code");
  function stop(){if(!active)return;active=false;if(frame!==null)cancelAnimationFrame(frame);frame=null;try{controls?.stop?.();}catch{}controls=null;stream?.getTracks?.().forEach(track=>{try{track.stop();}catch{}});stream=null;if(video){video.pause?.();video.srcObject=null;}}
  const close=m.close;
  const accept=value=>{if(accepted)return;const code=String(value??"").trim();if(!validScannedCode(code)){status.textContent="El código está vacío o no es válido. Revísalo e inténtalo otra vez.";return;}accepted=true;stop();close();onScan?.(code);};
  m.element.querySelector(".manual-submit").onclick=()=>accept(input.value);
  input.onkeydown=e=>{if(e.key==="Enter"){e.preventDefault();accept(e.target.value);}};
  const setError=error=>{if(active){stop();status.textContent=cameraErrorMessage(error);}};
  const schedule=()=>{if(active&&!accepted)frame=requestAnimationFrame(scanFrame);};
  async function startZXing(){
    const zxing=await loadZXingBrowser();if(!active)return;
    if(typeof zxing.BrowserMultiFormatReader!=="function")throw new Error("El lector automático no está disponible. Puedes escribir el código manualmente.");
    const reader=new zxing.BrowserMultiFormatReader();
    const started=await reader.decodeFromStream(stream,video,(result)=>{if(result&&active)accept(result.getText());});
    if(!active)started.stop();else{controls=started;status.textContent="Cámara activa. Centra el código dentro de la imagen.";}
  }
  async function startNative(){
    const BarcodeDetectorClass=window.BarcodeDetector;
    if(typeof BarcodeDetectorClass!=="function")return false;
    let formats=SCANNER_FORMATS;
    if(typeof BarcodeDetectorClass.getSupportedFormats==="function"){
      const supported=await BarcodeDetectorClass.getSupportedFormats();formats=SCANNER_FORMATS.filter(format=>supported.includes(format));
      if(!formats.length)return false;
    }
    try{detector=new BarcodeDetectorClass({formats});}catch{return false;}
    status.textContent="Cámara activa. Centra el código dentro de la imagen.";schedule();return true;
  }
  async function scanFrame(){
    frame=null;if(!active||accepted||detecting)return;
    if(video.readyState<2){schedule();return;}
    detecting=true;
    try{const hits=await detector.detect(video);if(hits?.length){const code=hits.find(hit=>validScannedCode(hit.rawValue))?.rawValue;if(code)return accept(code);status.textContent="La cámara leyó un código inválido. Vuelve a enfocar la etiqueta.";}}
    catch{if(active){if(frame!==null)cancelAnimationFrame(frame);frame=null;try{await startZXing();}catch(error){setError(error);}}detecting=false;return;}
    detecting=false;schedule();
  }
  try{
    if(!navigator.mediaDevices?.getUserMedia)throw new Error("La cámara requiere un navegador compatible y una conexión segura (HTTPS o localhost). Puedes escribir el código manualmente.");
    stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:"environment"},width:{ideal:1280},height:{ideal:720}},audio:false});
    if(!active){stream.getTracks().forEach(track=>track.stop());stream=null;return;}
    video.srcObject=stream;video.muted=true;video.playsInline=true;await video.play();
    let nativeReady=false;try{nativeReady=await startNative();}catch{nativeReady=false;}
    if(!active)return;
    if(!nativeReady)await startZXing();
  }catch(error){setError(error);}
}

function ticketHtml(r) {
  const simulated=["boleta","factura","nota_interna","comprobante_interno"].includes(r.doc_type);
  const establishment=r.establishment||{name:"Stock Up",ruc:"",address:""};
  const customer=(r.customer_name||r.customer_doc||r.customer_address)?`<section class="r-customer"><b>Cliente</b><br>${esc(r.customer_name||"")}${r.customer_doc?` · ${esc(r.customer_doc_type||"Documento")} ${esc(r.customer_doc)}`:""}${r.customer_address?`<br>${esc(r.customer_address)}`:""}</section>`:"";
  const taxRows=r.doc_type==="nota_interna"?"":simulated?`<div class="r-tot"><span>Base referencial</span><span>${money(r.base)}</span></div><div class="r-tot"><span>IGV incluido (referencial)</span><span>${money(r.igv)}</span></div><small class="r-muted">Desglose informativo calculado sobre el total; no representa una declaración tributaria.</small>`:`<div class="r-tot"><span>Op. gravada</span><span>${money(r.base)}</span></div><div class="r-tot"><span>IGV (18%)</span><span>${money(r.igv)}</span></div>`;
  const establishmentDetails=[establishment.ruc?"RUC: "+esc(establishment.ruc):"",establishment.address?esc(establishment.address):""].filter(Boolean).join("<br>");
  return `<article class="receipt ${simulated?"r-internal":""}"><header class="r-head"><img class="receipt-logo" src="./brand.png" alt=""><h2>${esc(establishment.name||"Stock Up")}</h2><div class="r-establishment"><b>Establecimiento</b>${establishmentDetails?`<br>${establishmentDetails}`:""}</div><div class="r-doc-title">${esc(r.doc_name||r.doc_type||"Comprobante")}</div><b class="r-number">${simulated?"Número interno: ":""}${esc(r.number||"")}</b></header><section class="r-meta"><span><b>Fecha y hora:</b> ${esc(r.date||"")}</span><span><b>Atendió:</b> ${esc(r.cashier||"")}</span></section>${customer}<table><thead><tr><th>Producto</th><th>Cant.</th><th>Precio</th><th>Importe</th></tr></thead><tbody>${(r.items||[]).map(i=>`<tr><td>${esc(i.description)}</td><td>${num(i.qty)}</td><td>${money(i.price)}</td><td>${money(i.subtotal??i.qty*i.price)}</td></tr>`).join("")}</tbody></table><div class="r-summary">${taxRows}<div class="r-tot"><span>Subtotal</span><span>${money(r.subtotal)}</span></div>${Number(r.discount)?`<div class="r-tot"><span>Descuento ${esc(r.promo_name||"")}</span><span>− ${money(r.discount)}</span></div>`:""}<div class="r-tot big"><span>TOTAL</span><span>${money(r.total)}</span></div></div><p class="r-payment"><b>Forma de pago:</b> ${esc(r.payment||"")}${r.payment_ref?` · ${esc(r.payment_ref)}`:""}</p>${r.status==="anulada"?'<div class="r-void">VENTA ANULADA</div>':""}${simulated?'<footer class="r-internal-notice">Representación de demostración sin validez tributaria.</footer>':r.doc_type==="nota_interna"?'<footer class="r-internal-notice">Representación de demostración sin validez tributaria.</footer>':'<footer class="r-demo">DOCUMENTO DE PRUEBA · NO VÁLIDO ANTE SUNAT</footer>'}</article>`;
}
function receiptPrintDocument(rows) {
  return `<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Comprobantes Stock Up</title><style>
    @page{size:80mm auto;margin:5mm}*{box-sizing:border-box}body{font:11px/1.4 Arial,sans-serif;color:#17212b;margin:0}
    .receipt{width:76mm;max-width:100%;margin:0 auto 10mm;padding:4mm 3mm;page-break-after:always;background:#fff}
    .receipt:last-child{page-break-after:auto}.r-head{text-align:center;border-bottom:1px dashed #8793a0;padding-bottom:3mm;margin-bottom:3mm}
    .receipt-logo{max-width:32mm;max-height:12mm;object-fit:contain}.r-head h2{font-size:18px;letter-spacing:.04em;margin:2mm 0}
    .r-establishment{font-size:10px;color:#526171;margin-bottom:2mm}.r-doc-title{font-size:12px;font-weight:700;text-transform:uppercase;margin-top:2mm}
    .r-number{display:inline-block;margin-top:1mm;font-size:12px}.r-meta{display:grid;gap:1mm;margin:2mm 0}
    .r-customer{border-top:1px solid #d8dee5;border-bottom:1px solid #d8dee5;padding:2mm 0;margin:2mm 0;overflow-wrap:anywhere}
    table{width:100%;border-collapse:collapse;table-layout:fixed;margin:3mm 0}th,td{text-align:left;padding:1.5mm .5mm;border-bottom:1px solid #d8dee5;vertical-align:top;overflow-wrap:anywhere}
    th{font-size:9px;color:#526171;text-transform:uppercase}th:first-child,td:first-child{width:40%}th:nth-child(2),td:nth-child(2){width:12%;text-align:right}
    th:nth-child(3),td:nth-child(3){width:22%;text-align:right}th:nth-child(4),td:nth-child(4){width:26%;text-align:right}
    .r-summary{border-top:1px solid #8793a0;padding-top:2mm}.r-tot{display:flex;justify-content:space-between;gap:4mm;padding:.7mm 0}
    .r-tot.big{font-size:15px;font-weight:700;border-top:1px solid #17212b;margin-top:1mm;padding-top:2mm}
    .r-muted{display:block;color:#657382;font-size:9px;margin:1mm 0 2mm}.r-payment{border-top:1px solid #d8dee5;padding-top:2mm}
    .r-internal-notice{display:block;text-align:center;color:#687585;font-size:9px;border-top:1px dashed #aab4bf;padding-top:2mm;margin-top:3mm}
    .r-demo,.r-void{text-align:center;border:1px solid #687585;padding:2mm;margin-top:3mm;font-weight:700}.r-void{color:#a22}
    @media screen{body{background:#eef1f4;padding:8mm}.receipt{box-shadow:0 2px 12px #0002}}
  </style></head><body>${rows.map(ticketHtml).join("")}<script>onload=()=>print()<\/script></body></html>`;
}
function printTickets(rows) {
  const w=window.open("","_blank","width=480,height=720");
  if(!w)return toast("Permite las ventanas emergentes para imprimir",true);
  w.document.write(receiptPrintDocument(rows));
  w.document.close();
}
async function printSales(ids) {
  const w=window.open("","_blank","width=480,height=720");
  if(!w)return toast("Permite las ventanas emergentes para imprimir",true);
  w.document.write("Cargando comprobantes…");
  try {
    const rows=await Promise.all(ids.map(id=>api(`/sales/${id}`)));
    w.document.open();
    w.document.write(receiptPrintDocument(rows));
    w.document.close();
  } catch(e) {
    w.close();
    toast(e.message,true);
  }
}
function showReceipt(r,label="",after) { modal({title:label||"Venta registrada",html:ticketHtml(r),noButtons:true});const m=$("#modal-root");const foot=document.createElement("div");foot.className="r-actions noprint";foot.innerHTML='<button class="btn ghost" type="button">Imprimir</button><button class="btn" type="button">Nueva venta</button>';m.querySelector(".modal-body").append(foot);foot.children[0].onclick=()=>printTickets([r]);foot.children[1].onclick=()=>{closeModal();after?.();}; }
function payLabel(value) { return META.payments?.[value]||value||"—"; }
function MENU() {
  return [
    {id:"dashboard",label:"Inicio",perm:"dashboard"},
    {id:"backup",label:"Copias de seguridad",perm:"users.manage"},
    {id:"pos",label:"Ventas",perm:"sales.create"},
    {id:"products",label:"Productos e Inventario",perm:"products.read"},
    {id:"cashreview",label:"Historial de cierres de caja",perm:"cash.review"},
    {id:"users",label:"Usuarios y permisos",perm:"users.manage"},
    {id:"expenses",label:"Egresos",any:["expenses.read","expenses.create"]},
    {id:"cash",label:"Mi caja",perm:"cash.own"},
    {id:"audit",label:"Auditor\u00eda",perm:"audit.read"},
    {id:"settings",label:"Configuraci\u00f3n",perm:"settings.manage"},
    {id:"myops",label:"Mis operaciones",perm:"sales.own"},
    {id:"authorizations",label:"Autorizaciones",perm:"sales.create"},
    {id:"finance",label:"Gesti\u00f3n financiera",perm:"finance.read"},
    {id:"purchases",label:"Compras y proveedores",perm:"purchases.manage"},
    {id:"documents",label:"Comprobantes",any:["sales.read","purchases.read"]},
    {id:"account",label:"Mi cuenta",public:true}
  ];
}

/* Mostrar u ocultar contraseña en el inicio y en los formularios futuros. */
const EYE_OPEN='<svg viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8Z"/><circle cx="12" cy="12" r="3"/></svg>';
const EYE_CLOSED='<svg viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor" stroke-width="2"><path d="m3 3 18 18M10.6 10.6a2 2 0 0 0 2.8 2.8M9.9 5.2A10.7 10.7 0 0 1 12 5c7 0 11 7 11 7a16.3 16.3 0 0 1-4 4.7M6.2 6.2C3 8.1 1 12 1 12s4 7 11 7a10.8 10.8 0 0 0 4-.8"/></svg>';
function addEyes(){document.querySelectorAll('input[type="password"]:not([data-eye])').forEach(input=>{input.dataset.eye="1";const wrap=document.createElement("span");wrap.className="pw-wrap";input.parentNode.insertBefore(wrap,input);wrap.append(input);const button=document.createElement("button");button.type="button";button.className="pw-eye";button.setAttribute("aria-label","Mostrar contraseña");button.innerHTML=EYE_OPEN;button.onclick=()=>{const visible=input.type==="password";input.type=visible?"text":"password";button.innerHTML=visible?EYE_CLOSED:EYE_OPEN;button.setAttribute("aria-label",visible?"Ocultar contraseña":"Mostrar contraseña");};wrap.append(button);});}
addEyes();new MutationObserver(addEyes).observe(document.body,{childList:true,subtree:true});
