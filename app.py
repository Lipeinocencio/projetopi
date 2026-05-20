import os
import sqlite3
import mercadopago
import re
import json  # ← Adicionado para fazer a conversão dos dados dos clientes para a Modal
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, session, flash, jsonify
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'chave_secreta_anderson_excursoes'

# Configuração para manter o usuário logado
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)  # Mantém logado por 30 dias


# --- 1. FUNÇÕES DE VALIDAÇÃO ---

def validar_cpf(cpf):
    cpf = re.sub(r'\D', '', cpf)
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    for i in range(9, 11):
        soma = sum(int(cpf[num]) * ((i + 1) - num) for num in range(i))
        digito = (soma * 10 % 11) % 10
        if digito != int(cpf[i]):
            return False
    return True


def validar_data_nascimento(data_str):
    try:
        if not data_str: return False
        data_nasc = datetime.strptime(data_str, '%Y-%m-%d')
        hoje = datetime.today()
        if data_nasc > hoje or (hoje.year - data_nasc.year) > 120:
            return False
        return True
    except (ValueError, TypeError):
        return False


# --- CONFIGURAÇÃO PARA TESTE LOCAL ---
DB_NAME = 'sistema.db'
UPLOAD_FOLDER = os.path.join('static', 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# --- CREDENCIAL DO MERCADO PAGO ---
sdk = mercadopago.SDK("APP_USR-4508380654619786-050619-e6b70695379fd4e5cdd4ded2c2614463-3384502064")


def salvar_imagem(file_obj):
    if file_obj and file_obj.filename != '':
        nome = secure_filename(file_obj.filename)
        file_obj.save(os.path.join(app.config['UPLOAD_FOLDER'], nome))
        return nome
    return None


def inicializar_banco():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Criação das tabelas principais caso não existam
    cursor.execute('''CREATE TABLE IF NOT EXISTS viagens (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, 
                        destino TEXT NOT NULL, 
                        data TEXT NOT NULL, 
                        vagas_totais INTEGER, 
                        preco REAL, 
                        imagem TEXT,
                        informacoes TEXT,
                        regras TEXT)''')

    cursor.execute(
        '''CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL, email TEXT NOT NULL UNIQUE, senha TEXT NOT NULL, cpf TEXT NOT NULL, telefone TEXT NOT NULL, data_nascimento TEXT)''')

    cursor.execute(
        '''CREATE TABLE IF NOT EXISTS reservas (id INTEGER PRIMARY KEY AUTOINCREMENT, id_usuario INTEGER, id_viagem INTEGER, data_reserva TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (id_usuario) REFERENCES usuarios(id), FOREIGN KEY (id_viagem) REFERENCES viagens(id))''')

    # --- NOVA TABELA DE FAVORITOS ADICIONADA AQUI ---
    cursor.execute('''CREATE TABLE IF NOT EXISTS favoritos (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, 
                        id_usuario INTEGER, 
                        id_viagem INTEGER, 
                        FOREIGN KEY (id_usuario) REFERENCES usuarios(id), 
                        FOREIGN KEY (id_viagem) REFERENCES viagens(id),
                        UNIQUE(id_usuario, id_viagem))''')

    cursor.execute(
        '''CREATE TABLE IF NOT EXISTS configuracoes (id INTEGER PRIMARY KEY CHECK (id = 1), nome_agencia TEXT, logo TEXT, banner1_img TEXT, banner1_link TEXT, banner2_img TEXT, banner2_link TEXT, passo1_tit TEXT, passo1_desc TEXT)''')
    cursor.execute(
        '''CREATE TABLE IF NOT EXISTS depoimentos (id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT, nota INTEGER, texto TEXT)''')
    cursor.execute(
        '''CREATE TABLE IF NOT EXISTS faqs (id INTEGER PRIMARY KEY AUTOINCREMENT, pergunta TEXT, resposta TEXT)''')

    # Atualização dinâmica do banco caso o usuário já tenha criado a tabela viagens sem os novos campos
    try:
        cursor.execute("ALTER TABLE viagens ADD COLUMN informacoes TEXT;")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE viagens ADD COLUMN regras TEXT;")
    except sqlite3.OperationalError:
        pass

    # AUTOMATIZAÇÃO: Cria o campo mensagem_whatsapp caso ele não exista na tabela do banco oficial
    try:
        cursor.execute("ALTER TABLE viagens ADD COLUMN mensagem_whatsapp TEXT;")
    except sqlite3.OperationalError:
        pass

    cursor.execute("SELECT id FROM configuracoes WHERE id=1")
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO configuracoes (id, nome_agencia, banner1_link, banner2_link, passo1_tit, passo1_desc) VALUES (1, 'Anderson Excursões', '#', '#', 'Escolha e Compre', 'Selecione o evento desejado e pague com segurança.')")

        # Força a criação da coluna mensagem_whatsapp caso o banco antigo ainda persista
        try:
            cursor.execute("ALTER TABLE viagens ADD COLUMN mensagem_whatsapp TEXT;")
        except sqlite3.OperationalError:
            pass  # Se a coluna já existir, ele só ignora e não quebra o código

    conn.commit()
    conn.close()


inicializar_banco()


def obter_dados_cms():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    config = cursor.execute("SELECT * FROM configuracoes WHERE id=1").fetchone()
    deps = cursor.execute("SELECT * FROM depoimentos ORDER BY id DESC").fetchall()
    faqs = cursor.execute("SELECT * FROM faqs ORDER BY id DESC").fetchall()
    conn.close()
    return config, deps, faqs


# --- ROTAS ADMINISTRATIVAS ---
@app.route('/')
def index():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Buscamos as viagens cruas do banco de dados
    viagens_cruas = cursor.execute("SELECT * FROM viagens").fetchall()
    usuarios = cursor.execute("SELECT * FROM usuarios").fetchall()

    # 1. Ajuste Dinâmico para a Aba "Gestão de Mensagens" e sua Modal de Compradores
    viagens = []
    for v in viagens_cruas:
        id_viagem = v[0]
        preco_unitario = v[4]

        # Agrupa os compradores desta viagem contando quantos assentos cada CPF/Usuário comprou repetido no carrinho
        compradores_db = cursor.execute('''
            SELECT u.nome, u.cpf, u.data_nascimento, u.telefone, u.email, COUNT(r.id) as assentos
            FROM reservas r
            JOIN usuarios u ON r.id_usuario = u.id
            WHERE r.id_viagem = ?
            GROUP BY u.id
        ''', (id_viagem,)).fetchall()

        compradores_lista = []
        for c in compradores_db:
            qtd_assentos = c[5]
            valor_pago = qtd_assentos * preco_unitario

            compradores_lista.append({
                'nome': c[0],
                'cpf': c[1],
                'data_nascimento': c[2] if c[2] else '-',
                'telefone': c[3],
                'email': c[4],
                'quantidade_assentos': qtd_assentos,
                'valor_pago': valor_pago,
                'forma_pagamento': 'Mercado Pago'  # Gateway padrão do sistema
            })

        # Transformamos a tupla em um dicionário manipulável para o Jinja2 no HTML
        viagem_dict = {
            'id': v[0], 'destino': v[1], 'data': v[2], 'vagas_totais': v[3],
            'preco': v[4], 'imagem': v[5], 'informacoes': v[6], 'regras': v[7],
            'compras': compradores_lista,  # Usado no filtro {{ v.compras|length }}
            'compras_json': json.dumps(compradores_lista)  # Capturado pelo JS da modal
        }

        # Criamos o mapeamento por índice numérico legado para não quebrar a primeira aba do seu HTML
        viagem_compativel = [v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7]]

        class ObjetoCompativel(list):
            pass

        v_obj = ObjetoCompativel(viagem_compativel)
        v_obj.id = v[0]
        v_obj.destino = v[1]
        v_obj.data = v[2]
        v_obj.compras = compradores_lista
        v_obj.compras_json = json.dumps(compradores_lista)

        viagens.append(v_obj)

    # 2. Mantém a lógica clássica da base de clientes intacta
    clientes_lista = []
    for u in usuarios:
        compras = cursor.execute(
            '''SELECT v.destino, v.data FROM reservas r JOIN viagens v ON r.id_viagem = v.id WHERE r.id_usuario = ?''',
            (u[0],)).fetchall()
        clientes_lista.append({'nome': u[1], 'email': u[2], 'cpf': u[4], 'telefone': u[5], 'compras': compras})

    total_viagens = len(viagens)
    total_clientes = len(usuarios)
    total_reservas = cursor.execute("SELECT COUNT(*) FROM reservas").fetchone()[0]
    faturamento_db = \
        cursor.execute('''SELECT SUM(v.preco) FROM reservas r JOIN viagens v ON r.id_viagem = v.id''').fetchone()[0]

    faturamento = faturamento_db if faturamento_db else 0.0
    faturamento_formatado = f"{faturamento:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    stats = {'viagens': total_viagens, 'clientes': total_clientes, 'reservas': total_reservas,
             'faturamento': faturamento_formatado}
    conn.close()
    config, deps, faqs = obter_dados_cms()
    return render_template('index.html', lista=viagens, clientes=clientes_lista, conf=config, deps=deps, faqs=faqs,
                           stats=stats)


