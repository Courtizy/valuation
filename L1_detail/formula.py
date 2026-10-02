"""Safe evaluation of registry formulas: concept ids joined by + - * / and ().

No eval(): the expression is parsed to an AST and only arithmetic on known
names is allowed.
"""
from __future__ import annotations

import ast

_OPS = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
        ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b}


def evaluate(formula: str, values: dict[str, float]) -> float | None:
    """Return the result, or None if an input is missing or a division is by zero."""

    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            left, right = walk(node.left), walk(node.right)
            if left is None or right is None:
                return None
            if isinstance(node.op, ast.Div) and right == 0:
                return None
            return _OPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            v = walk(node.operand)
            return None if v is None else -v
        if isinstance(node, ast.Name):
            return values.get(node.id)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"unsupported expression element: {ast.dump(node)}")

    return walk(ast.parse(formula, mode="eval"))
