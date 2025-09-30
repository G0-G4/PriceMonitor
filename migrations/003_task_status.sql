CREATE TABLE IF NOT EXISTS Task
(
    task_id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME,
    name TEXT,
    status TEXT,
    created_at DATETIME,
    updated_at DATETIME
);

