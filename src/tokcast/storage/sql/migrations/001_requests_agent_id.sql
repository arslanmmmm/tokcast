-- Subagent calls are linked to their turn through agent_id (tokcast 0.1 databases
-- created before subagent support lack the column).
ALTER TABLE requests ADD COLUMN IF NOT EXISTS agent_id VARCHAR;