@app.route('/comprar/<int:id>')
def comprar(id):
    if 'usuario_id' not in session:
        return redirect('/login')
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        viagem = cursor.execute("SELECT * FROM viagens WHERE id = ?", (id,)).fetchone()

        if not viagem:
            conn.close()
            return "<h1>Excursão não encontrada para compra!</h1>", 404

        cursor.execute("INSERT INTO reservas (id_usuario, id_viagem) VALUES (?, ?)", (session['usuario_id'], id))
        conn.commit()
        conn.close()

        preference_data = {
            "items": [{
                "title": f"Excursão: {viagem[1]}",
                "quantity": 1,
                "currency_id": "BRL",
                "unit_price": float(viagem[4])
            }],
            "back_urls": {
                "success": "https://projetointegrador.dominionulo.com.br/sucesso",
                "failure": "https://projetointegrador.dominionulo.com.br/falha",
                "pending": "https://projetointegrador.dominionulo.com.br/pendente"
            },
            "auto_return": "approved"
        }
        preference_response = sdk.preference().create(preference_data)
        return redirect(preference_response["response"]["init_point"])
    except Exception as e:
        return f"<h1>Erro no pagamento:</h1><p>{str(e)}</p>"


@app.route('/cadastrar', methods=['POST'])
def cadastrar():
    destino = request.form.get('destino')
    data = request.form.get('data')
    vagas = request.form.get('vagas')
    preco = request.form.get('preco')
    informacoes = request.form.get('informacoes')
    regras = request.form.get('regras')

    imagem_nome = salvar_imagem(request.files.get('imagem'))

    conn = sqlite3.connect(DB_NAME)
    conn.cursor().execute(
        "INSERT INTO viagens (destino, data, vagas_totais, preco, imagem, informacoes, regras) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (destino, data, vagas, preco, imagem_nome, informacoes, regras)
    )
    conn.commit()
    conn.close()
    return redirect('/')


