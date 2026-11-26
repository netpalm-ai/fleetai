DO $outer$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'fleetai_refuse_truncate') THEN
    EXECUTE $fn$
      CREATE FUNCTION fleetai_refuse_truncate()
      RETURNS trigger
      LANGUAGE plpgsql
      AS $body$
      BEGIN
        IF current_setting('cluster_name', true) IS DISTINCT FROM 'fleetai-ci' THEN
          RAISE EXCEPTION 'refusing to wipe this database. It is not a disposable test database, and the operator has not agreed to delete it.';
        END IF;
        RETURN NULL;
      END;
      $body$
    $fn$;
  END IF;

END;
$outer$;

DROP EVENT TRIGGER IF EXISTS fleetai_keep_wipe_guard;

CREATE OR REPLACE FUNCTION fleetai_keep_wipe_guard()
RETURNS event_trigger
LANGUAGE plpgsql
AS $body$
DECLARE
  cmd record;
  saw boolean := false;
BEGIN
  IF current_setting('cluster_name', true) = 'fleetai-ci' THEN
    RETURN;
  END IF;
  FOR cmd IN SELECT command_tag, object_identity, objid FROM pg_event_trigger_ddl_commands()
  LOOP
    saw := true;
    IF (
         cmd.command_tag IN ('CREATE FUNCTION', 'DROP FUNCTION', 'ALTER FUNCTION')
         AND coalesce(cmd.object_identity, '') LIKE '%fleetai_refuse_truncate%'
       ) OR (
         cmd.command_tag IN ('DROP TRIGGER', 'ALTER TRIGGER')
         AND coalesce(cmd.object_identity, '') LIKE '%fleetai_refuse_truncate%'
       ) THEN
      RAISE EXCEPTION 'refusing to wipe this database. It is not a disposable test database, and the operator has not agreed to delete it.';
    END IF;
    IF cmd.command_tag = 'CREATE TABLE' AND cmd.objid IS NOT NULL THEN
      IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'fleetai_refuse_truncate' AND tgrelid = cmd.objid
      ) THEN
        EXECUTE format(
          'CREATE TRIGGER fleetai_refuse_truncate BEFORE TRUNCATE ON %s FOR EACH STATEMENT EXECUTE FUNCTION fleetai_refuse_truncate()',
          cmd.objid::regclass
        );
      END IF;
    END IF;
  END LOOP;
  IF NOT saw AND position('fleetai_refuse_truncate' in current_query()) > 0 THEN
    RAISE EXCEPTION 'refusing to wipe this database. It is not a disposable test database, and the operator has not agreed to delete it.';
  END IF;
END;
$body$;

DO $attach$
DECLARE
  rel oid;
BEGIN
  FOR rel IN
    SELECT c.oid
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind = 'r'
  LOOP
    IF NOT EXISTS (
      SELECT 1 FROM pg_trigger WHERE tgname = 'fleetai_refuse_truncate' AND tgrelid = rel
    ) THEN
      EXECUTE format(
        'CREATE TRIGGER fleetai_refuse_truncate BEFORE TRUNCATE ON %s FOR EACH STATEMENT EXECUTE FUNCTION fleetai_refuse_truncate()',
        rel::regclass
      );
    END IF;
  END LOOP;
END;
$attach$;

DO $guard$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_event_trigger WHERE evtname = 'fleetai_keep_wipe_guard') THEN
    CREATE EVENT TRIGGER fleetai_keep_wipe_guard
      ON ddl_command_end
      WHEN TAG IN (
        'CREATE TABLE',
        'CREATE FUNCTION',
        'ALTER FUNCTION',
        'DROP FUNCTION',
        'DROP TRIGGER',
        'ALTER TRIGGER'
      )
      EXECUTE FUNCTION fleetai_keep_wipe_guard();
  END IF;
END;
$guard$;
