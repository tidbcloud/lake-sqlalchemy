import logging
import traceback
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, table, text
from sqlalchemy.dialects import registry
from sqlalchemy.exc import CompileError, DBAPIError

from tidbcloudlake_sqlalchemy import connector
from tidbcloudlake_sqlalchemy.diagnostics import Diagnostics, redact
from tidbcloudlake_sqlalchemy.dml import (
    AmazonS3,
    AzureBlobStorage,
    GoogleCloudStorage,
    CopyIntoTable,
    CopyIntoTableOptions,
    CopyIntoLocation,
    CopyFormat,
    FileColumnClause,
    CSVFormat,
    StageClause,
)
from tidbcloudlake_sqlalchemy.sql_literals import string_literal
from tidbcloudlake_sqlalchemy.tidbcloudlake_dialect import TiDBCloudLakeDialect


def compile_sql(statement):
    return str(statement.compile(dialect=TiDBCloudLakeDialect()))


@pytest.mark.parametrize(
    "value,expected",
    [
        ("normal.csv", "'normal.csv'"),
        ("a'file.csv", "'a\\'file.csv'"),
        ("a\\' OR injectedToken -- ", "'a\\\\\\' OR injectedToken -- '"),
        ("a\n\t\r\0", "'a\\n\\t\\r\\0'"),
    ],
)
def test_files_and_pattern_use_one_string_literal(value, expected):
    statement = CopyIntoTable(
        target=table("t"), from_=StageClause(name="s"), files=[value], pattern=value
    )
    rendered = compile_sql(statement)
    assert "FILES = (" + expected + ")" in rendered
    assert "PATTERN = " + expected in rendered


def test_percent_characters_survive_dbapi_rendering():
    sql = compile_sql(
        CopyIntoTable(
            target=table("t"),
            from_=StageClause(name="s"),
            files=["a%%.csv"],
            pattern="a%",
        )
    )
    inner = Mock()
    connector.Cursor(inner).execute(sql)
    actual = inner.execute.call_args.args[0]
    assert "FILES = ('a%%.csv')" in actual
    assert "PATTERN = 'a%'" in actual


@pytest.mark.parametrize(
    "storage",
    [
        AmazonS3(
            uri="s3://bucket/a'file",
            access_key_id="a\\'id",
            secret_access_key="s'key",
            endpoint_url="https://host/a'path",
            master_key="m'key",
            security_token="t'token",
            region="r'egion",
        ),
        AzureBlobStorage(
            uri="azblob://bucket/a'file", account_name="a'ccount", account_key="s'key"
        ),
        GoogleCloudStorage(uri="gcs://bucket/a'file", credentials="s'key"),
    ],
)
def test_storage_strings_are_escaped_on_both_copy_directions(storage):
    for statement in (
        CopyIntoTable(target=table("t"), from_=storage),
        CopyIntoLocation(target=storage, from_=table("t")),
    ):
        sql = compile_sql(statement)
        assert string_literal(storage.uri) in sql
        assert "s\\'key" in sql


def test_required_s3_fields_compile_without_optional_attributes():
    sql = compile_sql(
        CopyIntoTable(
            target=table("t"),
            from_=AmazonS3(
                uri="s3://bucket/", access_key_id="id", secret_access_key="secret"
            ),
        )
    )
    assert "SECRET_ACCESS_KEY = 'secret'" in sql
    assert "ENDPOINT_URL" not in sql


def test_s3_partial_options_preserve_false_and_initialize_unset_fields():
    storage = AmazonS3(uri="s3://bucket/", access_key_id="id", secret_access_key="secret",
                       endpoint_url="https://s3.example.com", enable_virtual_host_style=False,
                       region="us-west-2")
    assert storage.enable_virtual_host_style is False
    assert storage.master_key is None
    assert storage.security_token is None
    sql = compile_sql(CopyIntoTable(target=table("t"), from_=storage))
    assert "ENDPOINT_URL = 'https://s3.example.com'" in sql
    assert "REGION = 'us-west-2'" in sql
    assert "ENABLE_VIRTUAL_HOST_STYLE" not in sql


@pytest.mark.parametrize(
    "name,path,expected",
    [
        ("stage", "dir/file", "@stage/dir/file"),
        ("stage", "a'file", "'@stage/a\\'file'"),
        ("stage", "dir with space", "'@stage/dir with space'"),
        ("stage; injectedToken", "dir", "'@stage; injectedToken/dir'"),
    ],
)
def test_stage_token_delimiters_remain_part_of_the_location(name, path, expected):
    assert "FROM " + expected in compile_sql(
        CopyIntoTable(target=table("t"), from_=StageClause(name=name, path=path))
    )


