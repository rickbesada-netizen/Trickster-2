-- Antidetect browser: Supabase schema
-- Run this once in Supabase Dashboard -> SQL Editor -> New query -> paste -> Run.
--
-- Covers all three access patterns with one design:
--   - Just you across devices: your personal org (created automatically on signup)
--   - A small team: add teammates to your org's memberships
--   - Multiple separate customers: each gets their own org, invisible to each other

-- ============================================================
-- Tables
-- ============================================================

create table if not exists organizations (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  created_at timestamptz not null default now()
);

create table if not exists memberships (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null default 'member' check (role in ('owner', 'member')),
  created_at timestamptz not null default now(),
  unique (org_id, user_id)
);

create table if not exists browser_profiles (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations(id) on delete cascade,
  profile_id text not null,          -- human label, e.g. "profile_001_windows_desktop"
  config jsonb not null,             -- the full profile JSON (UA, platform, viewport, fonts, etc.)
  proxy jsonb not null default '{}', -- kept separate for clarity, still just JSON
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (org_id, profile_id)
);

-- ============================================================
-- Row Level Security — the actual access control
-- ============================================================

alter table organizations enable row level security;
alter table memberships enable row level security;
alter table browser_profiles enable row level security;

-- You can see an org only if you're a member of it.
create policy "members can view their orgs"
  on organizations for select
  using (
    id in (select org_id from memberships where user_id = auth.uid())
  );

-- You can see membership rows only for orgs you belong to.
create policy "members can view their own memberships"
  on memberships for select
  using (user_id = auth.uid());

-- Full CRUD on browser_profiles, but only within orgs you belong to.
-- This single policy is what makes profiles private per-org: swap the org
-- for a customer's own org and their profiles are invisible to anyone else.
create policy "members can manage their org's profiles"
  on browser_profiles for all
  using (org_id in (select org_id from memberships where user_id = auth.uid()))
  with check (org_id in (select org_id from memberships where user_id = auth.uid()));

-- ============================================================
-- Auto-create a personal org the moment someone signs up
-- ============================================================

create or replace function handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  new_org_id uuid;
begin
  insert into organizations (name)
  values (coalesce(new.email, 'My Organization'))
  returning id into new_org_id;

  insert into memberships (org_id, user_id, role)
  values (new_org_id, new.id, 'owner');

  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function handle_new_user();

-- ============================================================
-- Keep updated_at current on edits
-- ============================================================

create or replace function set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists browser_profiles_updated_at on browser_profiles;
create trigger browser_profiles_updated_at
  before update on browser_profiles
  for each row execute function set_updated_at();
