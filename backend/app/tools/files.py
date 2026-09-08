"""Read-only file tools over the ShopAI playground repo."""

from __future__ import annotations

from app.config import settings
from app.tools.registry import ToolResult, registry


def safe_path(rel: str):
    root = settings.shopai_path
    target = (root / rel).resolve() if rel else root
    try:
        target.relative_to(root)
    except ValueError:
        raise PermissionError(f"path escapes sandbox: {rel}")
    return target


def _tool_list_dir(args: dict) -> ToolResult:
    rel = args.get("path") or "."
    try:
        path = safe_path(rel)
    except PermissionError as e:
        return ToolResult("list_dir", False, str(e))
    if not path.exists():
        return ToolResult("list_dir", False, f"not found: {rel}")
    if path.is_file():
        return ToolResult("list_dir", True, str(path.name))
    names = []
    for p in sorted(path.iterdir()):
        if p.name.startswith(".") or p.name in {"__pycache__", ".venv", "node_modules"}:
            continue
        suffix = "/" if p.is_dir() else ""
        names.append(p.name + suffix)
    return ToolResult("list_dir", True, "\n".join(names) or "(empty)")


def _tool_read_file(args: dict) -> ToolResult:
    rel = args.get("path") or ""
    try:
        path = safe_path(rel)
    except PermissionError as e:
        return ToolResult("read_file", False, str(e))
    if not path.is_file():
        return ToolResult("read_file", False, f"not a file: {rel}")
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) > 12000:
        text = text[:12000] + "\n...[truncated]"
    return ToolResult("read_file", True, text)


def _tool_search_code(args: dict) -> ToolResult:
    query = (args.get("query") or "").strip()
    if not query:
        return ToolResult("search_code", False, "query required")
    root = settings.shopai_path
    hits: list[str] = []
    for path in root.rglob("*"):
        if path.suffix not in {".py", ".md", ".sql", ".yml", ".yaml", ".txt", ".ini"}:
            continue
        if any(part in {"__pycache__", ".venv"} for part in path.parts):
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        rel = path.relative_to(root)
        for i, line in enumerate(lines, 1):
            if query.lower() in line.lower():
                hits.append(f"{rel}:{i}: {line.strip()}")
                if len(hits) >= 40:
                    return ToolResult("search_code", True, "\n".join(hits))
    return ToolResult("search_code", True, "\n".join(hits) if hits else "no matches")


def register_file_tools() -> None:
    registry.register(
        "list_dir",
        "List files under ShopAI repo (relative path).",
        {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Relative directory, default ."}},
        },
        _tool_list_dir,
        phase=1,
    )
    registry.register(
        "read_file",
        "Read a source file from ShopAI repo.",
        {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        _tool_read_file,
        phase=1,
    )
    registry.register(
        "search_code",
        "Search ShopAI source for a keyword (order, payment, Kafka, status, etc).",
        {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        _tool_search_code,
        phase=1,
    )
