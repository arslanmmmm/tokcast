-- Headline numbers for the selected period (turns that started at or after $since).
WITH t AS (SELECT * FROM turns WHERE ts >= $since),
r AS (
    SELECT r.*
    FROM v_requests r
    JOIN prompts p ON p.prompt_id = r.turn_id
    WHERE p.ts >= $since
)
SELECT
    (SELECT min(ts) FROM t)                          AS first_ts,
    (SELECT max(ts) FROM t)                          AS last_ts,
    (SELECT count(DISTINCT session_id) FROM t)       AS sessions,
    (SELECT count(*) FROM t)                         AS turns,
    (SELECT count(*) FROM r)                         AS api_calls,
    (SELECT coalesce(sum(total_tokens), 0) FROM r)::BIGINT       AS total_tokens,
    (SELECT coalesce(sum(output_tokens), 0) FROM r)::BIGINT      AS output_tokens,
    (SELECT coalesce(sum(cache_read_tokens), 0) FROM r)::BIGINT  AS cache_read_tokens,
    (SELECT coalesce(sum(total_tokens), 0) FROM r WHERE agent_id IS NOT NULL)::BIGINT
                                                     AS subagent_tokens,
    (SELECT median(total_tokens) FROM t)             AS median_turn_tokens,
    (SELECT quantile_cont(total_tokens, 0.9) FROM t) AS p90_turn_tokens;
