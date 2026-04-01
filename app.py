import sqlite3
import hashlib
import uuid
import os
import qrcode
import io
import base64
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash, g
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message

app = Flask(__name__)
app.secret_key = 'auction_secret_key_2024_secure'

# ─── File Upload Configuration ────────────────────────────────────────────────
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ─── Mail Configuration ────────────────────────────────────────────────────────
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'sriharishkiruba@gmail.com'  # REPLACE WITH YOUR EMAIL
app.config['MAIL_PASSWORD'] = 'gtlaiwacbcsbfjni'     # REPLACE WITH YOUR APP PASSWORD
app.config['MAIL_DEFAULT_SENDER'] = 'sriharishkiruba@gmail.com'

mail = Mail(app)

DB_PATH = 'auction.db'

# ─── Database Setup ────────────────────────────────────────────────────────────

def get_db():
    """Opens a new database connection if there is none yet for the current application context."""
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    """Closes the database again at the end of the request."""
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        with app.open_resource('schema.sql', mode='r') as f:
            db.cursor().executescript(f.read())
        db.commit()

# ─── Helpers ───────────────────────────────────────────────────────────────────

def generate_qr_base64(data):
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode('utf-8')

def send_email_to_all_users(subject, body):
    db = get_db()
    users = db.execute("SELECT email FROM users").fetchall()
    
    emails = [user['email'] for user in users]
    if emails:
        try:
            msg = Message(subject, recipients=emails)
            msg.body = body
            mail.send(msg)
        except Exception as e:
            print(f"Error sending email to all users: {e}")

def send_winner_email(winner_email, item_title, amount):
    subject = f"Congratulations! You won the bid for {item_title}"
    body = f"""Hello,

Congratulations! You are the winner of this bid and you have won the bid for {item_title} at {amount} RS.

Please scan the attached QR code to make the payment for your winning bid.

Also, please reply to this email with your full address to send the product to you.

Thank you!
"""
    try:
        msg = Message(subject, recipients=[winner_email])
        msg.body = body
        
        # Path to the specific payment QR image provided by the user
        qr_image_path = os.path.join(app.root_path, 'static', 'uploads', 'WhatsApp Image 2026-03-26 at 5.58.03 PM.jpeg')
        
        if os.path.exists(qr_image_path):
            with open(qr_image_path, 'rb') as f:
                msg.attach("payment_qr.jpeg", "image/jpeg", f.read())
        else:
            # Fallback to generated QR if the specific file is missing
            qr_data = f"upi://pay?pa=7871138827@naviaxis&pn=SRIHARISH K&am={amount}&cu=INR&tn=Payment for {item_title}"
            qr_base64 = generate_qr_base64(qr_data)
            qr_img = base64.b64decode(qr_base64)
            msg.attach("payment_qr.png", "image/png", qr_img)
            
        mail.send(msg)
    except Exception as e:
        print(f"Error sending winner email: {e}")

def generate_bid_hash(item_id, bidder_id, amount, timestamp, prev_hash):
    data = f"{item_id}{bidder_id}{amount}{timestamp}{prev_hash}"
    return hashlib.sha256(data.encode()).hexdigest()

def get_last_hash(item_id):
    db = get_db()
    row = db.execute(
        "SELECT hash_id FROM public_ledger WHERE item_id=? ORDER BY id DESC LIMIT 1", (item_id,)
    ).fetchone()
    return row['hash_id'] if row else "GENESIS"

def log_to_ledger(item_id, bidder_id, amount):
    timestamp = datetime.utcnow().isoformat()
    prev_hash = get_last_hash(item_id)
    hash_id = generate_bid_hash(item_id, bidder_id, amount, timestamp, prev_hash)
    db = get_db()
    db.execute(
        "INSERT INTO public_ledger (hash_id, item_id, bidder_id, amount, prev_hash, timestamp) VALUES (?,?,?,?,?,?)",
        (hash_id, item_id, bidder_id, amount, prev_hash, timestamp)
    )
    db.commit()
    return hash_id

