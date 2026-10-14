-- Usage per model and effort level, counted per API call (so a haiku subagent
-- inside an opus turn is counted as haiku).
SELECT
    coalesce(r.model_family, r.model, 'unknown')  AS model,
    -- Subagents don't record an effort level of their own.
    coalesce(r.effort, CASE WHEN r.agent_id IS NOT NULL THEN 'subagent' ELSE '-' END) AS effort,
    count(DISTINCT r.turn_id)                     AS turns,
    count(*)                                      AS api_calls,
    sum(r.output_tokens)::BIGINT                  AS output_tokens,
    sum(r.total_tokens)::BIGINT                   AS total_tokens,
    round(100 * sum(r.total_tokens) / sum(sum(r.total_tokens)) OVER (), 1) AS share_pct
FROM v_requests r
JOIN prompts p ON p.prompt_id = r.turn_id
WHERE p.ts >= $since
GROUP BY ALL
ORDER BY total_tokens DESC;
