from flask import Blueprint, render_template, current_app, request, redirect, url_for, Response, flash, abort
from functools import wraps
from io import BytesIO
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
from flask_mail import Message
from flask_login import login_required, current_user
from google.cloud import bigquery

from bigquery_client import get_bq_client
from extensions import mail


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        rol = (getattr(current_user, "rol_usuario", "") or "").strip().lower()
        if rol != "admin":
            return abort(403)
        return f(*args, **kwargs)
    return wrapper


main = Blueprint('main', __name__)


# ================= HOME =================
@main.route('/')
def home():
    return render_template('login.html')


# ================= DASHBOARD =================
def _query_pie(client, job_config, fecha):
    where_pie = "WHERE DATE(fecha) = @fecha" if fecha else ""
    result = list(client.query(f"""
        SELECT
            fecha,
            COUNT(*) AS total,
            COUNTIF(ambiente = 'produccion') AS migrado,
            COUNTIF(ambiente = 'prototipado') AS pendiente
        FROM `monitor-migracion.migracion.procesos`
        {where_pie}
        GROUP BY fecha
        ORDER BY fecha
    """, job_config=job_config).result())

    migrado = int(result[0].migrado or 0) if result else 0
    pendiente = int(result[0].pendiente or 0) if result else 0

    return {
        "ok": migrado,
        "error": pendiente,
        "porcentaje": round(migrado / max(migrado + pendiente, 1) * 100)
    }


def _query_barras(client, job_config, where_procesos):
    rows = client.query(f"""
        SELECT
            DATE_TRUNC(fecha, WEEK) AS semana,
            COUNT(DISTINCT IF(ambiente = 'produccion', id_proceso, NULL)) AS migrado
        FROM `monitor-migracion.migracion.procesos`
        {where_procesos}
        GROUP BY semana
        ORDER BY semana
    """, job_config=job_config).result()

    labels, data = [], []
    for row in rows:
        labels.append(str(row.semana))
        data.append(row.migrado)

    return {"labels": labels, "data": data}


def _query_lineas(client, job_config, where_ejecuciones):
    rows = client.query(f"""
        SELECT
            fecha_ejecucion,
            SUM(
                CASE
                    WHEN estado_produccion='ERROR' OR estado_prototipado='ERROR'
                    THEN 1 ELSE 0
                END
            ) AS error,
            SUM(
                CASE
                    WHEN estado_produccion='OK' AND estado_prototipado='OK'
                    THEN 1 ELSE 0
                END
            ) AS ok
        FROM `monitor-migracion.migracion.ejecuciones`
        {where_ejecuciones}
        GROUP BY fecha_ejecucion
        ORDER BY fecha_ejecucion
    """, job_config=job_config).result()

    labels, errores, oks = [], [], []
    for row in rows:
        labels.append(str(row.fecha_ejecucion))
        errores.append(row.error)
        oks.append(row.ok)

    return {"labels": labels, "error": errores, "ok": oks}


def _query_fuentes(client, fecha):
    if fecha:
        rows = client.query("""
            SELECT nombre, cantidad_registros, estado
            FROM `monitor-migracion.migracion.fuentes`
            WHERE DATE(fecha) = @fecha
        """, job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("fecha", "DATE", fecha)]
        )).result()
    else:
        rows = client.query("""
            SELECT nombre, cantidad_registros, estado
            FROM `monitor-migracion.migracion.fuentes`
        """).result()

    data, listas = [], 0
    for row in rows:
        data.append({
            "nombre": row.nombre,
            "cantidad": row.cantidad_registros,
            "estado": row.estado
        })
        if row.estado == "OK":
            listas += 1

    return {
        "data": data,
        "total": len(data),
        "listas": listas,
        "porcentaje": round(listas / max(len(data), 1) * 100)
    }


