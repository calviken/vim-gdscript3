# Functions for retrieving information in the current script.

import re
from collections import namedtuple

import util
import classes

# Regex patterns for user declarations.
_VAR_PATTERN = "\s*(?:export(?:\(.*\)\s+)?)?var\s+(\w+)"
_CONST_PATTERN = "\s*const\s+(\w+)\s*=\s*(\w+)"
_FUNC_PATTERN = "\s*(static\s+)?func\s+(\w+)\(((\w|,|\s)*)\):"
_ENUM_PATTERN = "\s*enum\s+(\w+)"
_CLASS_PATTERN = "\s*class\s+(\w+)(?:\s+extends\s+(\w+))?"

# _ENUM_VALUES_PATTERN = "\s*enum\s+\w+\s*\{(\w|,|\s)*\}"

# Flags for choosing which decl types to gather.
VAR_DECLS = 1
CONST_DECLS = 2
FUNC_DECLS = 4
ENUM_DECLS = 8
CLASS_DECLS = 16

# These represent user-declared items in the script.
VarDecl = namedtuple("VarDecl", "line, name, type")
ConstDecl = namedtuple("ConstDecl", "line, name, value")
FuncDecl = namedtuple("FuncDecl", "line, static, name, args")
EnumDecl = namedtuple("EnumDecl", "line, name")
ClassDecl = namedtuple("ClassDecl", "line, name, extends")

VariableToken = namedtuple("VariableToken", "name, type")
ConstantToken = namedtuple("ConstantToken", "name, type, value")
MethodToken = namedtuple("MethodToken", "name, returns")
EnumToken = namedtuple("EnumToken", "name, line")
ClassToken = namedtuple("ClassToken", "name, line")

# Parse a user declaration.
# 'flags' indicates which decl types to look for.
def _get_decl(lnum, flags):
    line = util.get_line(lnum)

    if flags & VAR_DECLS:
        m = re.match(_VAR_PATTERN, line)
        if m:
            return VarDecl(lnum, m.group(1), None)

    if flags & CONST_DECLS:
        m = re.match(_CONST_PATTERN, line)
        if m:
            return ConstDecl(lnum, m.group(1), m.group(2))

    if flags & FUNC_DECLS:
        m = re.match(_FUNC_PATTERN, line)
        if m:
            static = m.group(1) != None
            name = m.group(2)
            args = m.group(3)
            if args:
                args = [a.strip() for a in args.split(",")]
            return FuncDecl(lnum, static, name, args)

    if flags & ENUM_DECLS:
        m = re.match(_ENUM_PATTERN, line)
        if m:
            return EnumDecl(lnum, m.group(1))

    if flags & CLASS_DECLS:
        m = re.match(_CLASS_PATTERN, line)
        if m:
            return ClassDecl(lnum, m.group(1), m.group(2))

# Map function arguments to VarDecls.
# Arguments are treated as VarDecls for simplicity's sake.
# If the function overrides a built-in method, the arg types are mapped as well.
def _args_to_vars(func_decl):
    vars = []
    method = None
    extended_class = classes.get_class(get_extended_class(func_decl.line))
    if extended_class:
        method = extended_class.get_method(func_decl.name)

    for i, arg in enumerate(func_decl.args):
        arg_type = None
        if method:
            method_arg = method.args[i]
            if method_arg:
                arg_type = method_arg.type
        vars.append(VarDecl(func_decl.line, arg, arg_type))
    return vars

# Generator function that scans the current file and yields user declarations.
#
# 'start' is the line num where scanning should start.
# 'direction' should be 1 for downwards, or -1 for upwards.
#
# When scanning downwards, 'start' should either be on an inner class decl, or
# on an unindented line (usually the top of the script). If starting on a
# class decl, only the decls within that class are yielded. Similarly, items
# within inner classes are ignored when scanning for global decls.
#
# When scanning upwards, 'start' should be inside a function. This yields
# the following items in this order:
# 1. Function arguments.
# 2. Function-local var declarations up until 'start'.
# 3. The function itself.
# 4. The inner class containing the function (if there is one)
def iter_decls(start, direction, flags=None):
    if direction != 1 and direction != -1:
        raise ValueError("'direction' must be 1 or -1!")
    if not flags:
        flags = VAR_DECLS | CONST_DECLS | FUNC_DECLS | ENUM_DECLS | CLASS_DECLS
    if direction == 1:
        return _iter_decls_down(start, flags)
    else:
        return _iter_decls_up(start, flags)

