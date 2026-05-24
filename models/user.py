from flask_login import UserMixin

class User(UserMixin):
    def __init__(self, row):
        self.id = row["id_usuario"]
        self.nombre = row["nombre"]
        self.correo = row["correo"]
        self.rol_usuario = row["rol_usuario"]