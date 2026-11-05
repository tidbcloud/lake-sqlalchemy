import pytest
from unittest.mock import Mock
from sqlalchemy import Column, Integer, MetaData, Table, UniqueConstraint, select
from sqlalchemy.schema import CreateTable, CreateIndex, Index
from sqlalchemy.exc import CompileError
from tidbcloudlake_sqlalchemy import connector
from tidbcloudlake_sqlalchemy.tidbcloudlake_dialect import TiDBCloudLakeDialect, LakeConstraintWarning


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


def test_orm_primary_key_metadata_warns_that_it_is_not_enforced():
    table = Table('t', MetaData(), Column('id', Integer, primary_key=True))
    with pytest.warns(LakeConstraintWarning, match='does not enforce PRIMARY KEY'):
        assert 'PRIMARY KEY' not in str(CreateTable(table).compile(dialect=TiDBCloudLakeDialect()))
