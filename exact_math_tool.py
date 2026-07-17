#!/usr/bin/env python3
"""Read-only exact-rational expression evaluator for the local chat console.

It deliberately accepts only numbers, parentheses, +, -, *, /, and ^. It does
not use Python eval, does not accept float values, and enforces small resource
limits. Decimal text such as 0.1 is parsed as the exact rational 1/10.

This small tool uses Python's standard-library ``Fraction`` directly. It is a
standalone rational calculator, not a second copy of the broader ``regime_math``
library, whose positional and Hahn-series features are not needed in chat.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction


MAX_INPUT = 1024
MAX_TOKENS = 256
MAX_EXPONENT = 1024
MAX_BITS = 4096
TOKEN = re.compile(r"\s*(?:(\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|([()+\-*/^]))")


class MathSyntaxError(ValueError):
    pass


@dataclass(frozen=True)
class MathResult:
    fraction: str
    decimal: str

    def as_dict(self) -> dict:
        return {"fraction": self.fraction, "decimal": self.decimal}


class ExactExpression:
    def __init__(self, source: str):
        if not isinstance(source, str) or not source.strip():
            raise MathSyntaxError("expression must be a non-empty string")
        source = source.strip()
        if len(source) > MAX_INPUT:
            raise MathSyntaxError("expression is too long")
        self.tokens = self._tokenize(source)
        self.i = 0

    @staticmethod
    def _tokenize(source: str) -> list[str]:
        result: list[str] = []
        pos = 0
        while pos < len(source):
            match = TOKEN.match(source, pos)
            if not match:
                raise MathSyntaxError(f"unsupported character at position {pos + 1}")
            number, symbol = match.groups()
            result.append(number or symbol)
            pos = match.end()
            if len(result) > MAX_TOKENS:
                raise MathSyntaxError("expression has too many tokens")
        return result

    def _peek(self) -> str | None:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def _take(self, expected: str | None = None) -> str:
        token = self._peek()
        if token is None:
            raise MathSyntaxError("unexpected end of expression")
        if expected is not None and token != expected:
            raise MathSyntaxError(f"expected '{expected}', got '{token}'")
        self.i += 1
        return token

    @staticmethod
    def _bounded(value: Fraction) -> Fraction:
        if value.numerator.bit_length() > MAX_BITS or value.denominator.bit_length() > MAX_BITS:
            raise MathSyntaxError("result exceeds the exact-calculation size limit")
        return value

    def parse(self) -> Fraction:
        result = self._sum()
        if self._peek() is not None:
            raise MathSyntaxError(f"unexpected token '{self._peek()}'")
        return result

    def _sum(self) -> Fraction:
        value = self._product()
        while self._peek() in {"+", "-"}:
            op = self._take()
            right = self._product()
            value = self._bounded(value + right if op == "+" else value - right)
        return value

    def _product(self) -> Fraction:
        value = self._power()
        while self._peek() in {"*", "/"}:
            op = self._take()
            right = self._power()
            if op == "/":
                value = self._bounded(value / right)
            else:
                value = self._bounded(value * right)
        return value

    def _power(self) -> Fraction:
        value = self._unary()
        if self._peek() == "^":
            self._take("^")
            exponent = self._power()  # right associative: 2^3^2 == 2^9
            if exponent.denominator != 1:
                raise MathSyntaxError("exponent must be an integer")
            n = exponent.numerator
            if abs(n) > MAX_EXPONENT:
                raise MathSyntaxError(f"exponent exceeds +/-{MAX_EXPONENT}")
            try:
                value = self._bounded(value ** n)
            except ZeroDivisionError as exc:
                raise MathSyntaxError("zero cannot have a negative exponent") from exc
        return value

    def _unary(self) -> Fraction:
        token = self._peek()
        if token == "+":
            self._take("+")
            return self._unary()
        if token == "-":
            self._take("-")
            return self._bounded(-self._unary())
        if token == "(":
            self._take("(")
            result = self._sum()
            self._take(")")
            return result
        if token is None:
            raise MathSyntaxError("expected a number or '('")
        if TOKEN.fullmatch(token) is None or not token[0].isdigit():
            raise MathSyntaxError(f"expected a number, got '{token}'")
        self._take()
        try:
            return self._bounded(Fraction(token))
        except ValueError as exc:
            raise MathSyntaxError(f"invalid exact number '{token}'") from exc


def to_decimal_string(value: Fraction, max_frac_digits: int = 50) -> str:
    """Render a Fraction without going through a binary float."""
    sign = "-" if value < 0 else ""
    numerator, denominator = abs(value.numerator), value.denominator
    integer, remainder = divmod(numerator, denominator)
    if remainder == 0:
        return sign + str(integer)
    digits: list[str] = []
    for _ in range(max_frac_digits):
        remainder *= 10
        digit, remainder = divmod(remainder, denominator)
        digits.append(str(digit))
        if remainder == 0:
            break
    return f"{sign}{integer}.{''.join(digits)}" + ("" if remainder == 0 else "…")


def evaluate(expression: str) -> MathResult:
    fraction = ExactExpression(expression).parse()
    return MathResult(
        fraction=str(fraction.numerator) if fraction.denominator == 1 else f"{fraction.numerator}/{fraction.denominator}",
        decimal=to_decimal_string(fraction),
    )
