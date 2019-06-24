# Functions for retrieving information in the current script.

import re
from collections import namedtuple

import util
import classes

# Regex patterns for user declarations.
_VAR_PATTERN = "\s*(?:export(?:\(.*\)\s+)?)?var\s+(\w+)(?:\s*:\s*(\w+))?"
_CONST_PATTERN = "\s*const\s+(\w+)\s*(?::\s*(\w+))?\s*=\s*(.+)"
_FUNC_PATTERN = "\s*(static\s+)?func\s+(\w+)\(([\w|:|,|\s]*)\)(?:\s*-\>\s*(\w+)\s*)?:"
_ENUM_PATTERN = "\s*enum\s+(\w+)"
_ENUM_VALUES_PATTERN = "\s*enum\s+\w+\s*\{(.*)\}"
_CLASS_PATTERN = "\s*class\s+(\w+)(?:\s+extends\s+(\w+))?"

# Flags for choosing which decl types to gather.
VAR_DECLS = 1
CONST_DECLS = 2
FUNC_DECLS = 4
ENUM_DECLS = 8
CLASS_DECLS = 16
ANY_DECLS = VAR_DECLS | CONST_DECLS | FUNC_DECLS | ENUM_DECLS | CLASS_DECLS

# These store info about user-declared items in the script.
VarDecl = namedtuple("VarDecl", "line, name, type")
ConstDecl = namedtuple("ConstDecl", "line, name, value, type")
FuncDecl = namedtuple("FuncDecl", "line, static, name, args, returns")
EnumDecl = namedtuple("EnumDecl", "line, name")
ClassDecl = namedtuple("ClassDecl", "line, name, extends")

# These store parts of a "token chain". See 'get_token_chain()' for more info.
VariableToken = namedtuple("VariableToken", "name, type")
MethodToken = namedtuple("MethodToken", "name, returns, args, qualifiers")
EnumToken = namedtuple("EnumToken", "name, line")
ClassToken = namedtuple("ClassToken", "name, line")
# This just acts as a marker with no extra data . Named tuples must have at
# least one field, which is why this is an empty class instead.
class SuperAccessorToken: pass

# Parse a user declaration.
# 'flags' indicates which decl types to look for.
def _get_decl(lnum, flags):
    line = util.get_line(lnum)

    if flags & VAR_DECLS:
        m = re.match(_VAR_PATTERN, line)
        if m:
            return VarDecl(lnum, m.group(1), m.group(2))

    if flags & CONST_DECLS:
        m = re.match(_CONST_PATTERN, line)
        if m:
            return ConstDecl(lnum, m.group(1), m.group(3), m.group(2))

    if flags & FUNC_DECLS:
        m = re.match(_FUNC_PATTERN, line)
        if m:
            static = m.group(1) != None
            name = m.group(2)
            args = m.group(3)
            returns = m.group(4)
            if args:
                args = [" ".join(a.split()) for a in args.split(",")]
            return FuncDecl(lnum, static, name, args, returns)

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
        m = re.match("(\w+)\s*:\s*(\w+)", arg)
        if m:
            arg = m.group(1)
            arg_type = m.group(2)
        if method and len(method.args) > i:
            method_arg = method.args[i]
            if method_arg:
                arg_type = method_arg.type
        vars.append(VarDecl(func_decl.line, arg, arg_type))
    return vars

# Generator function that scans the current file and yields user declarations.
#
# 'direction' should be 1 for downwards, or -1 for upwards.
#
# When scanning downwards, 'start_line' should either be on an inner class decl, or
# on an unindented line (usually the top of the script). If starting on a
# class decl, only the decls within that class are yielded. Similarly, items
# within inner classes are ignored when scanning for global decls.
#
# When scanning upwards, 'start_line' should be inside a function. This yields
# the following items in this order:
# 1. Function arguments.
# 2. Function-local var declarations up until 'start_line'.
# 3. The function itself.
# 4. The inner class containing the function (if there is one)
def iter_decls(start_line, direction, flags=None):
    if direction != 1 and direction != -1:
        raise ValueError("'direction' must be 1 or -1!")
    if not flags:
        flags = ANY_DECLS
    if direction == 1:
        return _iter_decls_down(start_line, flags)
    else:
        return _iter_decls_up(start_line, flags)