def test_null_display_is_quoted_and_valid_format_options_still_compile():
    statement = CopyIntoTable(
        target=table("t"),
        from_=StageClause(name="s"),
        file_format=CSVFormat(null_display="x' injectedToken", record_delimiter="\n"),
        options=CopyIntoTableOptions(on_error="CONTINUE", purge=True, size_limit=100),
    )
    sql = compile_sql(statement)
    assert "NULL_DISPLAY = 'x\\' injectedToken'" in sql
    assert "RECORD_DELIMITER = '\\n'" in sql
    assert "ON_ERROR = CONTINUE" in sql
    assert "PURGE = TRUE" in sql


@pytest.mark.parametrize(
    "value",
    [
        "CONTINUE) injectedToken --",
        "'CONTINUE' injectedToken",
        "CONTINUE; injectedToken",
    ],
)
def test_option_strings_cannot_append_a_clause(value):
    statement = CopyIntoTable(
        target=table("t"),
        from_=StageClause(name="s"),
        options=CopyIntoTableOptions(on_error=value),
    )
    with pytest.raises(CompileError):
        compile_sql(statement)


def test_named_formats_and_explicit_sql_expressions_keep_their_contract():
    stmt = CopyIntoTable(
        target=table("t"),
        from_=StageClause(name="s"),
        file_format=CopyFormat("my_format"),
        options=CopyIntoTableOptions(on_error=text("'CONTINUE'")),
    )
    assert "format_name = my_format" in compile_sql(stmt)
    assert "ON_ERROR = 'CONTINUE'" in compile_sql(stmt)
    stmt.file_format.options["format_name"] = "format) injectedToken"
    with pytest.raises(CompileError):
        compile_sql(stmt)


def test_safe_errors_preserve_codes_without_chaining_the_raw_exception():
    inner = Mock()
    secret = "synthetic-cloud-secret"
    inner.execute.side_effect = RuntimeError("Code: 1001 rejected " + secret)
    cursor = connector.Cursor(inner, Diagnostics("lake://user:dsn-secret@host"))
    sql = "COPY INTO t FROM 's3://b' CONNECTION=(SECRET_ACCESS_KEY='" + secret + "')"
    with pytest.raises(connector.Error) as caught:
        cursor.execute(sql)
    diagnostic = "".join(traceback.format_exception(caught.value))
    assert secret not in diagnostic
    assert "Code: 1001" in diagnostic
    assert caught.value.__suppress_context__ is True
    inner.execute.assert_called_once_with(sql)


def test_cursor_diagnostics_do_not_accumulate_or_share_statement_secrets():
    base = Diagnostics("lake://user:dsn-secret@host")
    first, second = base.for_cursor(), base.for_cursor()
    first.remember_statement("SECRET_ACCESS_KEY='first-secret'")
    second.remember_statement("SECRET_ACCESS_KEY='second-secret'")
    assert first.safe_error("first-secret dsn-secret") == "*** ***"
    assert first.safe_error("second-secret") == "second-secret"
    first.remember_statement("SELECT 1")
    assert first.safe_error("first-secret") == "first-secret"


def test_sqlalchemy_echo_and_statement_errors_redact_copies_only(monkeypatch, caplog):
    registry.register(
        "lake", "tidbcloudlake_sqlalchemy.tidbcloudlake_dialect", "TiDBCloudLakeDialect"
    )
    inner = Mock()
    inner.execute.side_effect = RuntimeError("Code: 1001 cloud-secret")
    client = Mock()
    client.cursor.return_value = inner
    monkeypatch.setattr(connector, "BlockingLakeClient", lambda dsn: client)
    engine = create_engine("lake://user:dsn-secret@host/default", echo=True)
    monkeypatch.setattr(engine.dialect, "initialize", lambda connection: None)
    monkeypatch.setattr(engine.dialect, "do_rollback", lambda connection: None)
    sql = "COPY INTO t FROM 's3://bucket/?signature=signed-secret' CONNECTION=(SECRET_ACCESS_KEY='cloud-secret')"
    with caplog.at_level(logging.INFO), engine.connect() as connection:
        with pytest.raises(DBAPIError) as caught:
            connection.exec_driver_sql(sql)
    assert "cloud-secret" not in str(caught.value)
    assert "signed-secret" not in str(caught.value)
    assert "cloud-secret" not in caplog.text
    assert "signed-secret" not in caplog.text
    assert "Code: 1001" in str(caught.value)
    inner.execute.assert_called_once_with(sql)
    engine.dispose()


