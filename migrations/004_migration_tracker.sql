-- This table is created automatically by the migration system
-- It tracks which migrations have been applied
CREATE TABLE IF NOT EXISTS migrations (
    filename TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
);