def _iter_decls_down(start_line, flags):
    # Check whether the starting line is a class decl.
    # If so, the indent of the next line is used as a baseline to determine
    # which items are direct children of the inner class.
    in_class = False
    class_decl = _get_decl(start_line, CLASS_DECLS)
    if class_decl:
        in_class = True
        class_indent = util.get_indent(start_line)
        inner_indent = None
        if flags & CLASS_DECLS:
            yield class_decl

    for lnum in range(start_line+1, util.get_line_count()):
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

def _iter_decls_up(start_line, flags):
    # Remove consts and enums from flags, since they can't exist inside functions.
    flags &= ~CONST_DECLS
    flags &= ~ENUM_DECLS

    # Gather decls, but don't yield them until we're sure that the start line
    # was inside a function. If it wasn't, only the class decl is yielded, or
    # nothing if the start line wasn't inside an inner class either.
    decls = []
    start_indent = util.get_indent(start_line)
    if start_indent == 0:
        return
    # Upon reaching a func decl, the search continues until a class decl is found.
    # This only happens if the func decl is indented.
    found_func = False
    for lnum in range(start_line-1, 0, -1):
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

# Helper function for gathering statically accessible items in classes.
def iter_static_decls(start_line, flags):
    # Vars can't be accessed statically.
    flags &= ~VAR_DECLS
    it = iter_decls(start_line, 1, flags)
    # The first decl will be the class itself, which we don't need.
    next(it)
    for decl in it:
        # Only yield static funcs
        if type(decl) is FuncDecl and not decl.static:
            continue
        yield decl

# Search for a user decl with a particular name.
def find_decl(start_line, name, flags=None):
    down_search_start = 1
    for decl in iter_decls(start_line, -1, flags | CLASS_DECLS):
        if type(decl) == ClassDecl:
            if flags & CLASS_DECLS and decl.name == name:
                return decl
            else:
                down_search_start = decl.line
                break
        elif decl.name == name:
            return decl
    return find_decl_down(down_search_start, name, flags)

def find_decl_down(start_line, name, flags=None):
    for decl in iter_decls(start_line, 1, flags):
        if decl.name == name:
            return decl

# Search for the 'extends' keyword and return the name of the extended class.
def get_extended_class(start_line=None):
    # Figure out if we're in an inner class and return its extended type if so.
    if not start_line:
        start_line = util.get_cursor_line_num()
    start_indent = util.get_indent(start_line)
    if start_indent > 0:
        for decl in iter_decls(start_line, -1, FUNC_DECLS | CLASS_DECLS):
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
        line = util.get_line(lnum).rstrip()
        m = re.match("extends\s+(\w+)", line)
        if m:
            return m.group(1)
        # Only 'tool' can appear before 'extends', so stop searching if any other
        # text is encountered.
        elif line and not re.match("tool\s*$", line) and not re.match("\s*\#", line):
            return None

def get_enum_values(line_num):
    lines = [util.strip_line(line_num, util.get_line(line_num))]
    line_count = util.get_line_count()
    while not lines[-1].endswith("}"):
        line_num += 1
        if line_num > line_count:
            return
        lines.append(util.strip_line(line_num, util.get_line(line_num)))
    m = re.match(_ENUM_VALUES_PATTERN, "\n".join(lines), re.DOTALL)
    if m:
        values = [v.strip() for v in m.group(1).replace("\n", ",").split(",")]
        def map_value(v):
            m = re.match("(\w+)(?:\s*=\s*(.*))?", v)
            if m:
                return ConstDecl(-1, m.group(1), m.group(2), "int")
        return list(filter(lambda v: v, map(map_value, values)))


