import os

# Directories to completely skip
EXCLUDED_DIRS = {'.venv', '__pycache__', '.git'}

# Only these directories will be shown directly under the project root
ALLOWED_TOP_LEVEL_DIRS = {'secondstateapp', 'secondstate', 'static', 'staticfiles', 'templates'}

# Only these file types will be shown
ALLOWED_FILE_EXTS = {'.py', '.html', '.css'}


def build_tree(start_path, indent="", is_root=False, lines=None):
    if lines is None:
        lines = []

    # List items in this directory
    try:
        items = sorted(os.listdir(start_path))
    except PermissionError:
        return lines  # skip directories we can't access

    filtered_items = []

    for item in items:
        path = os.path.join(start_path, item)

        if os.path.isdir(path):
            # Skip excluded directories
            if item in EXCLUDED_DIRS:
                continue
            # At the root level, only keep the allowed directories
            if is_root and item not in ALLOWED_TOP_LEVEL_DIRS:
                continue
            filtered_items.append((item, path, True))  # (name, path, is_dir=True)
        else:
            # Only keep .py and .html files
            _, ext = os.path.splitext(item)
            if ext in ALLOWED_FILE_EXTS:
                filtered_items.append((item, path, False))  # (name, path, is_dir=False)

    count = len(filtered_items)

    for index, (item, path, is_dir) in enumerate(filtered_items):
        connector = "└── " if index == count - 1 else "├── "
        lines.append(indent + connector + item)

        if is_dir:
            # Prepare indent for children
            extension = "    " if index == count - 1 else "│   "
            build_tree(path, indent + extension, is_root=False, lines=lines)
        else:
            # Optionally include file contents:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read().splitlines()
                file_indent = indent + ("    " if index == count - 1 else "│   ")
                for line in content:
                    lines.append(file_indent + line)
            except Exception:
                # silently skip files we can't read
                pass

    return lines


def main():
    root = "."  # change to your project path if needed
    abs_root = os.path.abspath(root)

    # Only show the project folder name (last part of the path)
    project_name = os.path.basename(abs_root.rstrip(os.sep)) or abs_root

    lines = [project_name]
    lines = build_tree(abs_root, indent="", is_root=True, lines=lines)

    tree_text = "\n".join(lines)

    # Print to console
    print(tree_text)

    # Also write to a .txt file
    out_file = "project_tree.txt"
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(tree_text)

    print(f"\nTree written to {out_file}")


if __name__ == "__main__":
    main()
