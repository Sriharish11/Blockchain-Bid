CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT DEFAULT 'bidder',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    image_url TEXT,
    starting_price REAL NOT NULL,
    current_price REAL NOT NULL,
    seller_id INTEGER NOT NULL,
    winner_id INTEGER,
    expires_at TIMESTAMP NOT NULL,
    status TEXT DEFAULT 'active',
    category TEXT DEFAULT 'Other',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (seller_id) REFERENCES users(id),
    FOREIGN KEY (winner_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS bids (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL,
    bidder_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    placed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (item_id) REFERENCES items(id),
    FOREIGN KEY (bidder_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS public_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hash_id TEXT UNIQUE NOT NULL,
    item_id INTEGER NOT NULL,
    bidder_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    prev_hash TEXT,
    timestamp TIMESTAMP NOT NULL,
    FOREIGN KEY (item_id) REFERENCES items(id),
    FOREIGN KEY (bidder_id) REFERENCES users(id)
);

INSERT OR IGNORE INTO users (username, email, password_hash, role) VALUES ('admin', 'admin@auction.com', 'pbkdf2:sha256:600000$zJ3bJ4gZJ2YhJ2Yh$9a2b2e2f2d2c2b2a292827262524232221201f1e1d1c1b1a1918171615141312', 'admin');
