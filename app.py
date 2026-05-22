import os
import psycopg2
import mercadopago
import re
import json
import cloudinary
import cloudinary.uploader
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, session, flash, jsonify
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'chave_secreta_anderson_excursoes')
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

# --- CONFIGURAÇÃO CLOUDINARY (Imagens na Nuvem) ---
cloudinary.config(
    cloud_name = os.environ.get('CLOUDINARY_CLOUD_NAME'),
    api_key = os.environ.get('CLOUDINARY_API_KEY'),
    api_secret = os.environ.get('CLOUDINARY_API_SECRET')
)

# --- CREDENCIAL DO MERCADO PAGO ---
sdk = mercadopago.SDK("APP_USR-4508380654619786-050619-e6b70695379fd4e5cdd4ded2c2614463-3384502064")

# --- CONEXÃO COM O BANCO DE DADOS POSTGRESQL ---
def get_db_connection():
    DATABASE_URL = os.environ.get('DATABASE_URL')
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL não configurada nas variáveis de ambiente.")
    return psycopg2.connect(DATABASE_URL, sslmode='require')

# --- FUNÇÕES DE VALIDAÇÃO ---
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

# Agora a imagem vai direto pro Cloudinary e retorna o link público
def salvar_imagem(file_obj):
    if file_obj and file_obj.filename != '':
        upload_result = cloudinary.uploader.upload(file_obj)
        return upload_result['secure_url']
    return None

