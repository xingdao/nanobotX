"""Hook engine for agent lifecycle rules."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, DefaultDict, Literal

HookSignal = Literal["ok", "hint", "abort"]


@dataclass
class AgentContext:
    input: str
    action: str | None = None
    params: dict = field(default_factory=dict)
    action_history: list[dict[str, Any]] = field(default_factory=list)
    observation: str | None = None
    loop_count: int = 0
    hinted: set[str] = field(default_factory=set)
    pending_hint: str | None = None
    force_summary: bool = False


class HookResult:
    @staticmethod
    def hint(msg: str) -> tuple[HookSignal, str | None]:
        return ("hint", msg)

    @staticmethod
    def abort(msg: str) -> tuple[HookSignal, str | None]:
        return ("abort", msg)

    @staticmethod
    def ok() -> tuple[HookSignal, None]:
        return ("ok", None)


HookFn = Callable[[AgentContext], tuple[HookSignal, str | None] | None]
_hooks: DefaultDict[str, list[tuple[HookFn, bool]]] = defaultdict(list)


def hook(name: str, once: bool = False) -> Callable[[HookFn], HookFn]:
    """Register a hook function for a lifecycle stage."""
    def decorator(fn: HookFn) -> HookFn:
        _hooks[name].append((fn, once))
        return fn
    return decorator


def trigger(name: str, ctx: AgentContext) -> tuple[HookSignal, str | None]:
    """Trigger hooks for a lifecycle stage."""
    for fn, once in _hooks.get(name, []):
        if once and fn.__name__ in ctx.hinted:
            continue
        result = fn(ctx)
        if result:
            action, msg = result
            if once:
                ctx.hinted.add(fn.__name__)
            if action in ("abort", "hint"):
                if action == "hint":
                    ctx.pending_hint = msg
                return (action, msg)
    return ("ok", None)
