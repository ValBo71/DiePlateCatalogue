import os
import io
import json
import zipfile
import sqlite3
import socket
import secrets
import hashlib
import time
import threading
import logging
from contextlib import contextmanager
from functools import wraps
from urllib.parse import urlparse
from flask import Flask, request, jsonify, render_template, send_from_directory, session, redirect, url_for, send_file
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
# PyMuPDF - renders a raster preview from uploaded PDF drawings.
# It was renamed from "fitz" to "pymupdf" in 1.24.3; the old name still works but
# is deprecated and will eventually be dropped, so prefer the new one and fall
# back only for older installs.
try:
    import pymupdf
except ImportError:  # PyMuPDF older than 1.24.3
    import fitz as pymupdf

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configurations
APP_ROOT = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = 'uploads'
DB_FOLDER = 'database'
DB_PATH = os.path.join(DB_FOLDER, 'catalog.db')
SECRET_KEY_FILE = os.path.join(DB_FOLDER, '.flask_secret_key')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'svg'}
# Design/production files that "Копирай файла" may copy from a tool's file_path.
# Anything else (databases, keys, scripts, configs...) is refused, so the feature
# cannot be used to read arbitrary files from the server.
COPYABLE_EXTENSIONS = ALLOWED_EXTENSIONS | {
    'ai', 'eps', 'ps', 'cdr', 'dxf', 'dwg', 'cf2', 'ard', 'mfg', 'plt', 'hpgl',
    'tif', 'tiff', 'psd', 'indd', 'idml', 'bmp', 'webp'
}
# Change this single value if port 5050 is already taken on this machine
# (remember to update run.bat/run_mac.command, which open the browser at it).
PORT = 5050

ROLE_ADMIN = 'admin'
ROLE_READ_WRITE = 'read_write'
ROLE_READ_ONLY = 'read_only'
ROLES = (ROLE_ADMIN, ROLE_READ_WRITE, ROLE_READ_ONLY)
ROLE_LABELS = {ROLE_ADMIN: 'Администратор', ROLE_READ_WRITE: 'Редактиране', ROLE_READ_ONLY: 'Само преглед'}

# Allowed values - also used as HTML/JS values in the UI, so anything else is refused
CATEGORY_PREFIXES = {'die': 'SH-', 'embossing': 'PR-', 'foil': 'TP-'}
STATUSES = ('active', 'borrowed', 'archived')

MIN_PASSWORD_LENGTH = 8
# First-run admin password, documented in README.md so a fresh install can be opened.
# Changing it after the first login is up to the users (see README).
DEFAULT_ADMIN_PASSWORD = 'admin'
SESSION_MAX_AGE_SECONDS = 12 * 60 * 60  # a login is valid for one working day
LOGIN_MAX_FAILURES = 5
LOGIN_LOCKOUT_SECONDS = 60

