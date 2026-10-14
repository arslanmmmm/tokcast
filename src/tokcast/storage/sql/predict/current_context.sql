-- Where the most recent conversation stands: the next turn will re-read everything the
-- last main-agent call read, plus what it wrote.
SELECT
    session_id,
    ts,
    context_tokens + output_tokens  AS context_now,
    coalesce(model_family, 'other') AS model,
    effort
FROM v_requests
WHERE agent_id IS NULL AND ts IS NOT NULL
ORDER BY ts DESC
LIMIT 1;
