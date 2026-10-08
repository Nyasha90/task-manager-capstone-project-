from datetime import date, timedelta
from functools import wraps

from flask import (Blueprint, current_app, flash, jsonify, redirect,
                   render_template, request, session, url_for)
from sqlalchemy import text

from .models import Task, User, db

bp = Blueprint("main", __name__)
VALID_STATUS = {"todo", "in_progress", "done"}
VALID_PRIORITY = {"high", "medium", "low"}


@bp.app_context_processor
def inject_version():
    user = None
    if "user_id" in session:
        user = db.session.get(User, session["user_id"])
    return {
        "version": current_app.config["APP_VERSION"],
        "current_user": user
    }


def seed_sample_tasks(user_id):
    """Seed a realistic initial dataset of tasks for the specified user."""
    today = date.today()
    sample_data = [
        {
            "title": "Deploy Kubernetes Cluster on AWS EKS",
            "description": "Provision EKS cluster using Terraform, configure VPC, subnets, and worker node groups for production workload.",
            "status": "in_progress",
            "priority": "high",
            "category": "DevOps",
            "due_date": today + timedelta(days=3)
        },
        {
            "title": "Configure CI/CD Pipeline in Jenkins",
            "description": "Setup Jenkins multibranch pipeline with automated unit testing, SonarQube quality gate, and Docker image build.",
            "status": "done",
            "priority": "high",
            "category": "CI/CD",
            "due_date": today - timedelta(days=1)
        },
        {
            "title": "Implement Session & Token Security",
            "description": "Audit authentication routes, add password hashing, session timeout, and RBAC middleware.",
            "status": "done",
            "priority": "high",
            "category": "Security",
            "due_date": today - timedelta(days=2)
        },
        {
            "title": "Setup Prometheus & Grafana Monitoring",
            "description": "Export app /metrics endpoint, configure Prometheus scrapers, and build Grafana dashboards for latency & error rate.",
            "status": "in_progress",
            "priority": "medium",
            "category": "Monitoring",
            "due_date": today + timedelta(days=5)
        },
        {
            "title": "Configure ELK Stack Log Aggregation",
            "description": "Setup Logstash & Elasticsearch pipeline to ingest and parse structured JSON application logs.",
            "status": "todo",
            "priority": "medium",
            "category": "Logging",
            "due_date": today + timedelta(days=7)
        },
        {
            "title": "Redesign Dark Mode UI & Glassmorphism Dashboard",
            "description": "Enhance user experience with modern dark theme palette, stats panel, filter bar, and interactive task cards.",
            "status": "done",
            "priority": "low",
            "category": "Frontend",
            "due_date": today
        },
        {
            "title": "Database Migration & Connection Pooling",
            "description": "Provision PostgreSQL database container, execute Alembic migrations, and configure SQLAlchemy connection pools.",
            "status": "todo",
            "priority": "high",
            "category": "Database",
            "due_date": today + timedelta(days=10)
        },
        {
            "title": "ArgoCD GitOps Deployment Setup",
            "description": "Connect ArgoCD to GitHub repository and configure automated sync policies for Kubernetes manifests.",
            "status": "todo",
            "priority": "low",
            "category": "DevOps",
            "due_date": today + timedelta(days=12)
        }
    ]

    for item in sample_data:
        task = Task(
            user_id=user_id,
            title=item["title"],
            description=item["description"],
            status=item["status"],
            priority=item["priority"],
            category=item["category"],
            due_date=item["due_date"]
        )
        db.session.add(task)
    db.session.commit()



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
def _register(username, password, auto_seed=True):
    username = (username or "").strip()
    if not username or not password or len(password) < 6:
        return None, "username and password (min 6 chars) are required"
    if User.query.filter_by(username=username).first():
        return None, "username already taken"
    user = User(username=username)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    if auto_seed:
        try:
            seed_sample_tasks(user.id)
        except Exception as ex:
            current_app.logger.warning("Failed to auto seed tasks: %s", ex)

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
    user, err = _register(data.get("username"), data.get("password"), auto_seed=False)
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
        task.description = data.get("description") or ""
    if "status" in data and data["status"]:
        if data["status"] not in VALID_STATUS:
            raise ValueError("status must be one of: " + ", ".join(sorted(VALID_STATUS)))
        task.status = data["status"]
    if "priority" in data and data["priority"]:
        if data["priority"] not in VALID_PRIORITY:
            raise ValueError("priority must be one of: " + ", ".join(sorted(VALID_PRIORITY)))
        task.priority = data["priority"]
    if "category" in data and data["category"]:
        task.category = data["category"].strip() or "General"
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
        user, err = _register(request.form.get("username"), request.form.get("password"), auto_seed=True)
        if err:
            flash(err, "danger")
        else:
            flash("Account created! Sample dataset loaded. Please log in.", "success")
            return redirect(url_for("main.login"))
    return render_template("register.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if _authenticate(request.form.get("username"), request.form.get("password")):
            return redirect(url_for("main.tasks_page"))
        flash("Invalid username or password", "danger")
    return render_template("login.html")


@bp.route("/login/demo", methods=["GET", "POST"])
def login_demo():
    admin = User.query.filter_by(username="admin").first()
    if not admin:
        admin, _ = _register("admin", "password123", auto_seed=True)
    elif not Task.query.filter_by(user_id=admin.id).first():
        seed_sample_tasks(admin.id)
    session["user_id"] = admin.id
    flash("Logged in as Demo Admin", "success")
    return redirect(url_for("main.tasks_page"))


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
            flash("Task created successfully!", "success")
        except ValueError as e:
            flash(str(e), "danger")
        return redirect(url_for("main.tasks_page"))

    tasks = Task.query.filter_by(user_id=session["user_id"]).order_by(Task.id.desc()).all()
    
    total = len(tasks)
    done_count = sum(1 for t in tasks if t.status == "done")
    in_progress_count = sum(1 for t in tasks if t.status == "in_progress")
    todo_count = sum(1 for t in tasks if t.status == "todo")
    completion_rate = round((done_count / total * 100)) if total > 0 else 0

    stats = {
        "total": total,
        "done": done_count,
        "in_progress": in_progress_count,
        "todo": todo_count,
        "completion_rate": completion_rate
    }

    return render_template("tasks.html", tasks=tasks, stats=stats)


@bp.post("/tasks/seed")
@login_required
def seed_dataset_route():
    seed_sample_tasks(session["user_id"])
    flash("Sample dataset loaded successfully!", "success")
    return redirect(url_for("main.tasks_page"))


@bp.post("/tasks/<int:task_id>/toggle")
@login_required
def toggle_task(task_id):
    task = _own_task(task_id)
    if task:
        task.status = "todo" if task.status == "done" else "done"
        db.session.commit()
    return redirect(url_for("main.tasks_page"))


@bp.post("/tasks/<int:task_id>/update_status")
@login_required
def update_task_status(task_id):
    task = _own_task(task_id)
    new_status = request.form.get("status")
    if task and new_status in VALID_STATUS:
        task.status = new_status
        db.session.commit()
    return redirect(url_for("main.tasks_page"))


@bp.post("/tasks/<int:task_id>/edit")
@login_required
def edit_task_web(task_id):
    task = _own_task(task_id)
    if task:
        try:
            _apply(task, request.form.to_dict(), creating=False)
            db.session.commit()
            flash("Task updated successfully!", "success")
        except ValueError as e:
            flash(str(e), "danger")
    return redirect(url_for("main.tasks_page"))


@bp.post("/tasks/<int:task_id>/delete")
@login_required
def delete_task_web(task_id):
    task = _own_task(task_id)
    if task:
        db.session.delete(task)
        db.session.commit()
        flash("Task deleted.", "info")
    return redirect(url_for("main.tasks_page"))

