"""Built-in tool for safe mathematical calculations using AST parsing."""

import ast
import operator
from typing import Any, Dict
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool


class CalculatorTool(BaseTool):
    """Safe arithmetic expression evaluator using AST parsing."""

    name = "calculator"
    description = "Perform simple mathematical calculations safely. Supports +, -, *, /, ** (exponentiation), and parentheses."
    safety_level = SafetyLevel.SAFE
    parameters: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "The mathematical expression to evaluate, e.g. '125 * 48' or '(3 + 5) ** 2'",
            }
        },
        "required": ["expression"],
    }

    # Supported AST operators mapping to Python operator functions
    _operators = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos,
    }

    def _eval(self, node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return self._eval(node.body)
        elif isinstance(node, ast.Num):  # Python < 3.8
            return float(node.n)
        elif isinstance(node, ast.Constant):  # Python >= 3.8
            if not isinstance(node.value, (int, float)):
                raise TypeError(f"Invalid constant type: {type(node.value).__name__}")
            return float(node.value)
        elif isinstance(node, ast.BinOp):
            left = self._eval(node.left)
            right = self._eval(node.right)
            op_type = type(node.op)

            if op_type not in self._operators:
                raise TypeError(f"Unsupported binary operator: {op_type.__name__}")

            # DoS check for exponentiation
            if op_type == ast.Pow:
                if right > 1000:
                    raise ValueError("Exponent too large (maximum is 1000 to prevent DoS)")
                if left > 1e6 and right > 10:
                    raise ValueError("Base and exponent combination too large to prevent DoS")

            return float(self._operators[op_type](left, right))
        elif isinstance(node, ast.UnaryOp):
            operand = self._eval(node.operand)
            op_type = type(node.op)
            if op_type not in self._operators:
                raise TypeError(f"Unsupported unary operator: {op_type.__name__}")
            return float(self._operators[op_type](operand))
        else:
            raise TypeError(f"Unsupported AST node: {type(node).__name__}")

    def execute(self, expression: str, **kwargs: Any) -> ToolResult:
        expr_clean = expression.strip()
        if not expr_clean:
            return ToolResult(
                name=self.name,
                content="Error: Empty expression.",
                is_error=True,
                safety_level=self.safety_level,
            )

        if len(expr_clean) > 500:
            return ToolResult(
                name=self.name,
                content="Error: Expression exceeds maximum length of 500 characters.",
                is_error=True,
                safety_level=self.safety_level,
            )

        try:
            # Parse the expression into an AST
            tree = ast.parse(expr_clean, mode="eval")
            result = self._eval(tree)
            # Format the output cleanly
            if result.is_integer():
                result_str = str(int(result))
            else:
                result_str = f"{result:.6f}".rstrip("0").rstrip(".")

            return ToolResult(
                name=self.name,
                content=result_str,
                is_error=False,
                safety_level=self.safety_level,
            )
        except ZeroDivisionError:
            return ToolResult(
                name=self.name,
                content="Error: Division by zero.",
                is_error=True,
                safety_level=self.safety_level,
            )
        except Exception as e:
            return ToolResult(
                name=self.name,
                content=f"Error: Invalid expression or unsupported syntax. Details: {str(e)}",
                is_error=True,
                safety_level=self.safety_level,
            )