# A token chain is a group of tokens chained via dot accessors.
# "Token" is a loose term referring to anything that produces a value.
# Example:
#     texture.get_data().get_pixel()
# 'texture', 'get_data', and 'get_pixel' all produce values, and are therefore tokens.
#
# A token chain is only considered valid if every token has a discernible type.
def get_token_chain(line, line_num, start_col):
    i = start_col
    paren_count = 0
    is_method = False
    end_col = None

    # Find the name of the token, skipping over any text in parentheses.
    while True:
        i -= 1
        char = line[i]
        if char == ")":
            is_method = True
            paren_count += 1
        elif char == "(":
            paren_count -= 1
            if paren_count == 0:
                start_col = i
                continue
        if paren_count <= 0 and not (char.isalnum() or char == "_"):
            end_col = i + 1
            break
        elif i == 0:
            end_col = i
            break
    name = line[end_col:start_col]

    if not name:
        if util.get_syn_attr(col_num=i+1) == "gdString":
            return [VariableToken(None, "String")]
        else:
            #
            return [SuperAccessorToken()]

    chain = None
    if line[i] == ".":
        chain = get_token_chain(line, line_num, i)
        if not chain:
            return

    # If this is the beginning of the chain, search global scope.
    # TODO: search user funcs and vars with type annotations.
    if (not chain or type(chain[-1]) is SuperAccessorToken or chain[-1].name == "self") and is_method:
        extended_class = classes.get_class(get_extended_class(line_num))
        if extended_class:
            method = extended_class.get_method(name, search_global=True)
            if method:
                return [MethodToken(name, method.returns, method.args, method.qualifiers)]
            decl = find_decl(line_num, name, FUNC_DECLS)
            if decl:
                return [MethodToken(name, None, decl.args, None)]
    elif not chain or chain[-1].name == "self":
        if not chain and name == "self":
            return [VariableToken(name, None)]
        decl = find_decl(line_num, name, ENUM_DECLS | CLASS_DECLS)
        if decl:
            decl_type = type(decl)
            if decl_type is EnumDecl:
                return [EnumToken(name, decl.line)]
            elif decl_type is ClassDecl:
                return [ClassToken(name, decl.line)]
        else:
            extended_class = classes.get_class(get_extended_class(line_num))
            if extended_class:
                member = extended_class.get_member(name, search_global=True)
                if member:
                    return [VariableToken(name, member.type)]
            c = classes.get_class(name)
            if c:
                return [ClassToken(name, -1)]
    # Not the beginning of a chain, so get the type of the previous token.
    else:
        prev_token = chain[-1]
        prev_token_type = type(prev_token)
        prev_class = None
        if prev_token_type is VariableToken:
            prev_class = classes.get_class(prev_token.type)
        elif prev_token_type is MethodToken:
            prev_class = classes.get_class(prev_token.returns)
        elif prev_token_type is ClassToken:
            if is_method and name == "new":
                if not (prev_token.line == -1 and
                        classes.get_class(prev_token.name).is_built_in()):
                    chain.append(MethodToken(name, prev_token.name, None, None))
                    return chain
            for decl in iter_static_decls(prev_token.line, ANY_DECLS):
                if decl.name == name:
                    decl_type = type(decl)
                    if decl_type is ClassDecl:
                        chain.append(ClassToken(name, decl.line))
                        return chain
                    elif decl_type is FuncDecl and decl.static:
                        chain.append(MethodToken(name, decl.returns, decl.args, None))
                        return chain
                    return
        if not prev_class:
            return
        if is_method:
            method = prev_class.get_method(name)
            if method:
                chain.append(MethodToken(name, method.returns, method.args, method.qualifiers))
                return chain
        else:
            member = prev_class.get_member(name)
            if member:
                chain.append(VariableToken(name, member.type))
                return chain




