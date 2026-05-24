from flask import Flask
from routes.main import main
from routes.login import login
from extensions import mail, mysql, login_manager
import config

app = Flask(__name__)

#CONFIG
app.config.from_object(config.Config)


app.mysql = mysql

#INIT EXTENSIONS
mail.init_app(app)
mysql.init_app(app)
login_manager.init_app(app)
login_manager.login_view = 'login.ruta_login'


# Registrar rutas
app.register_blueprint(main)
app.register_blueprint(login)


if __name__ == '__main__':
    app.run(debug=True)