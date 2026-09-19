/**
 * Valte v2 Realtime adapter
 * Supabase Realtime hint → debounced fetchSnapshot + polling fallback
 * Health: live / degraded / stale / offline (spec §14)
 *
 * Usage:
 *   const mgr = createRealtimeManager({ runId, fetchSnapshot, onSnapshot, onHealthChange });
 *   await mgr.start();
 *   mgr.triggerRefresh("realtime");
 *   mgr.stop();
 */

export const HEALTH = {
  LIVE: "live",
  DEGRADED: "degraded",
  STALE: "stale",
  OFFLINE: "offline",
};

function nowMs() {
  return Date.now();
}

/**
 * @param {Object} opts
 * @param {string} opts.runId
 * @param {() => Promise<any>} opts.fetchSnapshot - async function to fetch fresh snapshot
 * @param {(snap:any)=>void} [opts.onSnapshot]
 * @param {(health:string)=>void} [opts.onHealthChange]
 * @param {(err:Error)=>void} [opts.onError] - called for errors; 404 triggers offline
 * @param {string} [opts.supabaseUrl]
 * @param {string} [opts.supabaseAnonKey]
 * @param {number} [opts.pollIntervalMs=5000]
 * @param {number} [opts.staleThresholdMs=30000]
 * @param {number} [opts.debounceMs=250]
 * @param {Function} [opts.createClient] - injectable supabase createClient for tests
 * @param {any} [opts.supabaseClient] - pre-created client for tests
 */
