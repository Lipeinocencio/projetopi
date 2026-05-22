from flask import Flask, render_template, request, redirect, session
import sqlite3

app = Flask(__name__)
# Chave de segurança para as sessões de login
app.secret_key = 'chave_secreta_caroli_excursoes'


# --- 1. CONFIGURAÇÃO DO BANCO DE DADOS ---
def inicializar_banco():
    conn = sqlite3.connect('excursoes.db')
    cursor = conn.cursor()

    # Tabela de Viagens (Onde o dono cadastra)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS viagens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        destino TEXT NOT NULL,
        data TEXT NOT NULL,
        vagas_totais INTEGER,
        preco REAL
    )
    ''')

    # Tabela de Usuários (Com os novos campos CPF e Telefone)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        senha TEXT NOT NULL,
        cpf TEXT NOT NULL,
        telefone TEXT NOT NULL
    )
    ''')

    # Tabela de Reservas (A união entre Cliente e Viagem)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS reservas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        id_usuario INTEGER,
        id_viagem INTEGER,
        data_reserva TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (id_usuario) REFERENCES usuarios(id),
        FOREIGN KEY (id_viagem) REFERENCES viagens(id)
    )
    ''')

    conn.commit()
    conn.close()


# Garante que o banco seja criado ao iniciar o app
inicializar_banco()


# --- 2. ROTAS ADMINISTRATIVAS (O DONO) ---

@app.route('/')
def index():
    conn = sqlite3.connect('excursoes.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM viagens")
    viagens = cursor.fetchall()
    conn.close()
    return render_template('index.html', lista=viagens)


@app.route('/cadastrar', methods=['POST'])
def cadastrar():
    destino = request.form.get('destino')
    data = request.form.get('data')
    vagas = request.form.get('vagas')
    preco = request.form.get('preco')

    conn = sqlite3.connect('excursoes.db')
    cursor = conn.cursor()
    cursor.execute("INSERT INTO viagens (destino, data, vagas_totais, preco) VALUES (?, ?, ?, ?)",
                   (destino, data, vagas, preco))
    conn.commit()
    conn.close()
    return redirect('/')


# --- 3. ROTAS DE CLIENTE (CADASTRO E LOGIN) ---

@app.route('/cadastro')
def tela_cadastro():
    return render_template('cadastro.html')


@app.route('/cadastrar_usuario', methods=['POST'])
def cadastrar_usuario():
    nome = request.form.get('nome')
    email = request.form.get('email')
    senha = request.form.get('senha')
    cpf = request.form.get('cpf')
    telefone = request.form.get('telefone')

    conn = sqlite3.connect('excursoes.db')
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO usuarios (nome, email, senha, cpf, telefone) VALUES (?, ?, ?, ?, ?)",
                       (nome, email, senha, cpf, telefone))
        conn.commit()
    except:
        return "<h1>Erro: Este e-mail já está em uso!</h1><a href='/cadastro'>Voltar</a>"
    finally:
        conn.close()
    return redirect('/login')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')

    email = request.form.get('email')
    senha = request.form.get('senha')

    conn = sqlite3.connect('excursoes.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM usuarios WHERE email = ? AND senha = ?", (email, senha))
    usuario = cursor.fetchone()
    conn.close()

    if usuario:
        session['usuario_id'] = usuario[0]
        session['usuario_nome'] = usuario[1]
        return redirect('/dashboard')
    else:
        return "<h1>Erro: Login ou senha incorretos!</h1><a href='/login'>Tentar novamente</a>"


# --- 4. ÁREA DO CLIENTE (DASHBOARD E COMPRA) ---

@app.route('/dashboard')
def dashboard():
    if 'usuario_id' not in session:
        return redirect('/login')

    conn = sqlite3.connect('excursoes.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM viagens")
    viagens = cursor.fetchall()
    conn.close()
    return render_template('dashboard.html', lista=viagens)


@app.route('/comprar/<int:id_viagem>')
def comprar(id_viagem):
    if 'usuario_id' not in session:
        return redirect('/login')

    uid = session['usuario_id']

    conn = sqlite3.connect('excursoes.db')
    cursor = conn.cursor()
    cursor.execute("INSERT INTO reservas (id_usuario, id_viagem) VALUES (?, ?)", (uid, id_viagem))
    conn.commit()
    conn.close()

    return "<h1>Reserva Confirmada!</h1><a href='/dashboard'>Voltar ao Dashboard</a>"


@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')


# --- INICIALIZAÇÃO ---
if __name__ == '__main__':
    app.run(debug=True)
