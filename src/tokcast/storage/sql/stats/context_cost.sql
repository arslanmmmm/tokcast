-- How the cost of one API call grows with the conversation it has to re-read.
-- Main-agent calls only: subagents start with their own, smaller context.
WITH r AS (
    SELECT r.*
    FROM v_requests r
    JOIN prompts p ON p.prompt_id = r.turn_id
    WHERE p.ts >= $since AND r.agent_id IS NULL
)
SELECT
    CASE
        WHEN context_tokens < 50000  THEN '< 50k'
        WHEN context_tokens < 100000 THEN '50k-100k'
        WHEN context_tokens < 200000 THEN '100k-200k'
        WHEN context_tokens < 400000 THEN '200k-400k'
        ELSE '400k+'
    END                                AS context_size,
    count(*)                           AS api_calls,
    median(context_tokens)             AS median_context,
    median(output_tokens)              AS median_output,
    median(total_tokens)               AS median_call_tokens,
    -- Share of the context served from cache (cheap) rather than written to it.
    round(sum(cache_read_tokens) / nullif(sum(context_tokens), 0), 3) AS cache_hit_rate
FROM r
GROUP BY context_size
ORDER BY min(context_tokens);
