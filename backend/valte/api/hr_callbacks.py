"""Callbacks that are not part of either contract: outreach results and
the approve/reject links that travel inside approval emails."""

import html
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from valte.api.deps import crisis_tx, form_dict, log_callback, loose_body, require_hr_bearer, resolve_crisis_id
from valte.core import outreach
from valte.core.signals import loose_bool, loose_json
from valte.db import session_scope
from valte.engine import patrol, reconcile
from valte.models import Contact

router = APIRouter(tags=["hr-callbacks"])


@router.post("/hr/outreach/result", dependencies=[Depends(require_hr_bearer)])
async def outreach_result(request: Request) -> dict[str, Any]:
    body = await loose_body(request)
    log_callback("/hr/outreach/result", body)

    def work() -> dict[str, Any]:
        with session_scope() as db:
            k = db.get(Contact, str(body.get("contact_id") or ""))
            cid = k.crisis_id if k else None
        if cid is None:
            return {"ok": False, "error": "unknown contact_id"}
        with crisis_tx(cid) as (db, c):
            k = db.get(Contact, str(body["contact_id"]))
            reconcile.mark_done(db, body.get("hr_run_id"))
            ok = loose_bool(body.get("ok", True)) and not body.get("error")
            outreach.email_result(db, c, k, ok=ok, subject=str(body.get("subject") or ""),
                                  body=str(body.get("body") or ""), error=str(body.get("error") or ""))
            return {"ok": True, "status": k.status}

    return await run_in_threadpool(work)


@router.post("/hr/proactive", dependencies=[Depends(require_hr_bearer)])
async def proactive_result(request: Request) -> dict[str, Any]:
    """What PedroD-proactive decided on its round: same pipeline as /decisions, origin=proactive."""
    body = await loose_body(request)
    log_callback("/hr/proactive", body)
    if "actions" not in body and body.get("decisions_json"):
        body.update(loose_json(body["decisions_json"], {}) or {})
    cid = resolve_crisis_id(body.get("crisis_id"))

    def work() -> dict[str, Any]:
        with crisis_tx(cid) as (db, c):
            reconcile.mark_done(db, body.get("hr_run_id"))
            return patrol.apply_result(db, c, {"actions": loose_json(body.get("actions"), []) or [],
                                               "patrol_note": body.get("patrol_note")})

    return await run_in_threadpool(work)


PAGE = """<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Valte · {title}</title><body style="font:16px/1.5 system-ui;background:#F3F1E6;color:#0E0D0C;max-width:560px;margin:10vh auto;padding:0 24px">
<p style="font:13px ui-monospace,monospace;color:#5C5850">{code}</p><h1 style="font:400 40px/1.1 Georgia,serif">{title}</h1>{body}</body></html>"""


def _page(title: str, body: str, code: str = "Valte") -> HTMLResponse:
    return HTMLResponse(PAGE.format(title=html.escape(title), body=body, code=html.escape(code)))


def _find(token: str) -> Contact | None:
    with session_scope() as db:
        return db.scalars(select(Contact).where(Contact.token == token)).first()


@router.get("/a/{token}", response_class=HTMLResponse)
def approval_page(token: str, d: str = "approve") -> HTMLResponse:
    """GET never decides: mail scanners prefetch links. It shows a button that POSTs."""
    k = _find(token)
    if k is None:
        return _page("Enlace no válido", "<p>Este enlace no corresponde a ninguna solicitud.</p>")
    b = k.brief or {}
    verb = "Aprobar" if d == "approve" else "Rechazar"
    evidence = "".join(f"<li>{html.escape(e)}</li>" for e in b.get("evidence", []))
    return _page(f"{verb}: {b.get('verb_label', '')}", f"""
      <p><b>{html.escape(b.get('entity', ''))}</b> · {html.escape(', '.join(b.get('zones', [])))}</p>
      <p>{html.escape(b.get('reasoning', ''))}</p><ul>{evidence}</ul>
      <form method="post"><input type="hidden" name="d" value="{html.escape(d)}">
      <button style="font:600 16px system-ui;padding:14px 22px;border-radius:10px;border:0;background:#0E0D0C;color:#fff">{verb} {html.escape(b.get('action_id', ''))}</button></form>""",
                 code=f"{b.get('crisis_code', '')} · {b.get('crisis', '')}")


@router.post("/a/{token}", response_class=HTMLResponse)
async def approval_decide(token: str, request: Request) -> HTMLResponse:
    form = form_dict(await request.body())
    decision = "approve" if form.get("d", "approve") == "approve" else "reject"

    def work() -> str:
        k = _find(token)
        if k is None:
            return "missing"
        with crisis_tx(k.crisis_id) as (db, c):
            return outreach.decide_by_link(db, c, db.get(Contact, k.id), decision)

    res = await run_in_threadpool(work)
    if res == "missing":
        return _page("Enlace no válido", "<p>Este enlace no corresponde a ninguna solicitud.</p>")
    if res == "already_decided":
        return _page("Ya estaba decidido", "<p>Otra persona o el propio sistema resolvió esta solicitud antes.</p>")
    return _page("Registrado", f"<p>Decisión registrada: <b>{'aprobada' if decision == 'approve' else 'rechazada'}</b>. El sistema ya actúa en consecuencia.</p>")
