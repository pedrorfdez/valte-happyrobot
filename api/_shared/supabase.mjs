export function readEnv(name) {
  return globalThis.Deno?.env?.get?.(name)
    ?? globalThis.process?.env?.[name];
}

export function requiredEnv(name) {
  const value = readEnv(name);
  if (!value) throw new Error(`${name} is required`);
  return value;
}

function supabaseSecretKey() {
  const rawKeys = readEnv("SUPABASE_SECRET_KEYS");
  if (rawKeys) {
    let keys;
    try {
      keys = JSON.parse(rawKeys);
    } catch {
      throw new Error("SUPABASE_SECRET_KEYS must be valid JSON");
    }
    if (typeof keys?.default === "string" && keys.default) return keys.default;
    throw new Error("SUPABASE_SECRET_KEYS.default is required");
  }
  return requiredEnv("SUPABASE_SERVICE_ROLE_KEY");
}

const REQUEST_TIMEOUT_MS = 15_000;

export const jsonResponse = (status, body) => ({
  status,
  headers: { "content-type": "application/json; charset=utf-8" },
  body: JSON.stringify(body)
});

export function requireGatewayAuth(req, context) {
  const token = readEnv("GATEWAY_TOKEN");
  if (!token) return;
  const provided = req.headers?.["x-gateway-token"] ?? req.headers?.["X-Gateway-Token"];
  if (provided !== token) {
    context.log.warn?.("gateway auth failed");
    const err = new Error("gateway auth required");
    err.status = 401;
    err.exposeMessage = true;
    throw err;
  }
}

export async function supabaseRequest(path, { method = "GET", body } = {}) {
  const baseUrl = requiredEnv("SUPABASE_URL").replace(/\/$/, "");
  const serviceKey = supabaseSecretKey();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  let response;
  try {
    response = await fetch(`${baseUrl}/rest/v1/${path}`, {
      method,
      headers: {
        apikey: serviceKey,
        authorization: `Bearer ${serviceKey}`,
        "content-type": "application/json",
        accept: "application/json"
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal
    });
  } finally {
    clearTimeout(timeout);
  }

  const text = await response.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { message: text };
    }
  }

  if (!response.ok) {
    const safeMessage = `Supabase request failed with ${response.status}`;
    const error = new Error(safeMessage);
    error.status = response.status;
    error.details = data;
    error.exposeMessage = false;
    throw error;
  }

  return data;
}

export const callRpc = (name, args) =>
  supabaseRequest(`rpc/${name}`, { method: "POST", body: args });
