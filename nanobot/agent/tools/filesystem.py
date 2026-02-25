"""File system tools: read, write, edit, multi-edit."""

import difflib
from pathlib import Path

from nanobot.agent.tools.base import Tool
from nanobot.utils.helpers import get_workspace_path
from typing import Any, Dict

# Constants
MAX_FILE_SIZE = 20 * 1024  # 20KB

BINARY_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.ico', '.webp',
    '.pdf', '.zip', '.tar', '.gz', '.rar', '.7z',
    '.exe', '.dll', '.so', '.dylib', '.bin', '.dat',
    '.mp3', '.mp4', '.avi', '.mov', '.wav', '.flac',
    '.ppt', '.pptx', '.doc', '.docx', '.xls', '.xlsx'
}

# Magic numbers for binary file detection
MAGIC_NUMBERS = {
    b'\x89PNG': 'png',
    b'\xFF\xD8\xFF': 'jpeg',
    b'%PDF': 'pdf',
    b'PK\x03\x04': 'zip',
    b'\x7fELF': 'elf',
    b'MZ': 'exe',
}


# Helper functions
def _is_binary_file(content: bytes) -> bool:
    """Check if content is binary by detecting null bytes or patterns."""
    # Check for null bytes in first 8KB
    sample = content[:8192]
    if b'\x00' in sample:
        return True
    
    # Check magic numbers
    for magic, _ in MAGIC_NUMBERS.items():
        if sample.startswith(magic):
            return True
    
    return False


def _generate_diff(old_content: str, new_content: str, file_path: str) -> str:
    """Generate unified diff between two strings."""
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    
    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"{file_path}\t(before)",
        tofile=f"{file_path}\t(after)",
        lineterm=''
    )
    
    return ''.join(diff)


def _format_error(error_type: str, message: str, suggestion: str = None, details: dict = None) -> str:
    """Format error in a consistent structure."""
    return f"Error:{message} \nerror_type:{error_type} \nsuggestion:{suggestion} \ndetails:{details}"


def _format_success(message: str) -> str:
    """Format success response in a consistent structure."""
    if not message.startswith('Successfully'):
        return f"Successfully:{message}"
    return message


class ReadFileTool(Tool):
    """Tool to read file contents with optional line numbers and pagination."""
    
    @property
    def name(self) -> str:
        return "read_file"
    
    @property
    def description(self) -> str:
        return ("Read the contents of a file at the given path. "
                "Supports line numbers display and pagination for large files. "
                "Note: For large files, use offset and limit to read in chunks.")
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The absolute file path to read (must be absolute, not relative)"
                },
                "show_line_numbers": {
                    "type": "boolean",
                    "description": "Whether to prefix each line with line numbers (default: false)",
                    "default": False
                },
                "offset": {
                    "type": "number",
                    "description": "Optional: For text files, the 0-based line number to start reading from. Requires 'limit' to be set. Use for paginating through large files.(default: 0)",
                    "minimum": 0
                },
                "limit": {
                    "type": "number",
                    "description": "Optional: For text files, maximum number of lines to read. Use with 'offset' to paginate through large files. If omitted, reads the entire file (if feasible, up to a default 50).",
                    "minimum": 1
                }
            },
            "required": ["path"]
        }
    
    async def execute(self, path: str, show_line_numbers: bool = False,
                      offset: int = None, limit: int = None, **kwargs: Any) -> str:
        try:
            file_path = Path(path).expanduser()
            
            # Validation
            if not file_path.exists():
                return _format_error(
                    "file_not_found",
                    f"File not found: {path}",
                    suggestion="Check the file path and ensure it exists"
                )
            if not file_path.is_file():
                return _format_error(
                    "not_a_file",
                    f"Not a file: {path}",
                    suggestion=f"The path exists but is not a file. It may be a directory."
                )
            
            # Check file size
            file_size = file_path.stat().st_size
            if file_size > MAX_FILE_SIZE:
                if offset is None or limit is None:
                    return _format_error(
                        "file_too_large",
                        f"File is too large ({file_size / 1024:.2f}KB, limit is {MAX_FILE_SIZE / 1024}KB)",
                        suggestion="Use 'offset' and 'limit' parameters to read the file in chunks",
                        details={"file_size": file_size, "max_size": MAX_FILE_SIZE}
                    )
            
            # Read file
            content = file_path.read_text(encoding="utf-8")
            lines = content.splitlines(keepends=True)
            line_count = len(lines)
            # Apply pagination
            if (offset is not None) and (offset >= line_count):
                return _format_error(
                    "invalid_offset",
                    f"Offset {offset} exceeds file length ({line_count} lines)",
                    suggestion="Use a smaller offset value"
                )
            if offset is None:
                offset = 0
            if limit is None:
                limit = 50
            lines = lines[offset:offset + limit]
            
            # Add line numbers
            if show_line_numbers:
                start_line = offset if offset is not None else 0
                lines = [f"{start_line + i + 1:6d}\t{line}" for i, line in enumerate(lines)]
            
            result_text = ''.join(lines)
            
            if not result_text.strip() or result_text.startswith('Error'):
                return _format_success(
                    'Successfully reed:\n---filestart---\n' +
                    result_text +
                    '\n---fileend---'
                )
            return result_text
            
        except PermissionError:
            return _format_error(
                "permission_denied",
                f"Permission denied: {path}",
                suggestion="Check file permissions and try again"
            )
        except UnicodeDecodeError:
            return _format_error(
                "encoding_error",
                f"Failed to decode file with UTF-8 encoding: {path}",
                suggestion="The file may be binary or use a different encoding"
            )
        except Exception as e:
            return _format_error(
                "read_error",
                f"Error reading file: {str(e)}",
                details={"exception": str(e)}
            )


