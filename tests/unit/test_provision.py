from importlib.util import find_spec
from pathlib import Path
from runpy import run_path
from unittest.mock import MagicMock, call

import pytest


@pytest.fixture
def provision():
    return run_path(str(Path(__file__).resolve().parents[1] / "lake_provision.py"))


def test_test_provisioning_is_outside_the_dialect_package():
    assert find_spec("tidbcloudlake_sqlalchemy.provision") is None


@pytest.mark.parametrize("ident", ["production", "test_production", "test; DROP DATABASE production"])
def test_provisioning_rejects_non_follower_names(provision, ident):
    engine = MagicMock()
    for operation in ("create_db", "drop_db"):
        with pytest.raises(ValueError, match="Invalid Lake test database"):
            provision[operation]("lake://", engine, ident)
    engine.begin.assert_not_called()


def test_follower_provisioning_creates_and_drops_only_generated_names(provision):
    engine = MagicMock()
    connection = engine.begin.return_value.__enter__.return_value
    ident = "test_0123456789ab"
    names = [ident, f"{ident}_test_schema", f"{ident}_test_schema_2"]
    provision["create_db"]("lake://", engine, ident)
    provision["drop_db"]("lake://", engine, ident)
    assert connection.exec_driver_sql.call_args_list == [
        *[call(f"CREATE DATABASE IF NOT EXISTS `{name}`") for name in names],
        *[call(f"DROP DATABASE IF EXISTS `{name}`") for name in reversed(names)],
    ]


def test_follower_provisioning_surfaces_database_errors(provision):
    engine = MagicMock()
    connection = engine.begin.return_value.__enter__.return_value
    connection.exec_driver_sql.side_effect = RuntimeError("permission denied")
    with pytest.raises(RuntimeError, match="permission denied"):
        provision["drop_db"]("lake://", engine, "test_0123456789ab")
