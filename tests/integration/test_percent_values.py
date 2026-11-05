"""Bound percent data must round-trip identically for single and bulk inserts."""

from uuid import uuid4

from sqlalchemy import Column, Integer, MetaData, String, Table, select


def test_single_and_bulk_percent_values(engine):
    metadata = MetaData()
    table = Table(
        "percent_" + uuid4().hex,
        metadata,
        Column("id", Integer),
        Column("value%s", String),
    )
    values = ["50%", "50%%", "%s", "%(name)s", "O'Reilly \\ 資料 50%%"]
    metadata.create_all(engine)
    try:
        with engine.begin() as connection:
            connection.execute(table.insert(), {"id": 0, "value%s": values[0]})
            connection.execute(
                table.insert(),
                [{"id": i, "value%s": value} for i, value in enumerate(values, 1)],
            )
        with engine.connect() as connection:
            rows = connection.execute(select(table).order_by(table.c.id)).all()
            assert [row[1] for row in rows] == [values[0]] + values
    finally:
        metadata.drop_all(engine)
