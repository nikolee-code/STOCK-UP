const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const root = path.resolve(__dirname, "../..");
const pos = fs.readFileSync(path.join(root, "frontend/js/v-pos.js"), "utf8");
const business = fs.readFileSync(path.join(root, "frontend/js/v-business.js"), "utf8");
const customerFunctions = pos.slice(pos.indexOf("function drawPosCustomer(){"), pos.indexOf("async function confirmPosSale(){"));
const supplierFunctions = business.slice(business.indexOf("async function lookupSupplierRuc(root){"), business.indexOf("function purchaseLineHtml(){"));

test("la consulta de cliente solo ocurre al pulsar el botón y permite editar el nombre", async () => {
  const doc = {value: "", oninput: null};
  const name = {value: ""};
  const address = {value: ""};
  const status = {textContent: "", classList: {add() {}, remove() {}}};
  const button = {onclick: null};
  const box = {innerHTML: ""};
  const fields = {"#pos-doc": {value: "boleta"}, "#pos-customer": box, "#pos-cdoc": doc,
    "#pos-cname": name, "#pos-caddr": address, "#lookup-status": status,
    "#pos-customer-lookup": button};
  const calls = [];
  const context = {
    META: {lookup_enabled: true, boleta_limit: 700},
    $: selector => fields[selector],
    money: value => `S/ ${value}`,
    api: async (...args) => {calls.push(args);return {dni: "12345678", name: "ANA PEREZ"};},
    lookupState: {},
  };
  vm.createContext(context);
  vm.runInContext(customerFunctions, context);
  context.drawPosCustomer();
  assert.match(box.innerHTML, /Consultar DNI/);
  doc.value = "12345678";
  doc.oninput();
  assert.equal(calls.length, 0);
  await button.onclick();
  assert.deepEqual(calls, [["/lookup/dni/12345678"]]);
  assert.equal(name.value, "ANA PEREZ");
  assert.equal(context.lookupState.valid, true);
  name.value = "Nombre editado";
  assert.equal(name.value, "Nombre editado");
});

test("Nota de venta oculta por completo los datos del cliente y no consulta APISPERU", async () => {
  const box = {innerHTML: "Datos anteriores"};
  const fields = {"#pos-doc": {value: "nota_interna"}, "#pos-customer": box};
  let apiCalls = 0;
  const context = {
    META: {lookup_enabled: true, boleta_limit: 700},
    $: selector => fields[selector],
    api: async () => {apiCalls += 1;throw new Error("no debe llamar a una API");},
    lookupState: {},
  };
  vm.createContext(context);
  vm.runInContext(customerFunctions, context);
  context.drawPosCustomer();
  await context.lookupCustomer(true);
  assert.equal(box.innerHTML, "");
  assert.equal(apiCalls, 0);
  assert.equal(context.lookupState.type, "nota_interna");
});

test("la factura consulta RUC en APISPERU y completa razón social y dirección", async () => {
  const doc = {value: "20123456789", oninput: null};
  const name = {value: ""};
  const address = {value: ""};
  const status = {textContent: "", classList: {add() {}, remove() {}}};
  const button = {onclick: null};
  const box = {innerHTML: ""};
  const fields = {"#pos-doc": {value: "factura"}, "#pos-customer": box, "#pos-cdoc": doc,
    "#pos-cname": name, "#pos-caddr": address, "#lookup-status": status,
    "#pos-customer-lookup": button};
  const calls = [];
  const context = {
    META: {lookup_enabled: true, boleta_limit: 700},
    $: selector => fields[selector], money: value => `S/ ${value}`,
    api: async (...args) => {calls.push(args);return {ruc: doc.value, name: "EMPRESA DE PRUEBA", address: "AV. PRINCIPAL 123", status: "ACTIVO", condition: "HABIDO"};},
    lookupState: {},
  };
  vm.createContext(context);
  vm.runInContext(customerFunctions, context);
  context.drawPosCustomer();
  assert.match(box.innerHTML, /Consultar RUC/);
  await button.onclick();
  assert.deepEqual(calls, [["/lookup/ruc/20123456789"]]);
  assert.equal(name.value, "EMPRESA DE PRUEBA");
  assert.equal(address.value, "AV. PRINCIPAL 123");
  assert.equal(context.lookupState.valid, true);
});