def check_expired_auctions():
    db = get_db()
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M')
    # Normalize: replace T with space for comparison
    cursor = db.execute(
        "SELECT id, title FROM items WHERE status='active' AND replace(expires_at,'T',' ') <= ?", (now,)
    )
    expired = cursor.fetchall()
    for item in expired:
        top_bid_cursor = db.execute(
            "SELECT b.bidder_id, b.amount, u.email FROM bids b JOIN users u ON b.bidder_id=u.id WHERE b.item_id=? ORDER BY b.amount DESC LIMIT 1", (item['id'],)
        )
        top_bid = top_bid_cursor.fetchone()
        
        # When using sqlite3.Row, you access columns by name, not by index for unpacking
        winner_id = top_bid['bidder_id'] if top_bid else None
        db.execute(
            "UPDATE items SET status='closed', winner_id=? WHERE id=?", (winner_id, item['id'])
        )
        
        if top_bid:
            send_winner_email(top_bid['email'], item['title'], top_bid['amount'])
            
    db.commit()

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
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if user and check_password_hash(user['password_hash'], password):
            session.clear()
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
            db = get_db()
            db.execute(
                "INSERT INTO users (username, email, password_hash, role) VALUES (?,?,?,?)",
                (username, email, generate_password_hash(password), role)
            )
            db.commit()
            flash('Account created! Please login.', 'success')
            return redirect(url_for('login'))
        except db.IntegrityError:
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
    db = get_db()
    
    # Get current category filter
    category_filter = request.args.get('category', 'All')
    
    if category_filter == 'All':
        items_cursor = db.execute(
            "SELECT i.*, u.username as seller_name FROM items i JOIN users u ON i.seller_id=u.id WHERE i.status='active' ORDER BY i.created_at DESC"
        )
        items = items_cursor.fetchall()
    else:
        items_cursor = db.execute(
            "SELECT i.*, u.username as seller_name FROM items i JOIN users u ON i.seller_id=u.id WHERE i.status='active' AND i.category=? ORDER BY i.created_at DESC",
            (category_filter,)
        )
        items = items_cursor.fetchall()
    
    closed_items_cursor = db.execute(
        "SELECT i.*, u.username as seller_name, w.username as winner_name FROM items i JOIN users u ON i.seller_id=u.id LEFT JOIN users w ON i.winner_id=w.id WHERE i.status='closed' ORDER BY i.expires_at DESC LIMIT 10"
    )
    closed_items = closed_items_cursor.fetchall()
    
    # Get all categories for filter buttons
    categories_rows_cursor = db.execute("SELECT DISTINCT category FROM items")
    categories_rows = categories_rows_cursor.fetchall()
    categories = ['All'] + [row['category'] for row in categories_rows if row['category']]
    
    return render_template('dashboard.html', items=items, closed_items=closed_items, categories=categories, current_category=category_filter)

@app.route('/item/<int:item_id>')
@login_required
def item_detail(item_id):
    check_expired_auctions()
    db = get_db()
    item = db.execute(
        "SELECT i.*, u.username as seller_name FROM items i JOIN users u ON i.seller_id=u.id WHERE i.id=?", (item_id,)
    ).fetchone()
    if not item:
        return redirect(url_for('dashboard'))
    bids = db.execute(
        "SELECT b.*, u.username FROM bids b JOIN users u ON b.bidder_id=u.id WHERE b.item_id=? ORDER BY b.amount DESC LIMIT 10", (item_id,)
    ).fetchall()
    ledger = db.execute(
        "SELECT l.*, u.username FROM public_ledger l JOIN users u ON l.bidder_id=u.id WHERE l.item_id=? ORDER BY l.id DESC LIMIT 5", (item_id,)
    ).fetchall()
    return render_template('item_detail.html', item=item, bids=bids, ledger=ledger)

