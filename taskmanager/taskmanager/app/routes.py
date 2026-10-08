from datetime import date
from functools import wraps

from flask import (Blueprint, current_app, flash, jsonify, redirect,
                   render_template, request, session, url_for)
from sqlalchemy import text

from .models import Task, User, db

bp = Blueprint("main", __name__)
VALID_STATUS = {"todo", "in_progress", "done"}


@bp.app_context_processor
def inject_version():
    return {"version": current_app.config["APP_VERSION"]}


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            if request.path.startswith("/api/"):
                return jsonify(error="authentication required"), 401
            return redirect(url_for("main.login"))
        return f(*args, **kwargs)
    return wrapper


# ---------- health ----------
@bp.get("/health")
def health():
    try:
        db.session.execute(text("SELECT 1"))
        return jsonify(status="ok", version=current_app.config["APP_VERSION"])
    except Exception as e:
        current_app.logger.error("Health check failed: %s", e)
        return jsonify(status="unhealthy"), 503


# ---------- auth helpers ----------
def _register(username, password):
    username = (username or "").strip()
    if not username or not password or len(password) < 6:
        return None, "username and password (min 6 chars) are required"
    if User.query.filter_by(username=username).first():
        return None, "username already taken"
    user = User(username=username)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    current_app.logger.info("User registered: %s", username)
    return user, None


def _authenticate(username, password):
    user = User.query.filter_by(username=(username or "").strip()).first()
    if user and user.check_password(password or ""):
        session["user_id"] = user.id
        return user
    current_app.logger.warning("Failed login for: %s", username)
    return None


# ---------- auth: REST ----------
@bp.post("/api/auth/register")
def api_register():
    data = request.get_json(silent=True) or {}
    user, err = _register(data.get("username"), data.get("password"))
    if err:
        return jsonify(error=err), 400
    return jsonify(id=user.id, username=user.username), 201


@bp.post("/api/auth/login")
def api_login():
    data = request.get_json(silent=True) or {}
    user = _authenticate(data.get("username"), data.get("password"))
    if not user:
        return jsonify(error="invalid credentials"), 401
    return jsonify(message="logged in", username=user.username)


@bp.post("/api/auth/logout")
def api_logout():
    session.clear()
    return jsonify(message="logged out")


# ---------- tasks: REST ----------
def _apply(task, data, creating):
    if creating or "title" in data:
        title = (data.get("title") or "").strip()
        if not title:
            raise ValueError("title is required")
        task.title = title
    if "description" in data:
        task.description = data["description"] or ""
    if "status" in data:
        if data["status"] not in VALID_STATUS:
            raise ValueError("status must be one of: " + ", ".join(sorted(VALID_STATUS)))
        task.status = data["status"]
    if "due_date" in data:
        task.due_date = date.fromisoformat(data["due_date"]) if data["due_date"] else None


def _own_task(task_id):
    return Task.query.filter_by(id=task_id, user_id=session["user_id"]).first()


@bp.get("/api/tasks")
@login_required
def list_tasks():
    q = Task.query.filter_by(user_id=session["user_id"])
    status = request.args.get("status")
    if status:
        q = q.filter_by(status=status)
    return jsonify([t.to_dict() for t in q.order_by(Task.id).all()])


@bp.post("/api/tasks")
@login_required
def create_task():
    data = request.get_json(silent=True) or {}
    task = Task(user_id=session["user_id"])
    try:
        _apply(task, data, creating=True)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    db.session.add(task)
    db.session.commit()
    return jsonify(task.to_dict()), 201


@bp.get("/api/tasks/<int:task_id>")
@login_required
def get_task(task_id):
    task = _own_task(task_id)
    if not task:
        return jsonify(error="task not found"), 404
    return jsonify(task.to_dict())


@bp.put("/api/tasks/<int:task_id>")
@login_required
def update_task(task_id):
    task = _own_task(task_id)
    if not task:
        return jsonify(error="task not found"), 404
    try:
        _apply(task, request.get_json(silent=True) or {}, creating=False)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    db.session.commit()
    return jsonify(task.to_dict())


@bp.delete("/api/tasks/<int:task_id>")
@login_required
def delete_task(task_id):
    task = _own_task(task_id)
    if not task:
        return jsonify(error="task not found"), 404
    db.session.delete(task)
    db.session.commit()
    return "", 204


# ---------- web UI ----------
@bp.get("/")
def index():
    return redirect(url_for("main.tasks_page" if "user_id" in session else "main.login"))


@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        user, err = _register(request.form.get("username"), request.form.get("password"))
        if err:
            flash(err, "danger")
        else:
            flash("Account created. Please log in.", "success")
            return redirect(url_for("main.login"))
    return render_template("register.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if _authenticate(request.form.get("username"), request.form.get("password")):
            return redirect(url_for("main.tasks_page"))
        flash("Invalid username or password", "danger")
    return render_template("login.html")


@bp.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("main.login"))


@bp.route("/tasks", methods=["GET", "POST"])
@login_required
def tasks_page():
    if request.method == "POST":
        task = Task(user_id=session["user_id"])
        try:
            _apply(task, request.form.to_dict(), creating=True)
            db.session.add(task)
            db.session.commit()
        except ValueError as e:
            flash(str(e), "danger")
        return redirect(url_for("main.tasks_page"))
    tasks = Task.query.filter_by(user_id=session["user_id"]).order_by(Task.id.desc()).all()
    return render_template("tasks.html", tasks=tasks)


@bp.post("/tasks/<int:task_id>/toggle")
@login_required
def toggle_task(task_id):
    task = _own_task(task_id)
    if task:
        task.status = "todo" if task.status == "done" else "done"
        db.session.commit()
    return redirect(url_for("main.tasks_page"))


@bp.post("/tasks/<int:task_id>/delete")
@login_required
def delete_task_web(task_id):
    task = _own_task(task_id)
    if task:
        db.session.delete(task)
        db.session.commit()
    return redirect(url_for("main.tasks_page"))