def _query_cards(client, job_config, where_ejecuciones):
    result = list(client.query(f"""
        SELECT
            COUNT(*) AS total,
            SUM(
                CASE
                    WHEN estado_produccion='OK' AND estado_prototipado='OK'
                    THEN 1 ELSE 0
                END
            ) AS ok,
            SUM(
                CASE
                    WHEN estado_produccion='ERROR' OR estado_prototipado='ERROR'
                    THEN 1 ELSE 0
                END
            ) AS error,
            COUNTIF(IFNULL(diferencias_detectadas, 0) > 0) AS diferencias
        FROM `monitor-migracion.migracion.ejecuciones`
        {where_ejecuciones}
    """, job_config=job_config).result())

    if result:
        row = result[0]
        return {
            "total": int(row.total or 0),
            "ok": int(row.ok or 0),
            "error": int(row.error or 0),
            "diferencias": round(int(row.diferencias or 0), 2)
        }
    return {"total": 0, "ok": 0, "error": 0, "diferencias": 0}


@main.route('/dashboard')
@login_required
def dashboard():
    client = get_bq_client()
    fecha = request.args.get('fecha')

    params = []
    where_procesos = ""
    where_ejecuciones = ""

    if fecha:
        where_procesos = "WHERE DATE(fecha) = @fecha"
        where_ejecuciones = "WHERE DATE(fecha_ejecucion) = @fecha"
        params.append(bigquery.ScalarQueryParameter("fecha", "DATE", fecha))

    job_config = bigquery.QueryJobConfig(query_parameters=params)

    # Las 5 queries se lanzan en paralelo
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            "pie":     executor.submit(_query_pie,     client, job_config, fecha),
            "barras":  executor.submit(_query_barras,  client, job_config, where_procesos),
            "lineas":  executor.submit(_query_lineas,  client, job_config, where_ejecuciones),
            "fuentes": executor.submit(_query_fuentes, client, fecha),
            "cards":   executor.submit(_query_cards,   client, job_config, where_ejecuciones),
        }
        results = {key: future.result() for key, future in futures.items()}

    return render_template(
        'dashboard.html',
        pie=results["pie"],
        barras=results["barras"],
        lineas=results["lineas"],
        fuentes=results["fuentes"],
        cards=results["cards"],
        ultima_actualizacion="Ahora"
    )


# ================= PROCESOS =================
def _query_procesos_lista(client, job_config, where_busqueda):
    results = client.query(f"""
        SELECT
            p.cod_proceso,
            p.nombre,
            p.tipo_proceso,
            e.periodo,
            e.fecha_ejecucion,
            e.duracion,
            e.registros_procesados,
            e.diferencias_detectadas,
            e.estado_produccion,
            e.estado_prototipado,
            e.mensaje_error_produccion,
            e.mensaje_error_prototipado,
            a.mensaje AS mensaje_error,
            p.ambiente
        FROM `monitor-migracion.migracion.procesos` AS p
        LEFT JOIN `monitor-migracion.migracion.ejecuciones` AS e
            ON p.id_proceso = e.id_proceso
        LEFT JOIN `monitor-migracion.migracion.alertas` AS a
            ON e.id_ejecucion = a.id_ejecucion
        {where_busqueda}
        QUALIFY ROW_NUMBER() OVER(
            PARTITION BY p.id_proceso
            ORDER BY e.fecha_ejecucion DESC, e.hora_inicio DESC
        ) = 1
        ORDER BY e.fecha_ejecucion IS NOT NULL
    """, job_config=job_config).result()

    return [{
        "codigo": row.cod_proceso,
        "nombre": row.nombre,
        "tipo": row.tipo_proceso,
        "periodo": row.periodo,
        "ultima_ejecucion": str(row.fecha_ejecucion) if row.fecha_ejecucion else "N/A",
        "duracion": row.duracion or "00:00:00",
        "registros": row.registros_procesados or 0,
        "diferencias": row.diferencias_detectadas or 0,
        "estado_produccion": row.estado_produccion or "PENDIENTE",
        "estado_prototipado": row.estado_prototipado or "PENDIENTE",
        "mensaje_error_produccion": row.mensaje_error_produccion or "Sin detalle",
        "mensaje_error_prototipado": row.mensaje_error_prototipado or "Sin detalle",
        "mensaje_error": row.mensaje_error or "Sin detalle",
        "ambiente": row.ambiente,
    } for row in results]


