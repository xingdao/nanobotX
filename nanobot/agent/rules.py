"""Default hook rules for the agent loop."""

from __future__ import annotations

import re

from nanobot.agent.hooks import HookResult, hook

_REGISTERED = False


def register_default_rules() -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    _REGISTERED = True

    # The decorators register at import time, so nothing else is needed here.
    return


@hook("before_act")
def read_before_edit(ctx):
    if ctx.action != "edit_file":
        return None
    target = ctx.params.get("path")
    if not target:
        return None
    for item in ctx.action_history:
        if item.get("name") != "read_file":
            continue
        if item.get("params", {}).get("path") == target:
            return None
    return HookResult.hint(f"建议先读取文件`{target}`内容再写入")


@hook("before_act")
def block_secrets(ctx):
    if ctx.action != "exec":
        return None
    cmd = ctx.params.get("command", "")
    if re.search(r"cat.*(\.env|\.ssh/|API_KEY)", cmd):
        return HookResult.abort("禁止访问敏感文件")
    return None

# @hook("before_act", once=True)
# def read_skill_before_write(ctx):
#     if ctx.action != "write_file":
#         return None
#     return HookResult.hint("检测到`文件写入`请先阅读规范 read_skill(pre-exec-edit)")

@hook("before_plan", once=True)
def suggest_skill(ctx):
    if not ctx.action_history:
        return None
    if any(kw in ctx.input for kw in ["自举"]):
        return HookResult.hint("检测到`自举`是否先 read_skill(self-improvement)")
    
    if any(kw in ctx.input for kw in ["联网搜索"]):
        return HookResult.hint("检测到`联网搜索`是否先 read_skill(tavily-search)")
    
    return None


@hook("before_act")
def suggest_grep_for_repeated_reads(ctx):
    """Suggest using grep to get line count when repeatedly reading same file with increasing limits."""
    if ctx.action != "read_file":
        return None

    target_path = ctx.params.get("path")
    current_limit = ctx.params.get("limit")

    if not target_path:
        return None

    # Check if we have at least 2 previous actions in history
    if len(ctx.action_history) < 2:
        return None

    # Get last two actions
    last_action = ctx.action_history[-1]  # most recent
    second_last_action = ctx.action_history[-2] if len(ctx.action_history) >= 2 else None

    # Check if both previous actions are read_file for the same path
    if (last_action.get("name") != "read_file" or
        second_last_action is None or
        second_last_action.get("name") != "read_file"):
        return None

    last_params = last_action.get("params", {})
    second_last_params = second_last_action.get("params", {})

    if (last_params.get("path") != target_path or
        second_last_params.get("path") != target_path):
        return None

    # Now we have three consecutive reads of the same file (current + last two)
    # Check if limits are increasing
    limits = []

    # Get limit from second last read
    limit2 = second_last_params.get("limit")
    if limit2 is not None:
        limits.append(limit2)

    # Get limit from last read
    limit1 = last_params.get("limit")
    if limit1 is not None:
        limits.append(limit1)

    # Get current limit
    if current_limit is not None:
        limits.append(current_limit)

    # Need all three limits to check increasing pattern
    if len(limits) != 3:
        return None

    # Check if limits are strictly increasing
    is_increasing = limits[0] < limits[1] < limits[2]

    if is_increasing:
        return HookResult.hint(
            f"检测到连续读取文件 {target_path} 三次且每次 limit 增加。"
            f"建议先使用 rg/grep 通过关键词定位行数"
        )

    return None
