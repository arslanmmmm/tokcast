-- Usage values that look wrong, per Claude Code version. Some versions logged
-- incomplete counts (see docs/related-work.md); flagged calls are kept out of training.
SELECT
    coalesce(s.tool_version, 'unknown')                          AS version,
    count(*)                                                     AS api_calls,
    count(r.quality_flag)                                        AS flagged,
    count_if(r.quality_flag = 'thinking_exceeds_output')         AS thinking_exceeds_output,
    count_if(r.quality_flag = 'zero_output')                     AS zero_output,
    count_if(r.quality_flag = 'zero_input')                      AS zero_input
FROM v_requests r
LEFT JOIN sessions s USING (session_id)
GROUP BY ALL
ORDER BY version;
