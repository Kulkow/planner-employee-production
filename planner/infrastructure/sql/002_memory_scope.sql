ALTER TABLE planning_history ADD COLUMN IF NOT EXISTS memory_scope text NOT NULL DEFAULT 'process';
