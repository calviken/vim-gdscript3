# Functions for gathering completion items.

import os
import re

import classes
import util
import script

# Flags for selecting which built-in items to complete.
_MEMBERS = 1
_METHODS = 2
_CONSTANTS = 4

_completions = None

def clear_completions():
    global _completions
    _completions = []

def get_completions():
    return _completions

def append_completion(completion):
    if completion:
        _completions.append(completion)

def complete_paths():
    line = util.get_line()[0:util.get_cursor_col_num() - 1]
    m = re.search("res://(((\w|-)+/)*)$", line)
    if m:
        project_dir = util.get_project_dir()
        if not project_dir:
            return
        # Directories and files are grouped and sorted separately.
        dirs = []
        files = []
        base_dir = "{}/{}".format(project_dir, m.group(1))
        if not os.path.isdir(base_dir):
            return
        for entry in os.listdir(base_dir):
            if not entry.startswith("."):
                if not util.filter(entry):
                    continue
                if os.path.isdir("{}/{}".format(base_dir, entry)):
                    dirs.append("{}/".format(entry))
                else:
                    files.append(entry)
        for d in sorted(dirs):
            append_completion(d)
        for f in sorted(files):
            append_completion(f)

def complete_class_names(type=0):
    for name in classes.iter_class_names(type):
        append_completion(build_completion(name))

def complete_method_signatures():
    c = classes.get_class(script.get_extended_class())
    while c:
        for method in c.iter_methods():
            d = build_completion(method, c.get_name())
            if not d:
                continue
            mapped_args = map(lambda a: a.name, method.args)
            d["word"] = "{}({}):".format(method.name, ", ".join(mapped_args))
            append_completion(d)
        c = c.get_inherited_class()

def complete_dot():
    line_num = util.get_cursor_line_num()
    line = util.get_line(line_num)
    col_num = util.get_cursor_col_num()
    token_chain = script.get_token_chain(line, line_num, col_num-2)
    if token_chain:
        last_token = token_chain[-1]
        last_token_type = type(last_token)

        # Complete statically accessible items in classes.
        if last_token_type is script.ClassToken:
            # Class is defined by Godot.
            if last_token.line == -1:
                c = classes.get_class(last_token.name)
                # Manually add an entry for 'new()' for core types.
                if not c.is_built_in():
                    new_func = classes.GodotMethod("new", c.get_name(), [], None)
                    append_completion(build_completion(new_func, c.get_name()))
                _add_class_items(c, _CONSTANTS)
            else:
                for decl in script.iter_static_decls(last_token.line, script.ANY_DECLS):
                    append_completion(build_completion(decl))
            return

        # Treat 'self' like we're accessing script variables, but exclude globals.
        if last_token_type is script.VariableToken and last_token.name == "self":
            complete_script(include_globals=False)
            return

        # Complete enum values.
        if last_token_type is script.EnumToken:
            values = script.get_enum_values(last_token.line)
            if values:
                for value in values:
                    append_completion(build_completion(value))
            return

        c_name = None
        flags = None
        if len(token_chain) == 1 and last_token_type is script.SuperAccessorToken:
            c_name = script.get_extended_class(line_num)
            flags = _METHODS
        elif last_token_type is script.MethodToken:
            c_name = last_token.returns
        elif last_token_type is script.VariableToken:
            c_name = last_token.type
        if c_name:
            builtin_class = classes.get_class(c_name)
            if builtin_class:
                _add_class_items(builtin_class, flags)
            else:
                _add_user_class_items(c_name, flags)

