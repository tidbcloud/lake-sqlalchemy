"""Lake SQL literals used by the client-side COPY compiler."""

import re

from sqlalchemy.exc import CompileError


def string_literal(value):
    if not isinstance(value, str):
        raise CompileError("COPY string values must be strings")
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    escaped = (
        escaped.replace("\x00", "\\0")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return "'" + escaped + "'"


def option_name(value):
    name = str(value).strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name):
        raise CompileError("COPY option names must be identifiers")
    return name


def option_value(value):
    # Existing constructors use bare keywords/numbers and already quoted literal values.
    # Retain these spellings, but reject strings that can append a new SQL clause.
    text = str(value)
    if not re.fullmatch(
        r"(?:[A-Za-z_][A-Za-z_0-9]*|[+-]?[0-9]+(?:\.[0-9]+)?|"
        r"'(?:\\[\s\S]|''|[^'\\])*'|\"(?:\\[\s\S]|\"\"|[^\"\\])*\")",
        text,
    ):
        raise CompileError(
            "COPY options must be a keyword, number, quoted literal or bound value"
        )
    return text
