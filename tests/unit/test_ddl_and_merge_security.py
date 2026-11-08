import pytest
from sqlalchemy import Table, Column, Integer, MetaData, literal
from sqlalchemy.schema import CreateTable
from sqlalchemy.exc import CompileError
from tidbcloudlake_sqlalchemy import Merge
from tidbcloudlake_sqlalchemy.tidbcloudlake_dialect import TiDBCloudLakeDialect


def test_merge_names_use_the_identifier_preparer():
    d = TiDBCloudLakeDialect()
    m = MetaData()
    a = Table('a', m, Column('id', Integer))
    b = Table('b', m, Column('id', Integer))
    key = 'id) VALUES (1); DROP TABLE sentinel; --'
    statement = Merge(a, b, a.c.id == b.c.id)
    statement.when_not_matched_then_insert().values(**{key: literal(1)})
    sql = str(statement.compile(dialect=d))
    assert 'INSERT (' + d.identifier_preparer.quote_identifier(key) + ') VALUES' in sql


@pytest.mark.parametrize('option,value', [
    ('engine', 'FUSE; DROP TABLE sentinel'),
    ('engine', 'FUSE COMMENT=123'),
    ('cluster_by', 'id) AS SELECT 1; DROP TABLE sentinel; --'),
    ('cluster_by', r'"a\" ) ; DROP TABLE sentinel ; --"'),
    ('cluster_by', 'id, (SELECT id FROM secret)'),
    ('cluster_by', 'id /* comment */'),
    ('cluster_by', 'id) ENGINE=Memory ('),
    ('cluster_by', 'CAST(id AS INT'),
])
def test_ddl_options_cannot_escape_expression_boundary(option, value):
    t = Table('t', MetaData(), Column('id', Integer), **{'lake_' + option: value})
    with pytest.raises(CompileError):
        str(CreateTable(t).compile(dialect=TiDBCloudLakeDialect()))


@pytest.mark.parametrize('value', ['id', 'engine', 'comment', 'CAST(id AS VARCHAR), "Name"', "coalesce(id, 0)", "CASE WHEN id > 1 THEN id ELSE 0 END", "length('a; b')"])
def test_existing_cluster_expressions_remain_supported(value):
    t = Table('t', MetaData(), Column('id', Integer), lake_cluster_by=value)
    sql = str(CreateTable(t).compile(dialect=TiDBCloudLakeDialect()))
    assert 'CLUSTER BY ( ' + value + ' )' in sql


def test_cluster_expression_handles_identifier_backslashes_and_string_escapes():
    value = r'''length('it\'s; fine'), "a""name", "inner\name"'''
    table = Table('t', MetaData(), Column('id', Integer), lake_cluster_by=value)
    sql = str(CreateTable(table).compile(dialect=TiDBCloudLakeDialect()))
    assert 'CLUSTER BY ( ' + value + ' )' in sql
