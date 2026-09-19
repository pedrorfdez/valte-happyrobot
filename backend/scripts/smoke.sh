#!/usr/bin/env bash
# End-to-end check of the API against a running server, without spending HappyRobot credits:
#   VALTE_BRAIN=local VALTE_OUTREACH_MODE=dry VALTE_DB_URL=sqlite:////tmp/valte-smoke.db scripts/dev_server.sh 8011
#   scripts/smoke.sh localhost:8011
B="${1:-localhost:8010}"; J='content-type: application/json'; fail=0
T="${HAPPYROBOT_WEBHOOK_SECRET:-$(grep -E '^HAPPYROBOT_WEBHOOK_SECRET=' "$(dirname "$0")/../../.env" 2>/dev/null | cut -d= -f2-)}"
A="authorization: Bearer $T"
py() { python3 -c "import sys,json; d=json.load(sys.stdin); $1"; }
check() { if [ "$2" = "$3" ]; then echo "  ok   $1"; else echo "  FAIL $1 (got '$2', want '$3')"; fail=1; fi; }

CID=$(curl -s -X POST "$B/crises" -H "$J" -d '{"pack":"riada-paiporta","speed":120}' | py "print(d['id'])")
echo "crisis $CID"; sleep 8
curl -s -X POST "$B/crises/$CID/clock" -H "$J" -d '{"paused":true}' > /dev/null
check "scenario moved"            "$(curl -s "$B/crises/$CID" | py "print(d['kpis']['signals']['total'] > 3)")" True
check "noise is flagged"          "$(curl -s "$B/crises/$CID/signals/stats" | py "print(d['noise'] > 0)")" True
check "kernel: /state"            "$(curl -s -H "$A" "$B/state?crisis_id=$CID&format=string" | py "print('state_json' in d)")" True
check "kernel: needs bearer"      "$(curl -s -o /dev/null -w '%{http_code}' "$B/state?crisis_id=$CID")" 401
check "kernel: /perceptions (query string, like HappyRobot)" "$(curl -s -H "$A" -X POST "$B/perceptions?crisis_id=$CID&id=smoke-1&channel=call&source=112&zone=Paiporta&precision=street&is_noise=false&claims=%5B%7B%22hazard_type%22%3A%22flood%22%2C%22severity_hint%22%3A8%7D%5D" | py "print(d['noise'], d['confidence'])")" "False high"
check "kernel: /decisions rejects a verb outside capabilities" "$(curl -s -H "$A" -X POST "$B/decisions?crisis_id=$CID" -H "$J" -d '{"actions":[{"actor":"samu","verb":"close_road","target_zones":["paiporta"],"evidence":["smoke-1"]}]}' | py "print(d['rejected'])")" 1
check "gateway: snapshot"         "$(curl -s -H "$A" "$B/api/snapshot?run_id=$CID" | py "print('run' in d and 'zone_catalog' in d)")" True
PV=$(curl -s -H "$A" "$B/api/snapshot?run_id=$CID" | py "print(d['run']['plan_version'])")
check "gateway: stale plan -> 409" "$(curl -s -o /dev/null -w '%{http_code}' -H "$A" -X POST "$B/api/commands?command_id=smoke-stale&run_id=$CID&command_type=replace_plan&expected_plan_version=999" -H "$J" -d '{"incidents":[],"plan":{"summary":"x"}}')" 409
check "gateway: plan accepted"     "$(curl -s -o /dev/null -w '%{http_code}' -H "$A" -X POST "$B/api/commands?command_id=smoke-plan&run_id=$CID&command_type=replace_plan&expected_plan_version=$PV" -H "$J" -d '{"incidents":[],"plan":{"summary":"smoke"}}')" 200
check "gateway: idempotent"        "$(curl -s -H "$A" -X POST "$B/api/commands?command_id=smoke-plan&run_id=$CID&command_type=replace_plan" -H "$J" -d '{"plan":{}}' | py "print(d.get('duplicate'))")" True
PEND=$(curl -s "$B/crises/$CID/actions?status=pending_approval" | py "print(d['pending'][0]['action']['id'] if d['pending'] else '')")
[ -n "$PEND" ] && check "human approves $PEND" "$(curl -s -X POST "$B/crises/$CID/actions/$PEND/approve" -H "$J" -d '{"by":"operador"}' | py "print(d['status'] in ('approved','executed'))")" True
check "human: manual action validated" "$(curl -s -o /dev/null -w '%{http_code}' -X POST "$B/crises/$CID/actions" -H "$J" -d '{"actor":"samu","verb":"close_road","target_zones":["paiporta"]}')" 422
check "inject: road cut"           "$(curl -s -X POST "$B/crises/$CID/sim/inject" -H "$J" -d '{"kind":"road_cut","zone":"picanya","note":"Pont vell hundido"}' | py "print(d['injected'])")" road_cut
check "SSE stream opens"           "$(timeout 3 curl -sN "$B/crises/$CID/events?after=0" | head -c 200 | grep -c 'event:')" 1
check "close -> lessons"           "$(curl -s -X POST "$B/crises/$CID/close" | py "print(d['status'])")" closed
[ $fail = 0 ] && echo "SMOKE OK" || { echo "SMOKE FAILED"; exit 1; }
