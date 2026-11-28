"""Tests for the HTTP layer.

Routes that need a database are covered in tests/integration/; here we check
the parts that must work regardless -- notably /healthz, which has to answer
even when the database is down so a bad DB doesn't look like a dead deploy.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from gerry.app.main import app

client = TestClient(app)


class TestHealthz:
    def test_returns_ok(self):
        r = client.get("/healthz")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "version" in body

    def test_reports_the_git_sha(self):
        # Lets a running container be traced back to a commit.
        assert "git_sha" in client.get("/healthz").json()

    def test_works_without_a_database(self):
        # No init_engine() has run in this test process.
        assert client.get("/healthz").status_code == 200


class TestRouting:
    def test_root_redirects_to_shoots(self):
        r = client.get("/", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"] == "/shoots"

    def test_unknown_path_is_404(self):
        assert client.get("/nope").status_code == 404


class TestOverrideValidation:
    def test_rejects_an_invalid_verdict_before_touching_the_db(self):
        r = client.post("/frames/whatever/override?verdict=excellent")
        assert r.status_code == 400


class TestDatabaseUrlNormalisation:
    """Platforms hand out bare postgres:// URLs; SQLAlchemy needs a driver."""

    def test_rewrites_bare_postgres_scheme(self):
        from gerry.settings import Settings

        s = Settings(database_url="postgres://u:p@host:5432/db")
        assert s.database_url.startswith("postgresql+psycopg://")

    def test_rewrites_postgresql_scheme(self):
        from gerry.settings import Settings

        s = Settings(database_url="postgresql://u:p@host:5432/db")
        assert s.database_url.startswith("postgresql+psycopg://")

    def test_leaves_an_explicit_driver_alone(self):
        from gerry.settings import Settings

        url = "postgresql+psycopg://u:p@host:5432/db"
        assert Settings(database_url=url).database_url == url

    def test_preserves_query_parameters(self):
        from gerry.settings import Settings

        s = Settings(database_url="postgres://u:p@h:5432/db?sslmode=disable")
        assert s.database_url.endswith("?sslmode=disable")


class TestWaitForDatabase:
    """Fly stops idle Postgres; a cold start should be slow, not a 500."""

    def test_returns_true_when_the_database_answers(self):
        from sqlalchemy import create_engine

        from gerry.store.db import wait_for_database

        engine = create_engine("sqlite://")
        assert wait_for_database(engine, attempts=1, delay=0) is True

    def test_gives_up_after_the_attempt_budget(self):
        from sqlalchemy import create_engine

        from gerry.store.db import wait_for_database

        # A port nothing listens on: every attempt fails.
        engine = create_engine(
            "postgresql+psycopg://u:p@127.0.0.1:1/none",
            connect_args={"connect_timeout": 1},
        )
        assert wait_for_database(engine, attempts=2, delay=0) is False
