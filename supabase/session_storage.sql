-- Session sync storage policies — profile-sessions bucket
--
-- Run this in the Supabase SQL Editor AFTER creating the "profile-sessions"
-- bucket via Dashboard -> Storage -> New bucket (Private, not public).
-- Without these policies, every push_session/pull_session call in
-- gui/cloud.py will fail with a permissions error even though the bucket
-- itself exists — Storage buckets need row-level security policies the
-- same way the tables in schema.sql do.
--
-- Objects are stored as "<org_id>/<profile_id>.zip". These policies let a
-- signed-in user read/write only objects whose first path segment matches
-- an org_id they're a member of — the same membership check used
-- everywhere else in schema.sql, just applied to storage.objects instead
-- of an app table.

create policy "org members can read their org's session files"
  on storage.objects for select
  to authenticated
  using (
    bucket_id = 'profile-sessions'
    and (storage.foldername(name))[1] in (
      select org_id::text from memberships where user_id = auth.uid()
    )
  );

create policy "org members can upload their org's session files"
  on storage.objects for insert
  to authenticated
  with check (
    bucket_id = 'profile-sessions'
    and (storage.foldername(name))[1] in (
      select org_id::text from memberships where user_id = auth.uid()
    )
  );

-- upload(..., {"upsert": "true"}) in cloud.py's push_session updates an
-- existing object in place once one's already there for that profile —
-- needs its own UPDATE policy alongside INSERT above, or every push after
-- the first for a given profile would fail.
create policy "org members can update their org's session files"
  on storage.objects for update
  to authenticated
  using (
    bucket_id = 'profile-sessions'
    and (storage.foldername(name))[1] in (
      select org_id::text from memberships where user_id = auth.uid()
    )
  )
  with check (
    bucket_id = 'profile-sessions'
    and (storage.foldername(name))[1] in (
      select org_id::text from memberships where user_id = auth.uid()
    )
  );

create policy "org members can delete their org's session files"
  on storage.objects for delete
  to authenticated
  using (
    bucket_id = 'profile-sessions'
    and (storage.foldername(name))[1] in (
      select org_id::text from memberships where user_id = auth.uid()
    )
  );
