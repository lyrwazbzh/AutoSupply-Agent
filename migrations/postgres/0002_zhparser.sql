BEGIN;

CREATE EXTENSION IF NOT EXISTS zhparser;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_ts_config
        WHERE cfgname = 'procurement_zh'
          AND cfgnamespace = 'public'::regnamespace
    ) THEN
        CREATE TEXT SEARCH CONFIGURATION public.procurement_zh
            (PARSER = zhparser);
        ALTER TEXT SEARCH CONFIGURATION public.procurement_zh
            ADD MAPPING FOR n, v, a, i, e, l WITH simple;
    END IF;
END
$$;

COMMIT;
