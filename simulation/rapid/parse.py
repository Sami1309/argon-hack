"""Minimal RAPID parsing: data declarations, PROC bodies, and arithmetic/field expressions.

Shared by the kinematic checks and (later) the interpreter. Units are RAPID units (mm, quaternion [w,x,y,z]).
"""
import re
from dataclasses import dataclass, field

import numpy as np

_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"


@dataclass
class RobTarget:
    trans: np.ndarray  # mm, in the work object (wobj0 unless stated)
    rot: np.ndarray    # [w,x,y,z]
    conf: tuple        # (cf1, cf4, cf6, cfx)


@dataclass
class Tool:
    trans: np.ndarray  # mm, TCP in flange frame
    rot: np.ndarray


@dataclass
class Module:
    robtargets: dict = field(default_factory=dict)
    tools: dict = field(default_factory=dict)
    procs: dict = field(default_factory=dict)  # name -> (params, [(lineno, stmt)])


def _nums(s):
    return [float(x) for x in re.findall(_NUM, s)]


def strip_comment(line):
    out, q = [], False
    for ch in line:
        if ch == '"': q = not q
        if ch == "!" and not q: break
        out.append(ch)
    return "".join(out)


def parse_module(text):
    mod = Module()
    for m in re.finditer(r"robtarget\s+(\w+)\s*:=\s*\[\[([^\]]+)\],\[([^\]]+)\],\[([^\]]+)\]", text):
        mod.robtargets[m[1]] = RobTarget(np.array(_nums(m[2])), np.array(_nums(m[3])), tuple(int(x) for x in _nums(m[4])))
    for m in re.finditer(r"tooldata\s+(\w+)\s*:=\s*\[\s*\w+\s*,\s*\[\[([^\]]+)\],\[([^\]]+)\]\]", text):
        mod.tools[m[1]] = Tool(np.array(_nums(m[2])), np.array(_nums(m[3])))
    lines = text.splitlines()
    cur = None
    for i, raw in enumerate(lines, 1):
        s = strip_comment(raw).strip()
        if not s: continue
        m = re.match(r"PROC\s+(\w+)\s*\(([^)]*)\)", s)
        if m:
            params = [p.split()[-1] for p in m[2].split(",") if p.strip()]
            cur = m[1]; mod.procs[cur] = (params, [])
            continue
        if s.startswith("ENDPROC"):
            cur = None; continue
        if cur:
            mod.procs[cur][1].append((i, s))
    return mod


# ---- expressions: numbers, dotted names, + - * /, parentheses, unary minus ----
_TOK = re.compile(rf"\s*(?:({_NUM})|([A-Za-z_][\w.]*)|(.))")


def evaluate(expr, env):
    toks = [(n, name, op) for n, name, op in _TOK.findall(expr) if n or name or op.strip()]
    pos = 0

    def peek():
        return toks[pos] if pos < len(toks) else (None, None, None)

    def atom():
        nonlocal pos
        n, name, op = peek(); pos += 1
        if n: return float(n)
        if name:
            if name not in env: raise KeyError(f"unbound RAPID name: {name}")
            return env[name]
        if op == "(":
            v = add()
            pos += 1  # ')'
            return v
        if op == "-": return -atom()
        if op == "+": return atom()
        raise SyntaxError(f"bad token {op!r} in {expr!r}")

    def mul():
        nonlocal pos
        v = atom()
        while peek()[2] in ("*", "/"):
            op = peek()[2]; pos += 1
            v = v * atom() if op == "*" else v / atom()
        return v

    def add():
        nonlocal pos
        v = mul()
        while peek()[2] in ("+", "-"):
            op = peek()[2]; pos += 1
            v = v + mul() if op == "+" else v - mul()
        return v

    v = add()
    if pos != len(toks): raise SyntaxError(f"trailing tokens in {expr!r}")
    return v


def split_args(s):
    """Split a comma-separated argument list at depth 0 (respects (...) and [...])."""
    out, depth, cur = [], 0, []
    for ch in s:
        if ch in "([": depth += 1
        elif ch in ")]": depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(cur).strip()); cur = []
        else:
            cur.append(ch)
    if cur: out.append("".join(cur).strip())
    return out
