from flask import Blueprint, render_template, request, redirect, url_for, make_response, current_app
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer
from flask_login import login_user, logout_user, current_user
from flask_mail import Message
from extensions import mail, login_manager
from models.user import User
from datetime import datetime
from config import get_connection

login = Blueprint('login', __name__)

def get_serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])


@login_manager.user_loader
def load_user(user_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id_usuario, nombre, correo, rol_usuario
        FROM usuarios
        WHERE id_usuario=%s
    """, (user_id,))
    row = cur.fetchone()
    cur.close()

    if row:
        return User(row)
    return None


# ================= LOGIN =================
@login.route('/login', methods=['GET', 'POST'])
def ruta_login():
    if request.method == 'POST':
        correo = request.form['correo']
        password = request.form['password']

        conn = get_connection()
        cur = conn.cursor() 
        cur.execute(
            "SELECT id_usuario, nombre, correo, password, estado FROM usuarios WHERE correo=%s",
            (correo,)
        )
        user = cur.fetchone()
        cur.close()
        
        print("USER COMPLETO:", user)
        if user:
            print("PASSWORD BD:", user["password"])
            print("ESTADO BD:", user["estado"])

        if not user:
            return render_template('login.html', mensaje="Usuario o contraseña incorrectos", correo=correo)

        if not check_password_hash(user["password"], password):
            return render_template('login.html', mensaje="Usuario o contraseña incorrectos", correo=correo)

        estado = (user["estado"] or "").strip().lower()

        if estado != "activo":
            return render_template(
                'login.html',
                mensaje="⚠️ Tu usuario se encuentra inactivo. Contacta al administrador.",
                correo=correo
            )

        usuario = User(user)
        login_user(usuario)

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO sesiones (id_usuario, fecha_inicio, ip_usuario, estado)
            VALUES (%s, %s, %s, %s)
        """, (
            usuario.id,
            datetime.now(),
            request.remote_addr,
            'activo'
        ))
        conn.commit()
        cur.close()

        return make_response(redirect(url_for('main.dashboard')))

    return render_template('login.html')

    return render_template('login.html', mensaje="Usuario o contraseña incorrectos", correo=correo)

    return render_template('login.html')


# ================= REGISTRO =================
@login.route('/registro', methods=['GET', 'POST'])
def ruta_registro():
    if request.method == 'POST':
        nombre = request.form['nombre']
        correo = request.form['correo']
        password = generate_password_hash(request.form['password'])

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM usuarios WHERE correo = %s", (correo,))
        usuario_existente = cur.fetchone()

        if usuario_existente:
            cur.close()
            return render_template('registro.html', mensaje="⚠️ Este correo ya está registrado")

        cur.execute(
            "INSERT INTO usuarios (nombre, correo, password) VALUES (%s, %s, %s)",
            (nombre, correo, password)
        )
        conn.commit()
        cur.close()

        return redirect(url_for('login.ruta_login'))

    return render_template('registro.html')


# ================= RECUPERAR =================
@login.route('/recuperar', methods=['GET', 'POST'])
def ruta_recuperar():
    if request.method == 'POST':
        correo = request.form['correo']

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT correo FROM usuarios WHERE correo=%s", (correo,))
        user = cur.fetchone()
        cur.close()

        if user:
            token = serializer.dumps(correo, salt='recuperar-password')
            enlace = url_for('login.ruta_cambiar_password', token=token, _external=True)

            msg = Message(
                "Recuperación de contraseña",
                sender="corteskarenlk@gmail.com",
                recipients=[correo]
            )
            msg.body = f"Haz clic aquí para cambiar tu contraseña: {enlace}\nEl enlace expira en 30 minutos."
            mail.send(msg)

            return render_template('recuperar.html', mensaje="Se ha enviado un correo para restablecer su contraseña")

        return render_template('recuperar.html', mensaje="Correo no registrado")

    return render_template('recuperar.html')


@login.route('/cambiar_password/<token>', methods=['GET', 'POST'])
def ruta_cambiar_password(token):

    try:
        serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
        user_id = serializer.loads(token, salt="recuperar-password", max_age=1800)
    except:
        return "❌ El enlace es inválido o ha expirado"

    if request.method == 'POST':

        nueva_password = request.form['password']
        confirm_password = request.form['confirm_password']

        if nueva_password != confirm_password:
            return render_template("cambiar_password.html",
                                   mensaje="❌ Las contraseñas no coinciden")

        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
            UPDATE usuarios 
            SET password=%s 
            WHERE id_usuario=%s
        """, (generate_password_hash(nueva_password), user_id))

        conn.commit()

        print("FILAS AFECTADAS:", cur.rowcount)  # 👈 debug clave

        cur.close()

        return redirect(url_for("login.ruta_login"))

    return render_template("cambiar_password.html")


# ================= LOGOUT =================
@login.route('/logout')
def logout():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        UPDATE sesiones
        SET fecha_fin = %s,
            estado = %s
        WHERE id_sesion = (
            SELECT id_sesion FROM (
                SELECT id_sesion
                FROM sesiones
                WHERE id_usuario = %s
                ORDER BY fecha_inicio DESC
                LIMIT 1
            ) AS t
        )
    """, (
        datetime.now(),
        'inactivo',
        current_user.id
    ))
    conn.commit()
    cur.close()

    logout_user()
    return redirect(url_for('login.ruta_login'))