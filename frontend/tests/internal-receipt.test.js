const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const core = fs.readFileSync(path.resolve(__dirname, "../js/core.js"), "utf8");
const pos = fs.readFileSync(path.resolve(__dirname, "../js/v-pos.js"), "utf8");
const receiptStart = core.indexOf("function ticketHtml(r) {");
const receiptEnd = core.indexOf("function showReceipt(", receiptStart);
const receiptFunctions = core.slice(receiptStart, receiptEnd);
const confirmStart = pos.indexOf("async function confirmPosSale(){");
const confirmEnd = pos.indexOf("function markDiscountChanged", confirmStart);
const confirmFunction = pos.slice(confirmStart, confirmEnd);
const customerFunctions = pos.slice(pos.indexOf("function drawPosCustomer(){"), confirmStart);

function harness(overrides = {}) {
  const writes = [];
  const notifications = [];
  const popup = {
    document: {
      write: value => writes.push(value),
      open() {},
      close() {},
    },
    close() { this.closed = true; },
  };
  const calls = [];
  const context = {
    esc: value => String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;"),
    money: value => `S/ ${Number(value || 0).toFixed(2)}`,
    num: value => String(value ?? 0),
    toast: (message, error) => notifications.push({message, error}),
    window: {open: (...args) => { calls.push(args); return popup; }},
    api: async (...args) => { calls.push(args); return overrides.receipt; },
  };
  vm.createContext(context);
  vm.runInContext(receiptFunctions, context);
  return {context, writes, notifications, calls, popup};
}

const receipt = {
  id: 8,
  doc_type: "comprobante_interno",
  doc_name: "Comprobante interno de venta",
  number: "INT-00000001",
  date: "04/11/2026 10:30",
  cashier: "Caja de prueba",
  establishment: {name: "Stock Up", ruc: "", address: "Local de prueba"},
  customer_doc_type: "DNI",
  customer_doc: "12345678",
  customer_name: "Cliente de prueba",
  customer_address: "Dirección de prueba",
  items: [{description: "Producto A", qty: 2, price: 10, subtotal: 20}],
  subtotal: 20,
  discount: 2,
  promo_name: "Descuento autorizado",
  base: 15.25,
  igv: 2.75,
  total: 18,
  payment: "Efectivo",
  payment_ref: "",
  taxes_are_reference: true,
  status: "completada",
};

test("el comprobante interno contiene los datos de venta y aclara que no tiene validez tributaria", () => {
  const {context} = harness();
  const html = context.ticketHtml(receipt);
  for (const text of [
    "Stock Up", "Local de prueba", "Comprobante interno de venta", "Número interno: INT-00000001",
    "04/11/2026 10:30", "Cliente de prueba", "DNI 12345678", "Producto A", "S/ 10.00",
    "S/ 20.00", "Descuento autorizado", "IGV incluido (referencial)", "TOTAL",
    "S/ 18.00", "Efectivo", "Representación de demostración sin validez tributaria",
  ]) assert.ok(html.includes(text), `falta en el comprobante: ${text}`);
  assert.ok(!html.includes("DOCUMENTO DE PRUEBA"));
});

test("el selector ofrece Boleta, Factura y Nota de venta con sus nombres visibles", () => {
  for (const option of [
    '<option value="boleta">Boleta de venta electrónica</option>',
    '<option value="factura">Factura electrónica</option>',
    '<option value="nota_interna">Nota de venta</option>',
  ]) assert.ok(pos.includes(option), `falta opción: ${option}`);
  assert.ok(!pos.includes('<option value="comprobante_interno">'));
});

test("la impresión muestra títulos solicitados y correlativos internos para los tres tipos", () => {
  const {context} = harness();
  for (const [doc_type, doc_name, number] of [
    ["boleta", "Boleta de venta electrónica", "BI01-00000007"],
    ["factura", "Factura electrónica", "FI01-00000004"],
    ["nota_interna", "Nota de venta", "INT-00000009"],
  ]) {
    const html = context.ticketHtml({...receipt, doc_type, doc_name, number, customer_doc: "", customer_name: "", customer_address: ""});
    assert.ok(html.includes(`<div class="r-doc-title">${doc_name}</div>`));
    assert.ok(html.includes(`Número interno: ${number}`));
    assert.ok(html.includes("Representación de demostración sin validez tributaria"));
    assert.ok(!html.includes("simulada</div>") && !html.includes("prototipo</div>"));
  }
});

