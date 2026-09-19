-- Run in the Supabase SQL editor.
-- A crisis declared through the `crisis-start` voice intake, plus the
-- management manuals found on the web for it.
create table if not exists public.crises (
    id uuid primary key,
    run_id text,
    crisis_type text,
    location text,
    started_at text,
    scope text,
    people_affected int,
    immediate_needs text,
    transcript text,
    source text not null default 'crisis-start',
    created_at timestamptz not null default now()
);

create index if not exists crises_created_at_idx on public.crises (created_at desc);

create table if not exists public.crisis_manuals (
    id uuid primary key,
    crisis_id uuid not null references public.crises (id) on delete cascade,
    title text not null,
    url text not null,
    published_date text,
    highlights jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now(),
    unique (crisis_id, url)
);

create index if not exists crisis_manuals_crisis_id_idx on public.crisis_manuals (crisis_id);
