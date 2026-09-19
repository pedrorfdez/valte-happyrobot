const required = (name) => {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required`);
  return value;
};

const REQUEST_TIMEOUT_MS = 15_000;

export const jsonResponse = (status, body) => ({
  status,
  headers: { "content-type": "application/json; charset=utf-8" },
  body: JSON.stringify(body)
});

export async function supabaseRequest(path, { method = "GET", body } = {}) {
  const baseUrl = required("SUPABASE_URL").replace(/\/$/, "");
  const serviceKey = required("SUPABASE_SERVICE_ROLE_KEY");
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
