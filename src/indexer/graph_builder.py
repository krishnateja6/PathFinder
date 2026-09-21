"""Build the call/import/inherits/defines graph from a repo's AST.

Resolves the statically-common cases per the spec's v1 scope: direct
function calls, `self`/`cls` method calls (with single-inheritance
fallback when a method isn't overridden), calls through a locally
instantiated variable (`x = Foo(); x.method()`), class-instantiation
calls resolved to `__init__`, and absolute/relative intra-repo imports.

Known, deliberate limitations (dynamic dispatch is a research problem
in itself — see spec section 11): calls through a module alias
(`module.func()`), decorator invocation calls, `*args`/`**kwargs`
dispatch, `getattr`-based access, and multi-base MRO (we walk bases
depth-first, first match wins) are left unresolved. Star imports and
imports of names we can't statically find in the target module are
also left unresolved.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx
from tree_sitter import Node

from src.indexer.parser import CodeChunk, iter_python_files, new_parser, parse_file_with_nodes

_DEF_TYPES = {"function_definition", "class_definition"}


def _text(node: Node) -> str:
    """A named node's source text, decoded. tree-sitter types `.text` as
    optional for nodes representing a missing/error range, but every node
    we call this on here was just matched by name/type as a real part of
    the tree, so it always has real backing bytes."""
    assert node.text is not None
    return node.text.decode("utf-8")


@dataclass
class _ClassInfo:
    chunk_id: str
    base_names: list[str]
    methods: dict[str, str] = field(default_factory=dict)


@dataclass
class _FileDefs:
    functions: dict[str, str] = field(default_factory=dict)
    classes: dict[str, _ClassInfo] = field(default_factory=dict)


def build_graph(repo_root: Path) -> nx.MultiDiGraph:
    """Parse every Python file under `repo_root` into a call/import graph."""
    repo_root = Path(repo_root).resolve()
    files = sorted(p.relative_to(repo_root).as_posix() for p in iter_python_files(repo_root))

    parser = new_parser()
    entries_by_file: dict[str, list[tuple[CodeChunk, Node]]] = {}
    roots: dict[str, Node] = {}
    for rel_path in files:
        path = repo_root / rel_path
        entries_by_file[rel_path] = parse_file_with_nodes(path, rel_path, parser=parser)
        roots[rel_path] = parser.parse(path.read_bytes()).root_node

    graph = nx.MultiDiGraph()
    _add_module_and_definition_nodes(graph, files, entries_by_file)

    file_defs = {rel_path: _collect_file_defs(entries_by_file[rel_path]) for rel_path in files}
    module_index = _build_module_index(files)

    bindings_by_file = {
        rel_path: _add_import_edges_and_bindings(graph, rel_path, roots[rel_path], module_index, file_defs)
        for rel_path in files
    }

    for rel_path in files:
        _add_inherits_edges(graph, file_defs[rel_path], bindings_by_file[rel_path])

    classes_by_id = {info.chunk_id: info for fd in file_defs.values() for info in fd.classes.values()}

    for rel_path in files:
        _add_call_edges(graph, entries_by_file[rel_path], file_defs[rel_path], bindings_by_file[rel_path], classes_by_id)

    return graph


def _add_module_and_definition_nodes(
    graph: nx.MultiDiGraph, files: list[str], entries_by_file: dict[str, list[tuple[CodeChunk, Node]]]
) -> None:
    for rel_path in files:
        graph.add_node(rel_path, type="module", path=rel_path)
    for rel_path in files:
        for chunk, _def_node in entries_by_file[rel_path]:
            graph.add_node(
                chunk.id,
                type="class" if chunk.kind == "class" else "function",
                kind=chunk.kind,
                name=chunk.name,
                qualified_name=chunk.qualified_name,
                file=chunk.file,
                start_line=chunk.start_line,
                end_line=chunk.end_line,
                signature=chunk.signature,
                docstring=chunk.docstring,
            )
            graph.add_edge(rel_path, chunk.id, type="DEFINES")


def _owner_simple_name(chunk: CodeChunk) -> str:
    owner = chunk.qualified_name.rsplit("." + chunk.name, 1)[0]
    return owner.split(".")[-1]


def _collect_file_defs(entries: list[tuple[CodeChunk, Node]]) -> _FileDefs:
    fd = _FileDefs()
    for chunk, def_node in entries:
        if chunk.kind == "function":
            fd.functions[chunk.name] = chunk.id
        elif chunk.kind == "class":
            fd.classes[chunk.name] = _ClassInfo(chunk_id=chunk.id, base_names=_base_names(def_node))
        elif chunk.kind == "method":
            info = fd.classes.get(_owner_simple_name(chunk))
            if info is not None:
                info.methods[chunk.name] = chunk.id
    return fd


def _base_names(class_def_node: Node) -> list[str]:
    supers = class_def_node.child_by_field_name("superclasses")
    if supers is None:
        return []
    return [_text(arg) for arg in supers.named_children if arg.type in ("identifier", "attribute")]


def _build_module_index(files: list[str]) -> dict[str, str]:
    index: dict[str, str] = {}
    for rel_path in files:
        if rel_path == "__init__.py" or rel_path.endswith("/__init__.py"):
            dotted = rel_path[: -len("__init__.py")].rstrip("/").replace("/", ".")
        else:
            dotted = rel_path[: -len(".py")].replace("/", ".")
        index[dotted] = rel_path
    return index


def _package_of(rel_path: str) -> str:
    return ".".join(rel_path.split("/")[:-1])


def _relative_import_target(node: Node) -> tuple[int, str | None]:
    dots = 0
    trailing = None
    for child in node.named_children:
        if child.type == "import_prefix":
            dots = len(_text(child))
        elif child.type == "dotted_name":
            trailing = _text(child)
    return dots, trailing


def _resolve_relative_module(rel_path: str, dots: int, trailing: str | None) -> str:
    package = _package_of(rel_path)
    parts = package.split(".") if package else []
    levels_up = dots - 1
    if levels_up > 0:
        parts = parts[: len(parts) - levels_up] if levels_up <= len(parts) else []
    base = ".".join(parts)
    if trailing:
        return f"{base}.{trailing}" if base else trailing
    return base


def _add_import_edges_and_bindings(
    graph: nx.MultiDiGraph,
    rel_path: str,
    root: Node,
    module_index: dict[str, str],
    file_defs: dict[str, _FileDefs],
) -> dict[str, tuple[str, str]]:
    """Add IMPORTS edges for `rel_path` and return its local import bindings.

    A binding maps a locally-bound name to either `("module", rel_path)`
    (a module alias, e.g. `import foo as f`) or `("chunk", chunk_id)`
    (a specific function/class pulled in via `from ... import ...`).
    """
    bindings: dict[str, tuple[str, str]] = {}

    def handle_import_statement(node: Node) -> None:
        for child in node.named_children:
            if child.type == "dotted_name":
                dotted = _text(child)
                target = module_index.get(dotted)
                if target:
                    graph.add_edge(rel_path, target, type="IMPORTS")
                    bindings[dotted.split(".")[0]] = ("module", target)
            elif child.type == "aliased_import":
                name_node = child.child_by_field_name("name")
                alias_node = child.child_by_field_name("alias")
                if name_node is None or alias_node is None:
                    continue
                target = module_index.get(_text(name_node))
                if target:
                    graph.add_edge(rel_path, target, type="IMPORTS")
                    bindings[_text(alias_node)] = ("module", target)

    def handle_import_from_statement(node: Node) -> None:
        module_node = node.child_by_field_name("module_name")
        if module_node is None:
            return
        if module_node.type == "relative_import":
            dots, trailing = _relative_import_target(module_node)
            target_dotted = _resolve_relative_module(rel_path, dots, trailing)
        elif module_node.type == "dotted_name":
            target_dotted = _text(module_node)
        else:
            return
        target = module_index.get(target_dotted)
        if not target:
            return
        graph.add_edge(rel_path, target, type="IMPORTS")
        target_fd = file_defs.get(target)
        if target_fd is None:
            return
        for i in range(node.child_count):
            if node.field_name_for_child(i) != "name":
                continue
            name_child = node.child(i)
            if name_child is None:
                continue
            if name_child.type == "dotted_name":
                imported = _text(name_child)
                local_name = imported
            elif name_child.type == "aliased_import":
                name_node = name_child.child_by_field_name("name")
                alias_node = name_child.child_by_field_name("alias")
                if name_node is None:
                    continue
                imported = _text(name_node)
                local_name = _text(alias_node) if alias_node is not None else imported
            else:
                continue
            chunk_id = target_fd.functions.get(imported)
            if chunk_id is None:
                class_info = target_fd.classes.get(imported)
                chunk_id = class_info.chunk_id if class_info else None
            if chunk_id is not None:
                bindings[local_name] = ("chunk", chunk_id)

    def visit(node: Node) -> None:
        if node.type == "import_statement":
            handle_import_statement(node)
            return
        if node.type == "import_from_statement":
            handle_import_from_statement(node)
            return
        for child in node.named_children:
            visit(child)

    visit(root)
    return bindings


def _add_inherits_edges(graph: nx.MultiDiGraph, fd: _FileDefs, bindings: dict[str, tuple[str, str]]) -> None:
    for info in fd.classes.values():
        for base_name in info.base_names:
            base_id = None
            if base_name in fd.classes:
                base_id = fd.classes[base_name].chunk_id
            else:
                binding = bindings.get(base_name)
                if binding is not None and binding[0] == "chunk":
                    base_id = binding[1]
            if base_id is not None and graph.nodes.get(base_id, {}).get("type") == "class":
                graph.add_edge(info.chunk_id, base_id, type="INHERITS")


def _resolve_method(
    graph: nx.MultiDiGraph,
    classes_by_id: dict[str, _ClassInfo],
    class_chunk_id: str,
    method_name: str,
    seen: set[str] | None = None,
) -> str | None:
    seen = seen if seen is not None else set()
    if class_chunk_id in seen:
        return None
    seen.add(class_chunk_id)

    info = classes_by_id.get(class_chunk_id)
    if info is None:
        return None
    if method_name in info.methods:
        return info.methods[method_name]

    for _, base_id, data in graph.out_edges(class_chunk_id, data=True):
        if data.get("type") == "INHERITS":
            found = _resolve_method(graph, classes_by_id, base_id, method_name, seen)
            if found is not None:
                return found
    return None


def _resolve_name(
    name: str, fd: _FileDefs, bindings: dict[str, tuple[str, str]], classes_by_id: dict[str, _ClassInfo]
) -> tuple[str, str] | None:
    """Resolve a bare name to ('function', id), ('class', id), or ('module', rel_path)."""
    if name in fd.functions:
        return ("function", fd.functions[name])
    if name in fd.classes:
        return ("class", fd.classes[name].chunk_id)
    binding = bindings.get(name)
    if binding is None:
        return None
    kind, target = binding
    if kind == "module":
        return ("module", target)
    return ("class", target) if target in classes_by_id else ("function", target)


def _direct_calls(node: Node) -> list[Node]:
    """Call nodes reachable from `node` without crossing into a nested def."""
    calls: list[Node] = []

    def visit(n: Node) -> None:
        for child in n.named_children:
            if child.type == "decorated_definition" or child.type in _DEF_TYPES:
                continue
            if child.type == "call":
                calls.append(child)
            visit(child)

    visit(node)
    return calls


def _local_variable_types(
    body: Node, fd: _FileDefs, bindings: dict[str, tuple[str, str]], classes_by_id: dict[str, _ClassInfo]
) -> dict[str, str]:
    """`var = ClassName(...)` assignments within a chunk's own body."""
    types: dict[str, str] = {}

    def visit(n: Node) -> None:
        for child in n.named_children:
            if child.type == "decorated_definition" or child.type in _DEF_TYPES:
                continue
            if child.type == "assignment":
                left = child.child_by_field_name("left")
                right = child.child_by_field_name("right")
                if left is not None and left.type == "identifier" and right is not None and right.type == "call":
                    fn = right.child_by_field_name("function")
                    if fn is not None and fn.type == "identifier":
                        resolved = _resolve_name(_text(fn), fd, bindings, classes_by_id)
                        if resolved is not None and resolved[0] == "class":
                            types[_text(left)] = resolved[1]
            visit(child)

    visit(body)
    return types


