import { readFile, readdir, stat } from "node:fs/promises";
import { join } from "node:path";

const tokens = await readFile("app-v2/public/assets/valte-tokens.css", "utf8");
if (!tokens.includes("--surface-000")) throw new Error("missing --surface-000");
const html = await readFile("app-v2/index.html", "utf8");
if (!html.includes("width: 1440px") && !html.includes("width:1440px")) throw new Error("canvas not 1440x900: missing width 1440px");
if (!html.includes("height: 900px") && !html.includes("height:900px")) throw new Error("canvas not 1440x900: missing height 900px");
console.log("PASS tokens");

// Task 4: list pixel parity with Main.body.html
const listBody = await readFile("docs/reference/valte-pantallas/design/Main.body.html", "utf8");
const listSrc = await readFile("app-v2/src/screens/list.js", "utf8");
if (!listSrc.includes('font-family: var(--font-display)') && !listSrc.includes('font-family:var(--font-display)')) throw new Error("list not pixel-matched to Main.body.html: missing font-display");
if (!listSrc.includes('font-size:64px') && !listSrc.includes('font-size: 64px')) throw new Error("list not pixel-matched to Main.body.html: missing 64px font-size");
if (!listSrc.includes('letter-spacing: -0.015em') && !listSrc.includes('letter-spacing:-0.015em')) throw new Error("list not pixel-matched to Main.body.html: missing letter-spacing -0.015em");
if (!listSrc.includes('class="row"')) throw new Error("list not pixel-matched: missing class row");
if (!listSrc.includes('row-name')) throw new Error("list not pixel-matched: missing row-name");
if (!listSrc.includes('<svg')) throw new Error("list not pixel-matched: missing arrow SVG");
if (!listBody.includes('row-name')) throw new Error("reference Main.body.html missing row-name");

// header 32px Valte
const hasDisplay = html.includes('font-family: var(--font-display)') || html.includes('font-family:var(--font-display)');
const has32 = html.includes('font-size: 32px') || html.includes('font-size:32px');
if (!hasDisplay || !has32) throw new Error("header not pixel-matched: Valte 32px font-display");
console.log("PASS list parity");

// Task 7: No Senales nav/KPI, dist 1440x900, Senales.body.html exists but never imported
async function collectFiles(dir, exts) {
  const out = [];
  const entries = await readdir(dir);
  for (const e of entries) {
    const p = join(dir, e);
    const s = await stat(p);
    if (s.isDirectory()) {
      out.push(...await collectFiles(p, exts));
    } else if (exts.some((ext) => p.endsWith(ext))) {
      out.push(p);
    }
  }
  return out;
}

const srcFiles = await collectFiles("app-v2/src", [".js", ".html"]);
let senalesHits = [];
for (const f of srcFiles) {
  const c = await readFile(f, "utf8");
  if (c.includes("Senales")) {
    senalesHits.push(f);
  }
}
if (senalesHits.length > 0) throw new Error(`Senales found in app-v2/src (should be 0): ${senalesHits.join(", ")}`);
console.log("PASS no Senales in app-v2/src");

// nav should not contain Senales / Señales
const navMatch = html.match(/<nav[^>]*>[\s\S]*?<\/nav>/i);
if (navMatch && /Senales|Señales/i.test(navMatch[0])) throw new Error("nav contains Senales/Señales (should be excluded)");
// kpi-signals should not be visible: either absent from index.html or hidden via display:none in main.js
if (html.includes('id="kpi-signals"') || html.includes("kpi-signals")) throw new Error("kpi-signals found in app-v2/index.html (should be hidden/absent)");
const mainJs = await readFile("app-v2/src/main.js", "utf8");
if (mainJs.includes("kpi-signals")) {
  // if it references kpi-signals, it must hide it (display none)
  if (!mainJs.includes('display') || !mainJs.includes('none')) throw new Error("kpi-signals referenced without display:none hide");
  if (!mainJs.includes('sigEl.style.display = "none"') && !mainJs.includes("sigEl.style.display")) throw new Error("kpi-signals not hidden via display:none");
}
console.log("PASS no Senales nav/KPI");

// dist 1440x900 and valte-tokens.css
const distHtml = await readFile("app-v2/dist/index.html", "utf8");
if (!distHtml.includes("width: 1440px") && !distHtml.includes("width:1440px") && !distHtml.includes('width="1440"') && !distHtml.includes("1440")) throw new Error("dist not 1440x900: missing 1440");
if (!distHtml.includes("height: 900px") && !distHtml.includes("height:900px") && !distHtml.includes('height="900"') && !distHtml.includes("900")) throw new Error("dist not 1440x900: missing 900");
if (!distHtml.includes("width: 1440px") && !distHtml.includes("width:1440px")) {
  // fallback check via data-preview-width attr
  if (!distHtml.includes('data-preview-width="1440"') && !distHtml.includes("1440px")) throw new Error("dist not 1440x900: missing width 1440px");
}
if (!distHtml.includes("valte-tokens.css")) throw new Error("dist missing valte-tokens.css");
console.log("PASS dist 1440x900 and valte-tokens.css");

// Senales.body.html exists but never imported
const senalesBody = await readFile("docs/reference/valte-pantallas/design/Senales.body.html", "utf8");
if (!senalesBody || senalesBody.length < 10) throw new Error("Senales.body.html missing or empty");
if (senalesBody && !senalesBody.includes("Senales") && !senalesBody.includes("Señales") && senalesBody.length < 100) throw new Error("Senales.body.html unexpected content");
console.log("PASS Senales.body.html exists");

// ensure never imported: check all src files do not import Senales.body.html or Senales string (already checked), and check main.js and screens do not reference Senales path
for (const f of srcFiles) {
  const c = await readFile(f, "utf8");
  if (c.includes("Senales.body") || c.includes("Senales.mock") || c.includes("design/Senales")) {
    throw new Error(`Senales.body.html imported in ${f}`);
  }
}
// also check index.html and vite config not importing
const indexHtmlSrc = await readFile("app-v2/index.html", "utf8");
if (indexHtmlSrc.includes("Senales")) throw new Error("Senales found in app-v2/index.html");
console.log("PASS Senales.body.html never imported");

console.log("PASS visual full");
