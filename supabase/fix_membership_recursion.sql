-- Fixes "infinite recursion detected in policy for relation memberships"
-- from team_management.sql. Run this ONCE in Supabase SQL Editor, in a
-- new query, after team_management.sql.
--
-- Root cause: a policy ON memberships that subqueries memberships to
-- decide access triggers the same policy again on that subquery, forever.
-- Fix: move the lookup into a SECURITY DEFINER helper function, which runs
-- with elevated privileges and bypasses RLS internally — breaking the loop.

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

drop policy if exists "members can view their orgs memberships" on memberships;
create policy "members can view their orgs memberships"
  on memberships for select
  using (org_id = get_my_org_id());

drop policy if exists "owners and admins can update member roles" on memberships;
create policy "owners and admins can update member roles"
  on memberships for update
  using (org_id = get_my_org_id() and get_my_role() in ('owner', 'admin'))
  with check (org_id = get_my_org_id() and get_my_role() in ('owner', 'admin'));

drop policy if exists "owners and admins can remove members" on memberships;
create policy "owners and admins can remove members"
  on memberships for delete
  using (org_id = get_my_org_id() and get_my_role() in ('owner', 'admin') and user_id != auth.uid());
