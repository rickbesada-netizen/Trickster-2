-- Cloud job queue for Trickster workers.
-- Run once in the Supabase SQL Editor. Each row = "run these pages on this
-- profile at this time". Workers take jobs with claim_jobs() so two workers
-- never run the same job, and a job whose worker died is handed out again.

create table if not exists jobs (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations(id) on delete cascade,
  profile_id text not null,
  pages jsonb not null,                       -- [{url, seconds, scroll, actions}]
  run_at timestamptz not null default now(),
  status text not null default 'queued'
    check (status in ('queued', 'running', 'done', 'failed')),
  worker text,
  attempts int not null default 0,
  heartbeat timestamptz,
  started_at timestamptz,
  finished_at timestamptz,
  result jsonb,
  created_at timestamptz not null default now()
);

create index if not exists jobs_queue_idx on jobs (org_id, status, run_at);

alter table jobs enable row level security;

create policy "members can manage their org's jobs"
  on jobs for all
  using (org_id in (select org_id from memberships where user_id = auth.uid()))
  with check (org_id in (select org_id from memberships where user_id = auth.uid()));

-- Takes up to p_limit jobs that are due (or whose worker stopped reporting for
-- 10 minutes, at most 3 attempts) and marks them running for p_worker.
create or replace function claim_jobs(p_worker text, p_limit int)
returns setof jobs
language sql
as $$
  update jobs set
    status = 'running', worker = p_worker, attempts = attempts + 1,
    started_at = now(), heartbeat = now(), finished_at = null
  where id in (
    select id from jobs
    where ((status = 'queued' and run_at <= now())
        or (status = 'running' and heartbeat < now() - interval '10 minutes'))
      and attempts < 3
    order by run_at
    limit p_limit
    for update skip locked
  )
  returning *;
$$;
