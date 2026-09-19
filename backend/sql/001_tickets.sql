-- Run in the Supabase SQL editor.
create table if not exists public.tickets (
    id uuid primary key,
    user_id text not null,
    entity_id text not null,
    kind text not null check (kind in ('report', 'proposal')),
    subject text,
    content text not null,
    payload jsonb not null default '{}'::jsonb,
    workflow_run_id text,
    created_at timestamptz not null default now()
);

create index if not exists tickets_entity_id_idx on public.tickets (entity_id);
create index if not exists tickets_user_id_idx on public.tickets (user_id);
create index if not exists tickets_created_at_idx on public.tickets (created_at desc);
