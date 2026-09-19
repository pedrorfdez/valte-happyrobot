# Local dashboard `make up` design

**Date:** 2026-09-19

## Goal

Provide one foreground command, `make up`, that starts everything required locally for the dashboard to work against the already deployed Gateway. Supabase, HappyRobot, and the Gateway remain remote services; no local Azure Functions process is started.

## User interface

The repository root exposes these targets:

- `make up`: validate configuration and remote connectivity, serve `app/`, print the resolved dashboard URL, open it when the operating system provides a supported browser opener, and remain attached until `Ctrl-C`.
- `make check`: run the same configuration and Gateway checks without starting a server or opening a browser.
- `make help`: show the available targets and overrides.

`make up` uses `DANA_RUN_ID` from `.env` by default. A caller may select another run and port without editing files:

```bash
make up RUN_ID=run-wildfire-demo
make up PORT=4174
```

## Components

### Makefile

The `Makefile` is a small command interface. It declares phony targets and delegates lifecycle logic to a shell script. It does not duplicate environment loading, validation, URL construction, or process cleanup.

### Dashboard launcher

`scripts/dashboard-local.sh` owns the operational flow:

1. Resolve the repository root independently of the current working directory.
2. Load the root `.env` with automatic export enabled.
3. Resolve `RUN_ID` from the command override or `DANA_RUN_ID`.
4. Use an explicit remote `GATEWAY_URL`; when it is absent or equals the obsolete local Azure URL, derive the Supabase Edge base as `$SUPABASE_URL/functions/v1/gateway`.
5. Resolve `PORT` to `4173` when no override is provided.
6. Validate required commands, configuration, URL shape, run ID, and port.
7. Request `GET $GATEWAY_URL/api/snapshot?run_id=<encoded-run-id>` with a bounded timeout.
8. Build a browser-safe local URL containing the selected `run_id` and remote `gateway_url` query parameters.
9. Start `python3 -m http.server` for `app/`, wait until it responds locally, and then open or print the URL.
10. Stay in the foreground and forward shutdown by terminating only the Python process it created.

The URL is constructed with a standard-library URL encoder rather than shell concatenation so reserved characters cannot corrupt its query string.

## Error handling

The command exits before starting the dashboard when:

- `.env` is missing;
- `python3` or `curl` is unavailable;
- neither a usable `GATEWAY_URL` nor `SUPABASE_URL` is available, or the selected run ID still uses an example value;
- `GATEWAY_URL` is not an HTTP(S) base URL, or includes query parameters or credentials;
- the port is not an integer from 1 through 65535;
- the selected port is already occupied;
- the remote snapshot cannot be obtained successfully.

Each failure names the missing or invalid input and gives the next corrective action. The script never prints secret environment values. A missing browser opener is not fatal: the dashboard continues running and the complete local URL remains visible in the terminal.

## Runtime and safety boundaries

- Azure Functions are not launched locally.
- The launcher never migrates, seeds, or writes directly to Supabase.
- The launcher never starts or publishes HappyRobot workflows.
- Gateway connectivity is read-only during preflight.
- The Supabase Edge Gateway path `/functions/v1/gateway` is preserved when the launcher appends `/api/snapshot`.
- The obsolete `localhost:7071` setting is replaced in memory only when `SUPABASE_URL` is available; arbitrary remote Gateway URLs are never overridden.
- Supabase Realtime parameters are not required; the dashboard's existing polling path is sufficient for normal operation.
- `Ctrl-C` stops only the server process started by the current `make up` invocation.
- An occupied port is reported, never killed or reused implicitly.
- A released port can be reused immediately after `Ctrl-C`; the availability check follows the HTTP server's `SO_REUSEADDR` behavior.

## Documentation

The root README's local dashboard instructions will point to `make up` as the recommended path and state that it uses the deployed `GATEWAY_URL`. References that require a local Azure Functions process will not be presented as part of this dashboard startup path.

## Verification

Verification covers:

1. Shell syntax and Make target discovery.
2. Failure for a missing `.env`, invalid port, or unavailable Gateway.
3. `make check` succeeding against the configured remote Gateway without opening a local port.
4. `make up` serving the dashboard on the selected port.
5. The generated URL containing the selected run ID and remote Gateway, never `localhost:7071` unless explicitly configured by the user.
6. `Ctrl-C` stopping the server and releasing the port.
7. A second `make up` starting immediately on that released port.

## Acceptance criteria

- From the repository root, one `make up` command opens or prints a usable DANA dashboard URL and keeps the server attached to the terminal.
- The dashboard reads its snapshot from the deployed Gateway configured in `.env`.
- `make up RUN_ID=run-wildfire-demo` selects the wildfire run.
- No Azure Functions tooling is required.
- Failures are immediate, actionable, and do not leave a background server behind.
