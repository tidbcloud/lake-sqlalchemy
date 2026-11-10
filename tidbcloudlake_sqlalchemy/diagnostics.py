"""Redact diagnostic copies without changing connection or statement inputs."""

import logging
import re
from urllib.parse import parse_qsl, unquote, urlsplit, urlunsplit

from sqlalchemy import event


_ASSIGNMENT = re.compile(
    r"\b(?:access_key_id|secret_access_key|master_key|security_token|account_key|"
    r"credential|credentials|password|access_token|accesstoken|token)\s*=\s*",
    re.IGNORECASE,
)
_QUOTE = re.compile(r"['\"]")
_UNQUOTED_VALUE = re.compile(r"[^\s,)&]+")
_URL = re.compile(r"(?<![A-Za-z0-9+.-])[A-Za-z0-9+.-]+://[^\s'\"<>]+")
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
        if not parts.scheme or not parts.netloc:
            return "<redacted-url>"
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


def _literal_end(text, start):
    quote = text[start]
    index = start + 1
    while index < len(text):
        if text[index] == "\\":
            index += 2
        elif text[index] == quote:
            index += 1
            if index == len(text) or text[index] != quote:
                return index, True
            index += 1
        else:
            index += 1
    return len(text), False


def _quoted_literals(text):
    index = 0
    while match := _QUOTE.search(text, index):
        start = match.start()
        index, closed = _literal_end(text, start)
        yield start, index, closed


def _assignment_values(text):
    index = 0
    while match := _ASSIGNMENT.search(text, index):
        start = match.end()
        if start < len(text) and text[start] in "'\"":
            index, closed = _literal_end(text, start)
            yield start, index, True, closed
        else:
            value = _UNQUOTED_VALUE.match(text, start)
            index = value.end() if value else start
            if value:
                yield start, index, False, False


def _replace_spans(text, spans, replacement):
    parts = []
    previous = 0
    for start, end in spans:
        parts.extend((text[previous:start], replacement))
        previous = end
    parts.append(text[previous:])
    return "".join(parts)


def redact(value):
    value = str(value)
    # Replace complete URL literals first, so whitespace or an escaped quote
    # inside a signed URL cannot end the redaction early.
    urls = ((start, end) for start, end, _ in _quoted_literals(value) if _URL.search(value, start, end))
    value = _replace_spans(value, urls, "'<redacted-url>'")
    assignments = ((start, end) for start, end, _, _ in _assignment_values(value))
    return _URL.sub(_safe_url, _replace_spans(value, assignments, "'***'"))


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
        for start, end, quoted, closed in _assignment_values(sql):
            if not quoted:
                continue
            quote = sql[start]
            value = sql[start + 1 : end - int(closed)]
            self._secrets.add(value)
            self._secrets.add(
                re.sub(
                    r"\\(.)",
                    lambda m: {"n": "\n", "r": "\r", "t": "\t", "0": "\0"}.get(
                        m[1], m[1]
                    ),
                    value,
                ).replace(quote * 2, quote)
            )
        for start, end, closed in _quoted_literals(sql):
            quote = sql[start]
            value = sql[start + 1 : end - int(closed)]
            value = re.sub(r"\\(.)", r"\1", value).replace(quote * 2, quote)
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