test("confirmar una venta interna la envía una vez y muestra el comprobante sin error SUNAT", async () => {
  const fields = {
    "#pos-doc": {value: "comprobante_interno"},
    "#pos-cdoc": {value: "12345678"},
    "#pos-cname": {value: "Cliente de prueba"},
    "#pos-caddr": {value: ""},
    "#pos-pay": {value: "efectivo"},
    "#pos-ref": null,
    "#pos-submit": {disabled: false},
  };
  const calls = [];
  const notifications = [];
  const shown = [];
  const context = {
    META: {electronic_invoicing_enabled: false, lookup_enabled: false},
    posCash: {id: 1}, posCart: [{product_id: 4, qty: 2, presentation_id: null}],
    posDiscountValue: 0, posDiscountApprovalId: "", posRequestId: "internal-confirmation-key-01",
    $: selector => fields[selector], posSubtotal: () => 20, newPosRequestId: () => "fallback-key-00000001",
    api: async (...args) => {calls.push(args);return receipt;},
    clearPosDraft() { this.posRequestId = ""; },
    showReceipt: (...args) => shown.push(args), toast: (message, error) => notifications.push({message,error}),
    VIEWS: {pos() {}},
  };
  vm.createContext(context);
  vm.runInContext(confirmFunction, context);
  await context.confirmPosSale();

  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], "/sales");
  assert.equal(calls[0][1], "POST");
  assert.equal(calls[0][2].doc_type, "comprobante_interno");
  assert.equal(calls[0][2].customer_doc, "12345678");
  assert.equal(shown.length, 1);
  assert.deepEqual(notifications, []);
  assert.equal(fields["#pos-submit"].disabled, false);
});

test("Nota de venta confirma sin leer ni enviar datos del cliente", async () => {
  const fields = {
    "#pos-doc": {value: "nota_interna"}, "#pos-cdoc": {value: "12345678"},
    "#pos-cname": {value: "Dato oculto"}, "#pos-caddr": {value: "Dirección oculta"},
    "#pos-identification-requested": {checked: true}, "#pos-pay": {value: "efectivo"},
    "#pos-ref": null, "#pos-submit": {disabled: false},
  };
  let request;
  const context = {
    META: {lookup_enabled: true, boleta_limit: 700},
    posCash: {id: 1}, posCart: [{product_id: 4, qty: 2}], posDiscountValue: 0,
    posDiscountApprovalId: "", posRequestId: "note-pos-request-key-0001",
    $: selector => fields[selector], posSubtotal: () => 20,
    newPosRequestId: () => "fallback-key-00000005",
    api: async (...args) => {request = args[2];return receipt;}, clearPosDraft() {},
    showReceipt() {}, toast() {}, VIEWS: {pos() {}},
  };
  vm.createContext(context);
  vm.runInContext(confirmFunction, context);
  await context.confirmPosSale();
  assert.equal(request.doc_type, "nota_interna");
  assert.equal(Object.hasOwn(request, "customer_doc"), false);
  assert.equal(Object.hasOwn(request, "customer_name"), false);
  assert.equal(Object.hasOwn(request, "customer_address"), false);
  assert.equal(Object.hasOwn(request, "customer_identification_requested"), false);
});

test("una venta seleccionada como boleta mantiene su tipo sin depender de CPE", async () => {
  const fields = {
    "#pos-doc": {value: "boleta"}, "#pos-cdoc": {value: "12345678"},
    "#pos-cname": {value: "Cliente antiguo"}, "#pos-caddr": null,
    "#pos-pay": {value: "yape"}, "#pos-ref": {value: "op-456"},
    "#pos-submit": {disabled: false},
  };
  let request;
  const notices = [];
  const context = {
    META: {electronic_invoicing_enabled: false, lookup_enabled: false},
    posCash: {id: 1}, posCart: [{product_id: 4, qty: 1}], posDiscountValue: 0,
    posDiscountApprovalId: "", posRequestId: "legacy-pos-request-key-0001",
    $: selector => fields[selector], posSubtotal: () => 10, newPosRequestId: () => "fallback-key-00000003",
    api: async (url, method, body) => { request = {url,method,body}; return receipt; },
    clearPosDraft() {}, showReceipt() {}, toast: (message, error) => notices.push({message,error}),
    VIEWS: {pos() {}},
  };
  vm.createContext(context);
  vm.runInContext(confirmFunction, context);
  await context.confirmPosSale();

  assert.equal(request.url, "/sales");
  assert.equal(request.method, "POST");
  assert.equal(request.body.doc_type, "boleta");
  assert.equal(request.body.payment_method, "yape");
  assert.deepEqual(notices, []);
});

