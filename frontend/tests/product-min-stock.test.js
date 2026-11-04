const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.resolve(__dirname, "../js/v-products.js"), "utf8");

test("editing minimum stock to zero persists, stays on products, and reloads zero", async () => {
  let stored = {
    id: 1,
    code: "MIN001",
    barcode: null,
    name: "Producto de prueba",
    category: "General",
    unit: "und",
    cost: 2.5,
    price: 4,
    stock: 10,
    min_stock: 5,
    presentations: [],
  };
  let lastModal;
  let purchaseViewCalls = 0;
  const elements = new Map();
  const getElement = selector => {
    if (!elements.has(selector)) {
      elements.set(selector, {value: "", innerHTML: "", files: [], classList: {toggle() {}, remove() {}}});
    }
    return elements.get(selector);
  };
  const context = {
    VIEWS: {purchases: async () => { purchaseViewCalls += 1; }},
    me: {role: "admin"},
    META: {units: ["und"], decimal_units: ["kg", "g", "lt", "m"]},
    UNIT: {und: "Unidad"},
    has: permission => ["products.write", "costs.read", "purchases.manage"].includes(permission),
    hasAny: (...permissions) => permissions.includes("stock.read"),
    api: async (url, method = "GET", body) => {
      if (url === "/products" && method === "GET") return [structuredClone(stored)];
      if (url === "/products/1" && method === "PUT") {
        assert.equal(body.min_stock, 0);
        assert.equal(body.current_stock, 12);
        const {current_stock, ...fields} = body;
        stored = {...stored, ...fields, stock: current_stock};
        return {ok: true};
      }
      throw new Error(`Unexpected API call: ${method} ${url}`);
    },
    modal: config => { lastModal = config; },
    $: getElement,
    $$: () => [],
    opts: () => "",
    esc: value => String(value ?? ""),
    num: value => String(value ?? 0),
    money: value => `S/ ${value}`,
    stockBadge: () => "Disponible",
    categoryStyle: () => "",
    chipsHtml: () => "",
    getProductImage: async () => "",
    saveProductImage: async () => {},
    toast: () => {},
    confirmBox: () => {},
    scanBarcode: async () => {},
  };
  vm.createContext(context);
  vm.runInContext(source, context);

  await vm.runInContext("VIEWS.products()", context);
  vm.runInContext("openProductForm(1)", context);
  assert.match(lastModal.html, /id="pf-min"[^>]*value="5"/);
  assert.match(lastModal.html, /id="pf-stock-current"[^>]*value="10"/);

  const values = {
    "#pf-name": "Producto de prueba",
    "#pf-category": "General",
    "#pf-unit": "und",
    "#pf-price": "4",
    "#pf-code": "MIN001",
    "#pf-barcode": "",
    "#pf-cost": "2.5",
    "#pf-min": "0",
    "#pf-stock-current": "12",
  };
  const form = {
    querySelector: selector => selector === "#pf-photo"
      ? {files: []}
      : {value: values[selector] ?? ""},
    querySelectorAll: () => [],
  };
  await lastModal.onSubmit(form);

  assert.equal(stored.min_stock, 0);
  assert.equal(stored.stock, 12);
  assert.equal(purchaseViewCalls, 0);
  assert.match(getElement("#product-cards").innerHTML, /Mínimo: 0/);

  vm.runInContext("openProductForm(1)", context);
  assert.match(lastModal.html, /id="pf-min"[^>]*value="0"/);
  assert.match(lastModal.html, /id="pf-stock-current"[^>]*value="12"/);
});

test("non-admin product editors do not receive the direct stock field", async () => {
  const context = {
    VIEWS: {},
    META: {units: ["und"], decimal_units: []},
    UNIT: {und: "Unidad"},
    me: {role: "almacen"},
    has: permission => permission === "products.write",
    api: async () => [],
    modal: config => { context.lastModal = config; },
    $: () => ({files: []}),
    $$: () => [],
    opts: () => "",
    esc: value => String(value ?? ""),
    num: value => String(value ?? 0),
  };
  vm.createContext(context);
  vm.runInContext(source, context);
  vm.runInContext("productsList = [{id: 1, name: 'Producto', min_stock: 5, stock: 10, presentations: []}]; openProductForm(1)", context);
  assert.doesNotMatch(context.lastModal.html, /id="pf-stock-current"/);
});
