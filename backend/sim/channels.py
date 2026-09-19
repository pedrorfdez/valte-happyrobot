"""Channel adapters: turn normalized ground-truth signals into the native
payload each channel really delivers, stripping everything that only
perception can know (claims, trust, resolved zone).

perception-mode channels (call, social, news) emit native payloads for the
HappyRobot ingest workflows. direct-mode channels (sensor) emit the
normalized signal itself: structured sources do not need perception and
must not wait for an LLM."""

import random

FIRST = ["maria", "jose", "carmen", "paco", "lucia", "vicent", "amparo", "jordi", "pilar", "rafa"]
SUFFIX = ["_vlc", "84", "_horta", "2010", "_cv", "77", "_ok", "runner", "_sur", "fallas"]


class ChannelRouter:
    def __init__(self, entities: dict, rng: random.Random):
        self.bindings = {e["id"]: e["ingest"] for e in entities.values() if "ingest" in e}
        self.rng = rng
        self._fallback_seq = 0
        # caller continuity: a small persistent pool of numbers per zone, so
        # some callers recur and report deduplication is actually tested
        self._zone_callers: dict[str, list[str]] = {}

    def adapt(self, signal: dict, call_meta: dict | None = None) -> tuple[str, str, dict]:
        """Return (channel, mode, native_payload) for a normalized signal."""
        binding = self.bindings.get(signal["source"])
        if binding is None:
            # unknown source: pass through normalized, direct
            return "sensor", "direct", signal
        channel, mode = binding["channel"], binding["mode"]
        if mode == "direct":
            return channel, mode, signal
        if channel == "call":
            return channel, mode, self._call_record(signal, call_meta)
        if channel == "social":
            return channel, mode, self._social_post(signal)
        if channel == "news":
            return channel, mode, self._news_bulletin(signal)
        raise ValueError(f"unhandled channel {channel}")

    def _zone_number(self, zone_id: str | None) -> str:
        if zone_id is None:
            self._fallback_seq += 1
            return f"+3462{self._fallback_seq:07d}"
        pool = self._zone_callers.setdefault(
            zone_id, [f"+346{self.rng.randint(10000000, 99999999)}" for _ in range(6)])
        return self.rng.choice(pool)

    def _call_record(self, signal: dict, call_meta: dict | None) -> dict:
        call_meta = call_meta or {}
        caller: dict = {"number": call_meta.get("number") or
                        self._zone_number(signal["location"].get("zone"))}
        coords = signal["location"].get("coords")
        if coords:
            caller["gps"] = coords  # AML handset location
        record = {
            "id": signal["id"],
            "t": signal["t"],
            "channel": "call",
            "caller": caller,
            "transcript": signal["content"],
        }
        if call_meta.get("who"):
            record["persona"] = {
                "who": call_meta["who"],
                "knows": call_meta.get("knows", []),
                "unknowns": call_meta.get("unknowns", []),
            }
        return record

    def _social_post(self, signal: dict) -> dict:
        return {
            "id": signal["id"],
            "t": signal["t"],
            "channel": "social",
            "author": "@" + self.rng.choice(FIRST) + self.rng.choice(SUFFIX),
            "text": signal["content"],
        }

    def _news_bulletin(self, signal: dict) -> dict:
        content = signal["content"]
        headline = content.split(".")[0][:90]
        return {
            "id": signal["id"],
            "t": signal["t"],
            "channel": "news",
            "outlet": "A Punt" if "A Punt" in content else "Agencia local",
            "headline": headline,
            "body": content,
        }
