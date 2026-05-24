import pymysql

class Config:
    SECRET_KEY = 'mi_clave_super_secreta_123'

    # MAIL
    MAIL_SERVER = 'smtp.gmail.com'
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    MAIL_USERNAME = 'corteskarenlk@gmail.com'
    MAIL_PASSWORD = 'uwvxbdplfsqcxnow'
    MAIL_DEFAULT_SENDER = 'corteskarenlk@gmail.com'

    # BIGQUERY
    BQ_PROJECT = "monitor-migracion"

def get_connection():
    return pymysql.connect(
        host="zephyr.proxy.rlwy.net",
        user="root",
        password="slCuNIXYQlVcCBKiIROFgkkNNfiYSuuG",
        database="railway",
        port=38672,
        cursorclass=pymysql.cursors.DictCursor
    )