def _iter_decls_down(start, flags):
    # Check whether the starting line is a class decl.
    # If so, the indent of the next line is used as a baseline to determine
    # which items are direct children of the inner class.
    in_class = False
    class_decl = _get_decl(start, CLASS_DECLS)
    if class_decl:
        in_class = True
        class_indent = util.get_indent(start)
        inner_indent = None
        if flags & CLASS_DECLS:
            yield class_decl

    for lnum in range(start+1, util.get_line_count()):
        if not util.get_line(lnum):
            continue
        indent = util.get_indent(lnum)
        if in_class:
            if indent <= class_indent:
                return
            if not inner_indent:
                inner_indent = indent
            elif indent > inner_indent:
                continue
        else:
            if indent > 0:
                continue
        decl = _get_decl(lnum, flags)
        if decl:
            yield decl

def _iter_decls_up(start, flags):
    # Remove consts and enums from flags, since they can't exist inside functions.
    flags &= ~CONST_DECLS
    flags &= ~ENUM_DECLS

    # Gather decls, but don't yield them until we're sure that the start line
    # was inside a function. If it wasn't, only the class decl is yielded, or
    # nothing if the start line wasn't inside an inner class either.
    decls = []
    start_indent = util.get_indent(start)
    if start_indent == 0:
        return
    # Upon reaching a func decl, the search continues until a class decl is found.
    # This only happens if the func decl is indented.
    found_func = False
    for lnum in range(start-1, 0, -1):
        indent = util.get_indent(lnum)
        if indent > start_indent:
            continue
        if found_func:
            # After finding a function, we only care finding the inner class.
            decl = _get_decl(lnum, CLASS_DECLS)
        else:
            # We need to know when a func or class is encountered, even if they
            # aren't part of the search flags. Funcs and classes are still only
            # yielded if part of the original search flags.
            decl = _get_decl(lnum, flags | FUNC_DECLS | CLASS_DECLS)
        if not decl:
            continue
        if indent < start_indent:
            decl_type = type(decl)
            if decl_type is FuncDecl:
                found_func = True
                start_indent = indent
                if flags & VAR_DECLS:
                    # Yield function args
                    if len(decl.args) > 0:
                        mapped_args = _args_to_vars(decl)
                        for arg in mapped_args:
                            yield arg
                    # Yield var decls gathered up until now.
                    for stored_decl in reversed(decls):
                        yield stored_decl
                if flags & FUNC_DECLS:
                    yield decl
                if indent == 0:
                    break
            elif decl_type is ClassDecl:
                if flags & CLASS_DECLS:
                    yield decl
                break
        else:
            decls.append(decl)

# Search for the 'extends' keyword and return the name of the extended class.
def get_extended_class(start=None):
    # Figure out if we're in an inner class and return its extended type if so.
    if not start:
        start = util.get_cursor_line_num()
    start_indent = util.get_indent(start)
    if start_indent > 0:
        for decl in iter_decls(start, -1, FUNC_DECLS | CLASS_DECLS):
            indent = util.get_indent(decl.line)
            if indent == start_indent:
                continue
            decl_type = type(decl)
            if decl_type is FuncDecl:
                start_indent = indent
            elif decl_type is ClassDecl:
                if decl.extends:
                    return decl.extends
                else:
                    return None
            if indent == 0:
                break

    # Search for 'extends' at the top of the file.
    for lnum in range(1, util.get_line_count()):
        line = util.get_line(lnum)
        m = re.match("extends\s+(\w+)", line)
        if m:
            return m.group(1)
        # Only 'tool' can appear before 'extends', so stop searching if any other
        # text is encountered.
        elif not re.match("tool\s+$", line):
            return None
