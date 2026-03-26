import sqlite3
import hashlib
import uuid
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'auction_secret_key_2024_secure'

DB_PATH = 'auction.db'

# ─── Database Setup ────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT DEFAULT 'bidder',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS items (
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
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (seller_id) REFERENCES users(id),
        FOREIGN KEY (winner_id) REFERENCES users(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS bids (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER NOT NULL,
        bidder_id INTEGER NOT NULL,
        amount REAL NOT NULL,
        placed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (item_id) REFERENCES items(id),
        FOREIGN KEY (bidder_id) REFERENCES users(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS public_ledger (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hash_id TEXT UNIQUE NOT NULL,
        item_id INTEGER NOT NULL,
        bidder_id INTEGER NOT NULL,
        amount REAL NOT NULL,
        prev_hash TEXT,
        timestamp TIMESTAMP NOT NULL,
        FOREIGN KEY (item_id) REFERENCES items(id),
        FOREIGN KEY (bidder_id) REFERENCES users(id)
    )''')

    # Seed admin
    try:
        admin_hash = generate_password_hash('admin123')
        c.execute("INSERT INTO users (username, email, password_hash, role) VALUES (?, ?, ?, ?)",
                  ('admin', 'admin@auction.com', admin_hash, 'admin'))
    except:
        pass

    conn.commit()
    conn.close()

# ─── Helpers ───────────────────────────────────────────────────────────────────

def generate_bid_hash(item_id, bidder_id, amount, timestamp, prev_hash):
    data = f"{item_id}{bidder_id}{amount}{timestamp}{prev_hash}"
    return hashlib.sha256(data.encode()).hexdigest()

def get_last_hash(item_id):
    conn = get_db()
    row = conn.execute(
        "SELECT hash_id FROM public_ledger WHERE item_id=? ORDER BY id DESC LIMIT 1", (item_id,)
    ).fetchone()
    conn.close()
    return row['hash_id'] if row else "GENESIS"

def log_to_ledger(item_id, bidder_id, amount):
    timestamp = datetime.utcnow().isoformat()
    prev_hash = get_last_hash(item_id)
    hash_id = generate_bid_hash(item_id, bidder_id, amount, timestamp, prev_hash)
    conn = get_db()
    conn.execute(
        "INSERT INTO public_ledger (hash_id, item_id, bidder_id, amount, prev_hash, timestamp) VALUES (?,?,?,?,?,?)",
        (hash_id, item_id, bidder_id, amount, prev_hash, timestamp)
    )
    conn.commit()
    conn.close()
    return hash_id

def check_expired_auctions():
    conn = get_db()
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M')
    # Normalize: replace T with space for comparison
    expired = conn.execute(
        "SELECT id FROM items WHERE status='active' AND replace(expires_at,'T',' ') <= ?", (now,)
    ).fetchall()
    for item in expired:
        top_bid = conn.execute(
            "SELECT bidder_id FROM bids WHERE item_id=? ORDER BY amount DESC LIMIT 1", (item['id'],)
        ).fetchone()
        winner_id = top_bid['bidder_id'] if top_bid else None
        conn.execute(
            "UPDATE items SET status='closed', winner_id=? WHERE id=?", (winner_id, item['id'])
        )
    conn.commit()
    conn.close()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') != 'admin':
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated

# ─── Routes ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        conn.close()
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            if user['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('dashboard'))
        flash('Invalid credentials', 'error')
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        role = request.form.get('role', 'bidder')
        if role not in ['bidder', 'seller']:
            role = 'bidder'
        try:
            conn = get_db()
            conn.execute(
                "INSERT INTO users (username, email, password_hash, role) VALUES (?,?,?,?)",
                (username, email, generate_password_hash(password), role)
            )
            conn.commit()
            conn.close()
            flash('Account created! Please login.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Username or email already exists.', 'error')
    return render_template('signup.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    check_expired_auctions()
    conn = get_db()
    items = conn.execute(
        "SELECT i.*, u.username as seller_name FROM items i JOIN users u ON i.seller_id=u.id WHERE i.status='active' ORDER BY i.created_at DESC"
    ).fetchall()
    conn.close()
    return render_template('dashboard.html', items=items)

@app.route('/item/<int:item_id>')
@login_required
def item_detail(item_id):
    check_expired_auctions()
    conn = get_db()
    item = conn.execute(
        "SELECT i.*, u.username as seller_name FROM items i JOIN users u ON i.seller_id=u.id WHERE i.id=?", (item_id,)
    ).fetchone()
    if not item:
        return redirect(url_for('dashboard'))
    bids = conn.execute(
        "SELECT b.*, u.username FROM bids b JOIN users u ON b.bidder_id=u.id WHERE b.item_id=? ORDER BY b.amount DESC LIMIT 10", (item_id,)
    ).fetchall()
    ledger = conn.execute(
        "SELECT l.*, u.username FROM public_ledger l JOIN users u ON l.bidder_id=u.id WHERE l.item_id=? ORDER BY l.id DESC LIMIT 5", (item_id,)
    ).fetchall()
    conn.close()
    return render_template('item_detail.html', item=item, bids=bids, ledger=ledger)

@app.route('/bid', methods=['POST'])
@login_required
def place_bid():
    data = request.get_json()
    item_id = data.get('item_id')
    amount = float(data.get('amount', 0))
    user_id = session['user_id']

    conn = get_db()
    item = conn.execute("SELECT * FROM items WHERE id=? AND status='active'", (item_id,)).fetchone()

    if not item:
        conn.close()
        return jsonify({'success': False, 'message': 'Auction not active or not found.'})

    if item['seller_id'] == user_id:
        conn.close()
        return jsonify({'success': False, 'message': 'You cannot bid on your own item.'})

    if amount <= item['current_price']:
        conn.close()
        return jsonify({'success': False, 'message': f'Bid must exceed current price of ${item["current_price"]:.2f}'})

    # Check expiry (normalize separators)
    expires_normalized = item['expires_at'].replace('T', ' ')
    if datetime.utcnow().strftime('%Y-%m-%d %H:%M') > expires_normalized[:16]:
        conn.execute("UPDATE items SET status='closed' WHERE id=?", (item_id,))
        conn.commit()
        conn.close()
        return jsonify({'success': False, 'message': 'Auction has expired.'})

    conn.execute("INSERT INTO bids (item_id, bidder_id, amount) VALUES (?,?,?)", (item_id, user_id, amount))
    conn.execute("UPDATE items SET current_price=? WHERE id=?", (amount, item_id))
    conn.commit()
    conn.close()

    hash_id = log_to_ledger(item_id, user_id, amount)
    return jsonify({'success': True, 'message': 'Bid placed!', 'new_price': amount, 'hash': hash_id[:16] + '...'})

@app.route('/list-item', methods=['GET', 'POST'])
@login_required
def list_item():
    if session.get('role') not in ['seller', 'admin']:
        flash('Only sellers can list items.', 'error')
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        starting_price = float(request.form['starting_price'])
        expires_at = request.form['expires_at']
        image_url = request.form.get('image_url', '')
        conn = get_db()
        conn.execute(
            "INSERT INTO items (title, description, image_url, starting_price, current_price, seller_id, expires_at) VALUES (?,?,?,?,?,?,?)",
            (title, description, image_url, starting_price, starting_price, session['user_id'], expires_at)
        )
        conn.commit()
        conn.close()
        flash('Item listed successfully!', 'success')
        return redirect(url_for('dashboard'))
    return render_template('list_item.html')

@app.route('/ledger')
@login_required
def public_ledger():
    conn = get_db()
    entries = conn.execute(
        "SELECT l.*, u.username, i.title FROM public_ledger l JOIN users u ON l.bidder_id=u.id JOIN items i ON l.item_id=i.id ORDER BY l.id DESC LIMIT 50"
    ).fetchall()
    conn.close()
    return render_template('ledger.html', entries=entries)

@app.route('/my-bids')
@login_required
def my_bids():
    conn = get_db()
    bids = conn.execute(
        "SELECT b.*, i.title, i.current_price, i.status, i.expires_at FROM bids b JOIN items i ON b.item_id=i.id WHERE b.bidder_id=? ORDER BY b.placed_at DESC",
        (session['user_id'],)
    ).fetchall()
    conn.close()
    return render_template('my_bids.html', bids=bids)

# ─── Admin Routes ──────────────────────────────────────────────────────────────

@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    conn = get_db()
    users = conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
    items = conn.execute("SELECT i.*, u.username as seller_name FROM items i JOIN users u ON i.seller_id=u.id ORDER BY i.created_at DESC").fetchall()
    total_bids = conn.execute("SELECT COUNT(*) as cnt FROM bids").fetchone()['cnt']
    active_auctions = conn.execute("SELECT COUNT(*) as cnt FROM items WHERE status='active'").fetchone()['cnt']
    conn.close()
    return render_template('admin.html', users=users, items=items, total_bids=total_bids, active_auctions=active_auctions)

@app.route('/admin/delete-item/<int:item_id>', methods=['POST'])
@login_required
@admin_required
def admin_delete_item(item_id):
    conn = get_db()
    conn.execute("DELETE FROM items WHERE id=?", (item_id,))
    conn.execute("DELETE FROM bids WHERE item_id=?", (item_id,))
    conn.commit()
    conn.close()
    flash('Item removed.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/toggle-user/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def admin_toggle_user(user_id):
    conn = get_db()
    user = conn.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
    if user and user['role'] != 'admin':
        new_role = 'seller' if user['role'] == 'bidder' else 'bidder'
        conn.execute("UPDATE users SET role=? WHERE id=?", (new_role, user_id))
        conn.commit()
    conn.close()
    return redirect(url_for('admin_dashboard'))

@app.route('/api/item/<int:item_id>/status')
def api_item_status(item_id):
    check_expired_auctions()
    conn = get_db()
    item = conn.execute("SELECT current_price, status, expires_at FROM items WHERE id=?", (item_id,)).fetchone()
    conn.close()
    if not item:
        return jsonify({'error': 'Not found'}), 404
    return jsonify({
        'current_price': item['current_price'],
        'status': item['status'],
        'expires_at': item['expires_at']
    })

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)
