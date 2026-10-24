"""Normalize supported file payload shapes independently of provider tool names.

Names are hints for reads and incomplete legacy calls, never authority to hide a
write. Unknown path-only operations are unsupported, not implicitly reads.
"""
from dataclasses import dataclass
import os
from typing import Optional

PATH_KEYS = ("TargetFile", "AbsolutePath", "file_path", "filePath", "target_file", "path", "Path", "file", "filename")
CONTENT_KEYS = ("CodeContent", "Content", "content", "contents", "code", "text")
OLD_KEYS = ("TargetContent", "Target", "target", "old_string", "old_str", "search")
NEW_KEYS = ("ReplacementContent", "Replacement", "replacement", "new_string", "new_str", "replace")
CHUNK_KEYS = ("ReplacementChunks", "edits", "patches")
READ_NAMES = frozenset(("view_file", "read_file", "read_file_content", "view", "read"))
WRITE_NAMES = frozenset(("write_to_file", "write_file", "write"))
EDIT_NAMES = frozenset(("replace_file_content", "edit_file", "edit", "apply_diff"))


class UnsupportedOperation(ValueError):
    """The guard cannot safely interpret this file operation."""


@dataclass(frozen=True)
class FileOperation:
    kind: str
    path: str
    args: dict


def _value(args: dict, keys: tuple):
    present = [args[key] for key in keys if key in args]
    if not present:
        return None
    if any(not isinstance(value, str) for value in present):
        raise UnsupportedOperation("File paths and text arguments must be strings")
    if any(value != present[0] for value in present[1:]):
        raise UnsupportedOperation("Conflicting aliases in file operation")
    return present[0]


def normalize_operation(tool_name: str, args: dict) -> Optional[FileOperation]:
    """Return WRITE/EDIT/MULTI_EDIT/READ, None for non-file tools, or reject.

    Empty strings are values (especially deletion replacements), not missing
    arguments. URI, unified diff, notebook and multi-file formats need adapters.
    """
    if not isinstance(args, dict) or not isinstance(tool_name, str):
        raise UnsupportedOperation("Invalid tool name or argument object")
    path = _value(args, PATH_KEYS)
    name = tool_name.lower()
    known = name in READ_NAMES | WRITE_NAMES | EDIT_NAMES | {"multi_replace_file_content"}
    if path is None and not known:
        if any(key in args for key in ("patch", "diff", "uri", "input", "notebook_path")) and any(
            word in name for word in ("patch", "diff", "file", "notebook")
        ):
            raise UnsupportedOperation("Unsupported patch, URI or notebook operation")
        return None
    if not path or "\x00" in path or "://" in path:
        raise UnsupportedOperation("Missing or unsupported file path")
    content = _value(args, CONTENT_KEYS)
    old = _value(args, OLD_KEYS)
    new = _value(args, NEW_KEYS)
    lists = [args[key] for key in CHUNK_KEYS if key in args]
    forms = int(content is not None) + int(old is not None or new is not None) + int(bool(lists))
    if forms > 1:
        raise UnsupportedOperation("Ambiguous write/edit payload")
    canonical = {"TargetFile": path}
    if content is not None:
        return FileOperation("WRITE", path, {**canonical, "CodeContent": content})
    if lists:
        if len(lists) != 1 or not isinstance(lists[0], list) or not lists[0]:
            raise UnsupportedOperation("Expected one nonempty edit list")
        chunks = []
        for chunk in lists[0]:
            if not isinstance(chunk, dict) or any(key in chunk for key in PATH_KEYS):
                raise UnsupportedOperation("Unsupported multi-file or malformed edit chunk")
            op = normalize_operation("edit_file", {**chunk, "TargetFile": path})
            if op.kind != "EDIT":
                raise UnsupportedOperation("Edit list contains a non-edit operation")
            chunks.append({key: value for key, value in op.args.items() if key != "TargetFile"})
        return FileOperation("MULTI_EDIT", path, {**canonical, "ReplacementChunks": chunks})
    if old is not None or new is not None:
        if old is None or new is None:
            raise UnsupportedOperation("Both search and replacement text are required")
        multiple = args.get("AllowMultiple", args.get("replace_all", False))
        if not isinstance(multiple, bool):
            raise UnsupportedOperation("replace_all must be boolean")
        bounds = {}
        for key in ("StartLine", "EndLine"):
            if key in args:
                if type(args[key]) is not int or args[key] < 1:
                    raise UnsupportedOperation("Edit line bounds must be positive integers")
                bounds[key] = args[key]
        return FileOperation("EDIT", path, {**canonical, "TargetContent": old,
                             "ReplacementContent": new, "AllowMultiple": multiple, **bounds})
    if any(key in args for key in ("patch", "diff", "input", "operation", "action", "destination")):
        raise UnsupportedOperation("Unsupported file operation schema")
    if name in READ_NAMES:
        return FileOperation("READ", path, canonical)
    raise UnsupportedOperation("Unrecognized file operation; a path alone does not imply a read")


def provider_tool_call(name: str, args: dict, cwd: str) -> Optional[dict]:
    """Translate structured provider calls without dropping unknown schemas.

    Invalid calls reach the engine unchanged so its normal deny response and
    audit path handle them. Names are canonicalized only after classification.
    """
    try:
        operation = normalize_operation(name, args)
    except UnsupportedOperation:
        return {"name": name, "args": args}
    if operation is None:
        if isinstance(args, dict) and any(key in args for key in ("command", "CommandLine", "cmd", "script")):
            return {"name": name, "args": args}
        return None
    target = operation.path
    if not os.path.isabs(target):
        target = os.path.abspath(os.path.join(cwd, target))
    if operation.kind == "READ" and "env" not in os.path.basename(target).lower():
        return None
    canonical_name = {"WRITE": "write_to_file", "EDIT": "replace_file_content",
                      "MULTI_EDIT": "multi_replace_file_content", "READ": "read_file"}[operation.kind]
    return {"name": canonical_name, "args": {**operation.args, "TargetFile": target}}
