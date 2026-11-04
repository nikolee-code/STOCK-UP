const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const root = path.resolve(__dirname, "../..");
const core = fs.readFileSync(path.join(root, "frontend/js/core.js"), "utf8");
const app = fs.readFileSync(path.join(root, "frontend/app.js"), "utf8");
const menuStart = core.indexOf("function MENU() {");
const menuEnd = core.indexOf("/* Mostrar u ocultar", menuStart);
const permittedStart = app.indexOf("function permitted(item)");
const permittedEnd = app.indexOf("\n}", permittedStart) + 2;
const menuSource = core.slice(menuStart, menuEnd);
const permittedSource = app.slice(permittedStart, permittedEnd);

function visibleMenuIds(permissions) {
  const context = {
    me: {role: "almacen", additional_roles: ["cajero"], perms: permissions},
    has: permission => permissions.includes("*") || permissions.includes(permission),
    hasAny: (...items) => items.some(permission => permissions.includes("*") || permissions.includes(permission)),
  };
  vm.runInNewContext(menuSource + "\nthis.menuItems = MENU();", context);
  vm.runInNewContext(permittedSource, context);
  return Array.from(vm.runInNewContext("menuItems.filter(permitted).map(item => item.id)", context));
}

test("Almacén + Cajero gets all cashier and warehouse navigation without duplicates", () => {
  const permissions = [...new Set([
    "dashboard", "products.read", "products.write", "costs.read", "stock.read", "stock.adjust",
    "sales.create", "sales.own", "cash.own", "expenses.create", "notifications.read",
  ])];
  const ids = visibleMenuIds(permissions);
  for (const id of ["dashboard", "products", "pos", "cash", "myops", "authorizations"]) {
    assert.ok(ids.includes(id), `missing ${id}`);
  }
  assert.ok(!ids.includes("users"));
  assert.equal(new Set(ids).size, ids.length);
});

test("additional Contador permissions reveal shared sales documents", () => {
  const permissions = [
    "dashboard", "products.read", "products.write", "costs.read", "stock.read", "stock.adjust",
    "sales.create", "sales.own", "cash.own", "expenses.create", "expenses.read", "notifications.read",
    "sales.read", "profit.read",
  ];
  const ids = visibleMenuIds(permissions);
  assert.ok(ids.includes("documents"));
  assert.ok(ids.includes("expenses"));
  assert.equal(new Set(ids).size, ids.length);
});

test("administrator wildcard exposes the complete unique menu", () => {
  const ids = visibleMenuIds(["*"]);
  assert.ok(ids.includes("users"));
  assert.ok(ids.includes("settings"));
  assert.equal(new Set(ids).size, ids.length);
});