PUBLIC_PATHS = {'/login', '/logout'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload size
# Lax SameSite keeps the session cookie off cross-site requests; the Origin check in
# reject_cross_origin_writes also covers other sites on the same host (other ports).
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True

# Ensure folders exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(DB_FOLDER, exist_ok=True)

def get_or_create_secret_key():
    """Flask session signing key, persisted in the git-ignored database/ folder so
    sessions survive restarts but the key never ends up committed to the repo."""
    if os.path.exists(SECRET_KEY_FILE):
        with open(SECRET_KEY_FILE, 'r', encoding='utf-8') as f:
            saved_key = f.read().strip()
            if saved_key:
                return saved_key

    new_key = secrets.token_hex(32)
    with open(SECRET_KEY_FILE, 'w', encoding='utf-8') as f:
        f.write(new_key)
    return new_key

app.secret_key = get_or_create_secret_key()

@contextmanager
def get_db(row_factory=None):
    """Opens a SQLite connection that is ALWAYS closed and rolled back on errors.
    A connection left open after an exception keeps SQLite's write lock and makes
    every other operator's save fail with 'database is locked'."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    if row_factory:
        conn.row_factory = row_factory
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def password_fingerprint(password_hash):
    """Short digest of the stored hash: changes whenever the password changes, so
    sessions created before a password change stop being valid."""
    return hashlib.sha256(password_hash.encode('utf-8')).hexdigest()[:16]

@app.before_request
def reject_cross_origin_writes():
    """CSRF protection: browsers send Origin on cross-origin POST/PUT/DELETE, so a
    write coming from another site (or another port on this host) is refused."""
    if request.method in ('POST', 'PUT', 'DELETE', 'PATCH'):
        origin = request.headers.get('Origin')
        if origin and urlparse(origin).netloc != request.host:
            logger.warning("Rejected cross-origin %s %s from %s", request.method, request.path, origin)
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Заявката е отхвърлена (друг сайт).'}), 403
            return 'Forbidden', 403
    return None

@app.before_request
def enforce_login():
    if request.path in PUBLIC_PATHS or request.path.startswith('/static/'):
        return None

    user = None
    if 'user_id' in session:
        # The session only proves who logged in. Role, existence and password are
        # re-read on every request, so demoting/deleting a user or changing their
        # password takes effect immediately instead of at their next login.
        with get_db(sqlite3.Row) as conn:
            user = conn.execute(
                "SELECT id, username, role, password_hash FROM users WHERE id = ?", (session['user_id'],)
            ).fetchone()
        too_old = time.time() - session.get('login_at', 0) > SESSION_MAX_AGE_SECONDS
        if (not user or too_old
                or session.get('pw') != password_fingerprint(user['password_hash'])):
            user = None
            session.clear()

    if not user:
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Не сте влезли в системата.'}), 401
        return redirect(url_for('login_page'))

    session['username'] = user['username']
    session['role'] = user['role']
    return None

def require_role(*allowed_roles):
    """Route decorator restricting access to the given roles; assumes enforce_login
    already guaranteed the user is authenticated (and refreshed session['role'])."""
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            if session.get('role') not in allowed_roles:
                if request.path.startswith('/api/'):
                    return jsonify({'error': 'Нямате права за това действие.'}), 403
                return redirect(url_for('index'))
            return view_func(*args, **kwargs)
        return wrapped
    return decorator

def is_inside_app(candidate_path):
    """True if candidate_path is (or is inside) the application folder. Its static/
    folder is served without login and database/ holds the secret key and password
    hashes, so copying files into or out of it would leak them."""
    try:
        real_candidate = os.path.realpath(candidate_path)
    except (OSError, ValueError):
        return True
    # database/ and uploads/ are relative to the working folder, which is normally
    # APP_ROOT but may differ when started from elsewhere - protect them explicitly.
    for protected in (APP_ROOT, DB_FOLDER, UPLOAD_FOLDER):
        root = os.path.realpath(protected)
        if real_candidate == root or real_candidate.startswith(root + os.sep):
            return True
    return False

def get_local_ip():
    """Returns the local IP address of the machine."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Doesn't need to connect to anything, just triggers local IP routing
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def init_db():
    """Initializes the SQLite database with the tools table."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    c = conn.cursor()
    # WAL lets operators read while another one is saving
    c.execute("PRAGMA journal_mode=WAL")
    c.execute('''
        CREATE TABLE IF NOT EXISTS tools (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            category TEXT NOT NULL,
            name TEXT NOT NULL,
            client TEXT,
            dimensions TEXT,
            location TEXT,
            image_filename TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            notes TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Run migrations for new columns
    c.execute("PRAGMA table_info(tools)")
    columns = [row[1] for row in c.fetchall()]

    if 'die_shape' not in columns:
        c.execute("ALTER TABLE tools ADD COLUMN die_shape TEXT")
    if 'ups' not in columns:
        c.execute("ALTER TABLE tools ADD COLUMN ups INTEGER DEFAULT 1")
    if 'material' not in columns:
        c.execute("ALTER TABLE tools ADD COLUMN material TEXT")
    if 'die_type' not in columns:
        c.execute("ALTER TABLE tools ADD COLUMN die_type TEXT")
    if 'single_item_dimensions' not in columns:
        c.execute("ALTER TABLE tools ADD COLUMN single_item_dimensions TEXT")
    if 'file_path' not in columns:
        c.execute("ALTER TABLE tools ADD COLUMN file_path TEXT")
    if 'preview_filename' not in columns:
        c.execute("ALTER TABLE tools ADD COLUMN preview_filename TEXT")

    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'read_only',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # A tool can have several drawings (chertezhi) attached; each row is one
    # uploaded file plus its optional rendered preview (for PDFs).
    c.execute('''
        CREATE TABLE IF NOT EXISTS tool_drawings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tool_id INTEGER NOT NULL,
            image_filename TEXT NOT NULL,
            preview_filename TEXT,
            position INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()

    # One-time migration: earlier versions stored a single drawing directly on
    # the tools row. Copy it into tool_drawings so old tools keep their drawing.
    c.execute("SELECT id, image_filename, preview_filename FROM tools WHERE image_filename IS NOT NULL AND image_filename != ''")
    legacy_rows = c.fetchall()
    for legacy_tool_id, legacy_image, legacy_preview in legacy_rows:
        c.execute("SELECT COUNT(*) FROM tool_drawings WHERE tool_id = ?", (legacy_tool_id,))
        if c.fetchone()[0] == 0:
            c.execute(
                "INSERT INTO tool_drawings (tool_id, image_filename, preview_filename, position) VALUES (?, ?, ?, 0)",
                (legacy_tool_id, legacy_image, legacy_preview)
            )
    conn.commit()

    # Bootstrap a default admin account on first run.
    bootstrap_password = None
    c.execute("SELECT COUNT(*) FROM users")
    if c.fetchone()[0] == 0:
        bootstrap_password = os.environ.get('CATALOG_ADMIN_PASSWORD', '').strip() or DEFAULT_ADMIN_PASSWORD
        c.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            ('admin', generate_password_hash(bootstrap_password), ROLE_ADMIN)
        )
        conn.commit()

    # Optional recovery path if the admin password is forgotten: set this env var and restart.
    reset_password = os.environ.get('CATALOG_RESET_ADMIN_PASSWORD', '').strip()
    if reset_password:
        c.execute("SELECT id FROM users WHERE role = ? ORDER BY id ASC LIMIT 1", (ROLE_ADMIN,))
        row = c.fetchone()
        if row:
            c.execute("UPDATE users SET password_hash = ? WHERE id = ?", (generate_password_hash(reset_password), row[0]))
            conn.commit()
            logger.info("Admin password was reset via the CATALOG_RESET_ADMIN_PASSWORD env var.")

    conn.close()
    return bootstrap_password

def next_code(conn, category):
    """Next sequential code for the category (e.g. SH-0001, PR-0001, TP-0001).
    Looks at every code with the prefix - also manually entered ones and ones on
    tools of another category - and must run inside the same write transaction
    as the INSERT, so two operators saving at once cannot get the same code."""
    prefix = CATEGORY_PREFIXES[category]
    max_num = 0
    for (code_str,) in conn.execute("SELECT code FROM tools WHERE code LIKE ?", (prefix + "%",)):
        try:
            max_num = max(max_num, int(code_str[len(prefix):]))
        except ValueError:
            continue
    return f"{prefix}{max_num + 1:04d}"

def allowed_file(filename):
    """Checks if the file extension is allowed."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def generate_preview_image(source_filename):
    """Renders the first page of an uploaded PDF drawing into a PNG so it can be
    shown as a normal <img> thumbnail (browsers can't preview PDFs inline).
    Returns the generated filename, or None if the source isn't a PDF or rendering fails."""
    if not source_filename or not source_filename.lower().endswith('.pdf'):
        return None

    source_path = os.path.join(app.config['UPLOAD_FOLDER'], source_filename)
    preview_filename = f"{os.path.splitext(source_filename)[0]}_preview.png"
    preview_path = os.path.join(app.config['UPLOAD_FOLDER'], preview_filename)

    try:
        with pymupdf.open(source_path) as doc:
            page = doc.load_page(0)
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2))
            pixmap.save(preview_path)
        return preview_filename
    except Exception:
        logger.warning("Could not generate PDF preview for %s", source_filename, exc_info=True)
        return None

