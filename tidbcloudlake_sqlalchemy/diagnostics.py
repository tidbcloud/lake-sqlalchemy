"""Redact diagnostic copies without changing connection or statement inputs."""

import logging
import re
from urllib.parse import parse_qsl, unquote, urlsplit, urlunsplit

from sqlalchemy import event


_QUOTED = r"'(?:\\[\s\S]|''|[^'\\])*'|\"(?:\\[\s\S]|\"\"|[^\"\\])*\""
_ASSIGNMENT = re.compile(
    r"\b(?:access_key_id|secret_access_key|master_key|security_token|account_key|"
    r"credential|credentials|password|access_token|accesstoken|token)\s*=\s*"
    r"(?P<value>" + _QUOTED + r"|[^\s,)&]+)",
    re.IGNORECASE,
)
_URL = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s'\"<>]+")
_STRING = re.compile(_QUOTED)
_SECRET_KEYS = {
    "password",
    "token",
    "access_token",
    "accesstoken",
    "secret_access_key",
    "security_token",
}


def _safe_url(match):
    try:
        parts = urlsplit(match.group())
        return urlunsplit(
            (
                parts.scheme,
                parts.netloc.rsplit("@", 1)[-1],
                parts.path,
                "***" if parts.query else "",
                "***" if parts.fragment else "",
            )
        )
    except ValueError:
        return "<redacted-url>"


def redact(value):
    value = str(value)

    # A URL inside a SQL literal can itself contain escaped quotes or whitespace. Match the
    # complete literal before scanning ordinary URLs, so a signed query after such a character
    # cannot fall outside the URL redaction.
    def safe_literal(match):
        literal = match.group()
        if not _URL.search(literal):
            return literal
        return "'<redacted-url>'"

    value = _STRING.sub(safe_literal, value)
    value = _ASSIGNMENT.sub(
        lambda m: m.group()[: m.start("value") - m.start()] + "'***'", value
    )
    return _URL.sub(_safe_url, value)


class Diagnostics:
    def __init__(self, dsn):
        self._secrets = set()
        try:
            parts = urlsplit(dsn)
            if parts.password:
                self._secrets.update((parts.password, unquote(parts.password)))
            self._secrets.update(
                v for k, v in parse_qsl(parts.query) if k.lower() in _SECRET_KEYS and v
            )
        except ValueError:
            pass
        self._connection_secrets = frozenset(self._secrets)

    def for_cursor(self):
        child = Diagnostics("")
        child._connection_secrets = self._connection_secrets
        child._secrets = set(self._connection_secrets)
        return child

    def remember_statement(self, sql):
        # A cursor only needs the active statement for subsequent execute/fetch errors. Do not
        # retain every credential ever used by a long-lived connection, or share mutable state
        # between independent cursors.
        self._secrets = set(self._connection_secrets)
        for match in _ASSIGNMENT.finditer(sql):
            value = match.group("value")
            if len(value) >= 2 and value[0] in "'\"" and value[-1] == value[0]:
                value = value[1:-1]
                self._secrets.add(value)
                self._secrets.add(
                    re.sub(
                        r"\\(.)",
                        lambda m: {"n": "\n", "r": "\r", "t": "\t", "0": "\0"}.get(
                            m[1], m[1]
                        ),
                        value,
                    ).replace("''", "'")
                )
        for match in _STRING.finditer(sql):
            value = match.group()[1:-1]
            value = re.sub(r"\\(.)", r"\1", value).replace("''", "'")
            if not _URL.match(value):
                continue
            try:
                parts = urlsplit(value)
                if parts.password:
                    self._secrets.update((parts.password, unquote(parts.password)))
                self._secrets.update(v for _, v in parse_qsl(parts.query) if v)
            except ValueError:
                continue

    def safe_error(self, error):
        message = str(error)
        for secret in sorted(self._secrets, key=len, reverse=True):
            if secret:
                message = message.replace(secret, "***")
        return redact(message)


class _DiagnosticFilter(logging.Filter):
    def filter(self, record):
        # Format a diagnostic copy. Never replace the SQL/parameters passed to the DBAPI.
        record.msg = redact(record.getMessage())
        record.args = ()
        return True


def install_engine_diagnostics(engine):
    logger = getattr(engine.logger, "logger", engine.logger)
    if not any(isinstance(f, _DiagnosticFilter) for f in logger.filters):
        logger.addFilter(_DiagnosticFilter())

    def safe_statement_error(context):
        error = context.sqlalchemy_exception
        if error is not None and getattr(error, "statement", None):
            error.statement = redact(error.statement)

    event.listen(engine, "handle_error", safe_statement_error)
