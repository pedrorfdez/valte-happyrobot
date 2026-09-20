import { readFile } from "node:fs/promises";

const tokens = await readFile("app-v2/public/assets/valte-tokens.css", "utf8");
if (!tokens.includes("--surface-000")) throw new Error("missing --surface-000");
const html = await readFile("app-v2/index.html", "utf8");
if (!html.includes("width: 1440px") && !html.includes("width:1440px")) throw new Error("canvas not 1440x900: missing width 1440px");
if (!html.includes("height: 900px") && !html.includes("height:900px")) throw new Error("canvas not 1440x900: missing height 900px");
console.log("PASS tokens");