class WriteFileTool(Tool):
    """Tool to write content to a file."""
    
    @property
    def name(self) -> str:
        return "write_file"
    
    @property
    def description(self) -> str:
        return ("Write content to a text file at the given path. Auto Creates parent directories if needed. "
                "For existing files, the content will be completely overwritten by default. "
                "Use append parameter to append content instead of overwriting. "
                "Note: This operation is not reversible. Use with caution.")
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The absolute path to the file to write to"
                },
                "content": {
                    "type": "string",
                    "description": "The content to write to the file"
                },
                "append": {
                    "type": "boolean",
                    "description": "Optional: whether to append to file instead of overwriting (default: false)",
                    "default": False
                }
            },
            "required": ["path", "content"]
        }
    
    async def execute(self, path: str, content: str, append: bool = False, **kwargs: Any) -> str:
        try:
            # Validate that path is an absolute path
            if not Path(path).is_absolute():
                return _format_error(
                    "invalid_path",
                    f"Path must be absolute: {path}",
                    suggestion="Provide an absolute path starting with '/'"
                )
            
            file_path = Path(path).expanduser()
            # Check for binary content
            content_bytes = content.encode('utf-8')
            if _is_binary_file(content_bytes):
                return _format_error(
                    "binary_content",
                    "Content appears to be binary",
                    suggestion="Use binary write methods for binary files"
                )
            
            # Check if file exists and is binary
            if file_path.exists():
                if file_path.is_dir():
                    return _format_error(
                        "is_directory",
                        f"Path is a directory: {path}",
                        suggestion="Provide a file path, not a directory"
                    )
                
                existing_content = file_path.read_bytes()
                if _is_binary_file(existing_content):
                    return _format_error(
                        "binary_file",
                        f"Cannot write to binary file: {path}",
                        suggestion="Binary files should be handled with specialized tools"
                    )
            
            # Create parent directories
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write file with append mode if requested
            if append and file_path.exists():
                mode = 'a'  # append mode
                action = "appended"
            else:
                mode = 'w'  # write mode (overwrite)
                action = "wrote"
            
            with file_path.open(mode, encoding="utf-8") as f:
                f.write(content)
            
            return _format_success(
                f"Successfully {action} {len(content)} bytes to {path}",
            )
            
        except PermissionError:
            return _format_error(
                "permission_denied",
                f"Permission denied: {path}",
                suggestion="Check directory permissions and try again"
            )
        except Exception as e:
            return _format_error(
                "write_error",
                f"Error writing file: {str(e)}",
                details={"exception": str(e)}
            )