def inicializar_banco():
    # Só roda se as variáveis de ambiente estiverem presentes (Render)
    if not os.environ.get('DATABASE_URL'):
        return

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''CREATE TABLE IF NOT EXISTS viagens (
                        id SERIAL PRIMARY KEY, 
                        destino TEXT NOT NULL, 
                        data TEXT NOT NULL, 
                        vagas_totais INTEGER, 
                        preco REAL, 
                        imagem TEXT,
                        informacoes TEXT,
                        regras TEXT,
                        mensagem_whatsapp TEXT)''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS usuarios (
                        id SERIAL PRIMARY KEY, 
                        nome TEXT NOT NULL, 
                        email TEXT NOT NULL UNIQUE, 
                        senha TEXT NOT NULL, 
                        cpf TEXT NOT NULL, 
                        telefone TEXT NOT NULL, 
                        data_nascimento TEXT)''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS reservas (
                        id SERIAL PRIMARY KEY, 
                        id_usuario INTEGER REFERENCES usuarios(id), 
                        id_viagem INTEGER REFERENCES viagens(id), 
                        data_reserva TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS favoritos (
                        id SERIAL PRIMARY KEY, 
                        id_usuario INTEGER REFERENCES usuarios(id), 
                        id_viagem INTEGER REFERENCES viagens(id),
                        UNIQUE(id_usuario, id_viagem))''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS configuracoes (
                        id INTEGER PRIMARY KEY CHECK (id = 1), 
                        nome_agencia TEXT, 
                        logo TEXT, 
                        banner1_img TEXT, banner1_link TEXT, 
                        banner2_img TEXT, banner2_link TEXT, 
                        passo1_tit TEXT, passo1_desc TEXT)''')
                        
    cursor.execute('''CREATE TABLE IF NOT EXISTS depoimentos (
                        id SERIAL PRIMARY KEY, nome TEXT, nota INTEGER, texto TEXT)''')
                        
    cursor.execute('''CREATE TABLE IF NOT EXISTS faqs (
                        id SERIAL PRIMARY KEY, pergunta TEXT, resposta TEXT)''')

    # Configuração Inicial
    cursor.execute("SELECT id FROM configuracoes WHERE id=1")
    if not cursor.fetchone():
        cursor.execute('''INSERT INTO configuracoes (id, nome_agencia, banner1_link, banner2_link, passo1_tit, passo1_desc) 
                          VALUES (1, 'Anderson Excursões', '#', '#', 'Escolha e Compre', 'Selecione o evento desejado e pague com segurança.')''')

    # Injeção de Shows Padrão (Seed)
    cursor.execute("SELECT COUNT(*) FROM viagens")
    if cursor.fetchone()[0] == 0:
        viagens_teste = [
            ('Rock in Rio - Bate e Volta (Fim de Semana)', '2026-09-19', 46, 350.00, '', 'Transporte executivo com ar-condicionado. Chegada antes da abertura dos portões.', 'Ingresso não incluso. Retorno 1h após o último show do Palco Mundo.', 'Olá, quero reservar minha vaga para o Rock in Rio!'),
            ('Lollapalooza Brasil - Autódromo de Interlagos', '2026-03-27', 50, 180.00, '', 'Saída de manhã com parada para café. Retorno logo após o encerramento.', 'Tolerância máxima de 15 minutos de atraso no embarque.', 'Olá, quero ir pro Lollapalooza!'),
            ('Festa do Peão de Barretos', '2026-08-20', 40, 150.00, '', 'Excursão saindo na sexta-feira à noite. Clima de festa no ônibus!', 'Menores de idade apenas com autorização autenticada em cartório.', 'Olá, quero ir para Barretos!'),
            ('Show Bruno Mars - MorumBIS (SP)', '2026-11-10', 45, 120.00, '', 'Transporte direto para o estádio. Parada apenas para banheiro na estrada.', 'Proibido consumo de bebidas alcoólicas dentro do ônibus.', 'Olá, quero ir no show do Bruno Mars!'),
            ('Tardezinha / Thiaguinho - Neo Química Arena', '2026-12-05', 50, 100.00, '', 'Ônibus animado com esquenta! Desembarque na porta do evento.', 'Embarque apenas com apresentação de documento original com foto.', 'Olá, quero ir na Tardezinha!')
        ]
        cursor.executemany(
            "INSERT INTO viagens (destino, data, vagas_totais, preco, imagem, informacoes, regras, mensagem_whatsapp) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            viagens_teste
        )

    conn.commit()
    cursor.close()
    conn.close()

# Inicia o banco se as credenciais existirem
try:
    inicializar_banco()
except Exception as e:
    print(f"Aviso ao inicializar banco: {e}")


def obter_dados_cms():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM configuracoes WHERE id=1")
    config = cursor.fetchone()
    cursor.execute("SELECT * FROM depoimentos ORDER BY id DESC")
    deps = cursor.fetchall()
    cursor.execute("SELECT * FROM faqs ORDER BY id DESC")
    faqs = cursor.fetchall()
    conn.close()
    return config, deps, faqs


# --- ROTAS PRINCIPAIS ---
@app.route('/')
def index():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM viagens")
    viagens_cruas = cursor.fetchall()
    cursor.execute("SELECT * FROM usuarios")
    usuarios = cursor.fetchall()

    viagens = []
    for v in viagens_cruas:
        id_viagem = v[0]
        preco_unitario = v[4]

        cursor.execute('''
            SELECT u.nome, u.cpf, u.data_nascimento, u.telefone, u.email, COUNT(r.id) as assentos
            FROM reservas r
            JOIN usuarios u ON r.id_usuario = u.id
            WHERE r.id_viagem = %s
            GROUP BY u.id
        ''', (id_viagem,))
        compradores_db = cursor.fetchall()

        compradores_lista = []
        for c in compradores_db:
            qtd_assentos = c[5]
            valor_pago = qtd_assentos * preco_unitario

            compradores_lista.append({
                'nome': c[0], 'cpf': c[1], 'data_nascimento': c[2] if c[2] else '-',
                'telefone': c[3], 'email': c[4], 'quantidade_assentos': qtd_assentos,
                'valor_pago': valor_pago, 'forma_pagamento': 'Mercado Pago'
            })

        class ObjetoCompativel(list):
            pass

        viagem_compativel = [v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7]]
        v_obj = ObjetoCompativel(viagem_compativel)
        v_obj.id = v[0]
        v_obj.destino = v[1]
        v_obj.data = v[2]
        v_obj.compras = compradores_lista
        v_obj.compras_json = json.dumps(compradores_lista)
        viagens.append(v_obj)

    clientes_lista = []
    for u in usuarios:
        cursor.execute('''SELECT v.destino, v.data FROM reservas r JOIN viagens v ON r.id_viagem = v.id WHERE r.id_usuario = %s''', (u[0],))
        compras = cursor.fetchall()
        clientes_lista.append({'nome': u[1], 'email': u[2], 'cpf': u[4], 'telefone': u[5], 'compras': compras})

    cursor.execute("SELECT COUNT(*) FROM reservas")
    total_reservas = cursor.fetchone()[0]
    
    cursor.execute('''SELECT SUM(v.preco) FROM reservas r JOIN viagens v ON r.id_viagem = v.id''')
    faturamento_db = cursor.fetchone()[0]

    faturamento = faturamento_db if faturamento_db else 0.0
    faturamento_formatado = f"{faturamento:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    stats = {'viagens': len(viagens), 'clientes': len(usuarios), 'reservas': total_reservas, 'faturamento': faturamento_formatado}
    conn.close()
    
    config, deps, faqs = obter_dados_cms()
    return render_template('index.html', lista=viagens, clientes=clientes_lista, conf=config, deps=deps, faqs=faqs, stats=stats)


@app.route('/cadastrar', methods=['POST'])
def cadastrar():
    destino = request.form.get('destino')
    data = request.form.get('data')
    vagas = request.form.get('vagas')
    preco = request.form.get('preco')
    informacoes = request.form.get('informacoes')
    regras = request.form.get('regras')
    
    # O upload agora sobe pro Cloudinary e devolve a URL
    imagem_nome = salvar_imagem(request.files.get('imagem'))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO viagens (destino, data, vagas_totais, preco, imagem, informacoes, regras) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (destino, data, vagas, preco, imagem_nome, informacoes, regras)
    )
    conn.commit()
    conn.close()
    return redirect('/')

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
    conn = get_db_connection()
    cursor = conn.cursor()

    if imagem_nome:
        cursor.execute(
            "UPDATE viagens SET destino=%s, data=%s, vagas_totais=%s, preco=%s, imagem=%s, informacoes=%s, regras=%s, mensagem_whatsapp=%s WHERE id=%s",
            (destino, data, vagas, preco, imagem_nome, informacoes, regras, mensagem_whatsapp, id)
        )
    else:
        cursor.execute(
            "UPDATE viagens SET destino=%s, data=%s, vagas_totais=%s, preco=%s, informacoes=%s, regras=%s, mensagem_whatsapp=%s WHERE id=%s",
            (destino, data, vagas, preco, informacoes, regras, mensagem_whatsapp, id)
        )

    conn.commit()
    conn.close()
    return redirect('/')

@app.route('/deletar/<int:id>')
def deletar_viagem(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    # Remove dependencias antes (se necessário) ou usar CASCADE.
    cursor.execute("DELETE FROM favoritos WHERE id_viagem=%s", (id,))
    cursor.execute("DELETE FROM reservas WHERE id_viagem=%s", (id,))
    cursor.execute("DELETE FROM viagens WHERE id=%s", (id,))
    conn.commit()
    conn.close()
    return redirect('/')

@app.route('/salvar_identidade', methods=['POST'])
def salvar_identidade():
    nome_agencia = request.form.get('nome_agencia')
    b1_link, b2_link = request.form.get('banner1_link'), request.form.get('banner2_link')
    
    logo = salvar_imagem(request.files.get('logo'))
    b1_img = salvar_imagem(request.files.get('banner1_img'))
    b2_img = salvar_imagem(request.files.get('banner2_img'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE configuracoes SET nome_agencia=%s, banner1_link=%s, banner2_link=%s WHERE id=1',
                   (nome_agencia, b1_link, b2_link))
    if logo: cursor.execute("UPDATE configuracoes SET logo=%s WHERE id=1", (logo,))
    if b1_img: cursor.execute("UPDATE configuracoes SET banner1_img=%s WHERE id=1", (b1_img,))
    if b2_img: cursor.execute("UPDATE configuracoes SET banner2_img=%s WHERE id=1", (b2_img,))
    conn.commit()
    conn.close()
    return redirect('/#pane-config-site')

# --- ROTAS DE AUTENTICAÇÃO E CARRINHO (Simplificadas para Leitura) ---
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

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO usuarios (nome, email, senha, cpf, telefone, data_nascimento) VALUES (%s, %s, %s, %s, %s, %s)",
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
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM usuarios WHERE email = %s AND senha = %s", (email, senha))
    usuario = cursor.fetchone()
    conn.close()

    if usuario:
        session.permanent = True
        session['usuario_id'], session['usuario_nome'] = usuario[0], usuario[1]
        return redirect('/dashboard')

    flash("E-mail ou senha incorretos. Tente novamente!")
    return redirect('/login')

@app.route('/dashboard')
def dashboard():
    if 'usuario_id' not in session: return redirect('/login')
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM viagens")
    viagens = cursor.fetchall()
    conn.close()
    config, _, _ = obter_dados_cms()
    return render_template('dashboard.html', lista=viagens, conf=config)

@app.route('/sucesso')
def sucesso():
    return f"<div style='text-align:center; margin-top:100px;'><h1>Pagamento Aprovado! 🎉</h1><a href='/dashboard' style='background:#367C2B; color:white; padding:10px; text-decoration:none;'>Voltar</a></div>"

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

if __name__ == '__main__':
    app.run(debug=True)