# Complete user declared items in the script and items from the extended class.
# If 'include_globals' is True, add items from global scope.
def complete_script(include_globals):
    # Complete user decls.
    down_search_start = 1
    for decl in script.iter_decls(util.get_cursor_line_num(), direction=-1):
        decl_type = type(decl)
        if decl_type == script.ClassDecl:
            down_search_start = decl.line
        elif decl_type != script.FuncDecl:
            append_completion(build_completion(decl))
    for decl in script.iter_decls(down_search_start, direction=1):
        append_completion(build_completion(decl))

    # Complete extended class.
    c = classes.get_class(script.get_extended_class())
    _add_class_items(c)

    # Complete global scope.
    if include_globals:
        complete_class_names(classes.EXTENDABLE)
        _add_class_items(classes.get_global_scope())

# Recursively add class items for user defined classes.
def _add_user_class_items(c_name, flags):
    if not flags:
        flags = script.ANY_DECLS ^ script.CLASS_DECLS
    while c_name:
        c_decl = script.find_decl_down(0, c_name, script.CLASS_DECLS)
        for member in script.iter_decls(c_decl.line, 1, flags):
            append_completion(build_completion(member))
        c_name = c_decl.extends
        builtin_class = classes.get_class(c_name)
        if builtin_class:
            _add_class_items(builtin_class, flags)
            break

# Recursively add class items.
def _add_class_items(c, flags=None):
    if not flags:
        flags = _MEMBERS | _METHODS | _CONSTANTS
    while c:
        c_name = c.get_name()
        if flags & _MEMBERS:
            for member in c.iter_members():
                append_completion(build_completion(member, c_name))
        if flags & _METHODS:
            for method in c.iter_methods():
                append_completion(build_completion(method, c_name))
        if flags & _CONSTANTS:
            for constant in c.iter_constants():
                append_completion(build_completion(constant, c_name))
        c = c.get_inherited_class()

# Generic function for building completion dicts.
def build_completion(item, c_name=None):
    t = type(item)
    d = {}
    if t is str:
        if util.filter(item):
            d["word"] = item
    elif item.name:
        if not util.filter(item.name):
            return

        # Built-in
        if t is classes.GodotMember:
            d["word"] = item.name
            if c_name:
                d["abbr"] = "{}.{}".format(c_name, item.name)
            d["kind"] = item.type
        elif t is classes.GodotConstant:
            d["word"] = item.name
            if c_name:
                d["abbr"] = "{}.{} = {}".format(c_name, item.name, item.value)
            else:
                d["abbr"] = "{} = {}".format(item.name, item.value)
            if item.type:
                d["kind"] = item.type
        elif t is classes.GodotMethod:
            if len(item.args) > 0:
                d["word"] = "{}(".format(item.name)
            else:
                d["word"] = "{}()".format(item.name)
            args = list(map(lambda a: "{}: {}".format(a.name, a.type), item.args))
            qualifiers = " {}".format(item.qualifiers) if item.qualifiers else ""
            if "vararg" in qualifiers:
                args.append("...")
            joined_args = ", ".join(args)
            if c_name:
                d["abbr"] = "{}.{}({}){}".format(c_name, item.name, joined_args, qualifiers)
            else:
                d["abbr"] = "{}({}){}".format(item.name, joined_args, qualifiers)
            d["kind"] = item.returns

        # User decls
        elif t is script.VarDecl:
            d["word"] = item.name
            if item.type:
                d["kind"] = item.type
        elif t is script.ConstDecl:
            d["word"] = item.name
            if item.value:
                d["abbr"] = "{} = {}".format(item.name, item.value)
            if item.type:
                d["kind"] = item.type
        elif t is script.FuncDecl:
            if len(item.args) > 0:
                d["word"] = "{}(".format(item.name)
            else:
                d["word"] = "{}()".format(item.name)
            d["abbr"] = "{}({})".format(item.name, ", ".join(item.args))
            if item.returns:
                d["kind"] = item.returns
        elif t is script.EnumDecl:
            d["word"] = item.name
            d["kind"] = "enum"
        elif t is script.ClassDecl:
            d["word"] = item.name
            d["kind"] = "class"
    if not d:
        return
    d["dup"] = 1
    if util.get_ignore_case():
        d["icase"] = 1
    return d