class EditFileTool(Tool):
    """Tool to edit a file by replacing text with precise control."""
    
    @property
    def name(self) -> str:
        return "edit_file"
    
    @property
    def description(self) -> str:
        return ("Edit a file by replacing old_text with new_text. The old_text must exist exactly in the file. "
                "Use expected_replacements to control how many occurrences to replace. "
                "This tool requires exact string matching including whitespace."
                "Edit no more than 20 lines at a time.")
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The absolute file path to edit"
                },
                "old_text": {
                    "type": "string",
                    "description": "The exact text to find and replace (must match exactly, including whitespace)"
                },
                "new_text": {
                    "type": "string",
                    "description": "The text to replace with"
                },
                "expected_replacements": {
                    "type": "number",
                    "description": "The number of occurrences expected to replace. If not provided, defaults to 1. If the actual count differs, the operation will fail.",
                    "minimum": 1,
                    "default": 1
                }
            },
            "required": ["path", "old_text", "new_text"]
        }
    
    async def execute(self, path: str, old_text: str, new_text: str, 
                      expected_replacements: int = 1, **kwargs: Any) -> str:
        try:
            file_path = Path(path).expanduser()
            
            # Validation
            if not file_path.exists():
                return _format_error(
                    "file_not_found",
                    f"File not found: {path}",
                    suggestion="Check the file path and ensure it exists"
                )
            
            # Check if binary
            existing_content = file_path.read_bytes()
            if _is_binary_file(existing_content):
                return _format_error(
                    "binary_file",
                    f"Cannot edit binary file: {path}",
                    suggestion="Binary files should be handled with specialized tools"
                )
            
            content = file_path.read_text(encoding="utf-8")
            
            # Validate old_text
            if not old_text:
                return _format_error(
                    "empty_old_text",
                    "old_text cannot be empty",
                    suggestion="Provide the exact text to be replaced"
                )
            
            if old_text == new_text:
                return _format_error(
                    "no_change",
                    "old_text and new_text are identical",
                    suggestion="Provide different content for new_text"
                )
            # Count occurrences
            count = content.count(old_text)
            if count == 0:
                return _format_error(
                    "text_not_found",
                    "old_text not found in file",
                    suggestion="Ensure exact match including whitespace. Consider reading the file first to verify the exact content."
                )
            
            # Validate expected replacements
            if count != expected_replacements:
                return _format_error(
                    "mismatch_replacements",
                    f"Expected {expected_replacements} replacement(s) but found {count} occurrence(s)",
                    suggestion=f"Set expected_replacements to {count} or provide more specific old_text to make it unique",
                    details={
                        "expected": expected_replacements,
                        "found": count
                    }
                )
            
            # Perform replacement
            new_content = content.replace(old_text, new_text, expected_replacements)
            file_path.write_text(new_content, encoding="utf-8")
            
            # Generate diff
            # diff = _generate_diff(content, new_content, path)
            
            return _format_success(
                f"Successfully edited {path}: replaced {expected_replacements} occurrence(s)",
            )
            
        except PermissionError:
            return _format_error(
                "permission_denied",
                f"Permission denied: {path}",
                suggestion="Check file permissions and try again"
            )
        except Exception as e:
            return _format_error(
                "edit_error",
                f"Error editing file: {str(e)}",
                details={"exception": str(e)}
            )


class GlobTool(Tool):
    """Tool to list files matching a glob pattern under a base directory."""

    @property
    def name(self) -> str:
        return "glob"

    @property
    def description(self) -> str:
        return (
            "Find files matching a glob pattern under a base directory. "
            "Supports ** for recursive matches. Returns matched paths."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The absolute base directory to search"
                },
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern to match (e.g. **/*.py)"
                },
                "include_dirs": {
                    "type": "boolean",
                    "description": "Whether to include directories in results (default: false)",
                    "default": False
                },
                "max_results": {
                    "type": "number",
                    "description": "Optional maximum number of results to return (default: 200)",
                    "minimum": 1,
                    "default": 200
                }
            },
            "required": ["path", "pattern"]
        }

    async def execute(
        self,
        path: str,
        pattern: str,
        include_dirs: bool = False,
        max_results: int = 200,
        **kwargs: Any
    ) -> str:
        try:
            if not Path(path).is_absolute():
                return _format_error(
                    "invalid_path",
                    f"Path must be absolute: {path}",
                    suggestion="Provide an absolute path starting with '/'"
                )

            base = Path(path).expanduser()
            if not base.exists():
                return _format_error(
                    "path_not_found",
                    f"Path not found: {path}",
                    suggestion="Check the base directory path"
                )
            if not base.is_dir():
                return _format_error(
                    "not_a_directory",
                    f"Path is not a directory: {path}",
                    suggestion="Provide a directory path for glob search"
                )

            results = []
            for item in base.glob(pattern):
                if not include_dirs and item.is_dir():
                    continue
                results.append(str(item))
                if len(results) >= max_results:
                    break

            if not results:
                return _format_success(
                    f"Successfully found 0 matches for pattern '{pattern}' in {path}"
                )

            if len(results) >= max_results:
                tail = f"\n... (truncated, showing {max_results} results)"
            else:
                tail = ""

            return _format_success(
                "Successfully found matches:\n" + "\n".join(results) + tail
            )

        except PermissionError:
            return _format_error(
                "permission_denied",
                f"Permission denied: {path}",
                suggestion="Check directory permissions and try again"
            )
        except Exception as e:
            return _format_error(
                "glob_error",
                f"Error during glob search: {str(e)}",
                details={"exception": str(e)}
            )
