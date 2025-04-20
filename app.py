from flask import Flask, render_template, request, redirect, url_for
from sqlite3 import connect, Error
from datetime import datetime

import os
from collections import defaultdict


# +---------------------------------------------------------------+
# |                                                               |
# |     ____  _             _       ____     _    ____  ____      |
# |    / ___|| |_ __ _ _ __| |_    / __ \   / \  |  _ \|  _ \     |
# |    \___ \| __/ _` | '__| __|  / / _` | / _ \ | |_) | |_) |    |
# |     ___) | || (_| | |  | |_  | | (_| |/ ___ \|  __/|  __/     |
# |    |____/ \__\__,_|_|   \__|  \ \__,_/_/   \_\_|   |_|        |
# |                                \____/                         |
# |                                                               |
# +---------------------------------------------------------------+
# Initialize the Flask application
app = Flask(__name__)

# +---------------------------------------------------+
# |                                                   |
# |     ____        _        _                        |
# |    |  _ \  __ _| |_ __ _| |__   __ _ ___  ___     |
# |    | | | |/ _` | __/ _` | '_ \ / _` / __|/ _ \    |
# |    | |_| | (_| | || (_| | |_) | (_| \__ \  __/    |
# |    |____/ \__,_|\__\__,_|_.__/ \__,_|___/\___|    |
# |                                                   |
# +---------------------------------------------------+
class Database:
    def __init__(self, db_file):
        self.connection = None
        self.db_file = db_file

    def connect(self):
        """ create a database connection to a SQLite database """
        try:
            self.connection = connect(self.db_file)
            print(f"Connection to {self.db_file} successful")
        except Error as e:
            print(e)

    def close(self):
        print("Closing database connection")
        if self.connection:
            self.connection.close()

    def execute_query(self, query, params=()):
        try:
            self.connect()
            cursor = self.connection.cursor()
            cursor.execute(query, params)
            self.connection.commit()
            return cursor.fetchall()
        except Error as e:
            print(e)

        finally:
            self.close()


db = Database('database.db')
db.execute_query("""
CREATE TABLE IF NOT EXISTS depoimentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nick TEXT NOT NULL,
    mensagem TEXT NOT NULL,
    versao TEXT NOT NULL,
    data_envio TEXT DEFAULT CURRENT_TIMESTAMP
)
""")
db.execute_query("""
CREATE TABLE IF NOT EXISTS image_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    image_name TEXT NOT NULL,
    nick TEXT NOT NULL,
    comentario TEXT NOT NULL,
    data_envio TEXT DEFAULT CURRENT_TIMESTAMP
)
""")


# +---------------------------------------+
# |                                       |
# |     ____             _                |
# |    |  _ \ ___  _   _| |_ ___  ___     |
# |    | |_) / _ \| | | | __/ _ \/ __|    |
# |    |  _ < (_) | |_| | ||  __/\__ \    |
# |    |_| \_\___/ \__,_|\__\___||___/    |
# |                                       |
# +---------------------------------------+
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/history')
def history():
    base_path = os.path.join(app.root_path, 'static', 'img')
    version_images = {}

    for version_folder in sorted(os.listdir(base_path)):
        version_path = os.path.join(base_path, version_folder)
        if os.path.isdir(version_path) and version_folder.isdigit():
            images = []
            for filename in sorted(os.listdir(version_path)):
                if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif')):
                    images.append(f"/static/img/{version_folder}/{filename}")
            version_images[version_folder] = images

    return render_template('history.html', version_images=version_images)


@app.route('/experiences', methods=['GET'])
def experiences():
    query = "SELECT nick, mensagem, versao, data_envio FROM depoimentos ORDER BY data_envio DESC"
    results = db.execute_query(query)
    depoimentos = [{'nick': r[0], 'mensagem': r[1], 'versao': r[2], 'data': r[3]} for r in results]
    
    # Versões disponíveis manualmente (ou podem ser extraídas de arquivos se quiser depois)
    versoes = ['3.0', '2.0', '1.0']
    
    return render_template('experiences.html', depoimentos=depoimentos, versoes=versoes)

@app.route('/submit-depoimento', methods=['POST'])
def submit_depoimento():
    nick = request.form.get('nick')
    mensagem = request.form.get('depoimento')
    versao = request.form.get('versao')
    
    query = "INSERT INTO depoimentos (nick, mensagem, versao) VALUES (?, ?, ?)"
    db.execute_query(query, (nick, mensagem, versao))
    
    return redirect(url_for('experiences'))


@app.route('/comentar-imagem', methods=['POST'])
def comentar_imagem():
    nick = request.form.get('nick')
    comentario = request.form.get('comentario')
    image_name = request.form.get('image_name')

    query = "INSERT INTO image_comments (image_name, nick, comentario) VALUES (?, ?, ?)"
    db.execute_query(query, (image_name, nick, comentario))

    return '', 204

@app.route('/comentarios/<imagem>')
def comentarios(imagem):
    query = "SELECT nick, comentario, data_envio FROM image_comments WHERE image_name = ? ORDER BY data_envio DESC"
    results = db.execute_query(query, (imagem,))
    comentarios = [{'nick': r[0], 'comentario': r[1], 'data': r[2]} for r in results]
    return comentarios

# +-------------------------------------------------+
# |                                                 |
# |     ____                   _                    |
# |    |  _ \ _   _ _ __      / \   _ __  _ __      |
# |    | |_) | | | | '_ \    / _ \ | '_ \| '_ \     |
# |    |  _ <| |_| | | | |  / ___ \| |_) | |_) |    |
# |    |_| \_\\__,_|_| |_| /_/   \_\ .__/| .__/     |
# |                                |_|   |_|        |
# |                                                 |
# +-------------------------------------------------+
app.run(
    debug=True, 
    host="0.0.0.0",
    port=4589
)