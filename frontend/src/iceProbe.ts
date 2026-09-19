/** Classify what ICE candidates this network actually yields.
 *
 * LiveKit only reports "could not establish pc connection", which does
 * not say whether the browser failed to gather candidates or failed to
 * reach the media server. This answers the first half. */
export type IceProbe = {
  types: string[];
  udp: boolean;
  error?: string;
};

/** Networks that filter UDP by port (eduroam does) let STUN through on
 * 3478 while dropping the high ports media servers actually use. Probing
 * only one of the two gives a misleading answer, so probe both. */
export type IceVerdict = {
  lowPort: IceProbe;
  highPort: IceProbe;
  summary: string;
};

export async function diagnoseIce(turn: RTCIceServer[] = []): Promise<IceVerdict> {
  const [lowPort, highPort] = await Promise.all([
    probeIce([{ urls: "stun:global.stun.twilio.com:3478" }, ...turn]),
    probeIce([{ urls: "stun:stun.l.google.com:19302" }]),
  ]);

  let summary: string;
  if (lowPort.udp && highPort.udp) {
    summary =
      "el navegador sale por UDP sin restricción de puerto, así que el bloqueo está en el servidor de medios de HappyRobot";
  } else if (lowPort.udp) {
    summary =
      "esta red deja salir UDP solo a puertos conocidos (3478) y corta el rango alto, que es justo donde escucha el SFU de LiveKit: hace falta un TURN en 443";
  } else {
    summary = "este navegador o red no consigue ningún candidato UDP hacia fuera";
  }
  return { lowPort, highPort, summary };
}

export async function probeIce(iceServers: RTCIceServer[], ms = 5000): Promise<IceProbe> {
  const pc = new RTCPeerConnection({ iceServers });
  const types = new Set<string>();
  try {
    pc.createDataChannel("probe");
    await pc.setLocalDescription(await pc.createOffer());
    await new Promise<void>((resolve) => {
      const done = setTimeout(resolve, ms);
      pc.onicecandidate = (e) => {
        if (!e.candidate) {
          clearTimeout(done);
          resolve();
          return;
        }
        const { type, protocol } = e.candidate;
        if (type) types.add(protocol ? `${type}/${protocol}` : type);
      };
    });
    return {
      types: [...types],
      // A server-reflexive candidate means UDP reached a STUN server:
      // the browser can talk to the outside world over UDP.
      udp: [...types].some((t) => t.startsWith("srflx") || t.startsWith("relay")),
    };
  } catch (e) {
    return { types: [...types], udp: false, error: e instanceof Error ? e.message : String(e) };
  } finally {
    pc.close();
  }
}

/** Optional TURN relay, for networks that block UDP to the media server.
 * HappyRobot's LiveKit hands out STUN only, so without this there is no
 * fallback path. Configure with VITE_TURN_URL / _USERNAME / _PASSWORD. */
export function turnFromEnv(): RTCIceServer[] {
  const urls = import.meta.env.VITE_TURN_URL;
  if (!urls) return [];
  return [
    {
      urls,
      username: import.meta.env.VITE_TURN_USERNAME,
      credential: import.meta.env.VITE_TURN_PASSWORD,
    },
  ];
}
