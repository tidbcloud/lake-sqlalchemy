import pytest
from unittest.mock import Mock
from sqlalchemy import Column, Integer, MetaData, Table, UniqueConstraint, select
from sqlalchemy.schema import CreateTable, CreateIndex, Index
from sqlalchemy.exc import CompileError
from tidbcloudlake_sqlalchemy import connector
from tidbcloudlake_sqlalchemy.tidbcloudlake_dialect import TiDBCloudLakeDialect


def test_requires_explicit_endpoint_and_defaults_to_tls(monkeypatch):
    client = Mock()
    monkeypatch.setattr(connector, 'BlockingLakeClient', client)
    with pytest.raises(connector.Error, match='explicit'):
        connector.Connection()
    client.assert_not_called()
    connector.Connection('lake://user:pass@host/db')
    assert 'sslmode=require' in client.call_args.args[0]
    connector.Connection('lake://user:pass@localhost/db?sslmode=disable')
    assert 'sslmode=disable' in client.call_args.args[0]


@pytest.mark.parametrize('dsn', ['http://host', 'lake://host?sslmode=', 'lake://host?sslmode=typo', 'lake://host?sslmode=disable&sslmode=require'])
def test_unsafe_or_ambiguous_transport_is_rejected(dsn):
    with pytest.raises(connector.Error):
        connector.secure_dsn(dsn)


def test_for_update_cannot_silently_lose_locks():
    with pytest.raises(CompileError, match='FOR UPDATE'):
        select(1).with_for_update().compile(dialect=TiDBCloudLakeDialect())


def test_unsupported_enforcement_fails_before_ddl():
    table = Table('t', MetaData(), Column('id', Integer), UniqueConstraint('id'))
    with pytest.raises(CompileError, match='UniqueConstraint'):
        CreateTable(table).compile(dialect=TiDBCloudLakeDialect())
    with pytest.raises(CompileError, match='CREATE INDEX'):
        CreateIndex(Index('i', table.c.id)).compile(dialect=TiDBCloudLakeDialect())


def test_orm_primary_key_metadata_warns_that_it_is_not_enforced(caplog):
    table = Table('t', MetaData(), Column('id', Integer, primary_key=True))
    with caplog.at_level('WARNING'):
        assert 'PRIMARY KEY' not in str(CreateTable(table).compile(dialect=TiDBCloudLakeDialect()))
    assert 'does not enforce PRIMARY KEY' in caplog.text


@pytest.mark.parametrize("kind", ["check", "foreign"])
def test_explicit_check_and_foreign_keys_fail_before_execution(kind):
    from sqlalchemy import CheckConstraint, ForeignKeyConstraint
    metadata = MetaData()
    Table("parent", metadata, Column("id", Integer, primary_key=True))
    constraint = CheckConstraint("id > 0") if kind == "check" else ForeignKeyConstraint(["id"], ["parent.id"])
    table = Table("child", metadata, Column("id", Integer), constraint)
    with pytest.raises(CompileError, match="does not enforce"):
        CreateTable(table).compile(dialect=TiDBCloudLakeDialect())


@pytest.mark.parametrize("scheme", ["lake", "https", "http"])
def test_remote_plaintext_requires_operator_opt_in(monkeypatch, scheme):
    dsn = f"{scheme}://user:pass@warehouse.example/db?sslmode=disable"
    monkeypatch.delenv("TIDBCLOUDLAKE_ALLOW_INSECURE_REMOTE", raising=False)
    with pytest.raises(connector.Error, match="Remote plaintext"):
        connector.secure_dsn(dsn)
    monkeypatch.setenv("TIDBCLOUDLAKE_ALLOW_INSECURE_REMOTE", "1")
    assert connector.secure_dsn(dsn) == dsn
