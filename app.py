from flask import (Flask, render_template, request, redirect, url_for,
                   session, jsonify, flash, abort, g)
from werkzeug.security import generate_password_hash, check_password_hash
from sqlite3 import connect, Error, Row
from datetime import datetime
import os, json, markdown2
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'reliquia-dev-secret-2025-change-me')
DB_FILE = os.environ.get('DB_FILE', 'database.db')

# ─────────────────────────────────────────
#  DATABASE
# ─────────────────────────────────────────

def get_db():
    if 'db' not in g:
        g.db = connect(DB_FILE)
        g.db.row_factory = Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db: db.close()

def db_q(query, params=()):
    db = get_db()
    try:
        cur = db.execute(query, params)
        db.commit()
        return [dict(r) for r in cur.fetchall()]
    except Error as e:
        db.rollback()
        app.logger.error(f"DB Error: {e}\nQuery: {query}")
        return []

def db_one(query, params=()):
    r = db_q(query, params)
    return r[0] if r else None

def db_insert(query, params=()):
    db = get_db()
    try:
        cur = db.execute(query, params)
        db.commit()
        return cur.lastrowid
    except Error as e:
        db.rollback()
        app.logger.error(f"DB Insert Error: {e}")
        return None

# ─────────────────────────────────────────
#  INIT DB
# ─────────────────────────────────────────