def remove_upload(filename):
    """Deletes a file from the uploads folder (and its cached thumbnail) if it exists."""
    if not filename:
        return
    for path in (os.path.join(app.config['UPLOAD_FOLDER'], filename), thumbnail_path(filename)):
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                logger.warning("Could not remove upload %s", path, exc_info=True)

THUMB_FOLDER = os.path.join(UPLOAD_FOLDER, 'thumbs')
THUMB_MAX_WIDTH = 480  # 80px thumbnails at up to 6x density, grid previews at 2x
RASTER_THUMB_EXTENSIONS = ('.png', '.jpg', '.jpeg')

def thumbnail_path(filename):
    return os.path.join(THUMB_FOLDER, f"{filename}.png")

def sanitize_filename_component(name):
    """Strips a free-text name down to safe filesystem characters for use in a filename."""
    return "".join(c if c.isalnum() or c in (' ', '_', '-') else '' for c in (name or '')).strip().replace(' ', '_')

def build_upload_filename(original_name, index):
    """Server-side name for an upload. The extension is taken from the original name
    separately: secure_filename() drops Cyrillic, so 'чертеж.pdf' would otherwise
    become just 'pdf' and lose its extension (no preview, wrong type on download)."""
    stem, ext = os.path.splitext(original_name)
    safe_stem = secure_filename(stem) or 'drawing'
    return f"{int(time.time())}_{secrets.token_hex(3)}_{index}_{safe_stem}{ext.lower()}"

def save_new_drawing_files(conn, tool_id, files, start_position):
    """Validates and saves each uploaded file as a drawing for tool_id, generating a
    PDF preview where needed. Returns the number of drawings actually saved."""
    c = conn.cursor()
    position = start_position
    saved_count = 0
    for index, file in enumerate(files):
        if not file or file.filename == '' or not allowed_file(file.filename):
            continue
        filename = build_upload_filename(file.filename, index)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        preview_filename = generate_preview_image(filename)
        c.execute(
            "INSERT INTO tool_drawings (tool_id, image_filename, preview_filename, position) VALUES (?, ?, ?, ?)",
            (tool_id, filename, preview_filename, position)
        )
        position += 1
        saved_count += 1
    return saved_count

def get_drawings_by_tool_ids(conn, tool_ids):
    """Returns {tool_id: [drawing dicts...]} ordered by position, for the given tool ids."""
    if not tool_ids:
        return {}
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    placeholders = ",".join("?" for _ in tool_ids)
    c.execute(
        f"SELECT id, tool_id, image_filename, preview_filename FROM tool_drawings WHERE tool_id IN ({placeholders}) ORDER BY tool_id, position, id",
        list(tool_ids)
    )
    drawings_map = {}
    for row in c.fetchall():
        drawings_map.setdefault(row['tool_id'], []).append({
            'id': row['id'],
            'image_filename': row['image_filename'],
            'preview_filename': row['preview_filename']
        })
    return drawings_map

