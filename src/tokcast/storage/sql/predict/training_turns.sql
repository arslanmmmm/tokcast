-- Turns the predictor learns from: completed turns with at least one API call, no
-- suspicious usage values, and a known starting context. Oldest first.
SELECT
    turn_id,
    session_id,
    ts,
    turn_index,
    kind,
    text,
    text_chars,
    coalesce(model_family, 'other') AS model,
    coalesce(effort, 'unknown')     AS effort,
    context_tokens_before,
    n_requests,
    output_tokens,
    total_tokens
FROM turns
WHERE n_requests > 0
  AND n_flagged_requests = 0
  AND context_tokens_before IS NOT NULL
ORDER BY ts, turn_id;
