CREATE TABLE rugcheck_reports (
    token_address TEXT PRIMARY KEY,
    score REAL,
    is_rugged BOOLEAN,
    risks TEXT,
    top_holders TEXT,
    raw_report TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (token_address) REFERENCES tokens(address)
);