@app.route('/excursao/<int:id>')
def detalhes_excursao(id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    viagem = cursor.execute("SELECT * FROM viagens WHERE id = ?", (id,)).fetchone()
    conn.close()

    if not viagem:
        return "<h1>Excursão não encontrada!</h1>", 404

    config, deps, faqs = obter_dados_cms()
    return render_template('detalhes.html', v=viagem, conf=config)


@app.route('/editar/<int:id>')
def editar_viagem(id):
    try:
        conn = sqlite3.connect(DB_NAME)
        viagem = conn.cursor().execute("SELECT * FROM viagens WHERE id=?", (id,)).fetchone()
        conn.close()
        config, deps, faqs = obter_dados_cms()

        if not viagem:
            return f"<h1 style='color:#367C2B'>ID {id} não encontrado.</h1><p>Base de dados em uso: {DB_NAME}</p>", 200

        return render_template('editar.html', v=viagem, conf=config)
    except Exception as e:
        return f"<h1 style='color:#367C2B'>Erro na edição:</h1><p>{str(e)}</p>", 200


@app.route('/atualizar/<int:id>', methods=['POST'])
def atualizar_viagem(id):
    destino = request.form.get('destino')
    data = request.form.get('data')
    vagas = request.form.get('vagas')
    preco = request.form.get('preco')
    informacoes = request.form.get('informacoes')
    regras = request.form.get('regras')

    mensagem_whatsapp = request.form.get('mensagem_whatsapp')

    imagem_nome = salvar_imagem(request.files.get('imagem'))
    conn = sqlite3.connect(DB_NAME)

    if imagem_nome:
        conn.cursor().execute(
            "UPDATE viagens SET destino=?, data=?, vagas_totais=?, preco=?, imagem=?, informacoes=?, regras=?, mensagem_whatsapp=? WHERE id=?",
            (destino, data, vagas, preco, imagem_nome, informacoes, regras, mensagem_whatsapp, id)
        )
    else:
        conn.cursor().execute(
            "UPDATE viagens SET destino=?, data=?, vagas_totais=?, preco=?, informacoes=?, regras=?, mensagem_whatsapp=? WHERE id=?",
            (destino, data, vagas, preco, informacoes, regras, mensagem_whatsapp, id)
        )

    conn.commit()
    conn.close()
    return redirect('/')


@app.route('/deletar/<int:id>')
def deletar_viagem(id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM viagens WHERE id=?", (id,))
    conn.commit()
    conn.close()
    return redirect('/')


# --- ROTAS DO CMS E SITE ---
@app.route('/salvar_identidade', methods=['POST'])
def salvar_identidade():
    nome_agencia = request.form.get('nome_agencia')
    b1_link, b2_link = request.form.get('banner1_link'), request.form.get('banner2_link')
    logo, b1_img, b2_img = salvar_imagem(request.files.get('logo')), salvar_imagem(
        request.files.get('banner1_img')), salvar_imagem(request.files.get('banner2_img'))
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE configuracoes SET nome_agencia=?, banner1_link=?, banner2_link=? WHERE id=1',
                   (nome_agencia, b1_link, b2_link))
    if logo: cursor.execute("UPDATE configuracoes SET logo=? WHERE id=1", (logo,))
    if b1_img: cursor.execute("UPDATE configuracoes SET banner1_img=? WHERE id=1", (b1_img,))
    if b2_img: cursor.execute("UPDATE configuracoes SET banner2_img=? WHERE id=1", (b2_img,))
    conn.commit()
    conn.close()
    return redirect('/#pane-config-site')


@app.route('/site')
def site_oficial():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    viagens = cursor.execute("SELECT * FROM viagens").fetchall()

    favoritos_usuario = []
    if 'usuario_id' in session:
        favs = cursor.execute("SELECT id_viagem FROM favoritos WHERE id_usuario = ?",
                              (session['usuario_id'],)).fetchall()
        favoritos_usuario = [f[0] for f in favs]

    conn.close()
    config, deps, faqs = obter_dados_cms()
    return render_template('site.html', lista=viagens, conf=config, deps=deps, faqs=faqs, favs_user=favoritos_usuario)


@app.route('/meus_favoritos')
def meus_favoritos():
    if 'usuario_id' not in session:
        return redirect('/login')

    id_usuario = session['usuario_id']
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    viagens_favoritas = cursor.execute('''
        SELECT v.* FROM viagens v
        JOIN favoritos f ON v.id = f.id_viagem
        WHERE f.id_usuario = ?
    ''', (id_usuario,)).fetchall()

    conn.close()
    config, _, _ = obter_dados_cms()

    return render_template('favoritos.html', lista=viagens_favoritas, conf=config)


@app.route('/favoritar/<int:id_viagem>', methods=['POST'])
def favoritar(id_viagem):
    if 'usuario_id' not in session:
        return jsonify({'erro': 'Usuário não logado'}), 401

    id_usuario = session['usuario_id']
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    existe = cursor.execute(
        'SELECT 1 FROM favoritos WHERE id_usuario = ? AND id_viagem = ?',
        (id_usuario, id_viagem)
    ).fetchone()

    if existe:
        cursor.execute(
            'DELETE FROM favoritos WHERE id_usuario = ? AND id_viagem = ?',
            (id_usuario, id_viagem)
        )
        status = 'removido'
    else:
        cursor.execute(
            'INSERT INTO favoritos (id_usuario, id_viagem) VALUES (?, ?)',
            (id_usuario, id_viagem)
        )
        status = 'adicionado'

    conn.commit()
    conn.close()

    return jsonify({'status': status})


# --- ROTAS DE AUTENTICAÇÃO ---

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
    data_nasc = request.form.get('data_nascimento')

    if not validar_cpf(cpf):
        flash("CPF inválido!")
        return redirect('/cadastro')

    if not validar_data_nascimento(data_nasc):
        flash("Data de nascimento inválida.")
        return redirect('/cadastro')

    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO usuarios (nome, email, senha, cpf, telefone, data_nascimento) VALUES (?, ?, ?, ?, ?, ?)",
            (nome, email, senha, cpf, telefone, data_nasc))
        conn.commit()
        conn.close()
        return redirect('/login')
    except:
        flash("E-mail já cadastrado.")
        return redirect('/cadastro')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')

    email, senha = request.form.get('email'), request.form.get('senha')
    conn = sqlite3.connect(DB_NAME)
    usuario = conn.cursor().execute("SELECT * FROM usuarios WHERE email = ? AND senha = ?", (email, senha)).fetchone()
    conn.close()

    if usuario:
        session.permanent = True
        session['usuario_id'], session['usuario_nome'] = usuario[0], usuario[1]
        return redirect('/dashboard')

    flash("E-mail ou senha incorretos, ou cadastro inexistente. Tente novamente!")
    return redirect('/login')