def delete_drawings_for_tool(conn, tool_id):
    """Removes every drawing (files + rows) belonging to tool_id."""
    c = conn.cursor()
    c.execute("SELECT image_filename, preview_filename FROM tool_drawings WHERE tool_id = ?", (tool_id,))
    for image_filename, preview_filename in c.fetchall():
        remove_upload(image_filename)
        remove_upload(preview_filename)
    c.execute("DELETE FROM tool_drawings WHERE tool_id = ?", (tool_id,))

# Serve uploaded files
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    # Absolute path: send_from_directory resolves a relative folder against the code
    # folder, while uploads are saved relative to the working folder.
    response = send_from_directory(os.path.abspath(app.config['UPLOAD_FOLDER']), filename)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    if not filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.pdf')):
        # SVG (and anything unexpected) can carry <script>. When opened directly it
        # would run with the viewer's session; the sandbox CSP stops that, while
        # <img src> thumbnails keep working. (PDFs are excluded: Chrome refuses to
        # show a PDF in a sandboxed document.)
        response.headers['Content-Security-Policy'] = "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; sandbox"
    return response

# Small cached preview of an uploaded raster drawing (the table and cards show them at
# 80-300px, the originals are often >1000px). SVG/GIF/others fall back to the original.
@app.route('/thumbs/<filename>')
def thumbnail_file(filename):
    if filename != os.path.basename(filename) or not filename.lower().endswith(RASTER_THUMB_EXTENSIONS):
        return uploaded_file(filename)
    source = os.path.join(os.path.abspath(app.config['UPLOAD_FOLDER']), filename)
    if not os.path.isfile(source):
        return uploaded_file(filename)  # same 404 as a missing upload
    target = thumbnail_path(filename)
    try:
        if not os.path.exists(target) or os.path.getmtime(target) < os.path.getmtime(source):
            os.makedirs(THUMB_FOLDER, exist_ok=True)
            pix = pymupdf.Pixmap(source)
            if pix.n - pix.alpha > 3:  # CMYK JPEGs from prepress -> RGB for PNG
                pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
            while pix.width > THUMB_MAX_WIDTH * 2:
                pix.shrink(1)  # halves both sides, keeps the aspect ratio
            pix.save(target)
    except Exception:
        logger.warning("Could not create thumbnail for %s", filename, exc_info=True)
        return uploaded_file(filename)
    response = send_from_directory(os.path.abspath(THUMB_FOLDER), os.path.basename(target))
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response

# Home page
@app.route('/')
def index():
    local_ip = get_local_ip()
    return render_template(
        'index.html', local_ip=local_ip,
        username=session.get('username'), role=session.get('role'),
        role_label=ROLE_LABELS.get(session.get('role'), '')
    )

# Simple in-memory brute-force protection for /login: {key: [failures, locked_until]}
login_failures = {}
login_failures_lock = threading.Lock()

def login_lock_remaining(key):
    with login_failures_lock:
        entry = login_failures.get(key)
        return max(0, int(entry[1] - time.time())) if entry else 0

def register_login_failure(key):
    with login_failures_lock:
        entry = login_failures.setdefault(key, [0, 0])
        entry[0] += 1
        if entry[0] >= LOGIN_MAX_FAILURES:
            entry[0] = 0
            entry[1] = time.time() + LOGIN_LOCKOUT_SECONDS

@app.route('/login', methods=['GET', 'POST'])
def login_page():
    if request.method == 'GET':
        if 'user_id' in session:
            return redirect(url_for('index'))
        return render_template('login.html', error=None)

    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')

    lock_key = f"{request.remote_addr}|{username.lower()}"
    remaining = login_lock_remaining(lock_key)
    if remaining:
        return render_template('login.html', error=f'Твърде много неуспешни опити. Опитайте отново след {remaining} сек.'), 429

    with get_db(sqlite3.Row) as conn:
        user = conn.execute("SELECT id, username, password_hash, role FROM users WHERE username = ?", (username,)).fetchone()

    if not user or not check_password_hash(user['password_hash'], password):
        register_login_failure(lock_key)
        return render_template('login.html', error='Грешно потребителско име или парола.'), 401

    with login_failures_lock:
        login_failures.pop(lock_key, None)
    session.clear()
    session['user_id'] = user['id']
    session['username'] = user['username']
    session['role'] = user['role']
    session['pw'] = password_fingerprint(user['password_hash'])
    session['login_at'] = time.time()
    return redirect(url_for('index'))

@app.route('/logout', methods=['GET', 'POST'])
def logout():
    # GET stays for the plain "Изход" links; logging out has no harmful side effect.
    session.clear()
    return redirect(url_for('login_page'))

@app.route('/account')
def account_page():
    return render_template(
        'account.html', username=session.get('username'),
        role=session.get('role'), role_label=ROLE_LABELS.get(session.get('role'), '')
    )

@app.route('/admin')
@require_role(ROLE_ADMIN)
def admin_page():
    return render_template('admin.html', username=session.get('username'), role_labels=ROLE_LABELS)

# API: Shut down the server process (admin only) - used by the "Exit" button so
# the whole app (and the terminal window running it) can be closed from the browser.
EXIT_MARKER_FILE = os.path.join(DB_FOLDER, '.exit_requested')

