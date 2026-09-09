"""File tools over the ShopAI playground repo (or the run's isolated worktree)."""

from __future__ import annotations

from app.config import settings
from app.runtime.workspace import current_shopai_path
from app.tools.registry import ToolResult, registry

WRITE_SUFFIXES = {".py", ".md", ".ini", ".txt", ".yml", ".yaml", ".json", ".sql", ".cfg", ".toml"}
WRITE_MAX_BYTES = 64_000


def safe_path(rel: str):
    root = current_shopai_path()
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
    root = current_shopai_path()
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


def _tool_write_file(args: dict) -> ToolResult:
    if settings.agent_phase < 4:
        return ToolResult(
            "write_file",
            False,
            f"write_file 需要 Phase 4（当前 AGENT_PHASE={settings.agent_phase}）。",
            blocked=True,
        )
    rel = args.get("path") or ""
    content = args.get("content")
    if content is None or not isinstance(content, str):
        return ToolResult("write_file", False, "content (string) required")
    try:
        path = safe_path(rel)
    except PermissionError as e:
        return ToolResult("write_file", False, str(e))
    if path.suffix not in WRITE_SUFFIXES:
        return ToolResult("write_file", False, f"suffix not allowed: {path.suffix or '(none)'}")
    if len(content.encode("utf-8")) > WRITE_MAX_BYTES:
        return ToolResult("write_file", False, f"content too large (> {WRITE_MAX_BYTES} bytes)")
    if not path.exists() and rel.startswith("/"):
        return ToolResult("write_file", False, "use a relative path")
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    path.write_text(content, encoding="utf-8")
    note = "overwrote" if existed else "created"
    return ToolResult("write_file", True, f"{note} {rel} ({len(content)} chars)")


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
    registry.register(
        "write_file",
        "Write a file in the current (isolated) workspace. Phase 4+ only.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path"},
                "content": {"type": "string", "description": "Full file content"},
            },
            "required": ["path", "content"],
        },
        _tool_write_file,
        phase=4,
        readonly=False,
    )
