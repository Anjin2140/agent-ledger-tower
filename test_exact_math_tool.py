#!/usr/bin/env python3
from __future__ import annotations

import unittest
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from exact_math_tool import MathSyntaxError, evaluate


class ExactMathToolTests(unittest.TestCase):
    def test_decimal_drift_example_is_exact(self):
        result = evaluate("0.1 + 0.2 - 0.3")
        self.assertEqual(result.fraction, "0")
        self.assertEqual(result.decimal, "0")

    def test_precedence_parentheses_and_powers(self):
        self.assertEqual(evaluate("2 + 3 * 4").fraction, "14")
        self.assertEqual(evaluate("(2 + 3) * 4").fraction, "20")
        self.assertEqual(evaluate("2^3^2").fraction, "512")
        self.assertEqual(evaluate("1 / 3 + 1 / 6").fraction, "1/2")

    def test_rejects_code_and_excessive_exponents(self):
        with self.assertRaises(MathSyntaxError):
            evaluate("__import__('os')")
        with self.assertRaises(MathSyntaxError):
            evaluate("2^100000")
        with self.assertRaises(MathSyntaxError):
            evaluate("2^0.5")

    def test_calculator_is_standalone_from_the_historical_math_tree(self):
        source = Path(__file__).with_name("exact_math_tool.py")
        with tempfile.TemporaryDirectory(prefix="standalone-exact-") as temp:
            target = Path(temp) / source.name
            shutil.copy2(source, target)
            code = "import sys; sys.path.insert(0, sys.argv[1]); import exact_math_tool; print(exact_math_tool.evaluate('0.1+0.2').fraction)"
            result = subprocess.run(
                [sys.executable, "-I", "-c", code, str(target.parent)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "3/10")


if __name__ == "__main__":
    unittest.main(verbosity=2)
