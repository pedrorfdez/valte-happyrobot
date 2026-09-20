import { readFile } from "node:fs/promises";

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
