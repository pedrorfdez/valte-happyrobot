drop function if exists finish_outbox(uuid, uuid, boolean, text);

create or replace function finish_outbox(
  p_outbox_id uuid,
  p_dispatch_id uuid,
  p_succeeded boolean,
  p_error text default null,
  p_retryable boolean default true
) returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_row outbox%rowtype;
begin
  update outbox
  set status = case
        when p_succeeded then 'dispatched'
        when not p_retryable then 'failed'
        when attempts >= 3 then 'failed'
        else 'pending'
      end,
      available_at = case
        when p_succeeded or not p_retryable then available_at
        else now() + interval '5 seconds'
      end,
      lease_until = null,
      dispatched_at = case when p_succeeded then now() else null end,
      last_error = case
        when p_succeeded then null
        else left(coalesce(p_error, 'dispatch failed'), 1000)
      end
  where outbox_id = p_outbox_id
    and dispatch_id = p_dispatch_id
    and status = 'claimed'
    and lease_until > now()
  returning * into v_row;

  if not found then
    return jsonb_build_object('error', 'outbox_lease_not_found');
  end if;

  return jsonb_build_object(
    'outbox_id', v_row.outbox_id,
    'status', v_row.status,
    'attempts', v_row.attempts
  );
end;
$$;

revoke all on function finish_outbox(uuid, uuid, boolean, text, boolean)
from public, anon, authenticated;
grant execute on function finish_outbox(uuid, uuid, boolean, text, boolean)
to service_role;
