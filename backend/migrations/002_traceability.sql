-- Traceability: capture ephemeral moments into the permanent record.

-- every version of the agent's assessment, appended on each write
create table if not exists situation_history (
    pk bigserial primary key,
    run_id uuid not null references runs(id) on delete cascade,
    doc jsonb not null,
    written_at timestamptz not null default now()
);
create index if not exists situation_history_run on situation_history (run_id, pk);

-- link decision batches to the HappyRobot run that produced them
alter table actions add column if not exists hr_run_id text;
