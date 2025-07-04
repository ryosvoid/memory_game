from flask import Flask, render_template, request, redirect, url_for, session, g, jsonify
import os
import random
import sqlite3
from datetime import timedelta

app = Flask(__name__)
app.secret_key = "memorysecret"
app.permanent_session_lifetime = timedelta(hours=2)

DATABASE = "memory.db"

def init_db():
    """Initialize the database if it doesn't exist or is corrupted."""
    need_init = False
    if not os.path.exists(DATABASE):
        need_init = True
    else:
        try:
            conn = sqlite3.connect(DATABASE)
            conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
            conn.close()
        except sqlite3.DatabaseError:
            os.remove(DATABASE)
            need_init = True

    if need_init:
        # Use the correct schema file name here
        with open("schema_memory.sql", "r", encoding="utf-8") as f:
            schema = f.read()
        conn = sqlite3.connect(DATABASE)
        conn.executescript(schema)
        conn.commit()
        conn.close()
        print("Database initialized!")

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def get_user_id(username):
    cur = get_db().execute("SELECT id FROM utilisateurs WHERE username = ?", (username,))
    row = cur.fetchone()
    return row['id'] if row else None

THEMES = ["Fruits", "Drinks", "Food", "Flowers", "Bakery"]

DIFFICULTY_GRIDS = {
    "2x2": (2, 2),
    "2x3": (2, 3),
    "4x4": (4, 4),
    "4x5": (4, 5),
    "6x6": (6, 6),
    "8x8": (8, 8)
}

DIFFICULTY_LABELS = {
    "2x2": "Très facile",
    "2x3": "Facile",
    "4x4": "Normal",
    "4x5": "Difficile",
    "6x6": "Expert",
    "8x8": "Légendaire"
}

DEFAULT_DIFFICULTY = "4x4"

# Initialize the DB at app startup (for older Flask versions)
init_db()