def init_db():
    db = connect(DB_FILE)
    db.row_factory = Row
    db.execute("PRAGMA foreign_keys = ON")

    db.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        minecraft_nick TEXT DEFAULT '',
        role TEXT DEFAULT 'Forasteiro',
        banned INTEGER DEFAULT 0,
        ban_reason TEXT DEFAULT '',
        banned_by INTEGER DEFAULT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    db.execute("""CREATE TABLE IF NOT EXISTS role_permissions (
        role_name TEXT PRIMARY KEY,
        permissions TEXT NOT NULL DEFAULT '{}'
    )""")

    db.execute("""CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        author_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        post_type TEXT DEFAULT 'forum',
        version_tag TEXT DEFAULT '',
        status TEXT DEFAULT 'open',
        pinned INTEGER DEFAULT 0,
        featured INTEGER DEFAULT 0,
        image_urls TEXT DEFAULT '[]',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (author_id) REFERENCES users(id)
    )""")

    db.execute("""CREATE TABLE IF NOT EXISTS timeline (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER NOT NULL,
        event_date TEXT NOT NULL,
        is_version_milestone INTEGER DEFAULT 0,
        version_id INTEGER DEFAULT NULL,
        FOREIGN KEY (post_id) REFERENCES posts(id)
    )""")

    db.execute("""CREATE TABLE IF NOT EXISTS post_reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        review_type TEXT NOT NULL,
        body TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (post_id) REFERENCES posts(id),
        FOREIGN KEY (user_id) REFERENCES users(id)
    )""")

    db.execute("""CREATE TABLE IF NOT EXISTS reactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER DEFAULT NULL,
        user_id INTEGER NOT NULL,
        reaction TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(post_id, user_id, reaction)
    )""")

    db.execute("""CREATE TABLE IF NOT EXISTS server_versions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        description TEXT DEFAULT '',
        start_date TEXT DEFAULT '',
        end_date TEXT DEFAULT '',
        is_current INTEGER DEFAULT 0,
        post_id INTEGER DEFAULT NULL,
        map_zip TEXT DEFAULT '',
        map_mcworld TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    db.execute("""CREATE TABLE IF NOT EXISTS version_players (
        version_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        PRIMARY KEY (version_id, user_id),
        FOREIGN KEY (version_id) REFERENCES server_versions(id),
        FOREIGN KEY (user_id) REFERENCES users(id)
    )""")

    db.execute("""CREATE TABLE IF NOT EXISTS achievements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT DEFAULT '',
        icon TEXT DEFAULT 'nether_star',
        color TEXT DEFAULT '#FFAA00',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    db.execute("""CREATE TABLE IF NOT EXISTS user_achievements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        achievement_id INTEGER NOT NULL,
        awarded_by INTEGER,
        awarded_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, achievement_id)
    )""")

    db.execute("""CREATE TABLE IF NOT EXISTS site_settings (
        key TEXT PRIMARY KEY,
        value TEXT DEFAULT ''
    )""")

    db.execute("""CREATE TABLE IF NOT EXISTS image_comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        image_name TEXT NOT NULL,
        nick TEXT NOT NULL,
        comentario TEXT NOT NULL,
        data_envio TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    db.commit()

    # Default role permissions
    default_permissions = {
        'Forasteiro': dict(comment=True, react=True, create_post=False,
                           upload_photos=False, post_timeline=False, archive_posts=False,
                           ban_users=False, manage_roles=False, soft_delete_comments=False,
                           pin_posts=False, view_admin=False, manage_versions=False,
                           manage_settings=False, manage_featured=False, full_admin=False),
        'Jogador':    dict(comment=True, react=True, create_post=True,
                           upload_photos=True, post_timeline=True, archive_posts=False,
                           ban_users=False, manage_roles=False, soft_delete_comments=False,
                           pin_posts=False, view_admin=False, manage_versions=False,
                           manage_settings=False, manage_featured=False, full_admin=False),
        'Moderador':  dict(comment=True, react=True, create_post=True,
                           upload_photos=True, post_timeline=True, archive_posts=True,
                           ban_users=True, manage_roles=True, soft_delete_comments=True,
                           pin_posts=True, view_admin=True, manage_versions=False,
                           manage_settings=False, manage_featured=False, full_admin=False),
        'Master':     dict(comment=True, react=True, create_post=True,
                           upload_photos=True, post_timeline=True, archive_posts=True,
                           ban_users=True, manage_roles=True, soft_delete_comments=True,
                           pin_posts=True, view_admin=True, manage_versions=True,
                           manage_settings=True, manage_featured=True, full_admin=True),
    }
    for role, perms in default_permissions.items():
        if not db.execute("SELECT role_name FROM role_permissions WHERE role_name=?", (role,)).fetchone():
            db.execute("INSERT INTO role_permissions (role_name,permissions) VALUES (?,?)",
                       (role, json.dumps(perms)))

    defaults = {
        'server_name': 'Reliquia', 'server_ip': '', 'server_ip_visible': '1',
        'home_title': 'Reliquia Server', 'home_subtitle': 'Servidor de Minecraft multiplayer',
        'home_description': 'Entre agora e faça parte dessa jornada entre versões e eras!',
        'discord_url': 'https://discord.gg/5tNdasxqJ8', 'maintenance_mode': '0',
        'r2_endpoint': '', 'r2_access_key': '', 'r2_secret_key': '',
        'r2_bucket': '', 'r2_public_url': '',
    }
    for k, v in defaults.items():
        if not db.execute("SELECT key FROM site_settings WHERE key=?", (k,)).fetchone():
            db.execute("INSERT INTO site_settings (key,value) VALUES (?,?)", (k, v))

    for v in ['1', '2', '3']:
        vname = v + '.0'
        if not db.execute("SELECT id FROM server_versions WHERE name=?", (vname,)).fetchone():
            db.execute("INSERT INTO server_versions (name,is_current) VALUES (?,?)",
                       (vname, 1 if v == '3' else 0))

    # Default achievements
    ach_defaults = [
        ('O Explorador',      'Jogou em pelo menos 2 versões do servidor',     'ender_pearl',        '#58c8c0'),
        ('Cupim de Montanha', 'Construiu nas alturas máximas do mundo',        'diamond_pickaxe',    '#8b949e'),
        ('Veterano',          'Membro do servidor desde o início',             'golden_sword',        '#d29922'),
        ('Arquiteto',         'Construiu estruturas que marcaram o servidor',  'bricks',              '#3fb950'),
        ('Sobrevivente',      'Sobreviveu à primeira noite no servidor',       'shield',              '#a371f7'),
        ('Comerciante',       'Realizou trocas com outros jogadores',          'emerald',             '#3fb950'),
        ('Lendário',          'Jogador que deixou sua marca na Reliquia',      'nether_star',         '#FFAA00'),
        ('Corajoso',          'Nunca recuou de um desafio no servidor',        'iron_sword',          '#f85149'),
    ]
    for name, desc, icon, color in ach_defaults:
        if not db.execute("SELECT id FROM achievements WHERE name=?", (name,)).fetchone():
            db.execute("INSERT INTO achievements (name,description,icon,color) VALUES (?,?,?,?)",
                       (name, desc, icon, color))

    db.commit()
    db.close()
    print("✅ Database initialized.")


# ─────────────────────────────────────────
#  PERMISSIONS
# ─────────────────────────────────────────

PERMISSION_LABELS = {
    'comment':              'Comentar / Reviews',
    'react':                'Reagir a posts',
    'create_post':          'Criar posts',
    'upload_photos':        'Publicar fotos',
    'post_timeline':        'Publicar na timeline da história',
    'archive_posts':        'Arquivar posts',
    'ban_users':            'Banir usuários',
    'manage_roles':         'Elevar / rebaixar cargos',
    'soft_delete_comments': 'Remover reviews',
    'pin_posts':            'Fixar posts',
    'view_admin':           'Acessar painel de admin',
    'manage_versions':      'Gerenciar versões',
    'manage_settings':      'Gerenciar configurações',
    'manage_featured':      'Gerenciar posts em destaque',
    'full_admin':           'Permissão total (Master)',
}

ROLES_ORDER = ['Forasteiro', 'Jogador', 'Moderador', 'Master']

REACTION_EMOJIS = {
    'like':    ('👍', 'Gostei'),
    'love':    ('❤️', 'Amei'),
    'fire':    ('🔥', 'Fogo'),
    'diamond': ('💎', 'Diamante'),
    'sword':   ('⚔️', 'Espada'),
    'creeper': ('😈', 'Creeper'),
}

MC_ITEMS = [
    'diamond','emerald','nether_star','golden_apple','ender_pearl',
    'iron_sword','golden_sword','diamond_sword','bow',
    'diamond_pickaxe','iron_pickaxe','wooden_pickaxe',
    'shield','book','compass','map','arrow',
    'bricks','oak_log','grass_block',
]


def get_role_permissions(role_name):
    r = db_one("SELECT permissions FROM role_permissions WHERE role_name=?", (role_name,))
    return json.loads(r['permissions']) if r else {}


def has_permission(permission):
    if 'user_id' not in session:
        return False
    user = db_one("SELECT role,banned FROM users WHERE id=?", (session['user_id'],))
    if not user or user['banned']:
        return False
    perms = get_role_permissions(user['role'])
    return bool(perms.get('full_admin') or perms.get(permission))


def login_required(f):
    @wraps(f)
    def deco(*a, **kw):
        if 'user_id' not in session:
            flash('Você precisa estar logado.', 'warning')
            return redirect(url_for('login', next=request.url))
        return f(*a, **kw)
    return deco


# ─────────────────────────────────────────
#  CONTEXT PROCESSOR
# ─────────────────────────────────────────

@app.context_processor
def inject_globals():
    current_user = None
    user_perms = {}
    if 'user_id' in session:
        current_user = db_one(
            "SELECT id,username,minecraft_nick,role,banned FROM users WHERE id=?",
            (session['user_id'],))
        if current_user:
            user_perms = get_role_permissions(current_user['role'])
    site = {r['key']: r['value'] for r in db_q("SELECT key,value FROM site_settings")}
    versions = db_q("SELECT * FROM server_versions ORDER BY id DESC")
    return dict(current_user=current_user, user_perms=user_perms,
                has_perm=has_permission, site=site,
                server_versions=versions, now=datetime.now(),
                mc_items=MC_ITEMS)


# ─────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────

def render_md(text):
    if not text: return ''
    return markdown2.markdown(text, extras=[
        'fenced-code-blocks','tables','strike','task_list','header-ids','cuddled-lists'])

def fmt_date(s):
    if not s: return ''
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
        try: return datetime.strptime(s, fmt).strftime('%d/%m/%Y às %H:%M')
        except ValueError: pass
    return s

def parse_images(raw):
    try: return json.loads(raw or '[]') if raw else []
    except Exception: return []

def get_post_reactions(post_id):
    rows = db_q("SELECT reaction,COUNT(*) as c FROM reactions WHERE post_id=? GROUP BY reaction", (post_id,))
    return {r['reaction']: r['c'] for r in rows}

def get_user_reactions(post_id, user_id):
    if not user_id: return []
    return [r['reaction'] for r in db_q(
        "SELECT reaction FROM reactions WHERE post_id=? AND user_id=?", (post_id, user_id))]

app.jinja_env.filters['md']      = render_md
app.jinja_env.filters['fmtdate'] = fmt_date


# ─────────────────────────────────────────
#  AUTH
# ─────────────────────────────────────────

@app.route('/login', methods=['GET','POST'])
def login():
    if 'user_id' in session: return redirect(url_for('index'))
    if request.method == 'POST':
        ident = request.form.get('username','').strip()
        pwd   = request.form.get('password','')
        user  = db_one("SELECT * FROM users WHERE username=? OR email=?", (ident,ident))
        if user and check_password_hash(user['password_hash'], pwd):
            if user['banned']:
                flash(f'Conta banida. Motivo: {user["ban_reason"]}', 'danger')
                return redirect(url_for('login'))
            session.permanent = True
            session.update(user_id=user['id'], username=user['username'], role=user['role'])
            flash(f'Bem-vindo de volta, {user["username"]}! ⚔️', 'success')
            return redirect(request.args.get('next') or url_for('index'))
        flash('Usuário ou senha incorretos.', 'danger')
    return render_template('auth/login.html')


@app.route('/register', methods=['GET','POST'])
def register():
    if 'user_id' in session: return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username','').strip()
        email    = request.form.get('email','').strip()
        pwd      = request.form.get('password','')
        confirm  = request.form.get('confirm_password','')
        mc_nick  = request.form.get('minecraft_nick','').strip()
        if len(username) < 3:
            flash('Username precisa ter pelo menos 3 caracteres.', 'danger')
        elif len(pwd) < 6:
            flash('Senha precisa ter pelo menos 6 caracteres.', 'danger')
        elif pwd != confirm:
            flash('As senhas não coincidem.', 'danger')
        elif db_one("SELECT id FROM users WHERE username=?", (username,)):
            flash('Username já em uso.', 'danger')
        elif db_one("SELECT id FROM users WHERE email=?", (email,)):
            flash('E-mail já em uso.', 'danger')
        else:
            uid = db_insert(
                "INSERT INTO users (username,email,password_hash,minecraft_nick) VALUES (?,?,?,?)",
                (username, email, generate_password_hash(pwd), mc_nick))
            session.update(user_id=uid, username=username, role='Forasteiro')
            flash(f'Conta criada! Bem-vindo, {username}! 🎮', 'success')
            return redirect(url_for('index'))
    return render_template('auth/register.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('Você saiu. Até logo! 👋', 'info')
    return redirect(url_for('index'))


@app.route('/profile/<username>')
def profile(username):
    u = db_one("SELECT id,username,minecraft_nick,role,created_at FROM users WHERE username=?", (username,))
    if not u: abort(404)
    posts = db_q("""
        SELECT p.*,u2.username as author FROM posts p
        JOIN users u2 ON p.author_id=u2.id
        WHERE p.author_id=? AND p.post_type='forum' AND p.status!='archived'
        ORDER BY p.created_at DESC LIMIT 10
    """, (u['id'],))
    timeline_posts = db_q("""
        SELECT p.*,t.event_date FROM posts p
        JOIN timeline t ON t.post_id=p.id
        WHERE p.author_id=? AND p.status!='archived'
        ORDER BY t.event_date DESC LIMIT 5
    """, (u['id'],))
    achievements = db_q("""
        SELECT a.* FROM user_achievements ua
        JOIN achievements a ON ua.achievement_id=a.id
        WHERE ua.user_id=? ORDER BY ua.awarded_at ASC
    """, (u['id'],))
    return render_template('auth/profile.html', profile_user=u,
                           posts=posts, timeline_posts=timeline_posts,
                           achievements=achievements)


# ─────────────────────────────────────────
#  INDEX
# ─────────────────────────────────────────

@app.route('/')
def index():
    featured = db_q("""
        SELECT p.*,u.username as author,u.minecraft_nick,
               COUNT(DISTINCT r.id) as comment_count
        FROM posts p JOIN users u ON p.author_id=u.id
        LEFT JOIN post_reviews r ON r.post_id=p.id
        WHERE p.featured=1 AND p.status='open' AND p.post_type='forum'
        GROUP BY p.id ORDER BY p.created_at DESC LIMIT 3
    """)
    recent = db_q("""
        SELECT p.*,u.username as author,u.minecraft_nick,
               COUNT(DISTINCT r.id) as review_count
        FROM posts p JOIN users u ON p.author_id=u.id
        LEFT JOIN post_reviews r ON r.post_id=p.id
        WHERE p.status='open' AND p.post_type='forum'
        GROUP BY p.id ORDER BY p.created_at DESC LIMIT 5
    """)
    stats = {
        'users':    (db_one("SELECT COUNT(*) as c FROM users") or {'c':0})['c'],
        'posts':    (db_one("SELECT COUNT(*) as c FROM posts WHERE status!='archived' AND post_type='forum'") or {'c':0})['c'],
        'reviews':  (db_one("SELECT COUNT(*) as c FROM post_reviews") or {'c':0})['c'],
    }
    current_ver = db_one("SELECT * FROM server_versions WHERE is_current=1 ORDER BY id DESC")
    return render_template('index.html', featured=featured, recent=recent,
                           stats=stats, current_ver=current_ver)


# ─────────────────────────────────────────
#  FORUM
# ─────────────────────────────────────────

@app.route('/forum')
def forum():
    page     = request.args.get('page', 1, type=int)
    per_page = 20
    offset   = (page-1)*per_page
    status   = request.args.get('status','open')
    ver_f    = request.args.get('version','')
    search   = request.args.get('q','')

    conds  = ["p.post_type='forum'"]
    params = []
    if status in ('open','closed','archived'):
        conds.append("p.status=?"); params.append(status)
    if ver_f:
        conds.append("p.version_tag=?"); params.append(ver_f)
    if search:
        conds.append("(p.title LIKE ? OR p.content LIKE ?)")
        params += [f'%{search}%', f'%{search}%']
    where = " AND ".join(conds)

    posts = db_q(f"""
        SELECT p.*,u.username as author,u.minecraft_nick,
               COUNT(DISTINCT r.id) as review_count
        FROM posts p JOIN users u ON p.author_id=u.id
        LEFT JOIN post_reviews r ON r.post_id=p.id
        WHERE {where} GROUP BY p.id
        ORDER BY p.pinned DESC, p.created_at DESC
        LIMIT ? OFFSET ?
    """, params+[per_page, offset])

    total    = (db_one(f"SELECT COUNT(*) as c FROM posts p WHERE {where}", params) or {'c':0})['c']
    versions = db_q("SELECT name FROM server_versions ORDER BY id DESC")
    return render_template('forum/index.html', posts=posts, page=page,
                           per_page=per_page, total=total, status=status,
                           ver_f=ver_f, search=search, versions=versions,
                           reaction_emojis=REACTION_EMOJIS)


@app.route('/forum/<int:pid>')
def forum_post(pid):
    post = db_one("""
        SELECT p.*,u.username as author,u.minecraft_nick,u.role as author_role
        FROM posts p JOIN users u ON p.author_id=u.id
        WHERE p.id=? AND p.post_type='forum'
    """, (pid,))
    if not post: abort(404)
    post['parsed_images'] = parse_images(post.get('image_urls'))
    reviews = db_q("""
        SELECT pr.*,u.username,u.minecraft_nick,u.role
        FROM post_reviews pr JOIN users u ON pr.user_id=u.id
        WHERE pr.post_id=? ORDER BY pr.created_at ASC
    """, (pid,))
    reactions  = get_post_reactions(pid)
    user_reacs = get_user_reactions(pid, session.get('user_id'))
    return render_template('forum/post.html', post=post, reviews=reviews,
                           reactions=reactions, user_reacs=user_reacs,
                           reaction_emojis=REACTION_EMOJIS)


@app.route('/forum/new', methods=['GET','POST'])
@login_required
def forum_new():
    if not has_permission('create_post'):
        flash('Sem permissão para criar posts.', 'danger'); abort(403)
    versions = db_q("SELECT name FROM server_versions ORDER BY id DESC")
    if request.method == 'POST':
        title   = request.form.get('title','').strip()
        content = request.form.get('content','').strip()
        ver_tag = request.form.get('version_tag','')
        imgs    = request.form.get('image_urls','[]')
        if not title or not content:
            flash('Título e conteúdo são obrigatórios.', 'danger')
        else:
            pid = db_insert("""
                INSERT INTO posts (author_id,title,content,post_type,version_tag,image_urls)
                VALUES (?,?,?,'forum',?,?)
            """, (session['user_id'], title, content, ver_tag, imgs))
            flash('Post criado! ✅', 'success')
            return redirect(url_for('forum_post', pid=pid))
    return render_template('forum/create.html', versions=versions, post=None)


@app.route('/forum/<int:pid>/edit', methods=['GET','POST'])
@login_required
def forum_edit(pid):
    post = db_one("SELECT * FROM posts WHERE id=? AND post_type='forum'", (pid,))
    if not post: abort(404)
    if post['author_id'] != session['user_id'] and not has_permission('full_admin'):
        abort(403)
    versions = db_q("SELECT name FROM server_versions ORDER BY id DESC")
    if request.method == 'POST':
        title   = request.form.get('title','').strip()
        content = request.form.get('content','').strip()
        ver_tag = request.form.get('version_tag','')
        imgs    = request.form.get('image_urls','[]')
        if not title or not content:
            flash('Título e conteúdo são obrigatórios.', 'danger')
        else:
            db_q("""UPDATE posts SET title=?,content=?,version_tag=?,image_urls=?,
                    updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                 (title, content, ver_tag, imgs, pid))
            flash('Post atualizado! ✅', 'success')
            return redirect(url_for('forum_post', pid=pid))
    return render_template('forum/create.html', versions=versions, post=post)


@app.route('/forum/<int:pid>/react', methods=['POST'])
@login_required
def forum_react(pid):
    if not has_permission('react'):
        return jsonify({'error':'Sem permissão'}), 403
    reaction = (request.json or {}).get('reaction')
    if reaction not in REACTION_EMOJIS:
        return jsonify({'error':'Reação inválida'}), 400
    existing = db_one("SELECT id FROM reactions WHERE post_id=? AND user_id=? AND reaction=?",
                      (pid, session['user_id'], reaction))
    if existing:
        db_q("DELETE FROM reactions WHERE id=?", (existing['id'],))
        added = False
    else:
        db_insert("INSERT OR IGNORE INTO reactions (post_id,user_id,reaction) VALUES (?,?,?)",
                  (pid, session['user_id'], reaction))
        added = True
    count = (db_one("SELECT COUNT(*) as c FROM reactions WHERE post_id=? AND reaction=?",
                    (pid, reaction)) or {'c':0})['c']
    return jsonify({'added':added, 'count':count, 'reaction':reaction})


@app.route('/forum/<int:pid>/review', methods=['POST'])
@login_required
def forum_review(pid):
    if not has_permission('comment'):
        return jsonify({'error':'Sem permissão'}), 403
    post = db_one("SELECT id FROM posts WHERE id=? AND post_type='forum'", (pid,))
    if not post: return jsonify({'error':'Post não encontrado'}), 404
    rtype = (request.json or {}).get('type')
    body  = (request.json or {}).get('body','').strip()
    if rtype not in ('approve','changes','comment'):
        return jsonify({'error':'Tipo inválido'}), 400
    rid = db_insert(
        "INSERT INTO post_reviews (post_id,user_id,review_type,body) VALUES (?,?,?,?)",
        (pid, session['user_id'], rtype, body))
    user = db_one("SELECT username,minecraft_nick,role FROM users WHERE id=?",
                  (session['user_id'],))
    return jsonify({
        'id': rid, 'type': rtype, 'body': body,
        'author': user['username'], 'nick': user['minecraft_nick'] or '',
        'role': user['role'],
        'created_at': datetime.now().strftime('%d/%m/%Y às %H:%M')
    })


@app.route('/forum/<int:pid>/reviews')
def forum_reviews(pid):
    reviews = db_q("""
        SELECT pr.*,u.username,u.minecraft_nick,u.role
        FROM post_reviews pr JOIN users u ON pr.user_id=u.id
        WHERE pr.post_id=? ORDER BY pr.created_at ASC
    """, (pid,))
    return jsonify(reviews)


@app.route('/forum/<int:pid>/status', methods=['POST'])
@login_required
def forum_status(pid):
    post = db_one("SELECT * FROM posts WHERE id=? AND post_type='forum'", (pid,))
    if not post: abort(404)
    new_status = request.form.get('status')
    if new_status == 'archived' and not has_permission('archive_posts'):
        flash('Sem permissão para arquivar.', 'danger')
        return redirect(url_for('forum_post', pid=pid))
    if post['author_id'] != session['user_id'] and not has_permission('archive_posts'):
        abort(403)
    if new_status in ('open','closed','archived'):
        db_q("UPDATE posts SET status=? WHERE id=?", (new_status, pid))
    return redirect(url_for('forum_post', pid=pid))


# ─────────────────────────────────────────
#  HISTORY / TIMELINE  (completamente separado do fórum)
# ─────────────────────────────────────────

@app.route('/history')
def history():
    timeline = db_q("""
        SELECT p.*,u.username as author,u.minecraft_nick,u.role as author_role,
               t.id as timeline_id, t.event_date,t.is_version_milestone,t.version_id,
               sv.name as version_name,
               COUNT(DISTINCT r.id) as reaction_count
        FROM posts p JOIN users u ON p.author_id=u.id
        LEFT JOIN timeline t ON t.post_id=p.id
        LEFT JOIN server_versions sv ON sv.id=t.version_id
        LEFT JOIN reactions r ON r.post_id=p.id
        WHERE p.post_type IN ('history','version') AND p.status!='archived'
        GROUP BY p.id
        ORDER BY COALESCE(t.event_date, p.created_at) DESC
    """)
    for entry in timeline:
        entry['parsed_images'] = parse_images(entry.get('image_urls'))

    # version players
    vp_raw = db_q("""
        SELECT vp.version_id,u.username,u.minecraft_nick
        FROM version_players vp JOIN users u ON vp.user_id=u.id
    """)
    version_players_map = {}
    for row in vp_raw:
        version_players_map.setdefault(row['version_id'], []).append(row)

    # legacy image folders
    base = os.path.join(app.root_path, 'static', 'img')
    version_images = {}
    if os.path.exists(base):
        for vf in sorted(os.listdir(base)):
            vp = os.path.join(base, vf)
            if os.path.isdir(vp) and vf.isdigit():
                imgs = [f"/static/img/{vf}/{fn}" for fn in sorted(os.listdir(vp))
                        if fn.lower().endswith(('.png','.jpg','.jpeg','.webp','.gif'))]
                version_images[vf] = imgs

    versions = db_q("SELECT * FROM server_versions ORDER BY id DESC")
    return render_template('history/index.html', timeline=timeline,
                           version_images=version_images, versions=versions,
                           version_players_map=version_players_map)


@app.route('/history/<int:hid>')
def history_view(hid):
    post = db_one("""
        SELECT p.*,u.username as author,u.minecraft_nick,u.role as author_role,
               t.event_date,t.is_version_milestone,t.version_id,sv.name as version_name
        FROM posts p JOIN users u ON p.author_id=u.id
        LEFT JOIN timeline t ON t.post_id=p.id
        LEFT JOIN server_versions sv ON sv.id=t.version_id
        WHERE p.id=? AND p.post_type IN ('history','version')
    """, (hid,))
    if not post: abort(404)
    post['parsed_images'] = parse_images(post.get('image_urls'))
    reactions  = get_post_reactions(hid)
    user_reacs = get_user_reactions(hid, session.get('user_id'))
    return render_template('history/post.html', post=post,
                           reactions=reactions, user_reacs=user_reacs,
                           reaction_emojis=REACTION_EMOJIS)


@app.route('/history/new', methods=['GET','POST'])
@login_required
def history_new():
    if not has_permission('post_timeline'):
        flash('Sem permissão para publicar na timeline.', 'danger'); abort(403)
    versions = db_q("SELECT * FROM server_versions ORDER BY id DESC")
    if request.method == 'POST':
        title      = request.form.get('title','').strip()
        content    = request.form.get('content','').strip()
        event_date = request.form.get('event_date','').strip()
        version_id = request.form.get('version_id') or None
        imgs       = request.form.get('image_urls','[]')
        if not all([title, content, event_date]):
            flash('Título, conteúdo e data são obrigatórios.', 'danger')
        else:
            ver_tag = ''
            if version_id:
                v = db_one("SELECT name FROM server_versions WHERE id=?", (version_id,))
                if v: ver_tag = v['name']
            pid = db_insert("""
                INSERT INTO posts (author_id,title,content,post_type,version_tag,image_urls)
                VALUES (?,?,?,'history',?,?)
            """, (session['user_id'], title, content, ver_tag, imgs))
            db_insert("INSERT INTO timeline (post_id,event_date,version_id) VALUES (?,?,?)",
                      (pid, event_date, version_id))
            flash('Evento adicionado à timeline! 📅', 'success')
            return redirect(url_for('history_view', hid=pid))
    return render_template('history/create.html', versions=versions, post=None)


@app.route('/history/<int:hid>/edit', methods=['GET','POST'])
@login_required
def history_edit(hid):
    post = db_one("""
        SELECT p.*,t.event_date,t.version_id
        FROM posts p LEFT JOIN timeline t ON t.post_id=p.id
        WHERE p.id=? AND p.post_type IN ('history','version')
    """, (hid,))
    if not post: abort(404)
    if post['author_id'] != session['user_id'] and not has_permission('full_admin'):
        abort(403)
    versions = db_q("SELECT * FROM server_versions ORDER BY id DESC")
    if request.method == 'POST':
        title      = request.form.get('title','').strip()
        content    = request.form.get('content','').strip()
        event_date = request.form.get('event_date','').strip()
        version_id = request.form.get('version_id') or None
        imgs       = request.form.get('image_urls','[]')
        if not all([title, content, event_date]):
            flash('Título, conteúdo e data são obrigatórios.', 'danger')
        else:
            ver_tag = ''
            if version_id:
                v = db_one("SELECT name FROM server_versions WHERE id=?", (version_id,))
                if v: ver_tag = v['name']
            db_q("""UPDATE posts SET title=?,content=?,version_tag=?,image_urls=?,
                    updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                 (title, content, ver_tag, imgs, hid))
            db_q("UPDATE timeline SET event_date=?,version_id=? WHERE post_id=?",
                 (event_date, version_id, hid))
            flash('Evento atualizado! ✅', 'success')
            return redirect(url_for('history_view', hid=hid))
    return render_template('history/create.html', versions=versions, post=post)


@app.route('/history/<int:hid>/react', methods=['POST'])
@login_required
def history_react(hid):
    if not has_permission('react'):
        return jsonify({'error':'Sem permissão'}), 403
    reaction = (request.json or {}).get('reaction')
    if reaction not in REACTION_EMOJIS:
        return jsonify({'error':'Reação inválida'}), 400
    existing = db_one("SELECT id FROM reactions WHERE post_id=? AND user_id=? AND reaction=?",
                      (hid, session['user_id'], reaction))
    if existing:
        db_q("DELETE FROM reactions WHERE id=?", (existing['id'],))
        added = False
    else:
        db_insert("INSERT OR IGNORE INTO reactions (post_id,user_id,reaction) VALUES (?,?,?)",
                  (hid, session['user_id'], reaction))
        added = True
    count = (db_one("SELECT COUNT(*) as c FROM reactions WHERE post_id=? AND reaction=?",
                    (hid, reaction)) or {'c':0})['c']
    return jsonify({'added':added,'count':count,'reaction':reaction})


# ─────────────────────────────────────────
#  PLAYERS
# ─────────────────────────────────────────

@app.route('/players')
def players():
    role_filter = request.args.get('role','')
    search      = request.args.get('q','')
    conds  = ["banned=0"]
    params = []
    if role_filter and role_filter in ROLES_ORDER:
        conds.append("role=?"); params.append(role_filter)
    if search:
        conds.append("(username LIKE ? OR minecraft_nick LIKE ?)")
        params += [f'%{search}%', f'%{search}%']
    where   = " AND ".join(conds)
    players_list = db_q(f"""
        SELECT id,username,minecraft_nick,role,created_at FROM users
        WHERE {where}
        ORDER BY CASE role
            WHEN 'Master' THEN 1 WHEN 'Moderador' THEN 2
            WHEN 'Jogador' THEN 3 ELSE 4 END, created_at ASC
    """, params)
    post_counts = {r['author_id']: r['c'] for r in db_q(
        "SELECT author_id,COUNT(*) as c FROM posts WHERE status!='archived' AND post_type='forum' GROUP BY author_id")}
    for p in players_list:
        p['post_count'] = post_counts.get(p['id'], 0)
    return render_template('players.html', players=players_list,
                           roles=ROLES_ORDER, role_filter=role_filter, search=search)


# ─────────────────────────────────────────
#  REVIEW / MODERATION
# ─────────────────────────────────────────

@app.route('/review/<int:rid>/delete', methods=['POST'])
@login_required
def delete_review(rid):
    rev = db_one("SELECT * FROM post_reviews WHERE id=?", (rid,))
    if not rev: abort(404)
    if rev['user_id'] != session['user_id'] and not has_permission('soft_delete_comments'):
        abort(403)
    db_q("DELETE FROM post_reviews WHERE id=?", (rid,))
    flash('Review removida.', 'success')
    return redirect(request.referrer or url_for('forum'))


# ─────────────────────────────────────────
#  IMAGE UPLOAD
# ─────────────────────────────────────────

@app.route('/upload', methods=['POST'])
@login_required
def upload_image():
    if not has_permission('upload_photos'):
        return jsonify({'error':'Sem permissão'}), 403
    f = request.files.get('file')
    if not f: return jsonify({'error':'Sem arquivo'}), 400
    ext = (f.filename.rsplit('.',1)[-1].lower()) if '.' in f.filename else ''
    if ext not in ('png','jpg','jpeg','gif','webp'):
        return jsonify({'error':'Tipo não permitido'}), 400
    settings = {r['key']:r['value'] for r in db_q("SELECT key,value FROM site_settings")}
    r2_ep = settings.get('r2_endpoint') or os.environ.get('R2_ENDPOINT','')
    if r2_ep:
        try:
            import boto3
            s3 = boto3.client('s3', endpoint_url=r2_ep,
                              aws_access_key_id=settings.get('r2_access_key',''),
                              aws_secret_access_key=settings.get('r2_secret_key',''),
                              region_name='auto')
            fname = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{session['user_id']}.{ext}"
            s3.upload_fileobj(f, settings.get('r2_bucket',''), fname,
                              ExtraArgs={'ContentType': f.content_type})
            return jsonify({'url': settings.get('r2_public_url','').rstrip('/')+'/'+fname})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    else:
        upload_dir = os.path.join(app.root_path, 'static', 'uploads')
        os.makedirs(upload_dir, exist_ok=True)
        fname = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{session['user_id']}.{ext}"
        f.save(os.path.join(upload_dir, fname))
        return jsonify({'url': f'/static/uploads/{fname}'})


# ─────────────────────────────────────────
#  ADMIN
# ─────────────────────────────────────────

@app.route('/admin')
@login_required
def admin_dashboard():
    if not has_permission('view_admin'): abort(403)
    stats = {
        'users':   (db_one("SELECT COUNT(*) as c FROM users") or {'c':0})['c'],
        'posts':   (db_one("SELECT COUNT(*) as c FROM posts WHERE post_type='forum'") or {'c':0})['c'],
        'reviews': (db_one("SELECT COUNT(*) as c FROM post_reviews") or {'c':0})['c'],
        'banned':  (db_one("SELECT COUNT(*) as c FROM users WHERE banned=1") or {'c':0})['c'],
    }
    recent_users = db_q("SELECT * FROM users ORDER BY created_at DESC LIMIT 8")
    recent_posts = db_q("""
        SELECT p.*,u.username as author FROM posts p
        JOIN users u ON p.author_id=u.id
        WHERE p.post_type='forum'
        ORDER BY p.created_at DESC LIMIT 8
    """)
    return render_template('admin/dashboard.html', stats=stats,
                           recent_users=recent_users, recent_posts=recent_posts)


@app.route('/admin/users')
@login_required
def admin_users():
    if not has_permission('view_admin'): abort(403)
    q = request.args.get('q','')
    users = db_q("SELECT * FROM users WHERE username LIKE ? OR email LIKE ? ORDER BY created_at DESC",
                 (f'%{q}%',f'%{q}%')) if q else db_q("SELECT * FROM users ORDER BY created_at DESC")
    return render_template('admin/users.html', users=users, search=q, roles=ROLES_ORDER)


@app.route('/admin/users/<int:uid>/ban', methods=['POST'])
@login_required
def admin_ban(uid):
    if not has_permission('ban_users'): abort(403)
    target = db_one("SELECT * FROM users WHERE id=?", (uid,))
    if not target: abort(404)
    if target['role'] == 'Master':
        flash('Não é possível banir um Master.','danger')
        return redirect(url_for('admin_users'))
    if uid == session['user_id']:
        flash('Você não pode se banir.','danger')
        return redirect(url_for('admin_users'))
    if not has_permission('full_admin') and target['role'] not in ('Forasteiro','Jogador'):
        flash('Sem permissão para banir este cargo.','danger')
        return redirect(url_for('admin_users'))
    db_q("UPDATE users SET banned=1,ban_reason=?,banned_by=? WHERE id=?",
         (request.form.get('reason',''), session['user_id'], uid))
    flash(f'{target["username"]} banido.','success')
    return redirect(url_for('admin_users'))


@app.route('/admin/users/<int:uid>/unban', methods=['POST'])
@login_required
def admin_unban(uid):
    if not has_permission('ban_users'): abort(403)
    db_q("UPDATE users SET banned=0,ban_reason='' WHERE id=?", (uid,))
    flash('Usuário desbanido.','success')
    return redirect(url_for('admin_users'))


@app.route('/admin/users/<int:uid>/role', methods=['POST'])
@login_required
def admin_change_role(uid):
    if not has_permission('manage_roles'): abort(403)
    target = db_one("SELECT * FROM users WHERE id=?", (uid,))
    if not target: abort(404)
    new_role = request.form.get('role')
    if new_role not in ROLES_ORDER:
        flash('Cargo inválido.','danger'); return redirect(url_for('admin_users'))
    if new_role == 'Master' and not has_permission('full_admin'):
        flash('Apenas Masters podem promover Masters.','danger')
        return redirect(url_for('admin_users'))
    db_q("UPDATE users SET role=? WHERE id=?", (new_role, uid))
    flash(f'Cargo de {target["username"]} → {new_role}.','success')
    return redirect(url_for('admin_users'))


@app.route('/admin/versions')
@login_required
def admin_versions():
    if not has_permission('manage_versions'): abort(403)
    versions = db_q("SELECT * FROM server_versions ORDER BY id DESC")
    all_users = db_q("SELECT id,username,minecraft_nick FROM users WHERE banned=0 ORDER BY username")
    vp_rows = db_q("SELECT version_id,user_id FROM version_players")
    version_player_map = {}
    for row in vp_rows:
        version_player_map.setdefault(row['version_id'], []).append(row['user_id'])
    return render_template('admin/versions.html', versions=versions,
                           all_users=all_users, version_player_map=version_player_map)


@app.route('/admin/versions/new', methods=['POST'])
@login_required
def admin_version_new():
    if not has_permission('manage_versions'): abort(403)
    name        = request.form.get('name','').strip()
    description = request.form.get('description','').strip()
    start_date  = request.form.get('start_date','').strip()
    end_date    = request.form.get('end_date','').strip()
    is_current  = 1 if request.form.get('is_current') else 0
    if not name:
        flash('Nome é obrigatório.','danger'); return redirect(url_for('admin_versions'))
    if is_current:
        db_q("UPDATE server_versions SET is_current=0")
    vid = db_insert("""
        INSERT INTO server_versions (name,description,start_date,end_date,is_current)
        VALUES (?,?,?,?,?)
    """, (name, description, start_date, end_date, is_current))
    if vid:
        post_content = f"# 🎮 Versão {name} — Servidor Reliquia\n\n{description}\n\n---\n*Post oficial de lançamento da versão {name}.*"
        pid = db_insert("""
            INSERT INTO posts (author_id,title,content,post_type,version_tag,pinned,featured)
            VALUES (?,?,?,'version',?,1,1)
        """, (session['user_id'], f"🎮 Versão {name} — Servidor Reliquia", post_content, name))
        if pid:
            db_insert("INSERT INTO timeline (post_id,event_date,is_version_milestone,version_id) VALUES (?,?,1,?)",
                      (pid, start_date or datetime.now().strftime('%Y-%m-%d'), vid))
            db_q("UPDATE server_versions SET post_id=? WHERE id=?", (pid, vid))
    flash(f'Versão {name} criada! 🎉','success')
    return redirect(url_for('admin_versions'))


@app.route('/admin/versions/<int:vid>/edit', methods=['POST'])
@login_required
def admin_version_edit(vid):
    if not has_permission('manage_versions'): abort(403)
    is_current = 1 if request.form.get('is_current') else 0
    if is_current: db_q("UPDATE server_versions SET is_current=0")
    db_q("""UPDATE server_versions SET name=?,description=?,start_date=?,end_date=?,
            is_current=?,map_zip=?,map_mcworld=? WHERE id=?""",
         (request.form.get('name',''), request.form.get('description',''),
          request.form.get('start_date',''), request.form.get('end_date',''),
          is_current, request.form.get('map_zip',''), request.form.get('map_mcworld',''), vid))
    flash('Versão atualizada.','success')
    return redirect(url_for('admin_versions'))


@app.route('/admin/versions/<int:vid>/players', methods=['POST'])
@login_required
def admin_version_players(vid):
    if not has_permission('manage_versions'): abort(403)
    db_q("DELETE FROM version_players WHERE version_id=?", (vid,))
    for uid in request.form.getlist('player_ids'):
        db_insert("INSERT OR IGNORE INTO version_players (version_id,user_id) VALUES (?,?)",
                  (vid, int(uid)))
    flash('Jogadores da versão atualizados!','success')
    return redirect(url_for('admin_versions'))


@app.route('/admin/versions/<int:vid>/delete', methods=['POST'])
@login_required
def admin_version_delete(vid):
    if not has_permission('manage_versions'): abort(403)
    db_q("DELETE FROM version_players WHERE version_id=?", (vid,))
    db_q("DELETE FROM server_versions WHERE id=?", (vid,))
    flash('Versão removida.','success')
    return redirect(url_for('admin_versions'))


@app.route('/admin/settings', methods=['GET','POST'])
@login_required
def admin_settings():
    if not has_permission('manage_settings'): abort(403)
    if request.method == 'POST':
        keys = ['server_name','server_ip','server_ip_visible','home_title',
                'home_subtitle','home_description','discord_url','maintenance_mode',
                'r2_endpoint','r2_access_key','r2_secret_key','r2_bucket','r2_public_url']
        for k in keys:
            v = '1' if request.form.get(k) else '0' if k in ('server_ip_visible','maintenance_mode') else request.form.get(k,'')
            db_q("INSERT OR REPLACE INTO site_settings (key,value) VALUES (?,?)", (k,v))
        flash('Configurações salvas! ✅','success')
        return redirect(url_for('admin_settings'))
    settings = {r['key']:r['value'] for r in db_q("SELECT key,value FROM site_settings")}
    return render_template('admin/settings.html', settings=settings)


@app.route('/admin/posts')
@login_required
def admin_posts():
    if not has_permission('view_admin'): abort(403)
    posts = db_q("""
        SELECT p.*,u.username as author FROM posts p
        JOIN users u ON p.author_id=u.id
        WHERE p.post_type='forum'
        ORDER BY p.created_at DESC
    """)
    return render_template('admin/posts.html', posts=posts)


@app.route('/admin/posts/<int:pid>/toggle-featured', methods=['POST'])
@login_required
def toggle_featured(pid):
    if not has_permission('manage_featured'): abort(403)
    post = db_one("SELECT featured FROM posts WHERE id=?", (pid,))
    if post: db_q("UPDATE posts SET featured=? WHERE id=?", (0 if post['featured'] else 1, pid))
    return redirect(request.referrer or url_for('admin_posts'))


@app.route('/admin/posts/<int:pid>/toggle-pinned', methods=['POST'])
@login_required
def toggle_pinned(pid):
    if not has_permission('pin_posts'): abort(403)
    post = db_one("SELECT pinned FROM posts WHERE id=?", (pid,))
    if post: db_q("UPDATE posts SET pinned=? WHERE id=?", (0 if post['pinned'] else 1, pid))
    return redirect(request.referrer or url_for('admin_posts'))


@app.route('/admin/permissions', methods=['GET','POST'])
@login_required
def admin_permissions():
    if not has_permission('full_admin'): abort(403)
    if request.method == 'POST':
        role = request.form.get('role_name')
        if role in ROLES_ORDER:
            perms = {k: (k in request.form) for k in PERMISSION_LABELS}
            db_q("INSERT OR REPLACE INTO role_permissions (role_name,permissions) VALUES (?,?)",
                 (role, json.dumps(perms)))
            flash(f'Permissões de {role} atualizadas! ✅','success')
        return redirect(url_for('admin_permissions'))
    roles_perms = {r: get_role_permissions(r) for r in ROLES_ORDER}
    return render_template('admin/permissions.html', roles_perms=roles_perms,
                           permission_labels=PERMISSION_LABELS, roles=ROLES_ORDER)


@app.route('/admin/achievements', methods=['GET','POST'])
@login_required
def admin_achievements():
    if not has_permission('full_admin'): abort(403)
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'create':
            db_insert("INSERT INTO achievements (name,description,icon,color) VALUES (?,?,?,?)",
                      (request.form['name'], request.form.get('description',''),
                       request.form.get('icon','nether_star'), request.form.get('color','#FFAA00')))
            flash('Conquista criada!','success')
        elif action == 'award':
            uid = request.form.get('user_id')
            aid = request.form.get('achievement_id')
            if uid and aid:
                db_insert("INSERT OR IGNORE INTO user_achievements (user_id,achievement_id,awarded_by) VALUES (?,?,?)",
                          (uid, aid, session['user_id']))
                flash('Conquista concedida!','success')
        elif action == 'revoke':
            db_q("DELETE FROM user_achievements WHERE user_id=? AND achievement_id=?",
                 (request.form['user_id'], request.form['achievement_id']))
            flash('Conquista removida.','success')
        elif action == 'delete_ach':
            db_q("DELETE FROM user_achievements WHERE achievement_id=?", (request.form['achievement_id'],))
            db_q("DELETE FROM achievements WHERE id=?", (request.form['achievement_id'],))
            flash('Conquista deletada.','success')
        return redirect(url_for('admin_achievements'))
    achievements = db_q("SELECT * FROM achievements ORDER BY name")
    users        = db_q("SELECT id,username FROM users WHERE banned=0 ORDER BY username")
    awarded      = db_q("""
        SELECT ua.*,u.username,a.name as ach_name,a.icon,a.color
        FROM user_achievements ua
        JOIN users u ON ua.user_id=u.id
        JOIN achievements a ON ua.achievement_id=a.id
        ORDER BY ua.awarded_at DESC
    """)
    return render_template('admin/achievements.html',
                           achievements=achievements, users=users, awarded=awarded,
                           mc_items=MC_ITEMS)


# ─────────────────────────────────────────
#  LEGACY
# ─────────────────────────────────────────

@app.route('/comentar-imagem', methods=['POST'])
def comentar_imagem():
    db_insert("INSERT INTO image_comments (image_name,nick,comentario) VALUES (?,?,?)",
              (request.form.get('image_name'), request.form.get('nick'), request.form.get('comentario')))
    return '', 204

@app.route('/comentarios/<imagem>')
def comentarios(imagem):
    return jsonify(db_q("SELECT nick,comentario,data_envio FROM image_comments WHERE image_name=? ORDER BY data_envio DESC", (imagem,)))


# ─────────────────────────────────────────
#  ERRORS
# ─────────────────────────────────────────

@app.errorhandler(403)
def err_403(e): return render_template('errors/403.html'), 403
@app.errorhandler(404)
def err_404(e): return render_template('errors/404.html'), 404
@app.errorhandler(500)
def err_500(e): return render_template('errors/500.html'), 500


if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=4589)
