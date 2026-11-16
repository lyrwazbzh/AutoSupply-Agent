-- One active semantic-memory version per user/logical key.
-- LangGraph owns the store table; run this after PostgresStore.setup().
WITH ranked AS (
    SELECT prefix,
           key AS store_key,
           first_value(value->>'id') OVER (
               PARTITION BY prefix, value->>'key'
               ORDER BY updated_at DESC, key DESC
           ) AS winner_id,
           row_number() OVER (
               PARTITION BY prefix, value->>'key'
               ORDER BY updated_at DESC, key DESC
           ) AS version_rank
    FROM store
    WHERE prefix LIKE 'memories.%.semantic'
      AND coalesce(value->>'key', '') <> ''
      AND coalesce(value->>'invalidated_at', '') = ''
)
UPDATE store AS item
SET value = jsonb_set(
                jsonb_set(
                    item.value,
                    '{invalidated_at}',
                    to_jsonb(CURRENT_TIMESTAMP::text),
                    true
                ),
                '{supersedes}',
                to_jsonb(ranked.winner_id),
                true
            ),
    updated_at = CURRENT_TIMESTAMP
FROM ranked
WHERE ranked.version_rank > 1
  AND item.prefix = ranked.prefix
  AND item.key = ranked.store_key;

CREATE UNIQUE INDEX IF NOT EXISTS store_one_active_semantic_key_idx
ON store (prefix, (value->>'key'))
WHERE prefix LIKE 'memories.%.semantic'
  AND coalesce(value->>'key', '') <> ''
  AND coalesce(value->>'invalidated_at', '') = '';
