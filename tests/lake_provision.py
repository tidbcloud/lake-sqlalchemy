"""Provision isolated follower databases for the repository test suite."""

import logging
import re

from sqlalchemy.testing.provision import (
    configure_follower,
    create_db,
    drop_db,
    temp_table_keyword_args,
)


logger = logging.getLogger(__name__)


def _database_names(ident):
    if not isinstance(ident, str) or not re.fullmatch(r"test_[0-9a-f]{12}", ident):
        raise ValueError("Invalid Lake test database identifier")
    return (ident, f"{ident}_test_schema", f"{ident}_test_schema_2")


@create_db.for_db("lake")
def _lake_create_db(cfg, eng, ident):
    names = _database_names(ident)
    with eng.begin() as conn:
        for name in names:
            logger.info("Creating Lake test database %s", name)
            conn.exec_driver_sql(f"CREATE DATABASE IF NOT EXISTS `{name}`")


@drop_db.for_db("lake")
def _lake_drop_db(cfg, eng, ident):
    names = _database_names(ident)
    with eng.begin() as conn:
        for name in reversed(names):
            logger.info("Dropping Lake test database %s", name)
            conn.exec_driver_sql(f"DROP DATABASE IF EXISTS `{name}`")


@temp_table_keyword_args.for_db("lake")
def _lake_temp_table_keyword_args(cfg, eng):
    return {"prefixes": ["TEMPORARY"]}


@configure_follower.for_db("lake")
def _lake_configure_follower(config, ident):
    _, config.test_schema, config.test_schema_2 = _database_names(ident)