def delayed_exit():
    time.sleep(0.5)  # give the response below time to reach the browser first
    # Tells run.bat/run_mac.command this was a deliberate shutdown, so the
    # terminal window can close itself instead of pausing like it would for a
    # crash or a manual Ctrl+C.
    try:
        open(EXIT_MARKER_FILE, 'w').close()
    except OSError:
        pass
    os._exit(0)

@app.route('/api/shutdown', methods=['POST'])
@require_role(ROLE_ADMIN)
def api_shutdown():
    threading.Thread(target=delayed_exit, daemon=True).start()
    logger.info(f"Server shutdown requested by '{session.get('username')}' via the Exit button.")
    return jsonify({'success': True})

# API: Change my own password (any logged-in role)
@app.route('/api/me/password', methods=['PUT'])
def change_my_password():
    data = request.get_json(silent=True) or {}
    current_password = data.get('current_password', '')
    new_password = data.get('new_password', '')

    if not isinstance(new_password, str) or len(new_password) < MIN_PASSWORD_LENGTH:
        return jsonify({'error': f'Новата парола трябва да е поне {MIN_PASSWORD_LENGTH} символа.'}), 400

    with get_db(sqlite3.Row) as conn:
        row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (session['user_id'],)).fetchone()
        if not row or not check_password_hash(row['password_hash'], str(current_password)):
            return jsonify({'error': 'Текущата парола е грешна.'}), 400
        new_hash = generate_password_hash(new_password)
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, session['user_id']))

    # Keep this session valid; every other session of this user is logged out
    session['pw'] = password_fingerprint(new_hash)
    return jsonify({'success': True})

# API: List users (admin only)
@app.route('/api/users', methods=['GET'])
@require_role(ROLE_ADMIN)
def list_users():
    with get_db(sqlite3.Row) as conn:
        users = [dict(r) for r in conn.execute("SELECT id, username, role, created_at FROM users ORDER BY id ASC")]
    return jsonify(users)

# API: Create user (admin only)
@app.route('/api/users', methods=['POST'])
@require_role(ROLE_ADMIN)
def create_user():
    data = request.get_json(silent=True) or {}
    username = str(data.get('username', '')).strip()
    password = data.get('password', '')
    role = str(data.get('role', '')).strip()

    if not username or not password:
        return jsonify({'error': 'Моля попълнете потребителско име и парола.'}), 400
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        return jsonify({'error': f'Паролата трябва да е поне {MIN_PASSWORD_LENGTH} символа.'}), 400
    if role not in ROLES:
        return jsonify({'error': 'Невалидна роля.'}), 400

    with get_db() as conn:
        if conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone():
            return jsonify({'error': f'Потребител "{username}" вече съществува.'}), 400
        conn.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (username, generate_password_hash(password), role)
        )
    return jsonify({'success': True})

# API: Update a user's role and/or reset their password (admin only)
@app.route('/api/users/<int:user_id>', methods=['PUT'])
@require_role(ROLE_ADMIN)
def update_user(user_id):
    data = request.get_json(silent=True) or {}
    new_role = str(data.get('role', '')).strip()
    new_password = str(data.get('password', '')).strip()

    if new_role and new_role not in ROLES:
        return jsonify({'error': 'Невалидна роля.'}), 400
    if new_password and len(new_password) < MIN_PASSWORD_LENGTH:
        return jsonify({'error': f'Паролата трябва да е поне {MIN_PASSWORD_LENGTH} символа.'}), 400

    with get_db() as conn:
        target = conn.execute("SELECT id, role FROM users WHERE id = ?", (user_id,)).fetchone()
        if not target:
            return jsonify({'error': 'Потребителят не е намерен.'}), 404

        if new_role:
            if target[1] == ROLE_ADMIN and new_role != ROLE_ADMIN:
                if conn.execute("SELECT COUNT(*) FROM users WHERE role = ?", (ROLE_ADMIN,)).fetchone()[0] <= 1:
                    return jsonify({'error': 'Не може да премахнете ролята на единствения администратор.'}), 400
            conn.execute("UPDATE users SET role = ? WHERE id = ?", (new_role, user_id))

        if new_password:
            new_hash = generate_password_hash(new_password)
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user_id))
            if user_id == session.get('user_id'):
                session['pw'] = password_fingerprint(new_hash)

    return jsonify({'success': True})

# API: Delete a user (admin only)
@app.route('/api/users/<int:user_id>', methods=['DELETE'])
@require_role(ROLE_ADMIN)
def delete_user(user_id):
    if user_id == session.get('user_id'):
        return jsonify({'error': 'Не можете да изтриете собствения си акаунт.'}), 400

    with get_db() as conn:
        row = conn.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            return jsonify({'error': 'Потребителят не е намерен.'}), 404

        if row[0] == ROLE_ADMIN:
            if conn.execute("SELECT COUNT(*) FROM users WHERE role = ?", (ROLE_ADMIN,)).fetchone()[0] <= 1:
                return jsonify({'error': 'Не може да изтриете единствения администратор.'}), 400

        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    return jsonify({'success': True})

