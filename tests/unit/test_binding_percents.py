from unittest.mock import Mock

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table
from tidbcloudlake_sqlalchemy.connector import Cursor
from tidbcloudlake_sqlalchemy.tidbcloudlake_dialect import TiDBCloudLakeDialect


@pytest.mark.parametrize('value', ['50%', '50%%', '%s', '%(name)s', "O'Reilly \\ 資料 50%%"])
def test_execute_and_executemany_preserve_percent_values(value):
    inner = Mock()
    cursor = Cursor(inner)
    cursor.execute('INSERT INTO t VALUES (%s)', [value])
    single = inner.execute.call_args.args[0].rstrip(';')
    cursor.executemany('INSERT INTO t VALUES (%s)', [(value,)])
    batch = inner.execute.call_args.args[0].rstrip(';')
    assert batch.split('VALUES', 1)[1].strip() == single.split('VALUES', 1)[1].strip()
    assert value.count('%') == batch.count('%')


def test_compiled_percent_names_and_literal_percents_are_decoded_once():
    table = Table('table%name', MetaData(), Column('id', Integer), Column('value%s', String))
    compiled = table.insert().compile(dialect=TiDBCloudLakeDialect())
    inner = Mock()
    # SQLAlchemy escapes percent signs in bind keys separately from SQL names.
    value_key = next(key for key in compiled.params if key != 'id')
    Cursor(inner).executemany(str(compiled), [{'id': 1, value_key: '50%%'}])
    rendered = inner.execute.call_args.args[0]
    assert '"table%name"' in rendered
    assert '"value%s"' in rendered
    assert "'50%%'" in rendered
