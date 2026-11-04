let roleRefreshTimer = null;
async function doLogin(event) {
  event.preventDefault();
  const button = $("#login-btn");
  if (button) button.disabled = true;
  try {
    const data = await api("/login", "POST", {username: $("#lu").value.trim(), password: $("#lp").value});
    token = data.token;
    localStorage.setItem("su_token", token);
    localStorage.setItem("su_last_activity", String(Date.now()));
    me = data.user;
    await start();
  } catch (e) {
    toast(e.message, true);
  } finally {
    if (button) button.disabled = false;
  }
}
function logout(reason = "") {
  localStorage.removeItem("su_token");
  localStorage.removeItem("su_last_activity");
  token = null;
  me = null;
  if (roleRefreshTimer) clearInterval(roleRefreshTimer);
  roleRefreshTimer = null;
  if (reason) sessionStorage.setItem("su_logout_reason", reason);
  location.reload();
}
function permitted(item) {
  return !!item.public || (item.any ? hasAny(...item.any) : has(item.perm));
}
function renderIdentity() {
  if (!$("#who")) return;
  const extras = (me.additional_roles || []).map(code => esc(ROLE[code] || code));
  $("#who").innerHTML = "<b>" + esc(me.full_name) + "</b><small>Rol principal: " + esc(ROLE[me.role] || me.role) + "</small>" +
    (extras.length ? "<small>Adicionales: " + extras.join(", ") + "</small>" : "");
}
function renderMenu() {
  const activeId = $("#menu .active")?.id?.replace(/^m-/, "");
  const items = [...new Map(MENU().filter(permitted).map(item => [item.id, item])).values()];
  $("#menu").innerHTML = items.map(item => '<button type="button" id="m-' + item.id + '" onclick="go(&quot;' + item.id + '&quot;)">' + esc(item.label) + "</button>").join("");
  if (activeId && items.some(item => item.id === activeId)) $("#m-" + activeId)?.classList.add("active");
  return items;
}
async function refreshSessionUser() {
  const currentId = $("#menu .active")?.id?.replace(/^m-/, "");
  const before = JSON.stringify([me?.role, me?.additional_roles || [], me?.perms || []]);
  me = await api("/me");
  const after = JSON.stringify([me?.role, me?.additional_roles || [], me?.perms || []]);
  if (before === after) return false;
  renderIdentity();
  const items = renderMenu();
  if (currentId && !items.some(item => item.id === currentId)) {
    if (items.length) await go(items[0].id);
    else $("#view").innerHTML = '<div class="alert">No hay pantallas disponibles para este usuario.</div>';
  }
  return true;
}
function startRoleRefresh() {
  if (roleRefreshTimer) return;
  roleRefreshTimer = setInterval(() => {
    if (token) refreshSessionUser().catch(() => {});
  }, 30000);
}
async function start() {
  startIdleGuard();
  startRoleRefresh();
  try {
    META = await api("/meta");
  } catch (e) {
    console.warn("No se pudo cargar la configuracion inicial", e);
  }
  $("#login")?.classList.add("hidden");
  $("#app")?.classList.remove("hidden");
  renderIdentity();
  const items = renderMenu();
  if (items.length) await go(items[0].id);
  else $("#view").innerHTML = '<div class="alert">No hay pantallas disponibles para este usuario.</div>';
}
async function go(id){const item=MENU().find(x=>x.id===id);if(!item||!permitted(item))return toast("No tienes permiso para abrir esta pantalla.",true);if(typeof VIEWS[id]!=="function")return toast("Esta pantalla se habilitará en la siguiente entrega.",true);document.querySelectorAll("#menu button").forEach(x=>x.classList.toggle("active",x.id===`m-${id}`));$("#title").textContent=item.label;$("#view").innerHTML='<p class="muted">Cargando…</p>';try{await VIEWS[id]();$("#view").focus({preventScroll:true});}catch(e){$("#view").innerHTML=`<div class="alert" role="alert"><p>${esc(e.message||"Ocurrió un error al cargar la pantalla.")}</p><button class="btn ghost sm" type="button" onclick="go(&quot;${id}&quot;)">Reintentar</button></div>`;}}
(async function init(){const logoutReason=sessionStorage.getItem("su_logout_reason");if(logoutReason){sessionStorage.removeItem("su_logout_reason");toast(logoutReason,true);}if("serviceWorker"in navigator)navigator.serviceWorker.register("./sw.js").catch(()=>{});if(STATIC_PAGES){$("#deployment-message")?.classList.remove("hidden");$("#login").querySelectorAll("input").forEach(x=>x.disabled=true);const button=$("#login-btn");button.disabled=true;button.textContent="Servidor no conectado";$("#login")?.classList.remove("hidden");return;}if(token){try{me=await api("/me");await start();return;}catch{localStorage.removeItem("su_token");token=null;}}$("#login")?.classList.remove("hidden");})();

let idleCheckTimer=null,lastActivityAt=0,idleWarned=false;
function startIdleGuard(){
  if(idleCheckTimer)return;
  const idleLimit=30*60*1000;
  lastActivityAt=Number(localStorage.getItem("su_last_activity"))||Date.now();
  const record=()=>{if(!token)return;const now=Date.now();if(now-lastActivityAt<15000)return;lastActivityAt=now;idleWarned=false;localStorage.setItem("su_last_activity",String(now));};
  ["pointerdown","keydown","touchstart","scroll"].forEach(type=>document.addEventListener(type,record,{passive:true}));
  window.addEventListener("storage",event=>{if(event.key==="su_last_activity"&&event.newValue)lastActivityAt=Math.max(lastActivityAt,Number(event.newValue)||0);if(event.key==="su_token"&&!event.newValue&&token)location.reload();});
  idleCheckTimer=setInterval(()=>{if(!token)return;const idle=Date.now()-Math.max(lastActivityAt,Number(localStorage.getItem("su_last_activity"))||0);if(idle>=idleLimit){logout("La sesión se cerró tras 30 minutos sin actividad. Inicia sesión de nuevo.");return;}if(idle>=idleLimit-2*60*1000&&!idleWarned){idleWarned=true;toast("Por seguridad, la sesión se cerrará en 2 minutos si no hay actividad.",true);}},15000);
}