def _query_procesos_cards(client):
    result = list(client.query("""
        SELECT
            COUNT(*) AS total,
            SUM(
                CASE
                    WHEN estado_produccion = 'OK' AND estado_prototipado = 'OK'
                    THEN 1 ELSE 0
                END
            ) AS ok,
            SUM(
                CASE
                    WHEN estado_produccion = 'ERROR' OR estado_prototipado = 'ERROR'
                    THEN 1 ELSE 0
                END
            ) AS error,
            COUNTIF(IFNULL(diferencias_detectadas, 0) > 0) AS diferencias
        FROM (
            SELECT
                p.id_proceso,
                e.estado_produccion,
                e.estado_prototipado,
                e.diferencias_detectadas
            FROM `monitor-migracion.migracion.procesos` p
            LEFT JOIN `monitor-migracion.migracion.ejecuciones` e
                ON p.id_proceso = e.id_proceso
            QUALIFY ROW_NUMBER() OVER(
                PARTITION BY p.id_proceso
                ORDER BY e.fecha_ejecucion DESC, e.hora_inicio DESC
            ) = 1
        )
    """).result())[0]

    return {
        "total": result.total or 0,
        "ok": result.ok or 0,
        "error": result.error or 0,
        "diferencias": result.diferencias or 0
    }


@main.route('/procesos')
@login_required
def procesos():
    client = get_bq_client()

    busqueda = request.args.get("busqueda", "").strip()
    lista_busqueda = [b.strip().lower() for b in busqueda.split(",") if b.strip()]

    params = []
    where_busqueda = ""

    if lista_busqueda:
        condiciones = []
        for i, val in enumerate(lista_busqueda):
            condiciones.append(f"""
                (
                    LOWER(p.nombre) LIKE @b{i}
                    OR LOWER(p.cod_proceso) LIKE @b{i}
                )
            """)
            params.append(bigquery.ScalarQueryParameter(f"b{i}", "STRING", f"%{val}%"))

        where_busqueda = "WHERE (" + " OR ".join(condiciones) + ")"

    job_config = bigquery.QueryJobConfig(query_parameters=params)

    with ThreadPoolExecutor(max_workers=2) as executor:
        f_lista = executor.submit(_query_procesos_lista, client, job_config, where_busqueda)
        f_cards = executor.submit(_query_procesos_cards, client)
        procesos = f_lista.result()
        cards = f_cards.result()

    return render_template("procesos.html", procesos=procesos, cards=cards)


# ================= EXPORTAR PROCESOS =================
@main.route("/procesos/exportar")
@login_required
def exportar_procesos():
    client = get_bq_client()

    busqueda = request.args.get("busqueda", "").strip()
    lista_busqueda = [b.strip().lower() for b in busqueda.split(",") if b.strip()]

    params = []
    where_busqueda = ""

    if lista_busqueda:
        condiciones = []
        for i, val in enumerate(lista_busqueda):
            condiciones.append(f"""
                (
                    LOWER(p.nombre) LIKE @b{i}
                    OR LOWER(p.cod_proceso) LIKE @b{i}
                )
            """)
            params.append(bigquery.ScalarQueryParameter(f"b{i}", "STRING", f"%{val}%"))

        where_busqueda = "WHERE (" + " OR ".join(condiciones) + ")"

    job_config = bigquery.QueryJobConfig(query_parameters=params)

    query = f"""
        SELECT
            p.cod_proceso,
            p.nombre,
            e.periodo,
            e.fecha_ejecucion,
            e.registros_procesados,
            e.diferencias_detectadas,
            e.estado_produccion,
            e.estado_prototipado
        FROM `monitor-migracion.migracion.procesos` p
        LEFT JOIN `monitor-migracion.migracion.ejecuciones` e
            ON p.id_proceso = e.id_proceso
        {where_busqueda}
        QUALIFY ROW_NUMBER() OVER(
            PARTITION BY p.id_proceso
            ORDER BY e.fecha_ejecucion DESC
        ) = 1
    """

    results = client.query(query, job_config=job_config).result()

    rows = []
    for r in results:
        registros = r.registros_procesados or 0
        diferencias = r.diferencias_detectadas or 0
        rows.append({
            "CÓDIGO": r.cod_proceso,
            "PERIODO": r.periodo,
            "ÚLTIMA EJECUCIÓN": str(r.fecha_ejecucion),
            "SALDO PROTOTIPADO": registros,
            "SALDO PRODUCCIÓN": registros - diferencias,
            "DIFERENCIA": diferencias,
            "ALERTAS": "⚠" if diferencias > 0 else "",
            "ESTADO PRODUCCIÓN": r.estado_produccion,
            "ESTADO PROTOTIPADO": r.estado_prototipado
        })

    df = pd.DataFrame(rows)
    output = BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Procesos")

    output.seek(0)

    return Response(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=procesos.xlsx"}
    )