test("un error del endpoint se muestra y no anuncia una venta guardada", async () => {
  const fields = {
    "#pos-doc": {value: "comprobante_interno"}, "#pos-cdoc": {value: "1234"},
    "#pos-cname": {value: ""}, "#pos-caddr": null, "#pos-pay": {value: "efectivo"},
    "#pos-ref": null, "#pos-submit": {disabled: false},
  };
  const notifications = [];
  let receiptShown = false;
  const context = {
    META: {electronic_invoicing_enabled: false, lookup_enabled: false},
    posCash: {id: 1}, posCart: [{product_id: 4, qty: 2}], posDiscountValue: 0,
    posDiscountApprovalId: "", posRequestId: "internal-confirmation-key-02",
    $: selector => fields[selector], posSubtotal: () => 20, newPosRequestId: () => "fallback-key-00000002",
    api: async () => {throw new Error("Documento de cliente no válido");}, clearPosDraft() {},
    showReceipt() {receiptShown = true;}, toast: (message, error) => notifications.push({message,error}),
    VIEWS: {pos() {}},
  };
  vm.createContext(context);
  vm.runInContext(confirmFunction, context);
  await context.confirmPosSale();

  assert.equal(receiptShown, false);
  assert.deepEqual(notifications, [{message: "Documento de cliente no válido", error: true}]);
  assert.equal(fields["#pos-submit"].disabled, false);
});

test("si falla APISPERU, una factura con RUC y razon social manual puede continuar", async () => {
  const fields = {
    "#pos-doc": {value: "factura"}, "#pos-customer": {innerHTML: ""},
    "#pos-cdoc": {value: "20123456789", oninput: null},
    "#pos-cname": {value: "EMPRESA MANUAL"}, "#pos-caddr": {value: "Dirección manual"},
    "#lookup-status": {textContent: "", classList: {add() {}, remove() {}}},
    "#pos-customer-lookup": {onclick: null}, "#pos-identification-requested": null,
    "#pos-pay": {value: "efectivo"}, "#pos-ref": null, "#pos-submit": {disabled: false},
  };
  const calls = [];
  const notifications = [];
  const context = {
    META: {electronic_invoicing_enabled: false, lookup_enabled: true, boleta_limit: 700},
    lookupState: {doc: "", type: "", valid: false},
    posCash: {id: 1}, posCart: [{product_id: 4, qty: 2}],
    posDiscountValue: 0, posDiscountApprovalId: "", posRequestId: "manual-invoice-request-0001",
    $: selector => fields[selector], money: value => `S/ ${value}`, posSubtotal: () => 20,
    newPosRequestId: () => "fallback-key-00000004",
    api: async (...args) => {
      calls.push(args);
      if (args[0].startsWith("/lookup/")) throw new Error("APISPERU sin conexión");
      return receipt;
    },
    clearPosDraft() {}, showReceipt() {},
    toast: (message, error) => notifications.push({message,error}), VIEWS: {pos() {}},
  };
  vm.createContext(context);
  vm.runInContext(customerFunctions, context);
  context.drawPosCustomer();
  await fields["#pos-customer-lookup"].onclick();
  assert.match(fields["#lookup-status"].textContent, /Puedes completar los datos manualmente/);
  vm.runInContext(confirmFunction, context);
  await context.confirmPosSale();

  assert.ok(calls.some(call => call[0] === "/lookup/ruc/20123456789"));
  const saleCall = calls.find(call => call[0] === "/sales");
  assert.ok(saleCall);
  assert.equal(saleCall[2].doc_type, "factura");
  assert.equal(saleCall[2].customer_doc, "20123456789");
  assert.equal(saleCall[2].customer_name, "EMPRESA MANUAL");
  assert.deepEqual(notifications, []);
});

test("imprimir una venta existente genera el documento sin enviar otra venta", () => {
  const {context, writes, calls} = harness();
  context.printTickets([receipt]);
  assert.equal(writes.length, 1);
  assert.match(writes[0], /INT-00000001/);
  assert.match(writes[0], /onload=\(\)=>print\(\)/);
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], "");
});

test("reimpresión recupera el comprobante guardado mediante GET y no crea una venta", async () => {
  const {context, writes, calls} = harness({receipt});
  await context.printSales([receipt.id]);
  assert.ok(calls.some(call => call[0] === `/sales/${receipt.id}`));
  assert.ok(!calls.some(call => call[0] === "/sales" && call[1] === "POST"));
  assert.match(writes.at(-1), /INT-00000001/);
});

test("los errores al recuperar el comprobante se muestran y cierran la ventana", async () => {
  const state = harness();
  state.context.api = async () => { throw new Error("conexión interrumpida"); };
  await state.context.printSales([receipt.id]);
  assert.equal(state.popup.closed, true);
  assert.deepEqual(state.notifications, [{message: "conexión interrumpida", error: true}]);
});
