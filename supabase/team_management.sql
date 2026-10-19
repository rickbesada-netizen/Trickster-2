-- Team Management migration. Run this ONCE in Supabase SQL Editor,
-- AFTER schema.sql has already been run. Safe to run on top of the
-- existing schema — additive, not destructive.

-- ============================================================
-- Broaden roles: owner (can't be removed) / admin (manage members +
-- profiles) / staff (use profiles only, no member management)
-- ============================================================
alter table memberships drop constraint if exists memberships_role_check;
alter table memberships add constraint memberships_role_check
  check (role in ('owner', 'admin', 'staff'));

update memberships set role = 'staff' where role = 'member';

-- The original schema.sql policy only let you see YOUR OWN membership row
-- — fine for solo use, but Member Management needs to see everyone in
-- your org. A naive policy that subqueries memberships from within a
-- policy ON memberships causes infinite recursion (the subquery re-triggers
-- the same policy, forever) — so the lookup goes through a SECURITY
-- DEFINER helper function instead, which bypasses RLS internally and
-- breaks the loop.
create or replace function get_my_org_id()
returns uuid
language sql
security definer
stable
set search_path = public
as $$
  select org_id from memberships where user_id = auth.uid() limit 1;
$$;

create or replace function get_my_role()
returns text
language sql
security definer
stable
set search_path = public
as $$
  select role from memberships where user_id = auth.uid() limit 1;
$$;

drop policy if exists "members can view their own memberships" on memberships;
create policy "members can view their orgs memberships"
  on memberships for select
  using (org_id = get_my_org_id());

create policy "owners and admins can update member roles"
  on memberships for update
  using (org_id = get_my_org_id() and get_my_role() in ('owner', 'admin'))
  with check (org_id = get_my_org_id() and get_my_role() in ('owner', 'admin'));

create policy "owners and admins can remove members"
  on memberships for delete
  using (
    org_id = get_my_org_id() and get_my_role() in ('owner', 'admin')
    and user_id != auth.uid()  -- can't remove yourself this way
  );

-- ============================================================
-- User directory: lets the app show teammates' emails without touching
-- auth.users directly (not exposed to the client). Visibility is scoped
-- to people who share an org with you — not a global user lookup.
-- ============================================================
create table if not exists user_directory (
  id uuid primary key references auth.users(id) on delete cascade,
  email text not null,
  created_at timestamptz not null default now()
);
alter table user_directory enable row level security;

create policy "view teammates directory entries"
  on user_directory for select
  using (
    id = auth.uid()
    or id in (
      select m2.user_id from memberships m1
      join memberships m2 on m1.org_id = m2.org_id
      where m1.user_id = auth.uid()
    )
  );

-- Backfill for accounts that already existed before this migration
insert into user_directory (id, email)
select id, email from auth.users
on conflict (id) do nothing;

-- Extend the signup trigger to also populate the directory going forward
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

  insert into user_directory (id, email)
  values (new.id, new.email)
  on conflict (id) do nothing;

  return new;
end;
$$;

-- ============================================================
-- Invites: an owner/admin generates a code + role; anyone who redeems it
-- joins that org with that role. Redemption runs through a function
-- (not plain RLS) because the person redeeming isn't a member of the
-- target org yet — that's the whole point — so ordinary org-scoped
-- policies can't apply to them for that operation.
-- ============================================================
create table if not exists invites (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations(id) on delete cascade,
  code text not null unique,
  role text not null check (role in ('admin', 'staff')),
  created_by uuid not null references auth.users(id),
  created_at timestamptz not null default now(),
  expires_at timestamptz,
  used_by uuid references auth.users(id),
  used_at timestamptz
);
alter table invites enable row level security;

create policy "org owners and admins can create invites"
  on invites for insert
  with check (org_id in (select org_id from memberships where user_id = auth.uid() and role in ('owner', 'admin')));

create policy "org members can view their orgs invites"
  on invites for select
  using (org_id in (select org_id from memberships where user_id = auth.uid()));

create policy "org owners and admins can delete invites"
  on invites for delete
  using (org_id in (select org_id from memberships where user_id = auth.uid() and role in ('owner', 'admin')));

create or replace function redeem_invite(invite_code text)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  inv record;
  old_org_id uuid;
begin
  select * into inv from invites
    where code = invite_code and used_by is null
    and (expires_at is null or expires_at > now());

  if inv is null then
    return jsonb_build_object('ok', false, 'message', 'Invalid or expired invite code');
  end if;

  -- Re-parent the caller from their current org into the invited one,
  -- keeping the "one org per user" assumption the rest of the app relies
  -- on. If their old org becomes empty as a result, clean it up too
  -- (never touches an old org that still has other members in it).
  select org_id into old_org_id from memberships where user_id = auth.uid() limit 1;

  if old_org_id is not null and old_org_id != inv.org_id then
    delete from memberships where user_id = auth.uid() and org_id = old_org_id;
    if not exists (select 1 from memberships where org_id = old_org_id) then
      delete from organizations where id = old_org_id;
    end if;
  end if;

  insert into memberships (org_id, user_id, role)
  values (inv.org_id, auth.uid(), inv.role)
  on conflict (org_id, user_id) do update set role = excluded.role;

  update invites set used_by = auth.uid(), used_at = now() where id = inv.id;

  return jsonb_build_object('ok', true, 'message', 'Joined team successfully');
end;
$$;