# API: Get all tools (with filters and search)
@app.route('/api/tools', methods=['GET'])
def get_tools():
    search_query = request.args.get('q', '').strip()
    category = request.args.get('category', 'all').strip()
    status = request.args.get('status', 'all').strip()
    dim_query = request.args.get('dim', '').strip()

    sql = "SELECT * FROM tools WHERE 1=1"
    params = []

    if category != 'all':
        sql += " AND category = ?"
        params.append(category)

    if status != 'all':
        sql += " AND status = ?"
        params.append(status)

    if dim_query:
        sql += " AND (py_lower(single_item_dimensions) LIKE py_lower(?) OR py_lower(dimensions) LIKE py_lower(?))"
        params.extend([f"%{dim_query}%", f"%{dim_query}%"])

    if search_query:
        sql += " AND (py_lower(code) LIKE py_lower(?) OR py_lower(name) LIKE py_lower(?) OR py_lower(client) LIKE py_lower(?) OR py_lower(location) LIKE py_lower(?) OR py_lower(notes) LIKE py_lower(?) OR py_lower(dimensions) LIKE py_lower(?) OR py_lower(single_item_dimensions) LIKE py_lower(?) OR py_lower(file_path) LIKE py_lower(?))"
        like_param = f"%{search_query}%"
        params.extend([like_param] * 8)

    sql += " ORDER BY id DESC"

    with get_db(sqlite3.Row) as conn:
        conn.create_function("py_lower", 1, lambda x: str(x).lower() if x is not None else "")
        rows = conn.execute(sql, params).fetchall()
        drawings_map = get_drawings_by_tool_ids(conn, [r['id'] for r in rows])

    tools_list = []
    for r in rows:
        tools_list.append({
            'id': r['id'],
            'code': r['code'],
            'category': r['category'],
            'name': r['name'],
            'client': r['client'],
            'dimensions': r['dimensions'],
            'location': r['location'],
            'status': r['status'],
            'notes': r['notes'],
            'created_at': r['created_at'],
            'die_shape': r['die_shape'],
            'ups': r['ups'],
            'material': r['material'],
            'die_type': r['die_type'],
            'single_item_dimensions': r['single_item_dimensions'],
            'file_path': r['file_path'],
            'drawings': drawings_map.get(r['id'], [])
        })

    return jsonify(tools_list)

def parse_tool_form(form):
    """Extracts and normalizes the tool fields shared by add_tool and update_tool."""
    ups_str = form.get('ups', '1').strip()
    return {
        'category': form.get('category', '').strip(),
        'name': form.get('name', '').strip(),
        'client': form.get('client', '').strip(),
        'dimensions': form.get('dimensions', '').strip(),
        'location': form.get('location', '').strip(),
        'status': form.get('status', 'active').strip() or 'active',
        'notes': form.get('notes', '').strip(),
        'file_path': form.get('file_path', '').strip(),
        'die_shape': form.get('die_shape', '').strip(),
        'ups': int(ups_str) if ups_str.isdigit() else 1,
        'material': form.get('material', '').strip(),
        'die_type': form.get('die_type', '').strip(),
        'single_item_dimensions': form.get('single_item_dimensions', '').strip(),
    }

def validate_tool_fields(fields):
    """Returns an error message for invalid fields, or None. Category and status are
    fixed lists (they are used as CSS classes and values in the UI)."""
    if not fields['category'] or not fields['name']:
        return 'Моля попълнете категория и име на инструмента'
    if fields['category'] not in CATEGORY_PREFIXES:
        return 'Невалидна категория.'
    if fields['status'] not in STATUSES:
        return 'Невалиден статус.'
    return None

TOOL_COLUMNS = ('code', 'category', 'name', 'client', 'dimensions', 'location', 'status', 'notes',
                'die_shape', 'ups', 'material', 'die_type', 'single_item_dimensions', 'file_path')

# API: Add new tool
@app.route('/api/tools', methods=['POST'])
@require_role(ROLE_ADMIN, ROLE_READ_WRITE)
def add_tool():
    fields = parse_tool_form(request.form)
    error = validate_tool_fields(fields)
    if error:
        return jsonify({'error': error}), 400
    custom_code = request.form.get('code', '').strip()

    for attempt in range(5):
        try:
            with get_db() as conn:
                # BEGIN IMMEDIATE takes the write lock before reading the codes, so the
                # uniqueness check / next number and the INSERT happen atomically.
                conn.isolation_level = None
                conn.execute("BEGIN IMMEDIATE")
                if custom_code:
                    if conn.execute("SELECT id FROM tools WHERE code = ?", (custom_code,)).fetchone():
                        conn.execute("ROLLBACK")
                        return jsonify({'error': f'Инструмент с код "{custom_code}" вече съществува!'}), 400
                    code = custom_code
                else:
                    code = next_code(conn, fields['category'])

                values = dict(fields, code=code)
                cursor = conn.execute(
                    f"INSERT INTO tools ({', '.join(TOOL_COLUMNS)}) VALUES ({', '.join('?' for _ in TOOL_COLUMNS)})",
                    [values[col] for col in TOOL_COLUMNS]
                )
                tool_id = cursor.lastrowid

                # Multiple drawings can be attached at once (input field name: "images")
                save_new_drawing_files(conn, tool_id, request.files.getlist('images'), start_position=0)
                conn.execute("COMMIT")
            return jsonify({'success': True, 'tool': {'id': tool_id, 'code': code}})
        except sqlite3.IntegrityError:
            if custom_code:
                return jsonify({'error': f'Инструмент с код "{custom_code}" вече съществува!'}), 400
            continue  # a generated code was taken meanwhile - try the next number
        except sqlite3.OperationalError:
            logger.warning("Database busy while adding a tool (attempt %d)", attempt + 1, exc_info=True)
            time.sleep(0.2)

    return jsonify({'error': 'Базата данни е заета. Опитайте отново след малко.'}), 503

