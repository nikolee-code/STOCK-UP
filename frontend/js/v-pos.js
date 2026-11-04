let posDraftNotice="";
let posRequestId="";
function newPosRequestId(){return globalThis.crypto?.randomUUID?.()||("su-"+Date.now().toString(36)+"-"+Math.random().toString(36).slice(2)+Math.random().toString(36).slice(2));}
function posDraftKey(){return "su_pos_draft_v1_"+(me?.id||"unknown");}
function clearPosDraft(){localStorage.removeItem(posDraftKey());posRequestId="";}
function savePosDraft(){if(!me)return;if(!posCart.length){clearPosDraft();return;}if(!posRequestId)posRequestId=newPosRequestId();localStorage.setItem(posDraftKey(),JSON.stringify({request_id:posRequestId,saved_at:new Date().toISOString(),items:posCart.map(x=>({product_id:x.product_id,presentation_id:x.presentation_id,qty:x.qty})),payment_method:$("#pos-pay")?.value||"efectivo",doc_type:$("#pos-doc")?.value||"nota_interna"}));}
function loadPosDraft(){try{const data=JSON.parse(localStorage.getItem(posDraftKey())||"null");if(!data)return null;const age=Date.now()-Date.parse(data.saved_at);if(!Number.isFinite(age)||age<0||age>24*60*60*1000){clearPosDraft();return null;}let clamped=false;const items=(data.items||[]).flatMap(row=>{const p=posCatalog.find(x=>x.id===Number(row.product_id));if(!p)return [];const pr=row.presentation_id?(p.presentations||[]).find(x=>x.id===Number(row.presentation_id)):null;if(row.presentation_id&&!pr)return [];let qty=Number(row.qty),factor=Number(pr?.factor||1);if(!(qty>0)||!Number.isFinite(qty))return [];const max=Number(p.stock)/factor;if(qty>max){qty=pr||!p.decimal?Math.floor(max):round3(max);clamped=true;}if(qty<=0)return [];return [{key:p.id+":"+(pr?.id||0),product_id:p.id,presentation_id:pr?.id||null,name:pr?p.name+" ("+pr.name+")":p.name,unit:pr?.name||p.unit,price:Number(pr?.price??p.price),qty:pr||!p.decimal?Math.floor(qty):round3(qty),factor,decimal:!pr&&!!p.decimal}];});if(!items.length){clearPosDraft();return null;}posRequestId=data.request_id||newPosRequestId();return {items,payment_method:data.payment_method,doc_type:data.doc_type,clamped};}catch{clearPosDraft();return null;}}
function discardPosDraft(){clearPosDraft();posCart=[];posDraftNotice="";drawPosCart();document.querySelector("#pos-draft-banner")?.remove();toast("Borrador descartado.");}
let posCatalog=[], posCart=[], posCash=null, searchTerm="", category="", posDiscountValue=0, posDiscountApprovalId="";
VIEWS.pos = async function () {
  posCatalog=await api("/products");
  searchTerm=""; category=""; posDiscountValue=0; posDiscountApprovalId="";
  const draft=loadPosDraft();posCart=draft?.items||[];posDraftNotice=draft?(draft.clamped?"El borrador se recuperó; algunas cantidades se ajustaron al stock actual.":"Se recuperó una venta interrumpida."):"";
  try { const c=await api("/cash/current"); posCash=c.session; } catch { posCash=null; }
  const cats=[...new Set(posCatalog.map(p=>p.category||"General"))].sort((a,b)=>a.localeCompare(b,"es"));
  const payments=Object.entries(META.payments||{});
  const draftBanner=draft?'<div id="pos-draft-banner" class="banner"><b>Borrador recuperado.</b> '+esc(posDraftNotice)+' Revisa el carrito antes de cobrar. El borrador expira en 24 horas y no guarda los datos del cliente. <button class="btn ghost sm" type="button" onclick="discardPosDraft()">Descartar borrador</button></div>':'';
  $("#view").innerHTML=draftBanner+`${!posCash?`<div class="banner warn"><b>No hay una caja abierta.</b> Para vender, primero abre tu caja. <button class="btn ghost sm" type="button" onclick="go('cash')">Ir a Mi caja</button></div>`:""}<div class="pos"><section class="card"><div class="row-between"><h3>Productos</h3><button class="btn ghost sm" type="button" onclick="posScan()">Escanear código</button></div><div class="search-row"><input id="pos-search" placeholder="Busca por nombre, código de barras o PLU…" autocomplete="off"></div><div id="pos-chips" class="chips"></div><div id="pos-catalog" class="catalog"></div></section><section class="card"><h3>Venta actual</h3><div id="pos-cart"></div><div class="form-grid">${fld("Forma de pago",`<select id="pos-pay">${opts(payments)}</select>`)}<div id="pos-ref-wrap" class="hidden">${fld("N.º de operación",'<input id="pos-ref" maxlength="60" autocomplete="off">')}</div></div><p class="muted hint">Nota de venta no solicita datos del cliente. La boleta requiere DNI si el cliente pide identificarse o si el total supera S/ 700. La factura requiere RUC y razón social. Las tres opciones son representaciones de demostración sin validez tributaria; APISPERU solo completa los datos consultados.</p><div class="discount-box"><label>Descuento autorizado (S/)<input id="pos-discount-amount" type="number" min="0" step="0.01" value="0" oninput="markDiscountChanged(this.value)"></label><button class="btn ghost sm" type="button" onclick="requestDiscountAuthorization()">Solicitar clave del supervisor</button><small id="discount-approval-status" class="muted">Los descuentos requieren autorización vigente del supervisor.</small></div><div id="pos-doc-wrap">${fld("Comprobante",'<select id="pos-doc"><option value="boleta">Boleta de venta electrónica</option><option value="factura">Factura electrónica</option><option value="nota_interna">Nota de venta</option></select>')}</div><div id="pos-customer"></div><div class="totals"><div class="tl"><span>Subtotal</span><b id="pos-subtotal">S/ 0.00</b></div><div class="tl"><span>Descuento autorizado</span><b id="pos-discount">S/ 0.00</b></div><div class="tl big"><span>Total</span><b id="pos-total">S/ 0.00</b></div></div><button id="pos-submit" class="btn big" type="button" ${posCash?"":"disabled"}>Confirmar venta</button></section></div>`;
  const docSelect=$("#pos-doc");
  docSelect.innerHTML='<option value="boleta">Boleta de venta electrónica</option><option value="factura">Factura electrónica</option><option value="nota_interna">Nota de venta</option>';
  const draftDoc=draft?.doc_type;
  docSelect.value=["boleta","factura","nota_interna"].includes(draftDoc)?draftDoc:"nota_interna";
  const saleHint=docSelect.parentElement?.parentElement?.previousElementSibling?.previousElementSibling;
  if(saleHint)saleHint.textContent="Nota de venta no solicita datos del cliente. La boleta requiere DNI si el cliente pide identificarse o si el total supera S/ 700. La factura requiere RUC y razón social. Las tres opciones son representaciones de demostración sin validez tributaria.";
  const search=$("#pos-search");search.addEventListener("input",()=>{searchTerm=search.value.trim().toLocaleLowerCase("es");drawPosCatalog();});search.addEventListener("keydown",posSearchKey);
  $("#pos-chips").innerHTML=chipsHtml(["",...cats],"");bindChips("#pos-chips",v=>{category=v;$$("#pos-chips .chip").forEach(b=>b.classList.toggle("on",b.dataset.value===category));drawPosCatalog();});
  if(draft&&payments.some(([key])=>key===draft.payment_method))$("#pos-pay").value=draft.payment_method;
  $("#pos-pay").onchange=()=>{$("#pos-ref-wrap").classList.toggle("hidden",$("#pos-pay").value==="efectivo");savePosDraft();};
  $("#pos-doc").onchange=()=>{drawPosCustomer();savePosDraft();};$("#pos-submit").onclick=confirmPosSale;
  drawPosCatalog();drawPosCart();drawPosCustomer();
};
function posMatches(p,q){const s=[p.name,p.code,p.barcode,p.category,...(p.presentations||[]).flatMap(x=>[x.name,x.barcode])].join(" ").toLocaleLowerCase("es");return !q||s.includes(q);}
function drawPosCatalog(){const el=$("#pos-catalog");if(!el)return;const list=posCatalog.filter(p=>(!category||p.category===category)&&posMatches(p,searchTerm));el.innerHTML=list.length?list.map(p=>{const state=stockState(p);return `<article class="pcard ${state} ${p.stock<=0?"out":""}"><button type="button" class="pmain" ${p.stock<=0?"disabled":""} onclick="addPosItem(${p.id},null)"><b>${esc(p.name)}</b><small>${esc(p.category||"General")} · ${num(p.stock)} ${esc(p.unit)} disponibles${(p.presentations||[]).length?" · "+p.presentations.map(x=>num(x.available??Math.floor(p.stock/x.factor))+" "+esc(x.name)).join(" · "):""}</small><span class="pr">${money(p.price)} / ${esc(UNIT[p.unit]||p.unit)}</span></button><div class="pres"><button class="pbtn" ${p.stock<=0?"disabled":""} onclick="addPosItem(${p.id},null)">${esc(UNIT[p.unit]||p.unit)}</button>${(p.presentations||[]).map(x=>`<button class="pbtn" ${p.stock+1e-9<x.factor?"disabled":""} onclick="addPosItem(${p.id},${x.id})">${esc(x.name)} · ${money(x.price)} · ${num(x.available??Math.floor(p.stock/x.factor))} disponibles</button>`).join("")}</div></article>`;}).join(""):'<p class="muted">No se encontraron productos.</p>';}
function posSearchKey(e){if(e.key!=="Enter")return;e.preventDefault();const q=e.target.value.trim();if(!q)return;for(const p of posCatalog){if(p.barcode===q||p.code?.toLocaleLowerCase("es")===q.toLocaleLowerCase("es")){addPosItem(p.id,null);e.target.value="";return;}const pres=(p.presentations||[]).find(x=>x.barcode===q);if(pres){addPosItem(p.id,pres.id);e.target.value="";return;}}const found=posCatalog.filter(p=>posMatches(p,q.toLocaleLowerCase("es")));if(found.length===1){addPosItem(found[0].id,null);e.target.value="";}else toast(found.length?"Hay varios resultados: elige una tarjeta.":"No se encontró el producto.",true);}
function posUnits(pid){return sum(posCart.filter(x=>x.product_id===pid),x=>x.qty*x.factor);}
function addPosItem(pid,presId){const p=posCatalog.find(x=>x.id===pid);if(!p)return;const pr=presId?(p.presentations||[]).find(x=>x.id===presId):null;const factor=Number(pr?.factor||1);if(posUnits(pid)+factor>Number(p.stock)+1e-9)return toast(`Stock insuficiente de ${p.name}.`,true);const key=`${pid}:${presId||0}`;const line=posCart.find(x=>x.key===key);if(line)line.qty=round3(line.qty+1);else posCart.push({key,product_id:pid,presentation_id:presId||null,name:pr?`${p.name} (${pr.name})`:p.name,unit:pr?.name||p.unit,price:Number(pr?.price??p.price),qty:1,factor,decimal:!pr&&!!p.decimal});drawPosCart();}
function setPosQty(key,value){const l=posCart.find(x=>x.key===key);if(!l)return;const p=posCatalog.find(x=>x.id===l.product_id);let q=Number(String(value).replace(",","."));if(!Number.isFinite(q)||q<=0){posCart=posCart.filter(x=>x.key!==key);return drawPosCart();}q=round3(q);const other=posUnits(l.product_id)-l.qty*l.factor;if(other+q*l.factor>p.stock+1e-9){q=round3(Math.max(0,(p.stock-other)/l.factor));toast(`Stock máximo: ${num(p.stock)} ${p.unit}.`,true);}if(q<=0)posCart=posCart.filter(x=>x.key!==key);else l.qty=q;drawPosCart();}
function adjustPosQty(key,delta){const l=posCart.find(x=>x.key===key);if(!l)return;if(delta>0){const p=posCatalog.find(x=>x.id===l.product_id);if(posUnits(l.product_id)+l.factor>p.stock+1e-9)return toast("No hay más stock disponible.",true);}l.qty=round3(l.qty+delta);if(l.qty<=0)posCart=posCart.filter(x=>x.key!==key);drawPosCart();}
function posLineAmount(x){return Math.round((x.qty*x.price+Number.EPSILON)*100)/100;}
function posSubtotal(){return Math.round((sum(posCart,posLineAmount)+Number.EPSILON)*100)/100;}
function posDiscount(){return {value:Math.max(0,Number(posDiscountValue)||0),note:posDiscountApprovalId?"Autorizado por supervisor":"Pendiente de autorización"};}
function drawPosTotals(){const sub=posSubtotal(),d=posDiscount();if($("#pos-subtotal"))$("#pos-subtotal").textContent=money(sub);if($("#pos-discount"))$("#pos-discount").textContent=money(d.value);if($("#pos-total"))$("#pos-total").textContent=money(Math.max(0,sub-(posDiscountApprovalId?d.value:0)));if($("#pos-discount-label"))$("#pos-discount-label").textContent=d.note;const approvalStatus=$("#discount-approval-status");if(approvalStatus)approvalStatus.textContent=posDiscountApprovalId?"Descuento autorizado por el supervisor.":(d.value?"Falta autorización del supervisor.":"Los descuentos requieren autorización vigente del supervisor.");}
function drawPosCart(){const el=$("#pos-cart");if(!el)return;el.innerHTML=posCart.length?posCart.map(l=>`<div class="cartline"><div><b>${esc(l.name)}</b><br><small class="muted">${money(l.price)} · ${esc(l.unit)}</small></div><div class="qty">${l.decimal?`<input class="qin" type="number" min="0.001" step="0.001" value="${l.qty}" onchange="setPosQty('${l.key}',this.value)">`:`<button type="button" onclick="adjustPosQty('${l.key}',-1)">−</button><span>${num(l.qty)}</span><button type="button" onclick="adjustPosQty('${l.key}',1)">+</button>`}</div><b>${money(l.qty*l.price)}</b><button type="button" class="btn ghost sm" aria-label="Quitar ${esc(l.name)}" onclick="setPosQty('${l.key}',0)">×</button></div>`).join(""):'<p class="muted">Agrega productos desde el catálogo.</p>';drawPosTotals();savePosDraft();}
async function posScan(){await scanBarcode({title:"Escanear código",onScan:value=>{const input=$("#pos-search");if(!input)return;input.value=value;const query=value.toLocaleLowerCase("es");searchTerm=query;category="";$$("#pos-chips .chip").forEach(b=>b.classList.toggle("on",b.dataset.value===""));drawPosCatalog();const found=posCatalog.some(p=>[p.barcode,p.code,...(p.presentations||[]).map(x=>x.barcode)].some(code=>String(code||"").toLocaleLowerCase("es")===query));toast(found?"Código leído. Selecciona el producto para agregarlo a la venta.":"Código no encontrado; revisa el código o escríbelo manualmente.",!found);input.focus();}});}
let lookupState={doc:"",type:"",valid:false};
function drawPosCustomer(){
  const type=$("#pos-doc")?.value,box=$("#pos-customer");
  if(!box)return;
  if(type==="nota_interna"){box.innerHTML="";lookupState={doc:"",type,valid:false};return;}
  lookupState={doc:"",type,valid:false};
  const internal=type==="comprobante_interno",invoice=type==="factura",limit=invoice||internal?11:8;
  const documentLabel=internal?"DNI o RUC":invoice?"RUC":"DNI";
  const customerTitle=internal?"Datos del cliente (opcionales)":invoice?"Datos de la empresa":"Datos del cliente";
  const documentPrompt=internal?"DNI o RUC del cliente (opcional)":invoice?"RUC de la empresa *":"DNI del cliente (opcional)";
  const identificationRequest=!invoice&&!internal?`<label class="check"><input id="pos-identification-requested" type="checkbox"> El cliente solicita que se registren sus datos</label>`:"";
  const detailsHint=internal
    ?"Los datos del cliente son opcionales."
    :invoice
      ?"RUC y razón social son obligatorios. La dirección se completa si está disponible."
      :`El DNI es obligatorio si el cliente lo solicita o si la venta supera ${money(META.boleta_limit)}.`;
  box.innerHTML=`<div class="custbox"><h4>${customerTitle}</h4><label>${documentPrompt}<div class="search-row"><input id="pos-cdoc" inputmode="numeric" maxlength="${limit}" placeholder="${internal?'8 dígitos (DNI) o 11 (RUC)':limit+' dígitos'}" autocomplete="off" ${invoice?'required':''}><button id="pos-customer-lookup" class="btn ghost sm" type="button">Consultar ${documentLabel}</button></div></label><label>${invoice?'Razón social *':'Nombre del cliente'}<input id="pos-cname" autocomplete="off" ${invoice?'required':''}></label>${invoice||internal?'<label>Dirección<input id="pos-caddr" autocomplete="off"></label>':''}${identificationRequest}<p class="muted hint">${detailsHint}</p>${META.lookup_enabled?'<p class="muted hint">La consulta a APISPERU ocurre solo al pulsar el botón; si falla, puedes continuar manualmente.</p>':'<p class="lookup-warning">APISPERU no está configurada. Puedes ingresar los datos manualmente.</p>'}<p class="lookup-warning hidden" id="lookup-status" role="status" aria-live="polite"></p></div>`;
  const doc=$("#pos-cdoc"),status=$("#lookup-status");
  doc.oninput=()=>{doc.value=doc.value.replace(/\D/g,"").slice(0,limit);lookupState={doc:doc.value,type,valid:false};status.textContent="";status.classList.add("hidden");status.classList.remove("verified");};
  $("#pos-customer-lookup").onclick=()=>lookupCustomer(invoice||(internal&&doc.value.trim().length===11));
}
async function lookupCustomer(isRuc){
  if($("#pos-doc")?.value==="nota_interna")return;
  const doc=$('#pos-cdoc'),name=$('#pos-cname'),address=$('#pos-caddr'),status=$('#lookup-status'),value=doc?.value.trim()||'',type=isRuc?'factura':'boleta',length=isRuc?11:8,label=isRuc?'RUC':'DNI';
  if(!doc||!name||!status)return;
  status.classList.remove('hidden','verified');
  if(!/^\d+$/.test(value)||value.length!==length){status.textContent=`El ${label} debe tener exactamente ${length} dígitos.`;return;}
  if(!META.lookup_enabled){status.textContent='La consulta automática no está configurada. Puedes ingresar los datos manualmente.';return;}
  lookupState={doc:value,type,valid:false};status.textContent=`Consultando ${label} en APISPERU…`;
  try{
    const data=await api(`/lookup/${isRuc?'ruc':'dni'}/${encodeURIComponent(value)}`);
    if($('#pos-cdoc')?.value.trim()!==value)return;
    if(!data?.name)throw new Error('APISPERU devolvió una respuesta incompleta.');
    name.value=data.name;
    if(address&&data.address)address.value=data.address;
    const active=String(data.status||'').toUpperCase()==='ACTIVO'&&String(data.condition||'').toUpperCase()==='HABIDO';
    lookupState={doc:value,type,valid:isRuc?active:Boolean(data.name)};
    if(isRuc&&!active){status.textContent=`Datos encontrados, pero el RUC figura como ${data.status||'estado desconocido'} · ${data.condition||'condición desconocida'}. Verifica los datos antes de continuar.`;return;}
    status.textContent='Datos consultados correctamente. Puedes editarlos antes de guardar.';status.classList.add('verified');
  }catch(error){
    if($('#pos-cdoc')?.value.trim()!==value)return;
    status.textContent=`No se pudo consultar el ${label}: ${error.message||'falló el servicio'}. Puedes completar los datos manualmente.`;
  }
}
async function confirmPosSale(){
  if(!posCash)return toast("Abre una caja antes de registrar ventas.",true);
  if(!posCart.length)return toast("El carrito está vacío.",true);
  const docType=$("#pos-doc").value;
  const usesCustomer=docType!=="nota_interna";
  const doc=usesCustomer?$("#pos-cdoc")?.value.trim()||"":"";
  const customerName=usesCustomer?$("#pos-cname")?.value.trim()||"":"";
  const customerAddress=usesCustomer?$("#pos-caddr")?.value.trim()||"":"";
  const identificationRequested=$("#pos-identification-requested")?.checked===true;
  if(docType==="factura"&&(!/^\d{11}$/.test(doc)||!customerName))
    return toast("La factura requiere un RUC de 11 dígitos y razón social.",true);
  if(docType==="boleta"&&doc&&!/^\d{8}$/.test(doc))
    return toast("El DNI debe tener 8 dígitos.",true);
  const appliedDiscount=posDiscountApprovalId?Math.max(0,Number(posDiscountValue)||0):0;
  const identificationRequired=docType==="boleta"&&(identificationRequested||posSubtotal()-appliedDiscount>Number(META.boleta_limit??700));
  if(identificationRequired&&(!doc||!customerName))
    return toast("Para esta boleta se requieren el DNI y el nombre del cliente.",true);
  const requestedDiscount=Math.max(0,Number(posDiscountValue)||0);
  if(requestedDiscount>0&&!posDiscountApprovalId)
    return toast("Solicita autorización al supervisor para el descuento actual.",true);
  if(requestedDiscount>=posSubtotal())
    return toast("El descuento debe ser menor que el subtotal.",true);
  const body={
    items:posCart.map(x=>({product_id:x.product_id,qty:x.qty,presentation_id:x.presentation_id})),
    discount_amount:requestedDiscount,
    authorization_id:posDiscountApprovalId,
    payment_method:$("#pos-pay").value,
    payment_ref:$("#pos-ref")?.value.trim()||"",
    doc_type:docType,
    idempotency_key:posRequestId||newPosRequestId(),
  };
  if(usesCustomer){body.customer_doc=doc;body.customer_name=customerName;body.customer_address=customerAddress;}
  if(docType==="boleta")body.customer_identification_requested=identificationRequested;
  posRequestId=body.idempotency_key;
  const button=$("#pos-submit");
  button.disabled=true;
  try{
    const receipt=await api("/sales","POST",body);
    posCart=[];posDiscountValue=0;posDiscountApprovalId="";clearPosDraft();
    showReceipt(receipt,"Venta registrada",()=>VIEWS.pos());
  }catch(error){toast(error.message,true);}
  finally{button.disabled=!posCash;}
}
function markDiscountChanged(value){posDiscountValue=Number(value)||0;posDiscountApprovalId="";drawPosTotals();}
function requestDiscountAuthorization(){const amount=Number(document.querySelector("#pos-discount-amount")?.value||0);if(!(amount>0)||amount>=posSubtotal())return toast("Ingresa un descuento mayor que cero y menor al subtotal.",true);modal({title:"Autorización del supervisor",html:"<p>Ingresa las credenciales del supervisor. La autorización dura cinco minutos y sirve solo para este monto.</p><label>Usuario supervisor<input id=\"approval-user\" required></label><label>Clave supervisor<input id=\"approval-password\" type=\"password\" required></label>",submit:"Autorizar",onSubmit:async root=>{const result=await api("/discount-authorizations","POST",{supervisor_username:root.querySelector("#approval-user").value.trim(),supervisor_password:root.querySelector("#approval-password").value,amount});posDiscountValue=Number(result.amount);posDiscountApprovalId=result.authorization_id;document.querySelector("#pos-discount-amount").value=posDiscountValue.toFixed(2);drawPosTotals();toast("Descuento autorizado por cinco minutos.");}});}

VIEWS.authorizations=async function(){$("#view").innerHTML='<div class="card narrow"><h2>Autorizaciones</h2><p>Para aplicar un descuento, primero agrega los productos en Ventas e ingresa el monto. En esa pantalla, selecciona <b>Solicitar clave del supervisor</b>. El supervisor debe ingresar su usuario y contraseña.</p><p class="muted">La autorización se vincula a tu usuario, al monto exacto y a una sola venta. Vence en cinco minutos. Las solicitudes y descuentos aplicados quedan registrados en auditoría.</p><button class="btn" onclick="go(\'pos\')">Ir a Ventas</button></div>';};
