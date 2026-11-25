"""Static-only checks for code snippets proposed in the Silva System Panel."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

_FORBIDDEN_IMPORTS = frozenset(
    {
        "builtins",
        "code",
        "codeop",
        "ctypes",
        "ftplib",
        "http",
        "importlib",
        "marshal",
        "multiprocessing",
        "pickle",
        "pdb",
        "requests",
        "shutil",
        "smtplib",
        "socket",
        "ssl",
        "subprocess",
        "urllib",
        "webbrowser",
    }
)

_WARN_IMPORTS = frozenset({"os", "pathlib", "sys", "tempfile"})

_FORBIDDEN_CALLS = frozenset({"eval", "exec", "compile", "__import__"})

_WARN_CALLS = frozenset({"globals", "locals", "vars", "getattr", "setattr", "delattr"})

_RISKY_TEXT = (
    "rm -rf",
    "del /f",
    "takeown",
    "icacls",
    "taskkill",
    "powershell -enc",
    "curl ",
    "wget ",
    "os.system",
    "subprocess.",
    "socket.",
    "requests.",
)


@dataclass
class CodeCheckResult:
    ok: bool
    syntax_ok: bool
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "syntax_ok": self.syntax_ok,
            "issues": list(self.issues),
            "warnings": list(self.warnings),
            "summary": self.summary,
        }


class _SnippetVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.issues: list[str] = []
        self.warnings: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root = str(alias.name).split(".", 1)[0]
            if root in _FORBIDDEN_IMPORTS:
                self.issues.append(f"Import '{alias.name}' is blocked for proposed code.")
            elif root in _WARN_IMPORTS:
                self.warnings.append(f"Import '{alias.name}' needs owner review because it can access the system.")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = str(node.module or "")
        root = module.split(".", 1)[0]
        if root in _FORBIDDEN_IMPORTS:
            self.issues.append(f"Import '{module}' is blocked for proposed code.")
        elif root in _WARN_IMPORTS:
            self.warnings.append(f"Import '{module}' needs owner review because it can access the system.")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = ""
        func = node.func
        if isinstance(func, ast.Name):
            name = str(func.id)
        elif isinstance(func, ast.Attribute):
            name = str(func.attr)
        if name in _FORBIDDEN_CALLS:
            self.issues.append(f"Call '{name}(' is blocked for proposed code.")
        elif name in _WARN_CALLS:
            self.warnings.append(f"Call '{name}(' needs owner review because it can bypass normal access.")
        self.generic_visit(node)


def check_python_snippet(source: str) -> CodeCheckResult:
    """Parse and inspect a snippet. Never executes it and never writes it to disk."""
    text = str(source or "")
    if not text.strip():
        return CodeCheckResult(
            ok=False,
            syntax_ok=False,
            issues=["There is no code to check."],
            summary="No code supplied.",
        )

    issues: list[str] = []
    warnings: list[str] = []
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        detail = exc.msg or "invalid syntax"
        return CodeCheckResult(
            ok=False,
            syntax_ok=False,
            issues=[f"Syntax error on line {exc.lineno or 1}: {detail}"],
            summary="Syntax check failed.",
        )

    visitor = _SnippetVisitor()
    visitor.visit(tree)
    issues.extend(visitor.issues)
    warnings.extend(visitor.warnings)

    lowered = text.lower()
    for marker in _RISKY_TEXT:
        if marker in lowered:
            warning = f"Code contains '{marker.strip()}'; owner review required."
            if warning not in warnings:
                warnings.append(warning)

    ok = not issues
    if ok and warnings:
        summary = f"Syntax OK. {len(warnings)} owner-review warning(s)."
    elif ok:
        summary = "Syntax OK. No blocked patterns found."
    else:
        summary = f"{len(issues)} blocked issue(s) found."
    return CodeCheckResult(ok=ok, syntax_ok=True, issues=issues, warnings=warnings, summary=summary)


def format_check_result(result: CodeCheckResult) -> str:
    lines = [result.summary]
    if result.issues:
        lines.append("")
        lines.append("Blocked issues:")
        lines.extend(f"- {item}" for item in result.issues)
    if result.warnings:
        lines.append("")
        lines.append("Owner-review warnings:")
        lines.extend(f"- {item}" for item in result.warnings)
    lines.append("")
    lines.append("Nothing was executed. Code is never added to Silva without owner approval.")
    return "\n".join(lines)
