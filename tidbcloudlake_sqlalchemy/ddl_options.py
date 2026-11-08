"""Keep raw clustering expressions inside a single expression-list boundary."""
import re
from sqlalchemy.exc import CompileError

_STATEMENTS = set('SELECT INSERT UPDATE DELETE MERGE DROP ALTER CREATE GRANT REVOKE UNION COPY INTO FROM WHERE HAVING TRUNCATE ATTACH DETACH'.split())


def engine_name(value):
    if not isinstance(value, str) or re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', value) is None:
        raise CompileError('lake_engine must be a single engine name')
    return value


def cluster_expression(value):
    if not isinstance(value, str) or not value.strip():
        raise CompileError('lake_cluster_by must contain an expression')
    depth = 0
    index = 0
    while index < len(value):
        char = value[index]
        if char in "'\"`":
            quote = char
            index += 1
            while index < len(value):
                if value[index] == '\\':
                    if quote == "'":
                        index += 2
                        continue
                    escape_start = index
                    while index < len(value) and value[index] == '\\':
                        index += 1
                    # Identifier quote handling can differ across SQL dialects.
                    if index < len(value) and value[index] == quote and (index - escape_start) % 2:
                        raise CompileError('Ambiguous escape before a cluster expression identifier quote')
                    continue
                if value[index] == quote:
                    index += 1
                    if index < len(value) and value[index] == quote:
                        index += 1
                    else:
                        break
                else:
                    index += 1
            else:
                raise CompileError('Unterminated cluster expression quote')
            continue
        if char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
            if depth < 0:
                raise CompileError('Unbalanced cluster expression')
        elif char == ';' or char == '#' or value.startswith(('--', '/*', '*/'), index):
            raise CompileError('Statements and comments are not allowed in lake_cluster_by')
        elif char.isalpha() or char == '_':
            end = index + 1
            while end < len(value) and (value[end].isalnum() or value[end] in '_$'):
                end += 1
            word = value[index:end].upper()
            if word in _STATEMENTS or (word == 'AS' and depth == 0):
                raise CompileError('SQL statements are not cluster expressions')
            index = end
            continue
        index += 1
    if depth:
        raise CompileError('Unbalanced cluster expression')
    return value
