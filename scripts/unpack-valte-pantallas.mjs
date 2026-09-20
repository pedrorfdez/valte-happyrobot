#!/usr/bin/env node
import { readFile, writeFile, mkdir, cp } from "node:fs/promises";
import { existsSync } from "node:fs";
import { execSync } from "node:child_process";
import { dirname, join } from "node:path";

const SRC_LOCAL = "Valte \u00B7 Pantallas.html";
const REF = "origin/feat/valte-v2";
const OUT_ROOT = "docs/reference/valte-pantallas";
const OUT_INDEX = join(OUT_ROOT, "index.html");

async function ensureDir(p) {
  await mkdir(p, { recursive: true });
}

function gitShowBuffer(refPath) {
  // refPath like `frontend/assets/valte-tokens.css` or `Valte · Pantallas.html`
  // Use git show with quoted ref; capture buffer (handles binary like woff2)
  const spec = `${REF}:${refPath}`;
  // Use JSON stringify to safely quote? Instead shell-escape via single quotes where possible.
  // Build command: git show 'origin/feat/valte-v2:Valte · Pantallas.html'
  // For safety we use execSync with shell and escape single quotes.
  const escaped = spec.replace(/'/g, `'\\''`);
  const cmd = `git show '${escaped}'`;
  try {
    const buf = execSync(cmd, { maxBuffer: 20 * 1024 * 1024 });
    return buf;
  } catch (e) {
    const msg = e.stderr ? e.stderr.toString() : e.message;
    throw new Error(`git show failed for ${spec}: ${msg}`);
  }
}

async function gitShowToFile(refPath, outPath) {
  await ensureDir(dirname(outPath));
  const buf = gitShowBuffer(refPath);
  await writeFile(outPath, buf);
  console.log(`  wrote ${outPath} (${buf.length} bytes)`);
}

async function listRefFiles() {
  // Use `git ls-tree -r --name-only` and parse
  const out = execSync(`git ls-tree -r --name-only '${REF}'`, { encoding: "utf8", maxBuffer: 10 * 1024 * 1024 });
  return out.split("\n").filter(Boolean);
}

async function main() {
  console.log("[unpack] Valte Pantallas reference unpack");
  const hasLocal = existsSync(SRC_LOCAL);
  await ensureDir(OUT_ROOT);

  // Step 1 behaviour: check for bundled html locally, log, fallback to git show
  if (hasLocal) {
    try {
      const buf = await readFile(SRC_LOCAL);
      await ensureDir(dirname(OUT_INDEX));
      await writeFile(OUT_INDEX, buf);
      console.log(`found bundled html: ${SRC_LOCAL} -> ${OUT_INDEX} (${buf.length} bytes)`);
    } catch (e) {
      console.error(`missing ${SRC_LOCAL}: ${e.message}`);
      process.exit(1);
    }
  } else {
    console.log(`local "${SRC_LOCAL}" not found, falling back to git show ${REF}:"${SRC_LOCAL}"`);
    try {
      // quick probe: try to git show the bundled html
      await gitShowToFile(SRC_LOCAL, OUT_INDEX);
      console.log(`found bundled html via git show -> ${OUT_INDEX}`);
    } catch (e) {
      console.error(`missing Valte \u00B7 Pantallas.html (local and ${REF}): ${e.message}`);
      process.exit(1);
    }
  }

  // Verify fallback ability for at least one token (plan Step 1 demo)
  // This also matches the plan's execSync example:
  try {
    execSync(`git show '${REF}:frontend/assets/valte-tokens.css' > /tmp/valte-tokens.css`, { stdio: "inherit" });
    console.log("  probe /tmp/valte-tokens.css OK (git show tokens)");
  } catch {
    console.warn("  probe /tmp/valte-tokens.csv failed (non-fatal)");
  }

  const allFiles = await listRefFiles();

  // Assets: frontend/assets/** -> docs/reference/valte-pantallas/assets/**
  const assetFiles = allFiles.filter((f) => f.startsWith("frontend/assets/"));
  if (assetFiles.length === 0) {
    console.error("no assets found in ref");
    process.exit(1);
  }
  console.log(`[unpack] assets: ${assetFiles.length} files from ${REF}:frontend/assets/`);
  for (const f of assetFiles) {
    const rel = f.replace(/^frontend\/assets\//, "");
    const out = join(OUT_ROOT, "assets", rel);
    await gitShowToFile(f, out);
  }

  // Design: frontend/design/*.body.html + *.mock.js (+ *.page.css for completeness)
  const designFiles = allFiles.filter((f) => f.startsWith("frontend/design/"));
  // Keep at least .body.html and .mock.js; include .page.css if present for pixel parity
  const wanted = designFiles.filter((f) => f.endsWith(".body.html") || f.endsWith(".mock.js") || f.endsWith(".page.css"));
  if (wanted.length === 0) {
    console.error("no design files found");
    process.exit(1);
  }
  console.log(`[unpack] design: ${wanted.length} files from ${REF}:frontend/design/`);
  await ensureDir(join(OUT_ROOT, "design"));
  for (const f of wanted) {
    const rel = f.replace(/^frontend\/design\//, "");
    const out = join(OUT_ROOT, "design", rel);
    await gitShowToFile(f, out);
  }

  // Summary
  const bodyCount = wanted.filter((f) => f.endsWith(".body.html")).length;
  const mockCount = wanted.filter((f) => f.endsWith(".mock.js")).length;
  console.log(`[unpack] done: ${bodyCount} body.html + ${mockCount} mock.js (+ ${wanted.length - bodyCount - mockCount} page.css)`);
  console.log(`[unpack] assets: ${assetFiles.length} files`);
  console.log(`[unpack] output root: ${OUT_ROOT}/`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
