"""Where native payloads go.

console / file:<path>  -> debugging: print or log {channel, mode, payload}.
live                   -> POST each payload to its channel's URL from env:
                            call   -> HR_WEBHOOK_CALLS
                            social -> HR_WEBHOOK_SOCIAL
                            news   -> HR_WEBHOOK_NEWS
                            sensor -> KERNEL_SIGNALS_URL (direct mode)
Delivery guarantees are the kernel outbox's job; the simulator is
fire-and-forget, like reality."""

import json
import os
import sys
import urllib.request

CHANNEL_ENV = {
    "call": "HR_WEBHOOK_CALLS",
    "social": "HR_WEBHOOK_SOCIAL",
    "news": "HR_WEBHOOK_NEWS",
    "sensor": "KERNEL_SIGNALS_URL",
}

CHANNEL_COLORS = {"call": "31", "social": "35", "news": "32", "sensor": "33"}


class ConsoleEmitter:
    def emit(self, channel: str, mode: str, payload: dict):
        c = CHANNEL_COLORS.get(channel, "0")
        t = payload["t"][11:16]
        if channel == "call":
            body = f"caller {payload['caller']['number']}: {payload['transcript'][:100]}"
        elif channel == "social":
            body = f"{payload['author']}: {payload['text'][:100]}"
        elif channel == "news":
            body = f"{payload['outlet']}: {payload['headline'][:100]}"
        else:
            body = f"{payload['source']}: {payload['content'][:100]}"
        print(f"\033[{c}m{t} [{channel:>6}/{mode}]\033[0m {body}")

    def close(self):
        pass


class FileEmitter:
    def __init__(self, path: str):
        self._f = open(path, "a")

    def emit(self, channel: str, mode: str, payload: dict):
        self._f.write(json.dumps({"channel": channel, "mode": mode, "payload": payload},
                                 ensure_ascii=False) + "\n")

    def close(self):
        self._f.close()


class LiveEmitter:
    def __init__(self):
        self.urls = {ch: os.environ.get(env) for ch, env in CHANNEL_ENV.items()}
        self.token = os.environ.get("WORLD_API_TOKEN", "")
        self._warned: set[str] = set()

    def emit(self, channel: str, mode: str, payload: dict):
        url = self.urls.get(channel)
        if not url:
            if channel not in self._warned:
                self._warned.add(channel)
                print(f"live: no URL for channel {channel} "
                      f"(set {CHANNEL_ENV[channel]}), dropping its payloads", file=sys.stderr)
            return
        headers = {"Content-Type": "application/json"}
        if channel == "sensor" and self.token:  # kernel requires the token; HR webhooks do not
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     headers=headers, method="POST")
        try:
            urllib.request.urlopen(req, timeout=5).read()
        except Exception as e:
            print(f"emit failed for {payload.get('id')}: {e}", file=sys.stderr)

    def close(self):
        pass


def make_emitter(spec: str):
    if spec == "console":
        return ConsoleEmitter()
    if spec.startswith("file:"):
        return FileEmitter(spec[5:])
    if spec == "live":
        return LiveEmitter()
    raise ValueError(f"unknown emitter: {spec} (use console, file:<path>, or live)")
