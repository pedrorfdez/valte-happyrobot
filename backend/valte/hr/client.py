"""HappyRobot API client with one hard rule: it never writes to a workflow
that is not ours. The org is shared; everything we create is `PedroD-*`
and every non-GET call is checked against that before it leaves."""

import logging
import re
from typing import Any

import httpx

from valte.hr.registry import PREFIX
from valte.settings import settings

log = logging.getLogger("valte.hr")


class NotOurs(RuntimeError):
    pass


class HRClient:
    def __init__(self) -> None:
        self._http = httpx.AsyncClient(
            base_url=settings.happyrobot_base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {settings.happyrobot_api_key}", "Accept": "application/json"},
            timeout=httpx.Timeout(40.0, connect=10.0),
        )
        self._owned: set[str] = set()      # workflow ids/slugs and version ids verified as PedroD-*
        self._our_runs: set[str] = set()

    async def aclose(self) -> None:
        await self._http.aclose()

    # ── ownership guard ──────────────────────────────────────────────────

    async def own_workflow(self, workflow_id: str) -> dict[str, Any]:
        """Verify against HappyRobot itself (not our DB) that this is ours."""
        wf = await self.get(f"/workflows/{workflow_id}")
        wf = wf.get("data", wf)
        if not str(wf.get("name", "")).startswith(PREFIX):
            raise NotOurs(f"workflow {workflow_id} is '{wf.get('name')}', not a {PREFIX}* workflow")
        self._owned.update({wf["id"], wf.get("slug") or wf["id"]})
        return wf

    async def own_version(self, workflow_id: str, version_id: str) -> None:
        await self.own_workflow(workflow_id)
        versions = await self.get(f"/workflows/{workflow_id}/versions")
        ids = {v["id"] for v in versions.get("data", [])}
        if version_id not in ids:
            raise NotOurs(f"version {version_id} does not belong to workflow {workflow_id}")
        self._owned.add(version_id)

    def _check_write(self, method: str, path: str, body: Any) -> None:
        if method == "GET":
            return
        if path == "/workflows/":
            if not str((body or {}).get("name", "")).startswith(PREFIX):
                raise NotOurs(f"refusing to create a workflow not named {PREFIX}*")
            return
        m = re.match(r"^/(workflows|versions)/([^/]+)", path)
        if m:
            if m.group(2) not in self._owned:
                raise NotOurs(f"refusing {method} {path}: not verified as a {PREFIX}* resource")
            return
        if path == "/voice/tokens/":
            wf = (body or {}).get("workflow_id")
            if wf and wf not in self._owned:
                raise NotOurs(f"refusing voice token for workflow {wf}: not ours")
            return
        m = re.match(r"^/runs/([^/]+)/cancel$", path)
        if m:
            if m.group(1) not in self._our_runs:
                raise NotOurs(f"refusing to cancel run {m.group(1)}: we did not start it")
            return
        raise NotOurs(f"refusing {method} {path}: write not allowed by the client")

    # ── transport ────────────────────────────────────────────────────────

    async def request(self, method: str, path: str, *, json: Any = None, params: dict[str, Any] | None = None) -> Any:
        method = method.upper()
        self._check_write(method, path, json)
        r = await self._http.request(method, path, json=json, params=params)
        if r.status_code >= 400:
            raise httpx.HTTPStatusError(f"{method} {path} -> {r.status_code}: {r.text[:600]}", request=r.request, response=r)
        return r.json() if r.content else {}

    async def get(self, path: str, **params: Any) -> Any:
        return await self.request("GET", path, params={k: v for k, v in params.items() if v is not None} or None)

    # ── runs ─────────────────────────────────────────────────────────────

    async def trigger_run(self, workflow_id: str, payload: dict[str, Any]) -> str:
        if workflow_id not in self._owned:
            await self.own_workflow(workflow_id)
        res = await self.request("POST", f"/workflows/{workflow_id}/runs",
                                 json={"payload": payload, "environment": settings.hr_environment})
        run_id = res.get("run_id") or (res.get("queued_run_ids") or [None])[0]
        if not run_id:
            raise RuntimeError(f"HappyRobot accepted the run but returned no run_id: {res}")
        self._our_runs.add(run_id)
        return run_id

    async def get_run(self, run_id: str) -> dict[str, Any]:
        res = await self.get(f"/runs/{run_id}")
        return res.get("data", res)

    async def node_output(self, run_id: str, node_persistent_id: str) -> dict[str, Any] | None:
        """What a node produced in a finished run (pull-based reconciliation)."""
        nodes = await self.get(f"/runs/{run_id}/nodes", node_persistent_id=node_persistent_id)
        recs = nodes.get("data") or []
        if not recs:
            return None
        out = await self.get(f"/runs/{run_id}/outputs/{recs[-1]['output_id']}")
        rec = out.get("data", out)
        return {"status": rec.get("status"), "error": rec.get("error"), "data": rec.get("data") or {}}

    async def cancel_run(self, run_id: str) -> dict[str, Any]:
        return await self.request("POST", f"/runs/{run_id}/cancel")

    # ── voice ────────────────────────────────────────────────────────────

    async def voice_token(self, *, workflow_id: str | None = None, session_id: str | None = None,
                          data: dict[str, Any] | None = None, takeover: bool = False) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if workflow_id:
            if workflow_id not in self._owned:
                await self.own_workflow(workflow_id)
            body = {"workflow_id": workflow_id, "data": data or {}, "env": settings.hr_environment}
        elif session_id:
            body = {"session_id": session_id, "should_takeover": takeover}
        token = await self.request("POST", "/voice/tokens/", json=body)
        if token.get("run_id"):
            self._our_runs.add(token["run_id"])
        return token

    async def run_exists(self, run_id: str) -> dict[str, Any] | None:
        """A web-call run only materialises once someone joins the room."""
        try:
            return await self.get_run(run_id)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    async def run_sessions(self, run_id: str) -> list[dict[str, Any]]:
        try:
            return (await self.get(f"/runs/{run_id}/sessions")).get("data", [])
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return []
            raise

    async def transcript(self, run_id: str, *, agent: str = "Agente", human: str = "Interlocutor") -> tuple[list[dict[str, Any]], str | None]:
        """Read back what was actually said; HappyRobot's record is the one that survives."""
        lines: list[dict[str, Any]] = []
        session_id = None
        for s in await self.run_sessions(run_id):
            session_id = s["id"]
            msgs = await self.get(f"/sessions/{s['id']}/messages", page_size=200)
            for m in msgs.get("data", []):
                content = (m.get("content") or "").strip()
                if m.get("role") not in ("user", "assistant") or not content or content.startswith("<Thoughts>"):
                    continue
                lines.append({"who": agent if m["role"] == "assistant" else human, "text": content,
                              "t": m.get("timestamp")})
        return lines, session_id


_client: HRClient | None = None


def hr() -> HRClient:
    global _client
    if _client is None:
        _client = HRClient()
    return _client
