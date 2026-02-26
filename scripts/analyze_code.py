#!/usr/bin/env python3
"""代码分析脚本 - 分析Python文件的函数复杂度"""

from __future__ import annotations

import ast
from pathlib import Path
from dataclasses import dataclass
from typing import Optional


@dataclass
class FunctionInfo:
    name: str
    start_line: int
    end_line: int
    lines: int

    @property
    def is_method(self) -> bool:
        return False


@dataclass
class ClassInfo:
    name: str
    start_line: int
    end_line: int
    methods: list[FunctionInfo]


@dataclass
class FileStats:
    path: Path
    total_lines: int
    functions: list[FunctionInfo]
    classes: list[ClassInfo]

    @property
    def all_functions(self) -> list[FunctionInfo]:
        result = list(self.functions)
        for cls in self.classes:
            result.extend(cls.methods)
        return result

    @property
    def function_count(self) -> int:
        return len(self.all_functions)

    @property
    def avg_function_length(self) -> float:
        funcs = self.all_functions
        if not funcs:
            return 0.0
        return sum(f.lines for f in funcs) / len(funcs)

    @property
    def max_function_length(self) -> int:
        funcs = self.all_functions
        if not funcs:
            return 0
        return max(f.lines for f in funcs)

    @property
    def longest_function(self) -> Optional[FunctionInfo]:
        funcs = self.all_functions
        if not funcs:
            return None
        return max(funcs, key=lambda f: f.lines)


