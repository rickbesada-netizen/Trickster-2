-- One-time fix for a user who signed up BEFORE schema.sql's auto-org
-- trigger existed. New signups from now on don't need this — the trigger
-- handles them automatically. Change the email below to your own.

do $$
declare
  target_user_id uuid;
  new_org_id uuid;
begin
  select id into target_user_id from auth.users where email = 'besadapatrick@gmail.com';

  if target_user_id is null then
    raise exception 'No user found with that email — double check it matches exactly.';
  end if;

  insert into organizations (name) values ('besadapatrick@gmail.com')
  returning id into new_org_id;

  insert into memberships (org_id, user_id, role)
  values (new_org_id, target_user_id, 'owner');

  raise notice 'Done — organization % created for user %', new_org_id, target_user_id;
end $$;