test("al cambiar de boleta a factura y Nota de venta se muestran los campos correctos", () => {
  const selected = {value: "boleta"};
  const box = {innerHTML: ""};
  const status = {textContent: "", classList: {add() {}, remove() {}}};
  const fields = {
    "#pos-doc": selected, "#pos-customer": box,
    "#pos-cdoc": {value: "", oninput: null}, "#pos-cname": {value: ""},
    "#pos-caddr": {value: ""}, "#lookup-status": status,
    "#pos-customer-lookup": {onclick: null},
  };
  const context = {
    META: {lookup_enabled: true, boleta_limit: 700},
    $: selector => fields[selector], money: value => `S/ ${value}`,
    api: async () => {throw new Error("no debe consultar al cambiar el tipo");}, lookupState: {},
  };
  vm.createContext(context);
  vm.runInContext(customerFunctions, context);

  context.drawPosCustomer();
  assert.match(box.innerHTML, /Consultar DNI/);
  assert.match(box.innerHTML, /Nombre del cliente/);

  selected.value = "factura";
  context.drawPosCustomer();
  assert.match(box.innerHTML, /Consultar RUC/);
  assert.match(box.innerHTML, /Razón social \*/);
  assert.match(box.innerHTML, /Dirección/);

  selected.value = "nota_interna";
  context.drawPosCustomer();
  assert.equal(box.innerHTML, "");
  assert.equal(context.lookupState.type, "nota_interna");
});

test("el formulario de cliente conserva la captura manual si APISPERU no está configurada", async () => {
  const doc = {value: "", oninput: null};
  const name = {value: ""};
  const status = {textContent: "", classList: {add() {}, remove() {}}};
  const button = {onclick: null};
  const fields = {"#pos-doc": {value: "boleta"}, "#pos-customer": {innerHTML: ""},
    "#pos-cdoc": doc, "#pos-cname": name, "#pos-caddr": null,
    "#lookup-status": status, "#pos-customer-lookup": button};
  let apiCalls = 0;
  const context = {
    META: {lookup_enabled: false, boleta_limit: 700},
    $: selector => fields[selector], money: value => `S/ ${value}`,
    api: async () => {apiCalls += 1;throw new Error("should not request");}, lookupState: {},
  };
  vm.createContext(context);
  vm.runInContext(customerFunctions, context);
  context.drawPosCustomer();
  assert.match(fields["#pos-customer"].innerHTML, /id="pos-cname"/);
  doc.value = "12345678";
  doc.oninput();
  name.value = "Cliente ingresado manualmente";
  await button.onclick();
  assert.equal(apiCalls, 0);
  assert.equal(name.value, "Cliente ingresado manualmente");
  assert.match(status.textContent, /Puedes ingresar los datos manualmente/);
});

test("el botón de proveedor consulta RUC manualmente y completa la razón social", async () => {
  const tax = {value: "20123456789"};
  const name = {value: ""};
  const status = {textContent: "", classList: {add() {}, remove() {}}};
  const button = {onclick: null, disabled: false};
  const rootElement = {querySelector(selector) {return {"#sup-tax": tax, "#sup-name": name,
    "#sup-lookup-status": status, "#sup-lookup": button}[selector];}};
  let config;
  const context = {
    META: {lookup_enabled: true},
    modal: value => {config = value;return {element: rootElement};},
    api: async url => {assert.equal(url, "/lookup/ruc/20123456789");return {name: "COMERCIAL EJEMPLO", status: "ACTIVO", condition: "HABIDO"};},
    toast() {}, VIEWS: {purchases: async () => {}},
  };
  vm.createContext(context);
  vm.runInContext(supplierFunctions, context);
  context.supplierForm();
  assert.match(config.html, /Consultar RUC/);
  await button.onclick();
  assert.equal(name.value, "COMERCIAL EJEMPLO");
  assert.match(status.textContent, /Puedes editar los datos antes de guardar/);
});

test("el proveedor sigue guardándose manualmente si la consulta no está configurada", async () => {
  let submitted;
  const config = {};
  const rootElement = {querySelector() {return {onclick: null};}};
  const context = {
    META: {lookup_enabled: false},
    modal: value => {config.current = value;return {element: rootElement};},
    api: async (...args) => {submitted = args;return {ok: true};},
    toast() {}, VIEWS: {purchases: async () => {}},
  };
  vm.createContext(context);
  vm.runInContext(supplierFunctions, context);
  context.supplierForm();
  const values = {"#sup-name": {value: "Proveedor manual"}, "#sup-tax": {value: "20123456789"},
    "#sup-phone": {value: "999111222"}, "#sup-email": {value: ""}};
  await config.current.onSubmit({querySelector: selector => values[selector]});
  assert.equal(submitted[0], "/suppliers");
  assert.equal(submitted[1], "POST");
  assert.deepEqual(JSON.parse(JSON.stringify(submitted[2])), {
    name: "Proveedor manual", tax_id: "20123456789", phone: "999111222", email: "",
  });
});
