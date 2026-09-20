"""Creates/updates the PedroD-* workflows in HappyRobot, idempotently.

Node by node, because a node can only reference an upstream node by an id
that exists. Every node gets a custom output before publishing: publish
runs a test-all on untested nodes, and a test of the email node would
send a real email."""

import logging
from typing import Any

from valte.db import session_scope
from valte.hr.client import HRClient
from valte.hr.specs import Ctx, NodeSpec, WorkflowSpec
from valte.models import HrWorkflow, utcnow
from valte.settings import settings

log = logging.getLogger("valte.provision")


async def find_by_name(client: HRClient, name: str) -> dict[str, Any] | None:
    res = await client.get("/workflows/", search=name, page_size=100)
    return next((w for w in res.get("data", []) if w.get("name") == name), None)


def _node_body(node: NodeSpec, ids: dict[str, str], ctx: Ctx) -> dict[str, Any]:
    body: dict[str, Any] = {"type": node.type, "event_id": node.event_id, "name": node.name,
                            "configuration": node.config(ids, ctx)}
    if node.parent:
        body["parent_node_id"] = ids[node.parent]
    if node.webhook_payload:
        body["webhook_payload"] = node.webhook_payload
    prompt = node.prompt_for(ids)
    if prompt:
        body["prompt"] = prompt
    return body


def _saved(name: str) -> HrWorkflow | None:
    with session_scope() as db:
        return db.get(HrWorkflow, name)


async def provision(client: HRClient, spec: WorkflowSpec, ctx: Ctx, *, force: bool = False,
                    dry_run: bool = False) -> dict[str, Any]:
    fp = spec.fingerprint(ctx)
    existing = await find_by_name(client, spec.name)
    saved = _saved(spec.name)
    if existing and saved and saved.spec_hash == fp and saved.workflow_id == existing["id"] and not force:
        return {"name": spec.name, "status": "unchanged", "workflow_id": existing["id"]}

    trigger = spec.nodes[0]
    if dry_run:
        fake = {n.name: f"<{n.name}-id>" for n in spec.nodes}
        return {"name": spec.name, "status": "dry-run", "exists": bool(existing),
                "nodes": [_node_body(n, fake, ctx) for n in spec.nodes]}

    if existing is None:
        created = await client.request("POST", "/workflows/", json={
            "name": spec.name, "icon": spec.icon, "skip_test_all": True,
            "version": {"name": "v1", "nodes": [_node_body(trigger, {}, ctx)]}})
        created = created.get("data", created)
        workflow_id, version_id = created["id"], created["latest_version"]["id"]
        await client.own_version(workflow_id, version_id)
        status = "created"
    else:
        workflow_id = existing["id"]
        live = existing["latest_version"]["id"]
        await client.own_version(workflow_id, live)  # raises NotOurs unless it is a PedroD-* workflow
        if existing["latest_version"].get("is_published"):
            forked = await client.request("POST", f"/versions/{live}/fork", json={})
            forked = forked.get("data", forked)
            version_id = forked["id"]
            await client.own_version(workflow_id, version_id)
        else:
            version_id = live
        # A batch that starts with a trigger replaces every node of the version.
        await client.request("POST", f"/versions/{version_id}/nodes", json={"nodes": [_node_body(trigger, {}, ctx)]})
        status = "updated"

    nodes = (await client.get(f"/versions/{version_id}/nodes")).get("data", [])
    ids = {"trigger": next(n["id"] for n in nodes if n["type"] == "trigger" or n.get("parent_id") is None)}
    for node in spec.nodes[1:]:
        res = await client.request("POST", f"/versions/{version_id}/nodes", json={"nodes": [_node_body(node, ids, ctx)]})
        made = res.get("data", [])
        ids[node.name] = next((n["id"] for n in made if n.get("type") == node.type), made[0]["id"])
        log.info("%s: node %s -> %s", spec.name, node.name, ids[node.name])

    for node in spec.nodes:
        if node.custom_output:
            await client.request("PUT", f"/versions/{version_id}/nodes/{ids[node.name]}/custom-output",
                                 json={"data": node.custom_output})

    pub = await client.request("POST", f"/versions/{version_id}/publish",
                               json={"force": True, "environment": settings.hr_environment})
    pub = pub.get("data", pub)

    # Runs report node outputs by persistent id; on a fresh node it equals the id, after a fork it does not.
    nodes = (await client.get(f"/versions/{version_id}/nodes")).get("data", [])
    by_id = {n["id"]: n for n in nodes}
    persistent = {name: by_id[i].get("persistent_id", i) for name, i in ids.items() if i in by_id}
    with session_scope() as db:
        row = db.get(HrWorkflow, spec.name) or HrWorkflow(name=spec.name, workflow_id=workflow_id)
        row.workflow_id, row.version_id, row.slug = workflow_id, version_id, (existing or {}).get("slug", "")
        row.spec_hash, row.node_ids, row.updated_at = fp, persistent, utcnow()
        db.merge(row)
    return {"name": spec.name, "status": status, "workflow_id": workflow_id, "version_id": version_id,
            "live": pub.get("is_live"), "missing_variables": pub.get("missing_variables") or [],
            "test_errors": pub.get("test_errors") or []}
