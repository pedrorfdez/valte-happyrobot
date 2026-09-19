import snapshot from "../../../api/snapshot/index.mjs";
import commands from "../../../api/commands/index.mjs";
import eventRouter from "../../../api/event-router/index.mjs";
import runs from "../../../api/runs/index.mjs";

type AzureResponse = {
  status: number;
  headers?: Record<string, string>;
  body?: string;
};

type AzureContext = {
  res?: AzureResponse;
  log: {
    error: (...args: unknown[]) => void;
    warn: (...args: unknown[]) => void;
  };
};

type AzureRequest = {
  method?: string;
  query: Record<string, string>;
  headers: Record<string, string>;
  body?: string;
};

type AzureHandler = (
  context: AzureContext,
  request: AzureRequest,
) => Promise<void>;

const CORS_HEADERS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, POST, OPTIONS",
  "access-control-allow-headers": "accept, content-type",
  "access-control-max-age": "86400",
};

const ROUTES = new Map<string, AzureHandler>([
  ["GET /api/snapshot", snapshot],
  ["GET /api/runs", runs],
  ["POST /api/commands", commands],
  ["POST /api/event-router", eventRouter],
]);

const KNOWN_PATHS = new Set([
  "/api/snapshot",
  "/api/runs",
  "/api/commands",
  "/api/event-router",
]);

function json(status: number, body: Record<string, unknown>): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      ...CORS_HEADERS,
      "content-type": "application/json; charset=utf-8",
    },
  });
}

function gatewayPath(pathname: string): string | null {
  const marker = "/gateway";
  const markerIndex = pathname.lastIndexOf(marker);
  if (markerIndex === -1) return null;
  return pathname.slice(markerIndex + marker.length) || "/";
}

async function azureRequest(request: Request): Promise<AzureRequest> {
  const url = new URL(request.url);
  const body = request.method === "GET" ? undefined : await request.text();
  return {
    method: request.method,
    query: Object.fromEntries(url.searchParams.entries()),
    headers: Object.fromEntries(request.headers.entries()),
    body: body || undefined,
  };
}

Deno.serve(async (request) => {
  if (request.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: CORS_HEADERS });
  }

  const url = new URL(request.url);
  const path = gatewayPath(url.pathname);
  if (!path) return json(404, { error: "route_not_found" });

  const handler = ROUTES.get(`${request.method} ${path}`);
  if (!handler) {
    return KNOWN_PATHS.has(path)
      ? json(405, { error: "method_not_allowed" })
      : json(404, { error: "route_not_found" });
  }

  const context: AzureContext = {
    log: {
      error: (...args) => console.error(...args),
      warn: (...args) => console.warn(...args),
    },
  };

  try {
    await handler(context, await azureRequest(request));
    if (!context.res) {
      return json(500, { error: "gateway_response_missing" });
    }

    const headers = new Headers(context.res.headers);
    for (const [name, value] of Object.entries(CORS_HEADERS)) {
      headers.set(name, value);
    }
    return new Response(context.res.body ?? "", {
      status: context.res.status,
      headers,
    });
  } catch (error) {
    console.error(error);
    return json(500, { error: "gateway_failure", message: "internal error" });
  }
});