class CodeAnalyzer(ast.NodeVisitor):
    def __init__(self, source_lines: list[str]):
        self.source_lines = source_lines
        self.functions: list[FunctionInfo] = []
        self.classes: list[ClassInfo] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._process_function(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._process_function(node, is_async=True)
        self.generic_visit(node)

    def _process_function(self, node, is_async: bool = False) -> None:
        start_line = node.lineno
        end_line = self._find_end_line(node)
        lines = end_line - start_line + 1

        func_info = FunctionInfo(
            name=node.name,
            start_line=start_line,
            end_line=end_line,
            lines=lines
        )
        self.functions.append(func_info)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        start_line = node.lineno
        end_line = self._find_end_line(node)

        class_visitor = ClassMethodVisitor(self.source_lines)
        class_visitor.visit(node)

        class_info = ClassInfo(
            name=node.name,
            start_line=start_line,
            end_line=end_line,
            methods=class_visitor.methods
        )
        self.classes.append(class_info)

    def _find_end_line(self, node) -> int:
        max_line = node.lineno
        for child in ast.walk(node):
            if hasattr(child, 'lineno'):
                max_line = max(max_line, child.lineno)
            if hasattr(child, 'end_lineno') and child.end_lineno:
                max_line = max(max_line, child.end_lineno)
        return max_line


class ClassMethodVisitor(ast.NodeVisitor):
    def __init__(self, source_lines: list[str]):
        self.source_lines = source_lines
        self.methods: list[FunctionInfo] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._process_method(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._process_method(node)
        self.generic_visit(node)

    def _process_method(self, node) -> None:
        start_line = node.lineno
        end_line = self._find_end_line(node)
        lines = end_line - start_line + 1

        method_info = FunctionInfo(
            name=node.name,
            start_line=start_line,
            end_line=end_line,
            lines=lines
        )
        self.methods.append(method_info)

    def _find_end_line(self, node) -> int:
        max_line = node.lineno
        for child in ast.walk(node):
            if hasattr(child, 'lineno'):
                max_line = max(max_line, child.lineno)
            if hasattr(child, 'end_lineno') and child.end_lineno:
                max_line = max(max_line, child.end_lineno)
        return max_line


def analyze_file(file_path: Path) -> Optional[FileStats]:
    try:
        content = file_path.read_text(encoding='utf-8')
        source_lines = content.splitlines()

        tree = ast.parse(content)
        analyzer = CodeAnalyzer(source_lines)
        analyzer.visit(tree)

        return FileStats(
            path=file_path,
            total_lines=len(source_lines),
            functions=analyzer.functions,
            classes=analyzer.classes
        )
    except SyntaxError as e:
        print(f"语法错误 {file_path}: {e}")
        return None
    except Exception as e:
        print(f"分析错误 {file_path}: {e}")
        return None


def format_path(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def print_report(stats_list: list[FileStats], base_path: Path) -> None:
    print("\n" + "=" * 80)
    print("代码分析报告")
    print("=" * 80)

    print("\n【最大文件 (按行数)】")
    print("-" * 80)
    by_lines = sorted(stats_list, key=lambda s: s.total_lines, reverse=True)[:10]
    print(f"{'文件':<50} {'行数':>8} {'函数数':>8} {'平均函数长度':>12}")
    print("-" * 80)
    for stats in by_lines:
        path_str = format_path(stats.path, base_path)
        print(f"{path_str:<50} {stats.total_lines:>8} {stats.function_count:>8} {stats.avg_function_length:>12.1f}")

    print("\n【函数最多的文件】")
    print("-" * 80)
    by_func_count = sorted(stats_list, key=lambda s: s.function_count, reverse=True)[:10]
    print(f"{'文件':<50} {'函数数':>8} {'总行数':>8} {'平均函数长度':>12}")
    print("-" * 80)
    for stats in by_func_count:
        path_str = format_path(stats.path, base_path)
        print(f"{path_str:<50} {stats.function_count:>8} {stats.total_lines:>8} {stats.avg_function_length:>12.1f}")

    print("\n【函数平均长度最长的文件】")
    print("-" * 80)
    with_funcs = [s for s in stats_list if s.function_count > 0]
    by_avg_length = sorted(with_funcs, key=lambda s: s.avg_function_length, reverse=True)[:10]
    print(f"{'文件':<50} {'平均长度':>10} {'最大函数':>10} {'函数数':>8}")
    print("-" * 80)
    for stats in by_avg_length:
        path_str = format_path(stats.path, base_path)
        longest = stats.longest_function
        longest_name = f"{longest.name}({longest.lines})" if longest else "N/A"
        print(f"{path_str:<50} {stats.avg_function_length:>10.1f} {stats.max_function_length:>10} {stats.function_count:>8}")

    print("\n【最长的函数 (超过30行)】")
    print("-" * 80)
    long_functions: list[tuple[FileStats, FunctionInfo]] = []
    for stats in stats_list:
        for func in stats.all_functions:
            if func.lines > 30:
                long_functions.append((stats, func))

    long_functions.sort(key=lambda x: x[1].lines, reverse=True)
    long_functions = long_functions[:15]
    print(f"{'文件':<40} {'函数名':<25} {'行数':>6} {'位置':>12}")
    print("-" * 80)
    for stats, func in long_functions:
        path_str = format_path(stats.path, base_path)
        location = f"L{func.start_line}-L{func.end_line}"
        print(f"{path_str:<40} {func.name:<25} {func.lines:>6} {location:>12}")

    print("\n【优化建议】")
    print("-" * 80)

    candidates = []
    for stats in stats_list:
        score = 0
        reasons = []

        if stats.total_lines > 400:
            score += 3
            reasons.append(f"文件过大({stats.total_lines}行)")
        if stats.function_count > 15:
            score += 2
            reasons.append(f"函数过多({stats.function_count}个)")
        if stats.avg_function_length > 25:
            score += 2
            reasons.append(f"函数平均过长({stats.avg_function_length:.1f}行)")
        if stats.max_function_length > 60:
            score += 2
            reasons.append(f"存在超长函数({stats.max_function_length}行)")

        if score > 0:
            candidates.append((stats, score, reasons))

    candidates.sort(key=lambda x: x[1], reverse=True)

    for stats, score, reasons in candidates[:5]:
        path_str = format_path(stats.path, base_path)
        print(f"\n{path_str} (优先级: {'★' * min(score, 5)})")
        for reason in reasons:
            print(f"  - {reason}")

    print("\n" + "=" * 80)
    print("分析完成")
    print("=" * 80)


def main():
    project_root = Path(__file__).parent.parent
    nanobot_path = project_root / "nanobot"

    py_files = list(nanobot_path.rglob("*.py"))

    print(f"分析目录: {nanobot_path}")
    print(f"找到 {len(py_files)} 个Python文件")

    stats_list: list[FileStats] = []
    for py_file in py_files:
        stats = analyze_file(py_file)
        if stats:
            stats_list.append(stats)

    print_report(stats_list, project_root)


if __name__ == "__main__":
    main()