from flask_mail import Mail
from flask_mysqldb import MySQL
from flask_login import LoginManager
from flask import current_app

mail = Mail()
mysql = MySQL()
login_manager = LoginManager()


@login_manager.user_loader
def load_user(user_id):
    cur = current_app.mysql.connection.cursor()

    cur.execute("""
        SELECT id_usuario, nombre, correo, rol_usuario
        FROM usuarios
        WHERE id_usuario = %s
    """, (user_id,))

    row = cur.fetchone()
    cur.close()

    if row:
        return User(*row)

    return None