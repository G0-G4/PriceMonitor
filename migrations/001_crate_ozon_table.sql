CREATE TABLE IF NOT EXISTS Parameter
(
    parameter_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT, -- название параметра
    value TEXT -- значение параметра
);

CREATE INDEX idx_parameters_name ON Parameter (name);