# API: Update tool
@app.route('/api/tools/<int:tool_id>', methods=['PUT'])
@require_role(ROLE_ADMIN, ROLE_READ_WRITE)
def update_tool(tool_id):
    fields = parse_tool_form(request.form)
    code = request.form.get('code', '').strip()

    if not code:
        return jsonify({'error': 'Моля попълнете код, категория и име на инструмента'}), 400
    error = validate_tool_fields(fields)
    if error:
        return jsonify({'error': error}), 400

    try:
        with get_db() as conn:
            c = conn.cursor()
            if not c.execute("SELECT id FROM tools WHERE id = ?", (tool_id,)).fetchone():
                return jsonify({'error': 'Инструментът не е намерен!'}), 404

            # Check if code changed and is unique
            if c.execute("SELECT id FROM tools WHERE code = ? AND id != ?", (code, tool_id)).fetchone():
                return jsonify({'error': f'Инструмент с код "{code}" вече съществува!'}), 400

            values = dict(fields, code=code)
            c.execute(
                f"UPDATE tools SET {', '.join(col + ' = ?' for col in TOOL_COLUMNS)} WHERE id = ?",
                [values[col] for col in TOOL_COLUMNS] + [tool_id]
            )

            # Drawings the operator removed from the gallery in this edit
            try:
                delete_ids = [int(i) for i in json.loads(request.form.get('delete_drawing_ids', '[]'))]
            except (ValueError, TypeError):
                delete_ids = []
            for drawing_id in delete_ids:
                c.execute("SELECT image_filename, preview_filename FROM tool_drawings WHERE id = ? AND tool_id = ?", (drawing_id, tool_id))
                drawing_row = c.fetchone()
                if drawing_row:
                    remove_upload(drawing_row[0])
                    remove_upload(drawing_row[1])
                    c.execute("DELETE FROM tool_drawings WHERE id = ?", (drawing_id,))

            # New drawings appended in this edit
            c.execute("SELECT COALESCE(MAX(position), -1) FROM tool_drawings WHERE tool_id = ?", (tool_id,))
            next_position = c.fetchone()[0] + 1
            save_new_drawing_files(conn, tool_id, request.files.getlist('images'), start_position=next_position)
    except sqlite3.IntegrityError:
        return jsonify({'error': f'Инструмент с код "{code}" вече съществува!'}), 400

    return jsonify({'success': True})

def unique_destination(folder, filename):
    """Path in folder for filename that does not overwrite an existing file
    (adds _2, _3 ... before the extension)."""
    candidate = os.path.join(folder, filename)
    stem, ext = os.path.splitext(filename)
    counter = 2
    while os.path.exists(candidate):
        candidate = os.path.join(folder, f"{stem}_{counter}{ext}")
        counter += 1
    return candidate

