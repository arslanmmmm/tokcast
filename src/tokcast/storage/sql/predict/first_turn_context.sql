-- How big a fresh conversation is before the first prompt (system prompt, tools,
-- CLAUDE.md, ...), from the user's own first turns.
SELECT median(context_tokens_before) AS context, count(*) AS n
FROM turns
WHERE turn_index = 1 AND context_tokens_before IS NOT NULL;
