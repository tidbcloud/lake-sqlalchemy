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

Release Notes
-------------

0.5.8
~~~~~

* **Security**: the ``__repr__`` of the ``COPY INTO`` storage clauses (``AmazonS3``,
  ``AzureBlobStorage``, ``GoogleCloudStorage``) no longer renders cloud credentials. Secret-bearing
  fields (``SECRET_ACCESS_KEY``, ``MASTER_KEY``, ``SECURITY_TOKEN``, ``ACCESS_KEY_ID``, the Azure
  ``ACCOUNT_KEY`` and the GCS ``CREDENTIAL`` service-account key) are shown as ``'***'`` (``'<unset>'``
  when not set), so a repr, a log record or a pytest assertion dump can be shared safely. The compiled
  SQL still carries the real values: ``str(stmt)`` / ``print(stmt)`` are unchanged and must not be
  logged.
* Fixed two latent repr bugs on the same path: ``AmazonS3.__repr__`` used to raise ``AttributeError``
  when optional fields (``endpoint_url`` and friends) were unset, and the ``CopyIntoTable`` /
  ``CopyIntoLocation`` reprs used to raise ``UnsupportedCompilationError`` when the target was a
  ``StageClause`` or a storage clause (the target was rendered with ``str()``, i.e. compiled). The repr is now complete and stable instead of truncated. Behaviour change:
  ``repr(CopyIntoTable(target=<TableClause>))`` now prints the SQLAlchemy object text instead of
  ``schema.table``; use ``str(stmt)`` to compile the statement.
* ``ParamEscaper.escape_args`` error messages now report the parameter *type* (e.g. ``Unsupported param
  format: SecretParams``) instead of interpolating the parameter values into the exception text.
COPY values and diagnostics
---------------------------

COPY filenames, patterns, storage URI/credentials and stage locations are
compiled as data with Lake's string escaping. Existing simple stage locations,
keyword/numeric COPY options and quoted option values retain their semantics.
An option string cannot append arbitrary SQL clauses; use an explicit
SQLAlchemy SQL expression when intentionally supplying trusted SQL.

DBAPI error messages and SQLAlchemy engine diagnostics redact credential
assignments and credential-bearing URLs. Actual DSNs and SQL sent to the
driver retain their values. These protections cover this dialect's diagnostic
paths; applications remain responsible for their own logs and tracing.

Security defaults
-----------------
Connections require an explicit DSN. TLS certificate and hostname verification
are enabled by default (``sslmode=require``). Plain HTTP requires an explicit
``sslmode=disable`` development opt-out; never use it for remote credentials.
Lake does not enforce relational constraints. ORM primary-key identity metadata
emits a warning; foreign-key, unique/check constraints and index DDL fail rather
than pretending to install protection. ``SELECT FOR UPDATE`` raises a compilation
error because Lake cannot provide the requested row lock.

Remote plaintext DSNs require the process operator to set
``TIDBCLOUDLAKE_ALLOW_INSECURE_REMOTE=1``. Local loopback DSNs can continue to
use an explicit ``sslmode=disable`` for development.


Generated DDL boundaries
------------------------
MERGE INSERT columns use the same identifier quoting as MERGE UPDATE. A
`lake_engine` is a single engine name. String `lake_cluster_by` values retain
expression-list syntax (including CAST and quoted literals), but cannot close the
list, append a statement/comment or introduce a subquery. Prefer SQLAlchemy
expression objects for programmatic construction. Reflected options pass through
the same validation when emitted as CREATE TABLE.


Storage credentials for COPY
----------------------------

Use ``StageClause`` for an existing warehouse stage, or
``StorageConnection(uri="s3://bucket/path", connection_name="managed_storage")``
in the COPY source or destination. Create and grant access to the named
connection in Lake. SQLAlchemy sends the URI and connection name, so storage
credentials can be managed and rotated separately from application SQL.

When rotating warehouse login credentials, configure the new credentials for
new connections and dispose of the old SQLAlchemy engine pool after returning
checked-out connections. The driver also supports a trusted token-file DSN
option for file-backed rotation.
