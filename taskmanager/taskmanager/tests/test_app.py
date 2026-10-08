import pytest

from app import create_app


@pytest.fixture
def client():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                      "METRICS": False, "APP_VERSION": "9.9.9"})
    with app.test_client() as c:
        yield c


def signup(client, user="alice", pw="secret123"):
    client.post("/api/auth/register", json={"username": user, "password": pw})
    return client.post("/api/auth/login", json={"username": user, "password": pw})


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.get_json() == {"status": "ok", "version": "9.9.9"}


def test_register_validation_and_duplicate(client):
    assert client.post("/api/auth/register", json={"username": "a", "password": "x"}).status_code == 400
    assert client.post("/api/auth/register", json={"username": "bob", "password": "secret123"}).status_code == 201
    assert client.post("/api/auth/register", json={"username": "bob", "password": "secret123"}).status_code == 400


def test_login_failure(client):
    client.post("/api/auth/register", json={"username": "bob", "password": "secret123"})
    assert client.post("/api/auth/login", json={"username": "bob", "password": "wrong"}).status_code == 401


def test_tasks_require_auth(client):
    assert client.get("/api/tasks").status_code == 401


def test_task_crud(client):
    signup(client)
    r = client.post("/api/tasks", json={"title": "Write report", "due_date": "2026-11-01"})
    assert r.status_code == 201
    tid = r.get_json()["id"]
    assert client.get(f"/api/tasks/{tid}").get_json()["title"] == "Write report"
    r = client.put(f"/api/tasks/{tid}", json={"status": "done"})
    assert r.get_json()["status"] == "done"
    assert len(client.get("/api/tasks?status=done").get_json()) == 1
    assert client.delete(f"/api/tasks/{tid}").status_code == 204
    assert client.get(f"/api/tasks/{tid}").status_code == 404


def test_task_validation(client):
    signup(client)
    assert client.post("/api/tasks", json={"title": " "}).status_code == 400
    assert client.post("/api/tasks", json={"title": "x", "status": "bogus"}).status_code == 400
    assert client.post("/api/tasks", json={"title": "x", "due_date": "not-a-date"}).status_code == 400


def test_users_cannot_see_each_others_tasks(client):
    signup(client, "alice")
    tid = client.post("/api/tasks", json={"title": "private"}).get_json()["id"]
    client.post("/api/auth/logout")
    signup(client, "mallory")
    assert client.get(f"/api/tasks/{tid}").status_code == 404


def test_unknown_route_is_json_404(client):
    r = client.get("/nope")
    assert r.status_code == 404 and r.get_json()["error"] == "not found"


def test_web_flow(client):
    client.post("/register", data={"username": "web", "password": "secret123"})
    r = client.post("/login", data={"username": "web", "password": "secret123"}, follow_redirects=True)
    assert b"Task Manager" in r.data and b"v9.9.9" in r.data
    client.post("/tasks", data={"title": "From UI"})
    assert b"From UI" in client.get("/tasks").data
