import { useCrisisCall } from "./useCrisisCall";

export default function App() {
  const {
    phase,
    error,
    runId,
    crisisId,
    lines,
    manuals,
    manualsState,
    agentSpeaking,
    micLevel,
    start,
    hangUp,
  } = useCrisisCall();
  const live = phase === "live" || phase === "ending";

  return (
    <main className="shell">
      <header className="brand">
        <span className="dot" /> VALTE · centro de crisis
      </header>

      <div className="stage">
        <button
          className="crisis-btn"
          data-phase={phase}
          onClick={live ? hangUp : start}
          disabled={phase === "starting" || phase === "ending"}
          style={{ ["--level" as string]: micLevel.toFixed(2) }}
        >
          <span className="ring" aria-hidden />
          <span className="label">
            {phase === "idle" || phase === "error" ? "CREAR CRISIS" : null}
            {phase === "starting" ? "ABRIENDO CANAL" : null}
            {phase === "live" ? "EN LLAMADA" : null}
            {phase === "ending" ? "CERRANDO" : null}
          </span>
          <span className="hint">
            {live ? "pulsa para colgar" : "pulsa y explica qué está pasando"}
          </span>
        </button>

        {live && (
          <p className="status">
            {agentSpeaking ? "El operador está hablando…" : "Te escucha. Habla."}
          </p>
        )}
        {error && <p className="error">{error}</p>}
      </div>

      {lines.length > 0 && (
        <section className="transcript">
          {lines.map((l) => (
            <p key={l.id} className={l.who} data-final={l.final}>
              <b>{l.who === "agent" ? "Operador" : "Tú"}</b> {l.text}
            </p>
          ))}
        </section>
      )}

      {manualsState !== "idle" && (
        <section className="manuals">
          <h2>
            Manuales de gestión
            {manualsState === "loading" ? <span className="spin" aria-label="buscando" /> : null}
          </h2>
          {manualsState === "loading" && <p className="empty">Guardando la crisis y buscando protocolos…</p>}
          {manualsState === "done" && manuals.length === 0 && (
            <p className="empty">Sin resultados para lo que se describió en la llamada.</p>
          )}
          <ul>
            {manuals.map((m) => (
              <li key={m.url}>
                <a href={m.url} target="_blank" rel="noreferrer">
                  {m.title}
                </a>
                <span className="src">{new URL(m.url).hostname.replace(/^www\./, "")}</span>
                {m.highlights[0] && <p>{m.highlights[0]}</p>}
              </li>
            ))}
          </ul>
        </section>
      )}

      {(runId || crisisId) && (
        <footer className="run">
          {crisisId ? `crisis ${crisisId} · ` : ""}
          {runId ? `run ${runId}` : null}
        </footer>
      )}
    </main>
  );
}
