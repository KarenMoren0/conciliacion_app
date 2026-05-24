class Config:
    SECRET_KEY = 'mi_clave_super_secreta_123'
    # MYSQL
    MYSQL_HOST = 'localhost'
    MYSQL_USER = 'root'
    MYSQL_PASSWORD = ''
    MYSQL_DB = 'plataforma'

    # MAIL
    MAIL_SERVER = 'smtp.gmail.com'
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    MAIL_USERNAME = 'corteskarenlk@gmail.com'
    MAIL_PASSWORD = 'uwvxbdplfsqcxnow'
    MAIL_DEFAULT_SENDER = 'corteskarenlk@gmail.com'

    # BIGQUERY
    BQ_PROJECT = "monitor-migracion"