def test_connection_failures_redact_dsn_secrets(monkeypatch):
    client = Mock(side_effect=RuntimeError("Code: 1002 dsn-secret"))
    monkeypatch.setattr(connector, "BlockingLakeClient", client)
    with pytest.raises(connector.Error, match="Code: 1002") as caught:
        connector.Connection("lake://user:dsn-secret@host")
    assert "dsn-secret" not in str(caught.value)


def test_redaction_covers_escaped_literals_and_signed_urls():
    rendered = redact(
        "SECRET_ACCESS_KEY='a\\'secret' PASSWORD=bare lake://u:pw@host/?token=tok"
    )
    assert "secret" not in rendered
    assert "bare" not in rendered
    assert "pw" not in rendered
    assert "tok" not in rendered


def test_signed_url_after_an_escaped_quote_is_fully_redacted():
    sql = "COPY INTO t FROM 's3://bucket/a\\'file?signature=signed-secret'"
    assert "signed-secret" not in redact(sql)
    diagnostics = Diagnostics("")
    diagnostics.remember_statement(sql)
    assert "signed-secret" not in diagnostics.safe_error("Code: 1001 signed-secret")


def test_dsn_password_with_whitespace_is_redacted_before_url_parsing():
    diagnostics = Diagnostics("lake://user:synthetic pass@host")
    assert "synthetic" not in diagnostics.safe_error("lake://user:synthetic pass@host")
    assert "pass@host" not in diagnostics.safe_error("lake://user:synthetic pass@host")


@pytest.mark.parametrize("columns", ["$1 FROM other_table", "$1); DROP TABLE sentinel; --"])
def test_copy_projection_cannot_escape_into_another_clause(columns):
    statement = CopyIntoTable(
        target=table("t"),
        from_=FileColumnClause(columns=columns, from_=StageClause(name="src")),
        file_format=CSVFormat(),
    )
    with pytest.raises(CompileError):
        compile_sql(statement)


def test_diagnostic_url_scan_handles_long_words_and_prefixed_urls():
    from tidbcloudlake_sqlalchemy.diagnostics import redact

    value = "a" * 100_000
    assert redact(value) == value
    assert "dummy-secret" not in redact("123lake://user:dummy-secret@warehouse.example/db")


def test_copy_option_clause_cannot_append_another_option():
    statement = CopyIntoTable(
        target=table("t"),
        from_=StageClause(name="src"),
        file_format=CSVFormat(),
        options=CopyIntoTableOptions(on_error=text("'CONTINUE' FORCE=TRUE")),
    )
    with pytest.raises(CompileError):
        compile_sql(statement)


def test_copy_projections_keep_columns_and_aliases():
    statement = CopyIntoTable(
        target=table("t"),
        from_=FileColumnClause(columns="$1 AS id, upper($2)", from_=StageClause(name="src")),
        file_format=CSVFormat(),
    )
    assert "SELECT $1 AS id, upper($2) FROM @src" in compile_sql(statement)


@pytest.mark.parametrize("path", ["a/**/FORCE=TRUE", "a--x", "a*/x"])
def test_copy_stage_comment_markers_are_quoted(path):
    statement = CopyIntoTable(
        target=table("t"),
        from_=StageClause(name="src", path=path),
        file_format=CSVFormat(),
    )
    assert f"FROM '@src/{path}'" in compile_sql(statement)


def test_redaction_handles_long_unterminated_quotes():
    sql = "PASSWORD='" + "''" * 100_000 + "dummy-secret"
    assert redact(sql) == "PASSWORD='***'"
    Diagnostics("").remember_statement(sql)


def test_test_database_provisioning_rejects_sql_before_connecting():
    from tidbcloudlake_sqlalchemy.provision import _lake_create_db, _lake_drop_db

    engine = Mock()
    for provision in (_lake_create_db, _lake_drop_db):
        with pytest.raises(ValueError, match="Invalid Lake test database"):
            provision("lake://", engine, "test; DROP DATABASE production")
    engine.begin.assert_not_called()
