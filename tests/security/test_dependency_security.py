"""Dependency floors and Flask compatibility without a live database."""

import json
from importlib.metadata import version
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

# This optional profile runs in the dedicated Superset CI environment.
flask = pytest.importorskip("flask")
Flask, request, session = flask.Flask, flask.request, flask.session

ROOT = Path(__file__).parents[2]


@pytest.mark.parametrize(
    ("package", "minimum"), [("Flask", "3.1.3"), ("Werkzeug", "3.1.9")]
)
def test_installed_web_dependencies_are_patched(package, minimum):
    assert Version(version(package)) >= Version(minimum)


def test_lockfile_security_floors():
    lock = json.loads((ROOT / "Pipfile.lock").read_text())
    assert Version(lock["develop"]["black"]["version"].removeprefix("==")) >= Version(
        "26.3.1"
    )
    for group in ("default", "develop"):
        for package, minimum in (("flask", "2.2.5"), ("werkzeug", "3.0.3")):
            if package in lock[group]:
                assert Version(
                    lock[group][package]["version"].removeprefix("==")
                ) >= Version(minimum)
    assert "tidbcloudlake-sqlalchemy" in lock["default"]
    assert "databend-sqlalchemy" not in lock["default"]


def test_superset_requirements_exclude_vulnerable_web_versions():
    requirements = {}
    for line in (ROOT / "tests" / "superset_requirements.txt").read_text().splitlines():
        if line and not line.startswith("#"):
            requirement = Requirement(line)
            requirements[requirement.name.lower()] = requirement
    assert "2.2.4" not in requirements["flask"].specifier
    assert "3.0.2" not in requirements["werkzeug"].specifier
    assert "3.1.3" in requirements["flask"].specifier
    assert "3.1.9" in requirements["werkzeug"].specifier


def test_permanent_session_response_varies_on_cookie():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-only-session-key"

    @app.get("/init")
    def init():
        session.permanent = True
        session["visited"] = True
        return "ok"

    @app.get("/")
    def index():
        # Refresh a permanent cookie without accessing or modifying the session.
        return "ok"

    with app.test_client() as client:
        assert client.get("/init").status_code == 200
        response = client.get("/")
        assert response.status_code == 200
        assert "Set-Cookie" in response.headers
        assert "Cookie" in response.vary


def test_multipart_field_limit_is_enforced():
    app = Flask(__name__)
    app.config["MAX_FORM_PARTS"] = 2

    @app.post("/")
    def form():
        return dict(request.form)

    with app.test_client() as client:
        accepted = client.post(
            "/", data={"a": "1", "b": "2"}, content_type="multipart/form-data"
        )
        assert accepted.status_code == 200
        rejected = client.post(
            "/", data={"a": "1", "b": "2", "c": "3"}, content_type="multipart/form-data"
        )
        assert rejected.status_code == 413


def test_superset_imports_and_loads_lake_dialect():
    pytest.importorskip("superset")
    from sqlalchemy.dialects import registry
    from superset.app import create_app
    from superset.db_engine_specs.base import BaseEngineSpec

    from tidbcloudlake_sqlalchemy.tidbcloudlake_dialect import TiDBCloudLakeDialect

    assert callable(create_app)
    assert hasattr(BaseEngineSpec, "engine")
    assert registry.load("lake") is TiDBCloudLakeDialect