# ================= ESTADO DE FUENTES =================
@main.route("/estado_fuentes")
@login_required
def estado_fuentes():
    client = get_bq_client()
    
    page = request.args.get("page", 1, type=int)
    per_page = 10
    offset = (page - 1) * per_page

    q = request.args.get("q")

    where = ""
    params = []

    if q:
        where = "WHERE nombre = @q"
        params.append(bigquery.ScalarQueryParameter("q", "STRING", q))

    query = f"""
    SELECT nombre, cantidad_registros, estado, fecha
    FROM `monitor-migracion.migracion.fuentes`
    {where}
    ORDER BY nombre
    LIMIT {per_page}
    OFFSET {offset}
    """

    job_config = bigquery.QueryJobConfig(query_parameters=params)

    results = list(client.query(query, job_config=job_config).result())
    
    total_query = list(client.query("""
    SELECT COUNT(*) AS total
    FROM `monitor-migracion.migracion.fuentes`
    """).result())

    total_registros = total_query[0].total

    all_fuentes = list(client.query("""
    SELECT DISTINCT nombre
    FROM `monitor-migracion.migracion.fuentes`
    ORDER BY nombre
    """).result())

    nombres_fuentes = [row.nombre for row in all_fuentes]

    q = request.args.get("q")
    if q:
        results = [row for row in results if row.nombre == q]

    fuentes = []
    listas = 0

    for row in results:
        estado = "Lista" if row.estado == "OK" else "No Lista"
        fuentes.append({
            "nombre": row.nombre,
            "cantidad": row.cantidad_registros,
            "estado": estado,
            "raw_estado": row.estado,
            "fecha": row.fecha
        })
        if row.estado == "OK":
            listas += 1

    total = total_registros
    pendientes = total - listas

    return render_template(
    "estado_fuentes.html",
    fuentes=fuentes,
    nombres_fuentes=nombres_fuentes,
    total=total,
    listas=listas,
    pendientes=pendientes,
    page=page,
    per_page=per_page,
    ultima_actualizacion="Hace unos minutos"
    )   


# ================= CONSULTAS =================
def _query_consultas_count(client, job_config, where):
    result = list(client.query(f"""
        SELECT COUNT(*) as total
        FROM `monitor-migracion.migracion.ejecuciones` e
        LEFT JOIN `monitor-migracion.migracion.procesos` p
            ON e.id_proceso = p.id_proceso
        {where}
    """, job_config=job_config).result())
    return result[0].total


