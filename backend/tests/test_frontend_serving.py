"""Docker-режим: backend отдаёт собранный фронтенд, маршруты React открываются по прямой ссылке."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import mount_frontend


def test_frontend_files_and_spa_fallback(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>app</html>", encoding="utf-8")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path.parent / "secret.txt").write_text("nope", encoding="utf-8")
    app = FastAPI()
    mount_frontend(app, tmp_path)
    c = TestClient(app)
    assert c.get("/").text == "<html>app</html>"
    assert c.get("/assets/app.js").text == "console.log(1)"
    assert c.get("/portfolio").text == "<html>app</html>"  # маршрут React -> index.html
    assert c.get("/events/r21").text == "<html>app</html>"
    assert "nope" not in c.get("/../secret.txt").text  # за пределы сборки не выходим
    assert c.get("/api/unknown").status_code == 404
