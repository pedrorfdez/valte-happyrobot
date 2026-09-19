-- Crisis kernel schema. All state is scoped by run_id: one demo = one run.
-- Typed columns only where code filters; the full document lives in doc jsonb
-- and is validated against schemas/*.json at the API boundary.

create table if not exists runs (
    id uuid primary key default gen_random_uuid(),
    scenario_id text not null,
    seed integer,
    notes text,
    started_at timestamptz not null default now()
);

create table if not exists zones (
    run_id uuid not null references runs(id) on delete cascade,
    id text not null,
    doc jsonb not null,
    primary key (run_id, id)
);

create table if not exists entities (
    run_id uuid not null references runs(id) on delete cascade,
    id text not null,
    kind text not null,
    status text not null,
    provenance text not null,
    units_available integer,
    doc jsonb not null,
    primary key (run_id, id)
);

-- simulator ground truth; no agent-facing endpoint reads this
create table if not exists hazards (
    run_id uuid not null references runs(id) on delete cascade,
    id text not null,
    zone text not null,
    severity integer not null,
    trend text not null,
    doc jsonb not null,
    primary key (run_id, id)
);

create table if not exists signals (
    run_id uuid not null references runs(id) on delete cascade,
    id text not null,
    t timestamptz not null,
    source text not null,
    zone text,
    confidence text,
    doc jsonb not null,
    received_at timestamptz not null default now(),
    primary key (run_id, id)
);
create index if not exists signals_corr on signals (run_id, zone, t);
create index if not exists signals_source on signals (run_id, source, t);

-- raw channel deliveries, the perception audit trail
create table if not exists payloads (
    pk bigserial primary key,
    run_id uuid not null references runs(id) on delete cascade,
    signal_id text,
    channel text,
    payload jsonb not null,
    received_at timestamptz not null default now()
);

create table if not exists actions (
    run_id uuid not null references runs(id) on delete cascade,
    id text not null,
    t timestamptz not null,
    actor text not null,
    verb text not null,
    status text not null,
    idempotency_key text,
    doc jsonb not null,
    created_at timestamptz not null default now(),
    primary key (run_id, id),
    unique (run_id, idempotency_key)
);

create table if not exists assignments (
    pk bigserial primary key,
    run_id uuid not null references runs(id) on delete cascade,
    action_id text not null,
    entity_id text not null,
    units integer not null,
    zone text,
    status text not null default 'active',
    started_at timestamptz not null default now(),
    released_at timestamptz
);
create index if not exists assignments_entity on assignments (run_id, entity_id, status);

-- the agent's persistent memory, one row per run
create table if not exists situation (
    run_id uuid primary key references runs(id) on delete cascade,
    doc jsonb not null default '{}'::jsonb,
    updated_at timestamptz not null default now()
);

create table if not exists tripwires (
    run_id uuid not null references runs(id) on delete cascade,
    id text not null,
    status text not null default 'active',
    set_by text not null,
    doc jsonb not null,
    created_at timestamptz not null default now(),
    primary key (run_id, id)
);

-- outbox and timers in one table
create table if not exists events (
    pk bigserial primary key,
    run_id uuid not null references runs(id) on delete cascade,
    type text not null,
    lane text not null default 'coordinator',
    payload jsonb not null,
    status text not null default 'pending',
    attempts integer not null default 0,
    due_t timestamptz,
    created_at timestamptz not null default now(),
    sent_at timestamptz
);
create index if not exists events_pending on events (run_id, lane, status);
