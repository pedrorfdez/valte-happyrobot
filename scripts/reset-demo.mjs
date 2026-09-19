import { readFile } from "node:fs/promises";

const demoRunIds = new Set(["run-dana-demo", "run-wildfire-demo"]);
const args = process.argv.slice(2);
if (args.some((argument) => argument !== "--apply")) {
  console.error("Usage: node scripts/reset-demo.mjs [--apply]");
  process.exit(2);
}
const apply = args.includes("--apply");

function required(name) {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required; load .env first`);
  return value;
}

function validateSeed(sql) {
  const runIds = new Set([...sql.matchAll(/'(run-[^']+)'/g)].map(([, id]) => id));
  if (runIds.size !== demoRunIds.size || [...runIds].some((id) => !demoRunIds.has(id))) {
    throw new Error("Refusing to reset: supabase/seed.sql contains unexpected run IDs");
  }

  const deletes = [...sql.matchAll(/\bdelete\s+from\b[\s\S]*?;/gi)].map(([statement]) => statement);
  const unscopedDelete = deletes.some((statement) => {
    const where = statement.match(/\bwhere\s+run_id\s+in\s*\(([^)]*)\)/i);
    const ids = where ? [...where[1].matchAll(/'([^']+)'/g)].map(([, id]) => id) : [];
    return ids.length !== demoRunIds.size || new Set(ids).size !== demoRunIds.size
      || ids.some((id) => !demoRunIds.has(id));
  });
  if (deletes.length === 0 || unscopedDelete) {
    throw new Error("Refusing to reset: every DELETE must target only the two demo runs");
  }
}

try {
  const sql = await readFile(new URL("../supabase/seed.sql", import.meta.url), "utf8");
  validateSeed(sql);

  if (!apply) {
    console.log("DRY RUN: only run-dana-demo and run-wildfire-demo would be reset.");
    console.log("Pass --apply to execute the reset through the Supabase Management API.");
  } else {
    const projectUrl = new URL(required("SUPABASE_URL"));
    if (projectUrl.protocol !== "https:" || !projectUrl.hostname.endsWith(".supabase.co")) {
      throw new Error("SUPABASE_URL must be an https://<project-ref>.supabase.co URL");
    }

    const projectRef = projectUrl.hostname.slice(0, -".supabase.co".length);
    const response = await fetch(
      `https://api.supabase.com/v1/projects/${projectRef}/database/query`,
      {
        method: "POST",
        headers: {
          authorization: `Bearer ${required("SUPABASE_ACCESS_TOKEN")}`,
          "content-type": "application/json"
        },
        body: JSON.stringify({ query: sql }),
        signal: AbortSignal.timeout(30_000)
      }
    );
    if (!response.ok) {
      throw new Error(`Supabase Management API reset failed (HTTP ${response.status})`);
    }

    console.log(`PASS reset: run-dana-demo and run-wildfire-demo on project ${projectRef}`);
  }
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