# --- SISTEMA DE CARRINHO DE COMPRAS ---

@app.route('/adicionar_carrinho/<int:id_viagem>', methods=['POST'])
def adicionar_carrinho(id_viagem):
    if 'usuario_id' not in session:
        # Troquei o jsonify por um redirecionamento com mensagem
        flash("Faça login para adicionar itens ao carrinho.")
        return redirect('/login')

    quantidade = int(request.form.get('quantidade', 1))

    if 'carrinho' not in session:
        session['carrinho'] = {}

    carrinho = session['carrinho']

    id_str = str(id_viagem)
    if id_str in carrinho:
        carrinho[id_str] += quantidade
    else:
        carrinho[id_str] = quantidade

    session['carrinho'] = carrinho
    flash("Item adicionado ao carrinho com sucesso!")
    return redirect('/carrinho')


@app.route('/carrinho')
def ver_carrinho():
    if 'usuario_id' not in session:
        return redirect('/login')

    carrinho = session.get('carrinho', {})
    itens_carrinho = []
    total_geral = 0.0

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    for id_viagem_str, qtd in carrinho.items():
        viagem = cursor.execute("SELECT * FROM viagens WHERE id = ?", (int(id_viagem_str),)).fetchone()
        if viagem:
            subtotal = viagem[4] * qtd
            total_geral += subtotal
            itens_carrinho.append({
                'id': viagem[0],
                'destino': viagem[1],
                'data': viagem[2],
                'preco': viagem[4],
                'imagem': viagem[5],
                'quantidade': qtd,
                'subtotal': subtotal
            })

    conn.close()
    config, _, _ = obter_dados_cms()
    return render_template('carrinho.html', itens=itens_carrinho, total=total_geral, conf=config)