@app.route('/bid', methods=['POST'])
@login_required
def place_bid():
    try:
        data = request.get_json()
        item_id = data.get('item_id')
        amount = float(data.get('amount', 0))
        user_id = session['user_id']

        db = get_db()
        item = db.execute("SELECT * FROM items WHERE id=? AND status='active'", (item_id,)).fetchone()

        if not item:
            return jsonify({'success': False, 'message': 'Auction not active or not found.'})

        if item['seller_id'] == user_id:
            return jsonify({'success': False, 'message': 'You cannot bid on your own item.'})

        if amount <= float(item['current_price']):
            return jsonify({'success': False, 'message': f'Bid must exceed current price of {item["current_price"]:.2f} RS'})

        # Check expiry
        expires_at_str = str(item['expires_at']).replace('T', ' ')
        now_str = datetime.utcnow().strftime('%Y-%m-%d %H:%M')
        if now_str > expires_at_str[:16]:
            top_bid_cursor = db.execute(
                "SELECT b.bidder_id, b.amount, u.email FROM bids b JOIN users u ON b.bidder_id=u.id WHERE b.item_id=? ORDER BY b.amount DESC LIMIT 1", (item_id,)
            )
            top_bid = top_bid_cursor.fetchone()
            
            winner_id = top_bid['bidder_id'] if top_bid else None
            db.execute("UPDATE items SET status='closed', winner_id=? WHERE id=?", (winner_id, item_id))
            db.commit()
            
            if top_bid:
                try:
                    send_winner_email(top_bid['email'], item['title'], top_bid['amount'])
                except Exception as e:
                    pass
                
            return jsonify({'success': False, 'message': 'Auction has expired.'})

        db.execute("INSERT INTO bids (item_id, bidder_id, amount) VALUES (?,?,?)", (item_id, user_id, amount))
        db.execute("UPDATE items SET current_price=? WHERE id=?", (amount, item_id))
        db.commit()

        # Send notification to all users (don't block the response)
        try:
            subject = f"New bid for {item['title']}!"
            body = f"A new bid of {amount} RS has been placed on {item['title']}."
            send_email_to_all_users(subject, body)
        except Exception as e:
            pass

        hash_id = log_to_ledger(item_id, user_id, amount)
        return jsonify({'success': True, 'message': 'Bid placed!', 'new_price': amount, 'hash': hash_id[:16] + '...'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

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
        category = request.form.get('category', 'Other')
        
        # Image handling
        image_url = request.form.get('image_url', '')
        if 'image_file' in request.files:
            file = request.files['image_file']
            if file and allowed_file(file.filename):
                filename = f"{uuid.uuid4().hex}_{file.filename}"
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)
                image_url = f"/static/uploads/{filename}"

        db = get_db()
        db.execute(
            "INSERT INTO items (title, description, image_url, starting_price, current_price, seller_id, expires_at, category) VALUES (?,?,?,?,?,?,?,?)",
            (title, description, image_url, starting_price, starting_price, session['user_id'], expires_at, category)
        )
        db.commit()
        flash('Item listed successfully!', 'success')
        return redirect(url_for('dashboard'))
    return render_template('list_item.html')

@app.route('/ledger')
@login_required
def public_ledger():
    db = get_db()
    entries = db.execute(
        "SELECT l.*, u.username, i.title FROM public_ledger l JOIN users u ON l.bidder_id=u.id JOIN items i ON l.item_id=i.id ORDER BY l.id DESC LIMIT 50"
    ).fetchall()
    return render_template('ledger.html', entries=entries)

@app.route('/my-bids')
@login_required
def my_bids():
    db = get_db()
    bids = db.execute(
        "SELECT b.*, i.title, i.current_price, i.status, i.expires_at FROM bids b JOIN items i ON b.item_id=i.id WHERE b.bidder_id=? ORDER BY b.placed_at DESC",
        (session['user_id'],)
    ).fetchall()
    return render_template('my_bids.html', bids=bids)

# ─── Admin Routes ──────────────────────────────────────────────────────────────

@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    db = get_db()
    users = db.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
    items = db.execute("SELECT i.*, u.username as seller_name FROM items i JOIN users u ON i.seller_id=u.id ORDER BY i.created_at DESC").fetchall()
    total_bids = db.execute("SELECT COUNT(*) as cnt FROM bids").fetchone()['cnt']
    active_auctions = db.execute("SELECT COUNT(*) as cnt FROM items WHERE status='active'").fetchone()['cnt']
    return render_template('admin.html', users=users, items=items, total_bids=total_bids, active_auctions=active_auctions)

@app.route('/admin/stop-bid/<int:item_id>', methods=['POST'])
@login_required
def stop_bid(item_id):
    db = get_db()
    item = db.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not item:
        flash('Item not found.', 'error')
        return redirect(url_for('admin_dashboard'))

    # Check permissions (Seller or Admin)
    if session.get('role') != 'admin' and item['seller_id'] != session['user_id']:
        flash('Permission denied.', 'error')
        return redirect(url_for('dashboard'))

    # Manually close the auction
    top_bid = db.execute(
        "SELECT b.bidder_id, b.amount, u.email FROM bids b JOIN users u ON b.bidder_id=u.id WHERE b.item_id=? ORDER BY b.amount DESC LIMIT 1", (item_id,)
    ).fetchone()
    
    winner_id = top_bid['bidder_id'] if top_bid else None
    db.execute(
        "UPDATE items SET status='closed', winner_id=? WHERE id=?", (winner_id, item_id)
    )
    db.commit()

    if top_bid:
        send_winner_email(top_bid['email'], item['title'], top_bid['amount'])
    
    flash('Auction stopped successfully.', 'success')
    return redirect(request.referrer or url_for('admin_dashboard'))

@app.route('/admin/edit-expiry/<int:item_id>', methods=['POST'])
@login_required
def edit_expiry(item_id):
    new_expiry = request.form.get('expires_at')
    if not new_expiry:
        flash('Invalid expiry date.', 'error')
        return redirect(request.referrer or url_for('admin_dashboard'))

    db = get_db()
    item = db.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not item:
        flash('Item not found.', 'error')
        return redirect(url_for('admin_dashboard'))

    # Check permissions (Seller or Admin)
    if session.get('role') != 'admin' and item['seller_id'] != session['user_id']:
        flash('Permission denied.', 'error')
        return redirect(url_for('dashboard'))

    db.execute("UPDATE items SET expires_at=? WHERE id=?", (new_expiry, item_id))
    db.commit()
    
    flash('Auction expiry updated.', 'success')
    return redirect(request.referrer or url_for('admin_dashboard'))

@app.route('/admin/delete-item/<int:item_id>', methods=['POST'])
@login_required
@admin_required
def admin_delete_item(item_id):
    db = get_db()
    db.execute("DELETE FROM items WHERE id=?", (item_id,))
    db.execute("DELETE FROM bids WHERE item_id=?", (item_id,))
    db.commit()
    flash('Item removed.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/toggle-user/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def admin_toggle_user(user_id):
    db = get_db()
    user = db.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
    if user and user['role'] != 'admin':
        new_role = 'seller' if user['role'] == 'bidder' else 'bidder'
        db.execute("UPDATE users SET role=? WHERE id=?", (new_role, user_id))
        db.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/update-category/<int:item_id>', methods=['POST'])
@login_required
@admin_required
def admin_update_category(item_id):
    category = request.form.get('category')
    if not category:
        flash('Invalid category.', 'error')
        return redirect(url_for('admin_dashboard'))

    db = get_db()
    db.execute("UPDATE items SET category=? WHERE id=?", (category, item_id))
    db.commit()
    
    flash('Item category updated.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/api/item/<int:item_id>/status')
def api_item_status(item_id):
    check_expired_auctions()
    db = get_db()
    item = db.execute("SELECT current_price, status, expires_at FROM items WHERE id=?", (item_id,)).fetchone()
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
