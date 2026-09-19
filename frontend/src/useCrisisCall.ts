import { useCallback, useEffect, useRef, useState } from "react";
import { diagnoseIce, turnFromEnv } from "./iceProbe";
import {
  ConnectionState,
  RoomEvent,
  Room,
  type RemoteTrack,
  type TranscriptionSegment,
} from "livekit-client";

const API = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export type CallPhase = "idle" | "starting" | "live" | "ending" | "error";

export type Line = { id: string; who: "agent" | "you"; text: string; final: boolean };

export type Manual = {
  title: string;
  url: string;
  published_date: string | null;
  highlights: string[];
};

/** Drives one crisis-intake voice call against the HappyRobot agent.
 *
 * The backend mints the LiveKit token (the API key never reaches the
 * browser); we join the room, publish the mic and render transcripts. */
export function useCrisisCall() {
  const roomRef = useRef<Room | null>(null);
  const [phase, setPhase] = useState<CallPhase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const runIdRef = useRef<string | null>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const [agentSpeaking, setAgentSpeaking] = useState(false);
  const [manuals, setManuals] = useState<Manual[]>([]);
  const [manualsState, setManualsState] = useState<"idle" | "loading" | "done" | "error">("idle");
  const [crisisId, setCrisisId] = useState<string | null>(null);
  const [micLevel, setMicLevel] = useState(0);

  /** What we heard during intake, as one blob of text for the search. */
  const linesRef = useRef<Line[]>([]);
  linesRef.current = lines;

  /** Close the intake: the backend saves the crisis to Supabase, looks
   * up its management manuals and saves those too. */
  const declaredRef = useRef(false);

  const declareCrisis = useCallback(async (run: string | null) => {
    // Hanging up fires both our own path and RoomEvent.Disconnected;
    // the crisis gets declared once.
    if (declaredRef.current) return;
    declaredRef.current = true;

    // Send whatever the browser heard, but never gate on it: with the
    // run_id the backend reads the real transcript back from HappyRobot.
    const transcript = linesRef.current
      .filter((l) => l.final)
      .map((l) => `${l.who === "agent" ? "Operador" : "Mando"}: ${l.text}`)
      .join("\n")
      .trim();
    if (!transcript && !run) return;

    setManualsState("loading");
    try {
      const res = await fetch(`${API}/crisis`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ transcript, run_id: run }),
      });
      if (!res.ok) throw new Error((await res.text()) || `HTTP ${res.status}`);
      const crisis: { id: string; manuals: Manual[]; manuals_error: string | null } =
        await res.json();
      setCrisisId(crisis.id);
      setManuals(crisis.manuals);
      if (crisis.manuals_error) setError(crisis.manuals_error);
      setManualsState("done");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setManualsState("error");
    }
  }, []);

  const hangUp = useCallback(async () => {
    setPhase((p) => (p === "live" ? "ending" : p));
    await roomRef.current?.disconnect();
    roomRef.current = null;
    setPhase("idle");
    setAgentSpeaking(false);
    setMicLevel(0);
    void declareCrisis(runIdRef.current);
  }, [declareCrisis]);

  const start = useCallback(async () => {
    setError(null);
    setLines([]);
    setManuals([]);
    setManualsState("idle");
    setCrisisId(null);
    declaredRef.current = false;
    setPhase("starting");
    try {
      const res = await fetch(`${API}/crisis/voice-token`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ data: { source: "dashboard" } }),
      });
      if (!res.ok) throw new Error((await res.text()) || `HTTP ${res.status}`);
      const { url, token, run_id } = await res.json();

      const turn = turnFromEnv();
      const room = new Room({ adaptiveStream: true, dynacast: true });
      roomRef.current = room;

      room.on(RoomEvent.TrackSubscribed, (track: RemoteTrack) => {
        if (track.kind === "audio") {
          const el = track.attach();
          el.autoplay = true;
          document.body.appendChild(el);
        }
      });
      room.on(RoomEvent.TranscriptionReceived, (segments: TranscriptionSegment[], participant) => {
        const who = participant?.isLocal ? "you" : "agent";
        setLines((prev) => {
          const next = [...prev];
          for (const s of segments) {
            const at = next.findIndex((l) => l.id === s.id);
            const line: Line = { id: s.id, who, text: s.text, final: s.final };
            if (at >= 0) next[at] = line;
            else next.push(line);
          }
          return next.slice(-40);
        });
      });
      room.on(RoomEvent.ActiveSpeakersChanged, (speakers) => {
        setAgentSpeaking(speakers.some((s) => !s.isLocal));
        const me = speakers.find((s) => s.isLocal);
        setMicLevel(me?.audioLevel ?? 0);
      });
      room.on(RoomEvent.Disconnected, () => {
        roomRef.current = null;
        setPhase("idle");
        void declareCrisis(runIdRef.current);
      });

      room.on(RoomEvent.ConnectionStateChanged, (state) => console.info("[valte] livekit:", state));

      try {
        await room.connect(url, token, turn.length ? { rtcConfig: { iceServers: turn } } : undefined);
      } catch (e) {
        // HappyRobot's LiveKit only hands out STUN, so a media failure
        // here is almost always the network blocking UDP to the SFU.
        // Say which half broke instead of "pc connection".
        const ice = await diagnoseIce(turn);
        console.error("[valte] ice diagnosis:", ice, "livekit url:", url);
        throw new Error(
          `No se pudo abrir el canal de audio: ${ice.summary}. ` +
            `UDP/3478: ${ice.lowPort.types.join(", ") || "ninguno"} · ` +
            `UDP/19302: ${ice.highPort.types.join(", ") || "ninguno"}. (${
              e instanceof Error ? e.message : String(e)
            })`,
        );
      }
      await room.localParticipant.setMicrophoneEnabled(true);
      runIdRef.current = run_id;
      setRunId(run_id);
      setPhase("live");
    } catch (e) {
      await roomRef.current?.disconnect();
      roomRef.current = null;
      setError(e instanceof Error ? e.message : String(e));
      setPhase("error");
    }
  }, [declareCrisis]);

  useEffect(() => () => void roomRef.current?.disconnect(), []);

  const connecting = phase === "starting" || roomRef.current?.state === ConnectionState.Connecting;
  return {
    phase,
    connecting,
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
  };
}