@app.route('/remover_carrinho/<int:id_viagem>')
def remover_carrinho(id_viagem):
    if 'carrinho' in session:
        carrinho = session['carrinho']
        id_str = str(id_viagem)
        if id_str in carrinho:
            del carrinho[id_str]
            session['carrinho'] = carrinho
    return redirect('/carrinho')


@app.route('/finalizar_carrinho_mp', methods=['POST'])
def finalizar_carrinho_mp():
    if 'usuario_id' not in session or 'carrinho' not in session or not session['carrinho']:
        return redirect('/site')

    id_usuario = session['usuario_id']
    carrinho = session['carrinho']

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    itens_mercado_pago = []

    try:
        for id_viagem_str, qtd in carrinho.items():
            id_viagem = int(id_viagem_str)
            viagem = cursor.execute("SELECT * FROM viagens WHERE id = ?", (id_viagem,)).fetchone()

            if not viagem:
                continue

            for _ in range(qtd):
                cursor.execute("INSERT INTO reservas (id_usuario, id_viagem) VALUES (?, ?)", (id_usuario, id_viagem))

            itens_mercado_pago.append({
                "title": f"Excursão: {viagem[1]} (x{qtd})",
                "quantity": qtd,
                "currency_id": "BRL",
                "unit_price": float(viagem[4])
            })

        conn.commit()
        conn.close()

        session.pop('carrinho', None)

        preference_data = {
            "items": itens_mercado_pago,
            "back_urls": {
                "success": "https://projetointegrador.dominionulo.com.br/sucesso",
                "failure": "https://projetointegrador.dominionulo.com.br/falha",
                "pending": "https://projetointegrador.dominionulo.com.br/pendente"
            },
            "auto_return": "approved"
        }

        preference_response = sdk.preference().create(preference_data)
        return redirect(preference_response["response"]["init_point"])

    except Exception as e:
        return f"<h1>Erro ao processar lote do carrinho:</h1><p>{str(e)}</p>"

