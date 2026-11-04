const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const root = path.resolve(__dirname, "../..");
const core = fs.readFileSync(path.join(root, "frontend/js/core.js"), "utf8");
const pos = fs.readFileSync(path.join(root, "frontend/js/v-pos.js"), "utf8");
const scannerSource = core.slice(core.indexOf("const SCANNER_FORMATS="), core.indexOf("\nfunction ticketHtml"));
const modalSource = core.slice(core.indexOf("let activeModalClose=null;"), core.indexOf("\nfunction confirmBox"));

function makeHarness({BarcodeDetector, ZXingBrowser, getUserMedia, scriptFailure} = {}) {
  const stoppedTracks = [];
  const tracks = [{stop() { stoppedTracks.push(true); }}];
  const stream = {getTracks: () => tracks};
  const video = {
    readyState: 2,
    srcObject: null,
    muted: false,
    playsInline: false,
    played: false,
    paused: false,
    async play() { this.played = true; },
    pause() { this.paused = true; },
  };
  const status = {textContent: ""};
  const input = {value: "", onkeydown: null};
  const submit = {onclick: null};
  const elements = {video, ".scan-status": status, ".manual-code": input, ".manual-submit": submit};
  let modalConfig;
  let closed = false;
  const modalInstance = {
    element: {querySelector: selector => elements[selector]},
    close() {
      if (closed) return;
      closed = true;
      modalConfig.onClose?.();
    },
  };
  const frames = [];
  let frameId = 0;
  const context = {
    window: {BarcodeDetector, ZXingBrowser},
    navigator: {mediaDevices: {getUserMedia: getUserMedia || (async constraints => {
      context.constraints = constraints;
      return stream;
    })}},
    document: {createElement: () => ({}), head: {appendChild(script) { if (scriptFailure) script.onerror(); }}},
    modal: config => {modalConfig = config; return modalInstance;},
    requestAnimationFrame: callback => {frames.push(callback); return ++frameId;},
    cancelAnimationFrame: () => {},
    stoppedTracks,
    stream,
    video,
    status,
    input,
    submit,
    frames,
    modalInstance,
    scanned: [],
  };
  vm.createContext(context);
  vm.runInContext(scannerSource, context);
  return context;
}

test("Ventas muestra un solo botón de escaneo con el nombre solicitado", () => {
  assert.equal((pos.match(/onclick="posScan\(\)"/g) || []).length, 1);
  assert.match(pos, /onclick="posScan\(\)">Escanear código<\/button>/);
});

test("la cámara real se inicia con preferencia trasera y una lectura llama una sola vez", async () => {
  let detectorFormats;
  class Detector {
    static async getSupportedFormats() { return ["ean_13", "code_128"]; }
    constructor(options) { this.formats = options.formats; detectorFormats = options.formats; }
    async detect(video) {
      assert.equal(video.srcObject, context.stream);
      return [{rawValue: "0123456789012"}];
    }
  }
  const context = makeHarness({BarcodeDetector: Detector});
  await context.scanBarcode({onScan: code => context.scanned.push(code)});

  assert.equal(context.video.played, true);
  assert.equal(context.constraints.video.facingMode.ideal, "environment");
  assert.deepEqual(Array.from(detectorFormats), ["ean_13", "code_128"]);
  const scanFrame = context.frames.shift();
  await scanFrame();
  assert.deepEqual(context.scanned, ["0123456789012"]);
  assert.equal(context.stoppedTracks.length, 1);
  assert.equal(context.video.srcObject, null);
  assert.equal(context.video.paused, true);
  context.submit.onclick();
  assert.deepEqual(context.scanned, ["0123456789012"]);
});

test("ZXing Browser queda como respaldo cuando BarcodeDetector no existe", async () => {
  let zxingStopped = 0;
  class Reader {
    async decodeFromStream(stream, preview, callback) {
      assert.equal(stream, context.stream);
      assert.equal(preview, context.video);
      callback({getText: () => "ZXING-001"});
      return {stop() { zxingStopped += 1; }};
    }
  }
  const context = makeHarness({ZXingBrowser: {BrowserMultiFormatReader: Reader}});
  await context.scanBarcode({onScan: code => context.scanned.push(code)});
  assert.deepEqual(context.scanned, ["ZXING-001"]);
  assert.equal(zxingStopped, 1);
  assert.equal(context.stoppedTracks.length, 1);
  assert.equal(context.video.srcObject, null);
});

test("lector de respaldo inaccesible conserva la escritura manual y detiene la cámara", async () => {
  const context = makeHarness({scriptFailure: true});
  await context.scanBarcode({onScan: code => context.scanned.push(code)});
  assert.match(context.status.textContent, /No se pudo cargar el lector automático/);
  assert.equal(context.stoppedTracks.length, 1);
  context.input.value = "CODIGO-LOCAL";
  context.submit.onclick();
  assert.deepEqual(context.scanned, ["CODIGO-LOCAL"]);
});

