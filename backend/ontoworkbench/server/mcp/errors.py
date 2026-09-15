"""REST envelope -> MCP tool error mapping (spec §8): 指路型 messages."""

from __future__ import annotations

from mcp.server.mcpserver.exceptions import ToolError

_POINTERS = {
    "NOT_FOUND": "not found — call list_ontologies first to see valid ids",
    "SHAPES_REQUIRED": (
        "no SHACL shapes saved for this ontology yet — add them in the web UI (校验 view) first"
    ),
}


class LoopbackError(Exception):
    """A non-OK REST envelope surfaced through the loopback."""

    def __init__(self, code: str, message: str, hint: str | None) -> None:
        """Keep the envelope code/message/hint for the tool-error mapping."""
        self.code, self.message, self.hint = code, message, hint
        super().__init__(f"{code}: {message}")


def to_tool_error(exc: LoopbackError) -> ToolError:
    """Map to a one-sentence tool error; REST codes keep their wording (spec §8)."""
    if exc.code == "NOT_FOUND" and "entities" in (exc.hint or ""):
        return ToolError(f"Entity not found — try search_entities. ({exc.message})")
    pointer = _POINTERS.get(exc.code)
    text = f"{exc.message}. {pointer}" if pointer else f"{exc.message}"
    if exc.hint:
        text += f" ({exc.hint})"
    return ToolError(text[:500])
