from flask_login import UserMixin

class User(UserMixin):
    def __init__(self, row):
        self.id = row[0]
        self.nombre = row[1]
        self.correo = row[2]
        self.rol_usuario = row[3]