def _resolve_call(
    call_node: Node,
    fd: _FileDefs,
    bindings: dict[str, tuple[str, str]],
    local_types: dict[str, str],
    owning_class_id: str | None,
    classes_by_id: dict[str, _ClassInfo],
    graph: nx.MultiDiGraph,
) -> str | None:
    fn = call_node.child_by_field_name("function")
    if fn is None:
        return None

    if fn.type == "identifier":
        resolved = _resolve_name(_text(fn), fd, bindings, classes_by_id)
        if resolved is None:
            return None
        kind, target = resolved
        if kind == "function":
            return target
        if kind == "class":
            return _resolve_method(graph, classes_by_id, target, "__init__")
        return None

    if fn.type == "attribute":
        obj = fn.child_by_field_name("object")
        attr = fn.child_by_field_name("attribute")
        if obj is None or attr is None or obj.type != "identifier":
            return None
        obj_name = _text(obj)
        attr_name = _text(attr)
        if obj_name in ("self", "cls") and owning_class_id is not None:
            return _resolve_method(graph, classes_by_id, owning_class_id, attr_name)
        if obj_name in local_types:
            return _resolve_method(graph, classes_by_id, local_types[obj_name], attr_name)
        return None

    return None


def _add_call_edges(
    graph: nx.MultiDiGraph,
    entries: list[tuple[CodeChunk, Node]],
    fd: _FileDefs,
    bindings: dict[str, tuple[str, str]],
    classes_by_id: dict[str, _ClassInfo],
) -> None:
    for chunk, def_node in entries:
        if chunk.kind == "class":
            continue
        body = def_node.child_by_field_name("body")
        if body is None:
            continue

        owning_class_id = _owning_class_id(fd, chunk) if chunk.kind == "method" else None
        local_types = _local_variable_types(body, fd, bindings, classes_by_id)

        for call_node in _direct_calls(body):
            target = _resolve_call(call_node, fd, bindings, local_types, owning_class_id, classes_by_id, graph)
            if target is not None:
                graph.add_edge(chunk.id, target, type="CALLS")


def _owning_class_id(fd: _FileDefs, chunk: CodeChunk) -> str | None:
    info = fd.classes.get(_owner_simple_name(chunk))
    return info.chunk_id if info else None
