"""quasi core runtime helpers.

This package is deliberately tiny: it provides shared runtime plumbing for the
script entrypoints, but it does not know about vault schemas or any domain
workflow.
"""

from .core import (
    FrontmatterDoc,
    atomic_write_text,
    dump_frontmatter,
    load_script_module,
    plugin_root,
    print_json,
    project_root,
    read_frontmatter,
    resolve_project_path,
    write_frontmatter,
    write_json,
)

__all__ = [
    "FrontmatterDoc",
    "atomic_write_text",
    "dump_frontmatter",
    "load_script_module",
    "plugin_root",
    "print_json",
    "project_root",
    "read_frontmatter",
    "resolve_project_path",
    "write_frontmatter",
    "write_json",
]