@app.route('/gerenciar_clientes/<int:id_viagem>')
def gerenciar_clientes(id_viagem):
    if 'usuario_id' not in session:  # Opcional: protege a rota para admins/logados
        return redirect('/login')

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # 1. Busca os detalhes da excursão para colocar no título da página
    viagem = cursor.execute("SELECT destino, data, preco FROM viagens WHERE id = ?", (id_viagem,)).fetchone()
    if not viagem:
        conn.close()
        return "<h1>Excursão não encontrada!</h1>", 404

    destino, data_viagem, preco_unitario = viagem[0], viagem[1], viagem[2]

    # 2. Busca todos os dados dos clientes que compraram essa excursão específica
    # Agrupa por usuário para somar a quantidade de assentos se compraram mais de um no carrinho
    compradores_db = cursor.execute('''
        SELECT u.nome, u.cpf, u.data_nascimento, u.telefone, u.email, COUNT(r.id) as assentos
        FROM reservas r
        JOIN usuarios u ON r.id_usuario = u.id
        WHERE r.id_viagem = ?
        GROUP BY u.id
    ''', (id_viagem,)).fetchall()

    compradores_lista = []
    for c in compradores_db:
        qtd_assentos = c[5]
        valor_pago = qtd_assentos * preco_unitario

        compradores_lista.append({
            'nome': c[0],
            'cpf': c[1],
            'data_nascimento': c[2] if c[2] else '-',
            'telefone': c[3],
            'email': c[4],
            'quantidade_assentos': qtd_assentos,
            'valor_pago': valor_pago,
            'forma_pagamento': 'Mercado Pago'  # Gateway padrão do seu sistema
        })

    conn.close()

    # Busca dados do CMS apenas para manter o padrão visual/nome da agência se necessário
    config, _, _ = obter_dados_cms()

    return render_template('gerenciar_clientes.html',
                           destino=destino,
                           data_viagem=data_viagem,
                           compradores=compradores_lista,
                           conf=config)

@app.route('/dashboard')
def dashboard():
    if 'usuario_id' not in session:
        return redirect('/login')
    conn = sqlite3.connect(DB_NAME)
    viagens = conn.cursor().execute("SELECT * FROM viagens").fetchall()
    conn.close()
    config, _, _ = obter_dados_cms()
    return render_template('dashboard.html', lista=viagens, conf=config)


@app.route('/sucesso')
def sucesso():
    return f"<div style='text-align:center; margin-top:100px;'><h1>Pagamento Aprovado! 🎉</h1><a href='/dashboard' style='background:#1B264A; color:white; padding:10px; text-decoration:none;'>Voltar</a></div>"


@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')


if __name__ == '__main__':
    app.run(debug=True)
