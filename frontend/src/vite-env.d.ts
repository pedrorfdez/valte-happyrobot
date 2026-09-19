/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  /** Optional TURN relay for networks that block UDP to LiveKit. */
  readonly VITE_TURN_URL?: string;
  readonly VITE_TURN_USERNAME?: string;
  readonly VITE_TURN_PASSWORD?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
