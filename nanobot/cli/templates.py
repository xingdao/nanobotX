"""Workspace template management."""

from pathlib import Path

from nanobot.cli.app import console

WORKSPACE_TEMPLATES = Path(__file__).parent.parent.parent / "workspace"


def _load_template(name: str) -> str:
    """Load a template file by name from workspace directory."""
    template_path = WORKSPACE_TEMPLATES / name
    if template_path.exists():
        return template_path.read_text()
    return ""


def create_workspace_templates(workspace: Path):
    """Create default workspace template files."""
    templates = ["AGENTS.md", "SOUL.md", "USER.md"]
    
    for filename in templates:
        content = _load_template(filename)
        if not content:
            continue
        file_path = workspace / filename
        if not file_path.exists():
            file_path.write_text(content)
            console.print(f"  [dim]Created {filename}[/dim]")
    
    memory_dir = workspace / "memory"
    memory_dir.mkdir(exist_ok=True)
    memory_file = memory_dir / "MEMORY.md"
    if not memory_file.exists():
        memory_content = _load_template("memory/MEMORY.md")
        if memory_content:
            memory_file.write_text(memory_content)
            console.print("  [dim]Created memory/MEMORY.md[/dim]")