export function createRealtimeManager(opts = {}) {
  if (!opts.runId || typeof opts.runId !== "string") throw new Error("runId required");
  if (typeof opts.fetchSnapshot !== "function") throw new Error("fetchSnapshot required");

  const pollIntervalMs = opts.pollIntervalMs ?? 5000;
  const staleThresholdMs = opts.staleThresholdMs ?? 30000;
  const debounceMs = opts.debounceMs ?? 250;
  const onSnapshot = opts.onSnapshot || (() => {});
  const onHealthChange = opts.onHealthChange || (() => {});
  const onError = opts.onError || (() => {});

  let realtimeClient = opts.supabaseClient || null;
  let realtimeChannel = null;
  let realtimeSubscribed = false;

  let lastSuccessfulSync = 0;
  let consecutiveFailures = 0;

  let refreshTimer = null;
  let refreshWaiters = [];
  let debounceTimer = null;

  let pollTimer = null;
  let healthTimer = null;
  let currentHealth = HEALTH.OFFLINE;
  let started = false;

  function computeHealth() {
    const age = lastSuccessfulSync ? nowMs() - lastSuccessfulSync : Infinity;
    if (age <= 10_000 && realtimeSubscribed) return HEALTH.LIVE;
    if (age <= 10_000) return HEALTH.DEGRADED;
    if (age <= staleThresholdMs) return HEALTH.STALE;
    return HEALTH.OFFLINE;
  }

  function emitHealthIfChanged() {
    const next = computeHealth();
    if (next !== currentHealth) {
      currentHealth = next;
      try { onHealthChange(currentHealth); } catch {}
    }
    return currentHealth;
  }

  function getHealth() {
    return computeHealth();
  }

  async function doFetch(reason) {
    try {
      const snap = await opts.fetchSnapshot();
      // validate at least run exists
      if (!snap || typeof snap !== "object" || !snap.run) throw new Error("Snapshot invalid");
      lastSuccessfulSync = nowMs();
      consecutiveFailures = 0;
      emitHealthIfChanged();
      try { onSnapshot(snap, reason); } catch {}
      return snap;
    } catch (err) {
      consecutiveFailures += 1;
      // 404 run_not_found → offline and notify
      if (err && (err.status === 404 || err.code === "run_not_found" || String(err.message).includes("run_not_found"))) {
        currentHealth = HEALTH.OFFLINE;
        try { onHealthChange(currentHealth); } catch {}
        try { onError(err); } catch {}
        throw err;
      }
      // other errors keep polling; health may become stale/offline
      emitHealthIfChanged();
      try { onError(err); } catch {}
      throw err;
    }
  }

  // Debounced trigger that coalesces multiple calls
  function triggerRefresh(reason = "realtime") {
    // Return promise that resolves when debounced fetch completes
    const p = new Promise((resolve, reject) => {
      refreshWaiters.push({ resolve, reject });
    });

    if (debounceTimer) clearTimeout(debounceTimer);

    debounceTimer = setTimeout(async () => {
      debounceTimer = null;
      const waiters = refreshWaiters.splice(0);
      // Coalesce to single fetch
      try {
        const snap = await doFetch(reason);
        for (const w of waiters) w.resolve(snap);
      } catch (e) {
        for (const w of waiters) w.reject(e);
      }
    }, debounceMs);

    return p;
  }

  // Immediate refresh without debounce (for version_conflict, command success)
  async function refreshNow(reason = "manual") {
    if (debounceTimer) {
      clearTimeout(debounceTimer);
      debounceTimer = null;
      // flush waiters before immediate?
    }
    // If there's a pending debounce, we resolve those waiters with this fetch
    const waiters = refreshWaiters.splice(0);
    try {
      const snap = await doFetch(reason);
      for (const w of waiters) w.resolve(snap);
      return snap;
    } catch (e) {
      for (const w of waiters) w.reject(e);
      throw e;
    }
  }

  async function startRealtime() {
    const url = opts.supabaseUrl;
    const key = opts.supabaseAnonKey;

    // Allow injected client for tests, otherwise try to connect if credentials present
    if (realtimeClient) {
      try {
        realtimeChannel = realtimeClient
          .channel(`ops-events-${opts.runId}`)
          .on("postgres_changes", { event: "INSERT", schema: "public", table: "events", filter: `run_id=eq.${opts.runId}` }, () => {
            void triggerRefresh("realtime").catch(() => {});
          });

        // subscribe callback handling
        if (typeof realtimeChannel.subscribe === "function") {
          const sub = realtimeChannel.subscribe((status) => {
            const prev = realtimeSubscribed;
            realtimeSubscribed = status === "SUBSCRIBED";
            if (["CHANNEL_ERROR", "TIMED_OUT", "CLOSED"].includes(status)) realtimeSubscribed = false;
            if (prev !== realtimeSubscribed) emitHealthIfChanged();
          });
          // For mock clients that return promise or not
          if (sub && typeof sub.then === "function") {
            await sub.catch(() => { realtimeSubscribed = false; emitHealthIfChanged(); });
          }
        } else {
          realtimeSubscribed = true;
          emitHealthIfChanged();
        }
      } catch {
        realtimeSubscribed = false;
        emitHealthIfChanged();
      }
      return;
    }

    if (!url || !key) {
      realtimeSubscribed = false;
      emitHealthIfChanged();
      return;
    }

    if (typeof opts.createClient === "function") {
      try {
        realtimeClient = opts.createClient(url, key);
        await startRealtime();
      } catch {
        realtimeSubscribed = false;
        emitHealthIfChanged();
      }
      return;
    }

    // Try dynamic import of supabase-js if available (browser)
    try {
      const mod = await import("https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.45.4/+esm").catch(() => null);
      if (mod && mod.createClient) {
        realtimeClient = mod.createClient(url, key, { auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false } });
        realtimeChannel = realtimeClient
          .channel(`ops-events-${opts.runId}`)
          .on("postgres_changes", { event: "INSERT", schema: "public", table: "events", filter: `run_id=eq.${opts.runId}` }, () => {
            void triggerRefresh("realtime").catch(() => {});
          })
          .subscribe((status) => {
            realtimeSubscribed = status === "SUBSCRIBED";
            if (["CHANNEL_ERROR", "TIMED_OUT", "CLOSED"].includes(status)) realtimeSubscribed = false;
            emitHealthIfChanged();
          });
      }
    } catch {
      realtimeSubscribed = false;
      emitHealthIfChanged();
    }
  }

  function startPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(() => {
      const age = lastSuccessfulSync ? nowMs() - lastSuccessfulSync : Infinity;
      const needsReconciliation = age >= staleThresholdMs;
      if (!realtimeSubscribed || needsReconciliation) {
        void triggerRefresh(realtimeSubscribed ? "reconcile" : "poll").catch(() => {});
      }
    }, pollIntervalMs);
    // Also run health timer every second for stale detection
    if (healthTimer) clearInterval(healthTimer);
    healthTimer = setInterval(() => {
      emitHealthIfChanged();
    }, 1000);
  }

  function stopPolling() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    if (healthTimer) { clearInterval(healthTimer); healthTimer = null; }
    if (debounceTimer) { clearTimeout(debounceTimer); debounceTimer = null; }
  }

  async function start() {
    if (started) return;
    started = true;
    // initial sync with degraded health until success
    try {
      await doFetch("initial");
    } catch {
      // remain offline/stale, polling will retry
    }
    await startRealtime();
    startPolling();
    emitHealthIfChanged();
  }

  async function stop() {
    started = false;
    stopPolling();
    if (debounceTimer) { clearTimeout(debounceTimer); debounceTimer = null; }
    refreshWaiters = [];
    if (realtimeClient && realtimeChannel && typeof realtimeClient.removeChannel === "function") {
      try { await realtimeClient.removeChannel(realtimeChannel); } catch {}
    }
    realtimeChannel = null;
    // keep lastSuccessfulSync for health calculation but allow offline transition
    // Do not clear realtimeSubscribed immediately; set false and emit
    realtimeSubscribed = false;
    emitHealthIfChanged();
  }

  // Test helpers
  function _setRealtimeSubscribed(val) {
    realtimeSubscribed = !!val;
    emitHealthIfChanged();
  }
  function setRealtimeConnected(val) { _setRealtimeSubscribed(val); }
  function isRealtimeConnected() { return realtimeSubscribed; }
  function _getState() {
    return { realtimeSubscribed, lastSuccessfulSync, consecutiveFailures, currentHealth: computeHealth(), pollIntervalMs, staleThresholdMs };
  }

  return {
    start,
    stop,
    getHealth,
    triggerRefresh,
    refreshNow,
    isRealtimeConnected,
    // aliases for test compatibility
    _setRealtimeSubscribed,
    setRealtimeConnected,
    _getState,
    // legacy names
    HEALTH,
  };
}

// Alias for test that may import createRealtimeClient
export const createRealtimeClient = createRealtimeManager;

export default { createRealtimeManager, createRealtimeClient, HEALTH };