test("una detección vacía se identifica como código inválido sin cerrar el escáner", async () => {
  class Detector {
    static async getSupportedFormats() { return ["ean_13"]; }
    constructor() {}
    async detect() { return [{rawValue: ""}]; }
  }
  const context = makeHarness({BarcodeDetector: Detector});
  await context.scanBarcode({onScan: code => context.scanned.push(code)});
  await context.frames.shift()();
  assert.match(context.status.textContent, /código inválido/);
  assert.deepEqual(context.scanned, []);
  context.modalInstance.close();
  assert.equal(context.stoppedTracks.length, 1);
});

test("cerrar mientras se solicita permiso detiene la pista cuando llega el stream", async () => {
  let resolveCamera;
  const context = makeHarness({getUserMedia: () => new Promise(resolve => { resolveCamera = resolve; })});
  const opening = context.scanBarcode({onScan: code => context.scanned.push(code)});
  context.modalInstance.close();
  resolveCamera(context.stream);
  await opening;
  assert.equal(context.stoppedTracks.length, 1);
  assert.equal(context.video.srcObject, null);
  assert.deepEqual(context.scanned, []);
});

test("closeModal también ejecuta la limpieza del escáner una sola vez", () => {
  let cleanupCalls = 0;
  const overlay = {addEventListener() {}, querySelector() { return null; }};
  const rootElement = {
    firstElementChild: null,
    set innerHTML(value) { this._html = value; this.firstElementChild = value ? overlay : null; },
    get innerHTML() { return this._html || ""; },
  };
  const context = {
    $: selector => selector === "#modal-root" ? rootElement : null,
    esc: value => String(value ?? ""),
    document: {addEventListener() {}, removeEventListener() {}},
  };
  vm.createContext(context);
  vm.runInContext(modalSource, context);
  context.modal({title: "Escáner", html: "", noButtons: true, onClose() { cleanupCalls += 1; }});
  context.closeModal();
  context.closeModal();
  assert.equal(cleanupCalls, 1);
});

test("permiso denegado muestra una explicación y permite escribir el código", async () => {
  const denied = Object.assign(new Error("permission denied"), {name: "NotAllowedError"});
  const context = makeHarness({getUserMedia: async () => { throw denied; }});
  await context.scanBarcode({onScan: code => context.scanned.push(code)});
  assert.match(context.status.textContent, /No se autorizó el acceso a la cámara/);
  context.submit.onclick();
  assert.match(context.status.textContent, /vacío o no es válido/);
  context.input.value = "PLU-42";
  context.submit.onclick();
  assert.deepEqual(context.scanned, ["PLU-42"]);
});

test("cámara no disponible muestra un mensaje específico", async () => {
  const missingCamera = Object.assign(new Error("camera missing"), {name: "NotFoundError"});
  const context = makeHarness({getUserMedia: async () => { throw missingCamera; }});
  await context.scanBarcode();
  assert.match(context.status.textContent, /No hay una cámara disponible/);
});

test("el escaneo llena el buscador y conserva la acción de agregar el resultado", async () => {
  const input = {value: "", focused: false, focus() { this.focused = true; }};
  const chips = [{dataset: {value: ""}, classList: {toggle(value) { this.selected = value; }}}];
  let drawn = 0;
  const added = [];
  const context = {
    scanBarcode: async ({onScan}) => onScan("0012345678905"),
    $: () => input,
    $$: () => chips,
    posCatalog: [{id: 7, code: "SKU7", barcode: "0012345678905", name: "Leche", category: "Bebidas", presentations: []}],
    posCart: [],
    category: "Otros",
    searchTerm: "",
    drawPosCatalog() { drawn += 1; },
    toast() {},
    addPosItem(id, presentationId) { added.push({id, presentationId}); },
  };
  const posScan = pos.match(/^async function posScan\(\).*$/m)[0];
  const posMatches = pos.match(/^function posMatches\(p,q\).*$/m)[0];
  const posSearchKey = pos.match(/^function posSearchKey\(e\).*$/m)[0];
  vm.createContext(context);
  vm.runInContext(`${posMatches}\n${posScan}\n${posSearchKey}`, context);
  await context.posScan();

  assert.equal(input.value, "0012345678905");
  assert.equal(context.searchTerm, "0012345678905");
  assert.equal(context.category, "");
  assert.equal(drawn, 1);
  assert.equal(input.focused, true);
  context.posSearchKey({key: "Enter", target: input, preventDefault() {}});
  assert.deepEqual(added, [{id: 7, presentationId: null}]);
});