def _query_consultas_data(client, job_config, where, per_page, offset):
    results = client.query(f"""
        SELECT
            e.id_ejecucion,
            p.cod_proceso,
            p.nombre,
            e.periodo,
            e.fecha_ejecucion,
            e.registros_procesados,
            e.suma_conciliados,
            e.suma_no_conciliados,
            e.ambiente_ejecucion,
            e.estado_produccion,
            e.estado_prototipado,
            p.usuario_responsable,
            p.ambiente,
            a.mensaje AS mensaje_error
        FROM `monitor-migracion.migracion.ejecuciones` e
        LEFT JOIN `monitor-migracion.migracion.procesos` p
            ON e.id_proceso = p.id_proceso
        LEFT JOIN (
            SELECT id_ejecucion, ANY_VALUE(mensaje) AS mensaje
            FROM `monitor-migracion.migracion.alertas`
            GROUP BY id_ejecucion
        ) a ON e.id_ejecucion = a.id_ejecucion
        {where}
        ORDER BY e.fecha_ejecucion DESC
        LIMIT {per_page} OFFSET {offset}
    """, job_config=job_config).result()

    data = []
    ok = 0
    errores_count = 0

    for row in results:
        estado_fila = (
            "OK"
            if row.estado_produccion == "OK" and row.estado_prototipado == "OK"
            else "ERROR"
        )

        if estado_fila == "OK":
            ok += 1
        else:
            errores_count += 1

        data.append({
            "codigo": row.cod_proceso,
            "nombre": row.nombre,
            "periodo": row.periodo,
            "fecha": row.fecha_ejecucion.strftime("%Y-%m-%d %H:%M") if row.fecha_ejecucion else None,
            "registros": row.registros_procesados or 0,
            "conciliados": row.suma_conciliados or 0,
            "no_conciliados": row.suma_no_conciliados or 0,
            "ambiente": row.ambiente_ejecucion or row.ambiente,
            "responsable": row.usuario_responsable,
            "estado": estado_fila,
            "mensaje_error": row.mensaje_error or "Sin detalle disponible"
        })

    return data, ok, errores_count


@main.route("/consultas", methods=["GET"])
@login_required
def consultas():
    client = get_bq_client()

    proceso = request.args.get("proceso")
    periodo = request.args.get("periodo")
    estado = request.args.get("estado")
    ambiente = request.args.get("ambiente")
    responsable = request.args.get("responsable")

    filtros = []
    params = []

    if proceso:
        filtros.append("p.cod_proceso = @proceso")
        params.append(bigquery.ScalarQueryParameter("proceso", "STRING", proceso))

    if periodo:
        filtros.append("DATE(e.periodo) = @periodo")
        params.append(bigquery.ScalarQueryParameter("periodo", "DATE", periodo))

    if ambiente:
        filtros.append("e.ambiente_ejecucion = @ambiente")
        params.append(bigquery.ScalarQueryParameter("ambiente", "STRING", ambiente))

    if responsable:
        filtros.append("p.usuario_responsable LIKE @responsable")
        params.append(bigquery.ScalarQueryParameter("responsable", "STRING", f"%{responsable}%"))

    if estado:
        if estado == "OK":
            filtros.append("e.estado_produccion = 'OK' AND e.estado_prototipado = 'OK'")
        elif estado == "ERROR":
            filtros.append("e.estado_produccion != 'OK' OR e.estado_prototipado != 'OK'")

    where = "WHERE " + " AND ".join(f"({f})" for f in filtros) if filtros else ""

    page = request.args.get("page", 1, type=int)
    per_page = 10
    offset = (page - 1) * per_page

    job_config = bigquery.QueryJobConfig(query_parameters=params)

    with ThreadPoolExecutor(max_workers=2) as executor:
        f_total = executor.submit(_query_consultas_count, client, job_config, where)
        f_data  = executor.submit(_query_consultas_data,  client, job_config, where, per_page, offset)
        total = f_total.result()
        data, ok, errores_count = f_data.result()

    porcentaje_ok = round(ok / max(len(data), 1) * 100)

    return render_template(
        "consultas.html",
        data=data,
        total=total,
        ok=ok,
        error=errores_count,
        porcentaje_ok=porcentaje_ok,
        page=page,
        per_page=per_page
    )


