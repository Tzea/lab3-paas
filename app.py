"""Lab 03 - Ung dung quan ly nguoi dung (Flask) chay tren Render (PaaS).

- Co bien moi truong DATABASE_URL -> ket noi Neon PostgreSQL (sslmode=require).
- Co bien moi truong DB_HOST       -> ket noi MySQL (co ma hoa SSL/TLS).
- Khong co DB_HOST        -> dung SQLite tam trong /tmp (deploy lan 1, du lieu mat khi
  instance bi thay the).
"""
import hashlib
import os
import socket
import tempfile
import time

from flask import Flask, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import (Column, DateTime, Integer, MetaData, String, Table,
                        create_engine, delete, func, insert, select, text, update)
from sqlalchemy.engine import URL

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-doi-khi-deploy")

# ---------------------------------------------------------------- Ket noi CSDL
DB_HOST = os.environ.get("DB_HOST", "").strip()
DB_PORT = int(os.environ.get("DB_PORT", "3306"))
DB_USER = os.environ.get("DB_USER", "lab3admin")
DB_PASS = os.environ.get("DB_PASS", "")
DB_NAME = os.environ.get("DB_NAME", "lab3db")


DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()


def make_engine():
    if DATABASE_URL:
        url = DATABASE_URL
        # Neon cho chuoi dang postgresql://... -> dung driver psycopg (v3)
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        if url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        engine = create_engine(url, pool_size=5, max_overflow=2, pool_recycle=300,
                               pool_pre_ping=True)
        return engine, "Neon PostgreSQL"

    if DB_HOST:
        url = URL.create("mysql+pymysql", username=DB_USER, password=DB_PASS,
                         host=DB_HOST, port=DB_PORT, database=DB_NAME,
                         query={"charset": "utf8mb4"})
        engine = create_engine(url, pool_size=5, max_overflow=2, pool_timeout=30,
                               pool_recycle=1800, pool_pre_ping=True,
                               connect_args={"ssl": {"check_hostname": False},
                                             "connect_timeout": 10})
        return engine, "MySQL"

    path = os.path.join(tempfile.gettempdir(), "lab3.db")
    return create_engine(f"sqlite:///{path}"), "SQLite tạm"


engine, DB_LABEL = make_engine()
metadata = MetaData()
users = Table(
    "users", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("full_name", String(100), nullable=False),
    Column("email", String(120), nullable=False),
    Column("phone", String(20)),
    Column("created_at", DateTime, server_default=func.now()),
)

_db_ready = False


def ensure_db():
    """Tao bang users neu chua co (chay 1 lan moi instance)."""
    global _db_ready
    if not _db_ready:
        metadata.create_all(engine)
        _db_ready = True


def instance_id():
    # Moi instance co ID rieng (Render: RENDER_INSTANCE_ID)
    inst = os.environ.get("RENDER_INSTANCE_ID") or os.environ.get("WEBSITE_INSTANCE_ID")
    return inst[-12:] if inst else socket.gethostname().split(".")[0]


@app.context_processor
def inject_globals():
    return {"db_label": DB_LABEL, "instance_id": instance_id(),
            "db_host": (DATABASE_URL.split("@")[-1].split("/")[0] if DATABASE_URL else DB_HOST) or "(cục bộ)"}


# ---------------------------------------------------------------- Tuong lua tang ung dung
# Bien moi truong DENY_IPS: danh sach IP bi chan, cach nhau dau phay; "*" = chan tat ca.
@app.before_request
def app_firewall():
    deny = [x.strip() for x in os.environ.get("DENY_IPS", "").split(",") if x.strip()]
    if not deny:
        return None
    fwd = request.headers.get("X-Forwarded-For", request.remote_addr or "")
    client_ip = fwd.split(",")[0].strip()
    if "*" in deny or client_ip in deny:
        return (f"<h1>403 Forbidden</h1><p>Địa chỉ IP {client_ip} bị chặn bởi "
                f"tường lửa ứng dụng (DENY_IPS).</p>", 403)
    return None


# ---------------------------------------------------------------- CRUD
@app.route("/")
def index():
    ensure_db()
    with engine.connect() as conn:
        rows = conn.execute(select(users).order_by(users.c.id)).mappings().all()
    return render_template("index.html", users=rows)


@app.route("/users", methods=["POST"])
def create_user():
    ensure_db()
    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip()
    phone = request.form.get("phone", "").strip()
    if not full_name or not email:
        flash("Vui lòng nhập họ tên và email.", "error")
        return redirect(url_for("index"))
    with engine.begin() as conn:
        conn.execute(insert(users).values(full_name=full_name, email=email, phone=phone))
    flash(f"Đã thêm người dùng: {full_name}", "success")
    return redirect(url_for("index"))


@app.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
def edit_user(user_id):
    ensure_db()
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()
        if not full_name or not email:
            flash("Vui lòng nhập họ tên và email.", "error")
            return redirect(url_for("edit_user", user_id=user_id))
        with engine.begin() as conn:
            conn.execute(update(users).where(users.c.id == user_id)
                         .values(full_name=full_name, email=email, phone=phone))
        flash(f"Đã cập nhật người dùng #{user_id}", "success")
        return redirect(url_for("index"))

    with engine.connect() as conn:
        row = conn.execute(select(users).where(users.c.id == user_id)).mappings().first()
    if row is None:
        abort(404)
    return render_template("edit.html", user=row)


@app.route("/users/<int:user_id>/delete", methods=["POST"])
def delete_user(user_id):
    ensure_db()
    with engine.begin() as conn:
        conn.execute(delete(users).where(users.c.id == user_id))
    flash(f"Đã xoá người dùng #{user_id}", "success")
    return redirect(url_for("index"))


# ---------------------------------------------------------------- Kiem tra / thu tai
@app.route("/health")
def health():
    """Kiem tra ung dung song - khong truy cap CSDL."""
    return {"status": "ok", "instance": instance_id()}


@app.route("/dbinfo")
def dbinfo():
    """Minh chung ket noi CSDL: phien ban, may chu, so ban ghi, trang thai SSL."""
    ensure_db()
    host = DATABASE_URL.split("@")[-1].split("/")[0] if DATABASE_URL else (DB_HOST or "(sqlite)")
    info = {"db": DB_LABEL, "host": host, "instance": instance_id()}
    with engine.connect() as conn:
        info["rows_in_users"] = conn.execute(select(func.count()).select_from(users)).scalar()
        if DATABASE_URL:
            info["postgres_version"] = conn.execute(text("SELECT version()")).scalar()
            info["database"] = conn.execute(text("SELECT current_database()")).scalar()
            info["ssl"] = conn.execute(text(
                "SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()")).scalar()
        elif DB_HOST:
            info["mysql_version"] = conn.execute(text("SELECT VERSION()")).scalar()
            info["database"] = conn.execute(text("SELECT DATABASE()")).scalar()
            row = conn.execute(text("SHOW SESSION STATUS LIKE 'Ssl_cipher'")).first()
            info["ssl_cipher"] = row[1] if row else ""
    return info


@app.route("/stress")
def stress():
    """Ton CPU khoang `ms` mili-giay de kiem tra auto-scaling (toi da 1000 ms)."""
    ms = min(int(request.args.get("ms", 300)), 1000)
    end = time.time() + ms / 1000
    h = b"lab3"
    while time.time() < end:
        h = hashlib.sha256(h).digest()
    return {"instance": instance_id(), "ms": ms}


if __name__ == "__main__":
    # Chay thu tren may: python app.py  ->  http://127.0.0.1:8080
    app.run(host="127.0.0.1", port=8080, debug=True)
