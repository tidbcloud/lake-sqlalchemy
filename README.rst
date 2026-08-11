tidbcloudlake-sqlalchemy
=========================

TiDB Cloud Lake dialect for SQLAlchemy.

Installation
------------

The package is installable through PIP::

    pip install tidbcloudlake-sqlalchemy

Usage
-----

Use a ``lake://`` URL with SQLAlchemy. The database name and warehouse are
part of the URL::

    from sqlalchemy import create_engine, text

    engine = create_engine(
        "lake://<username>:<password>@<host>:443/default?warehouse=default"
    )
    with engine.connect() as connection:
        assert connection.execute(text("SELECT 1")).scalar_one() == 1

Merge Command Support
---------------------

TiDB Cloud Lake SQLAlchemy supports upserts via its ``Merge`` custom expression. See `Merge <https://docs.pingcap.com/tidbcloudlake/merge/>`_ for full documentation.

The Merge command can be used as below::

        from sqlalchemy.orm import sessionmaker
        from sqlalchemy import MetaData, create_engine
        from tidbcloudlake_sqlalchemy.tidbcloudlake_dialect import Merge

        engine = create_engine("lake://<username>:<password>@<host>:443/default?warehouse=default")
        session = sessionmaker(bind=engine)()
        connection = engine.connect()

        meta = MetaData()
        meta.reflect(bind=session.bind)
        t1 = meta.tables['t1']
        t2 = meta.tables['t2']

        merge = Merge(target=t1, source=t2, on=t1.c.t1key == t2.c.t2key)
        merge.when_matched_then_delete().where(t2.c.marked == 1)
        merge.when_matched_then_update().where(t2.c.isnewstatus == 1).values(val = t2.c.newval, status=t2.c.newstatus)
        merge.when_matched_then_update().values(val=t2.c.newval)
        merge.when_not_matched_then_insert().values(val=t2.c.newval, status=t2.c.newstatus)
        connection.execute(merge)


Copy Into Command Support
-------------------------

TiDB Cloud Lake SQLAlchemy supports copy into operations through its
``CopyIntoTable`` and ``CopyIntoLocation`` methods. See `CopyIntoLocation <https://docs.pingcap.com/tidbcloudlake/copy-into-location/>`_ or `CopyIntoTable <https://docs.pingcap.com/tidbcloudlake/copy-into-table/>`_ for full documentation.

The CopyIntoTable command can be used as below::

        import base64

        from sqlalchemy.orm import sessionmaker
        from sqlalchemy import MetaData, create_engine
        from tidbcloudlake_sqlalchemy import (
            CopyIntoTable, GoogleCloudStorage, ParquetFormat, CopyIntoTableOptions,
            FileColumnClause, CSVFormat, Compression,
        )

        engine = create_engine("lake://<username>:<password>@<host>:443/default?warehouse=default")
        session = sessionmaker(bind=engine)()
        connection = engine.connect()

        meta = MetaData()
        meta.reflect(bind=session.bind)
        t1 = meta.tables['t1']
        t2 = meta.tables['t2']
        gcs_private_key = 'full_gcs_json_private_key'
        case_sensitive_columns = True

        copy_into = CopyIntoTable(
            target=t1,
            from_=GoogleCloudStorage(
                uri='gcs://bucket-name/path/to/file',
                credentials=base64.b64encode(gcs_private_key.encode()).decode(),
            ),
            file_format=ParquetFormat(),
            options=CopyIntoTableOptions(
                force=True,
                column_match_mode='CASE_SENSITIVE' if case_sensitive_columns else None,
            )
        )
        result = connection.execute(copy_into)
        result.fetchall()  # always call fetchall() to ensure the cursor executes to completion

        # More involved example with column selection clause that can be altered to perform operations on the columns during import.

        copy_into = CopyIntoTable(
            target=t2,
            from_=FileColumnClause(
                columns=', '.join([
                    f'${index + 1}'
                    for index, column in enumerate(t2.columns)
                ]),
                from_=GoogleCloudStorage(
                    uri='gcs://bucket-name/path/to/file',
                    credentials=base64.b64encode(gcs_private_key.encode()).decode(),
                )
            ),
            pattern='*.*',
            file_format=CSVFormat(
                record_delimiter='\n',
                field_delimiter=',',
                quote='"',
                escape='',
                skip_header=1,
                empty_field_as='NULL',
                compression=Compression.AUTO,
            ),
            options=CopyIntoTableOptions(
                force=True,
            )
        )
        result = connection.execute(copy_into)
        result.fetchall()  # always call fetchall() to ensure the cursor executes to completion

The CopyIntoLocation command can be used as below::

        import base64

        from sqlalchemy import MetaData, create_engine, select
        from sqlalchemy.orm import sessionmaker
        from tidbcloudlake_sqlalchemy import (
            CopyIntoLocation, GoogleCloudStorage, ParquetFormat, CopyIntoLocationOptions,
        )

        engine = create_engine("lake://<username>:<password>@<host>:443/default?warehouse=default")
        session = sessionmaker(bind=engine)()
        connection = engine.connect()

        meta = MetaData()
        meta.reflect(bind=session.bind)
        t1 = meta.tables['t1']
        gcs_private_key = 'full_gcs_json_private_key'

        copy_into = CopyIntoLocation(
            target=GoogleCloudStorage(
                uri='gcs://bucket-name/path/to/target_file',
                credentials=base64.b64encode(gcs_private_key.encode()).decode(),
            ),
            from_=select(t1).where(t1.c['col1'] == 1),
            file_format=ParquetFormat(),
            options=CopyIntoLocationOptions(
                single=True,
                overwrite=True,
                include_query_id=False,
                use_raw_path=True,
            )
        )
        result = connection.execute(copy_into)
        result.fetchall()  # always call fetchall() to ensure the cursor executes to completion

Table Options
---------------------

TiDB Cloud Lake SQLAlchemy supports Lake-specific table options for Engine, Cluster Keys and Transient tables

The table options can be used as below::

        from sqlalchemy import Column, Integer, MetaData, String, Table, cast, create_engine

        engine = create_engine("lake://<username>:<password>@<host>:443/default?warehouse=default")

        meta = MetaData()
        # Example of Transient Table
        t_transient = Table(
            "t_transient",
            meta,
            Column("c1", Integer),
            lake_transient=True,
        )

        # Example of Engine
        t_engine = Table(
            "t_engine",
            meta,
            Column("c1", Integer),
            lake_engine='Memory',
        )

        # Examples of Table with Cluster Keys
        t_cluster_1 = Table(
            "t_cluster_1",
            meta,
            Column("c1", Integer),
            lake_cluster_by=[c1],
        )
        #
        c = Column("id", Integer)
        c2 = Column("Name", String)
        t_cluster_2 = Table(
            't_cluster_2',
            meta,
            c,
            c2,
            lake_cluster_by=[cast(c, String), c2],
        )

        meta.create_all(engine)