# ================= USUARIOS =================
@main.route('/usuarios')
@login_required
@admin_required
def usuarios():
    busqueda = request.args.get("busqueda", "").strip()

    cur = current_app.mysql.connection.cursor()

    if busqueda:
        cur.execute("""
            SELECT id_usuario, nombre, correo, rol_usuario, fecha_registro, estado
            FROM usuarios
            WHERE nombre LIKE %s OR correo LIKE %s
        """, (f"%{busqueda}%", f"%{busqueda}%"))
    else:
        cur.execute("""
            SELECT id_usuario, nombre, correo, rol_usuario, fecha_registro, estado
            FROM usuarios
        """)

    data = cur.fetchall()
    cur.close()

    total = len(data)
    activos = sum(1 for u in data if u[5] == 'activo')
    inactivos = total - activos

    cards = {"total": total, "activos": activos, "inactivos": inactivos}

    return render_template('usuarios.html', usuarios=data, cards=cards, busqueda=busqueda)

@main.route('/usuarios/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_usuario(id):

    cur = current_app.mysql.connection.cursor()

    if request.method == 'POST':

        nombre = request.form['nombre']
        correo = request.form['correo']
        rol = request.form['rol']
        estado = request.form['estado']

        cur.execute("""
            UPDATE usuarios
            SET nombre=%s,
                correo=%s,
                rol_usuario=%s,
                estado=%s
            WHERE id_usuario=%s
        """, (nombre, correo, rol, estado, id))

        current_app.mysql.connection.commit()
        cur.close()

        flash("Usuario actualizado correctamente", "success")
        return redirect(url_for('main.usuarios'))

    cur.execute("""
        SELECT id_usuario, nombre, correo, rol_usuario, estado
        FROM usuarios
        WHERE id_usuario = %s
    """, (id,))

    usuario = cur.fetchone()
    cur.close()

    return render_template("editar_usuario.html", usuario=usuario)

@main.route('/usuarios/rol/<int:id>', methods=['POST'])
@login_required
@admin_required
def cambiar_rol(id):
    nuevo_rol = request.form.get("rol")

    cur = current_app.mysql.connection.cursor()
    cur.execute("""
        UPDATE usuarios SET rol_usuario = %s WHERE id_usuario = %s
    """, (nuevo_rol, id))
    current_app.mysql.connection.commit()
    cur.close()

    return redirect(url_for('main.usuarios'))


@main.route('/usuarios/estado/<int:id>', methods=['POST'])
@login_required
@admin_required
def cambiar_estado(id):
    nuevo_estado = request.form.get("estado")

    cur = current_app.mysql.connection.cursor()
    cur.execute("""
        UPDATE usuarios SET estado = %s WHERE id_usuario = %s
    """, (nuevo_estado, id))
    current_app.mysql.connection.commit()
    cur.close()

    return redirect(url_for('main.usuarios'))


@main.route('/usuarios/eliminar/<int:id>', methods=['POST'])
@login_required
@admin_required
def eliminar_usuario(id):

    cur = current_app.mysql.connection.cursor()

    cur.execute("""
        UPDATE usuarios
        SET estado = 'inactivo'
        WHERE id_usuario = %s
    """, (id,))

    current_app.mysql.connection.commit()
    cur.close()

    flash("Usuario desactivado correctamente", "success")
    return redirect(url_for('main.usuarios'))

# ================= SESIONES =================
@main.route('/sesiones')
@login_required
@admin_required
def sesiones():
    cur = current_app.mysql.connection.cursor()

    busqueda = request.args.get("busqueda", "").strip()
    estado = request.args.get("estado", "").strip()
    fecha = request.args.get("fecha", "").strip()

    filtros = []
    params = []

    if busqueda:
        filtros.append("(u.nombre LIKE %s OR s.id_usuario = %s)")
        params.append(f"%{busqueda}%")
        params.append(busqueda)

    if fecha:
        filtros.append("DATE(s.fecha_inicio) = %s")
        params.append(fecha)

    if estado:
        if estado.lower() == "activo":
            filtros.append("(s.fecha_fin IS NULL)")
        elif estado.lower() == "finalizado":
            filtros.append("(s.fecha_fin IS NOT NULL)")

    where = "WHERE " + " AND ".join(filtros) if filtros else ""

    query = f"""
        SELECT
            s.id_sesion,
            s.id_usuario,
            u.nombre,
            s.fecha_inicio,
            s.fecha_fin,
            s.ip_usuario,
            s.estado
        FROM sesiones s
        LEFT JOIN usuarios u ON s.id_usuario = u.id_usuario
        {where}
        ORDER BY s.fecha_inicio DESC
        LIMIT 100
    """

    cur.execute(query, params)
    rows = cur.fetchall()
    cur.close()

    data = []
    for r in rows:
        data.append({
            "id_sesion": r[0],
            "id_usuario": r[1],
            "nombre": r[2] or "Usuario",
            "fecha": r[3],
            "fecha_fin": r[4],
            "ip": r[5] or "—",
            "estado": (r[6] or "inactivo").lower()
        })

    sesiones_activas = sum(
        1 for s in data if not s["fecha_fin"] or str(s["fecha_fin"]).startswith("0000")
    )

    for s in data:
        nombre = s["nombre"] or "Usuario"
        partes = nombre.split()
        s["iniciales"] = "".join([p[0] for p in partes[:2]]).upper()

    return render_template("sesiones.html", sesiones=data, sesiones_activas=sesiones_activas)


# ================= EXPORTAR SESIONES =================
@main.route("/sesiones/exportar")
@login_required
@admin_required
def exportar_sesiones():
    cur = current_app.mysql.connection.cursor()

    busqueda = request.args.get("busqueda", "").strip()
    estado = request.args.get("estado", "").strip()
    fecha = request.args.get("fecha", "").strip()

    filtros = []
    params = []

    if busqueda:
        filtros.append("(u.nombre LIKE %s OR s.id_usuario = %s)")
        params.append(f"%{busqueda}%")
        params.append(busqueda)

    if fecha:
        filtros.append("DATE(s.fecha_inicio) = %s")
        params.append(fecha)

    if estado:
        if estado.lower() == "activo":
            filtros.append("s.fecha_fin IS NULL")
        elif estado.lower() == "finalizado":
            filtros.append("s.fecha_fin IS NOT NULL")

    where = "WHERE " + " AND ".join(filtros) if filtros else ""

    query = f"""
        SELECT
            s.id_sesion,
            u.nombre,
            s.fecha_inicio,
            s.fecha_fin,
            s.ip_usuario,
            s.estado
        FROM sesiones s
        LEFT JOIN usuarios u ON s.id_usuario = u.id_usuario
        {where}
        ORDER BY s.fecha_inicio DESC
    """

    cur.execute(query, params)
    data = cur.fetchall()
    cur.close()

    rows = []
    for r in data:
        fecha_fin = r[3]
        estado_fila = "Activo" if not fecha_fin or str(fecha_fin).startswith("0000") else "Finalizado"
        rows.append({
            "ID SESION": r[0],
            "USUARIO": r[1],
            "FECHA INICIO": r[2],
            "FECHA FIN": r[3],
            "IP": r[4],
            "ESTADO": estado_fila
        })

    df = pd.DataFrame(rows)
    output = BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Sesiones")

    output.seek(0)

    return Response(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=sesiones.xlsx"}
    )


# ================= RECUPERAR (main blueprint) =================
@main.route("/recuperar", methods=["GET", "POST"])
def recuperar():
    if request.method == "POST":
        correo = request.form["correo"]

        cur = current_app.mysql.connection.cursor()
        cur.execute("SELECT id_usuario FROM usuarios WHERE correo = %s", (correo,))
        user = cur.fetchone()
        cur.close()

        if not user:
            flash("❌ El correo no está registrado", "error")
            return redirect(url_for("main.recuperar"))

        msg = Message(
            subject="Recuperación de contraseña",
            sender=current_app.config["MAIL_USERNAME"],
            recipients=[correo],
            body="Este es tu enlace de recuperación"
        )
        mail.send(msg)

        flash("✅ Correo enviado correctamente", "success")
        return redirect(url_for("main.recuperar"))

    return render_template("recuperar.html")