@app.route('/', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        action = request.form.get('action')
        db = get_db()
        if not username or not password:
            error = "Please fill all fields."
        elif action == "Login":
            cur = db.execute("SELECT * FROM utilisateurs WHERE username=? AND password_hash=?", (username, password))
            user = cur.fetchone()
            if user:
                session['username'] = username
                session['score'] = 100
                return redirect(url_for('theme_select'))
            else:
                error = "Invalid credentials."
        elif action == "Register":
            cur = db.execute("SELECT id FROM utilisateurs WHERE username=?", (username,))
            if cur.fetchone():
                error = "Username already exists."
            else:
                db.execute("INSERT INTO utilisateurs (username, password_hash) VALUES (?, ?)", (username, password))
                db.commit()
                session['username'] = username
                session['score'] = 100
                return redirect(url_for('theme_select'))
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/themes')
def theme_select():
    if 'username' not in session:
        return redirect(url_for('login'))
    return render_template(
        "index.html",
        themes=THEMES,
        DIFFICULTY_LABELS=DIFFICULTY_LABELS
    )

@app.route('/historique')
def historique():
    if 'username' not in session:
        return redirect(url_for('login'))
    user_id = get_user_id(session['username'])
    cur = get_db().execute("""
        SELECT pj.id, pj.date_partie, th.nom as theme, d.label as difficulte,
               pj.mode_multijoueur, pj.duree_seconds, u.username as gagnant
        FROM parties_jouees pj
        JOIN themes th ON pj.theme_id = th.id
        JOIN difficultes d ON pj.difficulte_id = d.id
        LEFT JOIN utilisateurs u ON pj.gagnant_id = u.id
        WHERE pj.id IN (
            SELECT partie_id FROM scores_parties WHERE utilisateur_id = ?
        )
        ORDER BY pj.date_partie DESC
        LIMIT 20
        """, (user_id,))
    parties = cur.fetchall()
    return render_template('historique.html', parties=parties)

@app.route('/game/<theme>')
def game(theme):
    if 'username' not in session:
        return redirect(url_for('login'))
    session.permanent = True

    difficulty = request.args.get('difficulty', DEFAULT_DIFFICULTY)
    is_multiplayer = request.args.get('multiplayer') == '1'

    rows, cols = DIFFICULTY_GRIDS.get(difficulty, DIFFICULTY_GRIDS[DEFAULT_DIFFICULTY])
    total_cards = rows * cols
    if total_cards % 2 != 0:
        total_cards -= 1
    pairs = total_cards // 2

    theme_folder = os.path.join("static", "images", theme.lower())
    if not os.path.exists(theme_folder):
        return "Invalid theme folder."
    all_images = [f for f in os.listdir(theme_folder) if f.endswith(".jpg")]

    # --- Flexible image selection logic ---
    if difficulty in ("6x6", "8x8"):
        if len(all_images) == 0:
            return "No images in the theme folder."
        # For 6x6 and 8x8, repeat images as needed
        selected_images = [all_images[i % len(all_images)] for i in range(pairs)]
    else:
        if len(all_images) < pairs:
            return "Not enough images in the theme folder for this level."
        selected_images = random.sample(all_images, pairs)
    card_images = selected_images * 2
    random.shuffle(card_images)

    if is_multiplayer:
        if (session.get('multi_theme') != theme or session.get('multi_diff') != difficulty):
            session['multi_theme'] = theme
            session['multi_diff'] = difficulty
            session['multi_scores'] = [0, 0]
            session['multi_player'] = 0
        scores = session['multi_scores']
        current_player = session['multi_player']
    else:
        session.pop('multi_theme', None)
        session.pop('multi_diff', None)
        session.pop('multi_scores', None)
        session.pop('multi_player', None)
        scores = None
        current_player = None

    score = int(session.get('score', 100))
    # Fixed if-elif block for time_limit
    if difficulty == "2x2":
        time_limit = 20
    elif difficulty == "2x3":
        time_limit = 28
    elif difficulty == "4x4":
        time_limit = 56
    elif difficulty == "4x5":
        time_limit = 70
    elif difficulty == "6x6":
        time_limit = 110
    elif difficulty == "8x8":
        time_limit = 200
    else:
        time_limit = 56

    db = get_db()
    user_id = get_user_id(session['username'])
    cur = db.execute("""
        SELECT pj.date_partie, th.nom as theme, d.label as difficulte,
               pj.mode_multijoueur, pj.duree_seconds, u.username as gagnant
        FROM parties_jouees pj
        JOIN themes th ON pj.theme_id = th.id
        JOIN difficultes d ON pj.difficulte_id = d.id
        LEFT JOIN utilisateurs u ON pj.gagnant_id = u.id
        WHERE pj.id IN (
            SELECT partie_id FROM scores_parties WHERE utilisateur_id = ?
        )
        ORDER BY pj.date_partie DESC
        LIMIT 10
        """, (user_id,))
    game_history = cur.fetchall()

    return render_template("game.html",
        theme=theme,
        rows=rows, columns=cols,
        pairs=pairs,
        card_images=card_images,
        score=score,
        time_limit=time_limit,
        difficulty=difficulty,
        difficulty_label=DIFFICULTY_LABELS[difficulty],
        is_multiplayer=is_multiplayer,
        scores=scores,
        current_player=current_player,
        difficulty_labels=DIFFICULTY_LABELS,
        game_history=game_history
    )

@app.route('/restart/<theme>')
def restart_level(theme):
    params = {}
    if "difficulty" in request.args: params["difficulty"] = request.args["difficulty"]
    if "multiplayer" in request.args: params["multiplayer"] = request.args["multiplayer"]
    return redirect(url_for('game', theme=theme, **params))

@app.route('/next/<theme>')
def next_level(theme):
    difficulty = request.args.get('difficulty', DEFAULT_DIFFICULTY)
    is_multiplayer = request.args.get('multiplayer') == '1'
    if not is_multiplayer:
        session['score'] = int(session.get('score', 100)) + 100
    return redirect(url_for('game', theme=theme, difficulty=difficulty, multiplayer=('1' if is_multiplayer else None)))

@app.route('/lose/<theme>')
def lose_level(theme):
    difficulty = request.args.get('difficulty', DEFAULT_DIFFICULTY)
    is_multiplayer = request.args.get('multiplayer') == '1'
    if not is_multiplayer:
        session['score'] = max(0, int(session.get('score', 100)) - 20)
    return redirect(url_for('game', theme=theme, difficulty=difficulty, multiplayer=('1' if is_multiplayer else None)))

@app.route('/reset')
def reset():
    session.clear()
    return redirect(url_for('theme_select'))

@app.route('/api/finish', methods=['POST'])
def api_finish():
    if 'username' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    data = request.get_json()
    required_fields = ['theme', 'difficulty', 'duration', 'moves', 'score']
    for field in required_fields:
        if field not in data:
            return jsonify({'success': False, 'error': f'Missing required field: {field}'}), 400

    user_id = get_user_id(session['username'])
    db = get_db()

    # Get theme_id
    theme_name = data.get('theme')
    cur = db.execute("SELECT id FROM themes WHERE LOWER(nom) = LOWER(?)", (theme_name.lower(),))
    row = cur.fetchone()
    if not row:
        return jsonify({'success': False, 'error': 'Invalid theme'}), 400
    theme_id = row['id']

    # Get difficulty_id
    difficulty_code = data.get('difficulty')
    cur = db.execute("SELECT id FROM difficultes WHERE code = ?", (difficulty_code,))
    row = cur.fetchone()
    if not row:
        return jsonify({'success': False, 'error': 'Invalid difficulty'}), 400
    difficulty_id = row['id']

    duration = data.get('duration')
    moves = data.get('moves')
    score = data.get('score')

    try:
        db.execute("""
            INSERT INTO parties_jouees (theme_id, difficulte_id, mode_multijoueur, duree_seconds, gagnant_id, date_partie)
            VALUES (?, ?, 0, ?, ?, datetime('now'))
        """, (theme_id, difficulty_id, duration, user_id))
        partie_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        db.execute("""
            INSERT INTO scores_parties (partie_id, utilisateur_id, score)
            VALUES (?, ?, ?)
        """, (partie_id, user_id, score))

        db.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)