# API: Copy a tool's design file and drawings into a folder on the SERVER's disk
# (e.g. a shared network folder mounted on the server machine)
@app.route('/api/tools/<int:tool_id>/copy-file', methods=['POST'])
@require_role(ROLE_ADMIN, ROLE_READ_WRITE)
def copy_tool_file(tool_id):
    import shutil

    data = request.get_json(silent=True) or {}
    dest_folder = str(data.get('destination_folder', '')).strip()

    if not dest_folder:
        return jsonify({'error': 'Моля въведете път до целевата папка'}), 400

    if not os.path.isabs(dest_folder):
        return jsonify({'error': 'Въведете пълен път до папката (напр. D:\\Щанци или \\\\server\\share\\Щанци).'}), 400

    if is_inside_app(dest_folder):
        return jsonify({'error': 'Целевата папка не може да е в папката на приложението - файловете там може да станат достъпни без парола.'}), 400

    with get_db(sqlite3.Row) as conn:
        tool = conn.execute("SELECT code, name, file_path FROM tools WHERE id = ?", (tool_id,)).fetchone()
        drawings = get_drawings_by_tool_ids(conn, [tool_id]).get(tool_id, [])

    if not tool:
        return jsonify({'error': 'Инструментът не е намерен!'}), 404

    # Ensure destination folder exists
    try:
        os.makedirs(dest_folder, exist_ok=True)
    except Exception as e:
        return jsonify({'error': f'Невалиден или недостъпен път на диска: {str(e)}'}), 400

    copied_files = []
    errors = []

    # 1. Copy original file_path if it exists. Only design-file types from outside the
    # application folder: file_path is free text, so without these checks it could
    # point at the secret key, the database or any other file on the server.
    original_path = tool['file_path']
    if original_path:
        original_ext = original_path.rsplit('.', 1)[-1].lower() if '.' in os.path.basename(original_path) else ''
        if original_ext not in COPYABLE_EXTENSIONS or is_inside_app(original_path):
            errors.append("Оригиналният файл не е копиран: разрешени са само файлове с чертежи/дизайн извън папката на приложението.")
        elif os.path.exists(original_path) and os.path.isfile(original_path):
            try:
                base_name = os.path.basename(original_path)
                target = unique_destination(dest_folder, base_name)
                shutil.copy2(original_path, target)
                copied_files.append(f"оригинален файл ({os.path.basename(target)})")
            except Exception as e:
                errors.append(f"Грешка при копиране на оригиналния файл: {str(e)}")
        else:
            errors.append("Оригиналният файл не беше намерен на посочения път.")

    # 2. Copy every attached drawing
    safe_name = sanitize_filename_component(tool['name'])
    for index, drawing in enumerate(drawings):
        img_name = drawing['image_filename']
        src_img_path = os.path.join(app.config['UPLOAD_FOLDER'], img_name)
        if os.path.exists(src_img_path):
            try:
                # Rename to include tool code for clarity (e.g. SH-0001_die_box.svg)
                ext = img_name.rsplit('.', 1)[1].lower() if '.' in img_name else 'bin'
                suffix = f"_{index + 1}" if len(drawings) > 1 else ""
                target = unique_destination(dest_folder, f"{tool['code']}_{safe_name}{suffix}.{ext}")
                shutil.copy2(src_img_path, target)
                copied_files.append(f"чертеж ({os.path.basename(target)})")
            except Exception as e:
                errors.append(f"Грешка при копиране на чертежа: {str(e)}")
        else:
            errors.append("Чертежът не беше намерен в папката на сървъра.")

    if not copied_files:
        err_msg = "Не бяха копирани файлове. " + " ".join(errors)
        return jsonify({'error': err_msg}), 400

    success_msg = f"Успешно копирахте: {', '.join(copied_files)} в папка \"{dest_folder}\" на сървъра."
    if errors:
        success_msg += " Забележки: " + " ".join(errors)

    return jsonify({'success': True, 'message': success_msg})

# API: Delete tool
@app.route('/api/tools/<int:tool_id>', methods=['DELETE'])
@require_role(ROLE_ADMIN, ROLE_READ_WRITE)
def delete_tool(tool_id):
    with get_db() as conn:
        delete_drawings_for_tool(conn, tool_id)
        conn.execute("DELETE FROM tools WHERE id = ?", (tool_id,))

    return jsonify({'success': True})

# API: Download every drawing attached to a tool as a single zip archive
@app.route('/api/tools/<int:tool_id>/drawings/download')
def download_tool_drawings(tool_id):
    with get_db(sqlite3.Row) as conn:
        tool = conn.execute("SELECT code, name FROM tools WHERE id = ?", (tool_id,)).fetchone()
        drawings = get_drawings_by_tool_ids(conn, [tool_id]).get(tool_id, [])

    if not tool:
        return jsonify({'error': 'Инструментът не е намерен!'}), 404
    if not drawings:
        return jsonify({'error': 'Няма качени чертежи за този инструмент.'}), 404

    safe_name = sanitize_filename_component(tool['name'])
    mem_zip = io.BytesIO()
    with zipfile.ZipFile(mem_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
        for index, drawing in enumerate(drawings):
            img_name = drawing['image_filename']
            src_path = os.path.join(app.config['UPLOAD_FOLDER'], img_name)
            if not os.path.exists(src_path):
                continue
            ext = img_name.rsplit('.', 1)[1].lower() if '.' in img_name else 'bin'
            suffix = f"_{index + 1}" if len(drawings) > 1 else ""
            zf.write(src_path, arcname=f"{tool['code']}_{safe_name}{suffix}.{ext}")
    mem_zip.seek(0)

    return send_file(
        mem_zip,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f"{tool['code']}_chertezhi.zip"
    )

# Create/migrate the schema at import, so the app also works when started through
# a WSGI server or `flask run` (not only `python app.py`).
BOOTSTRAP_PASSWORD = init_db()

if __name__ == '__main__':
    local_ip = get_local_ip()
    print("==================================================")
    print(f" Сървърът стартира успешно!")
    print(f" Локален достъп: http://localhost:{PORT}")
    print(f" Достъп от мрежата: http://{local_ip}:{PORT}")
    if BOOTSTRAP_PASSWORD:
        print(" Създаден е първоначален администраторски акаунт:")
        print("   Потребител: admin")
        print(f"   Парола: {BOOTSTRAP_PASSWORD}")
        print("   (препоръчително е да я смените от /account след вход)")
    print("==================================================")
    app.run(host='0.0.0.0', port=PORT, debug=False, threaded=True)
