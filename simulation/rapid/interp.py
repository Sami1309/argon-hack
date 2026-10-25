"""RAPID interpreter (the subset used by the sorting-cell programs and their guarded ports).

Parsing -> small AST of tuples; execution -> Python generators that yield wait requests to the scheduler:
    ("sleep", seconds)            ("until", predicate, max_time_or_None)
Motion and I/O are delegated to a `world` object (simulation/cell.py).
Semantics notes (documented approximations):
  * main() is re-run in continuous mode until Stop/EXIT.
  * RETRY re-executes the top-level statement of the routine in which the error occurred (max 4 retries).
  * An ERROR handler that ends without RETRY/TRYNEXT/RAISE/RETURN returns from the routine.
"""
import copy
import re

import numpy as np

KEYWORDS = {"IF", "THEN", "ELSEIF", "ELSE", "ENDIF", "TEST", "CASE", "DEFAULT", "ENDTEST", "WHILE", "DO", "ENDWHILE",
            "FOR", "FROM", "TO", "STEP", "ENDFOR", "PROC", "ENDPROC", "FUNC", "ENDFUNC", "TRAP", "ENDTRAP", "ERROR",
            "RETURN", "RAISE", "RETRY", "TRYNEXT", "EXIT", "MODULE", "ENDMODULE", "RECORD", "ENDRECORD", "VAR", "PERS",
            "CONST", "LOCAL", "TASK", "AND", "OR", "XOR", "NOT", "DIV", "MOD", "TRUE", "FALSE", "INOUT", "UNDO",
            "BACKWARD", "GOTO"}
ERR_WAIT_MAXTIME = 41
MAX_RETRY = 4

_TOKEN = re.compile(r"""
    (?P<ws>\s+) | (?P<comment>![^\n]*) |
    (?P<num>(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?) |
    (?P<str>"(?:[^"]|"")*") |
    (?P<id>[A-Za-z_][A-Za-z0-9_]*) |
    (?P<op>:=|<>|<=|>=|[-+*/=<>()\[\]{},;:\\.|])
""", re.X)


class RapidSyntaxError(Exception):
    pass


class RapidError(Exception):
    """A RAPID run-time error that an ERROR handler may catch."""
    def __init__(self, errno, msg=""):
        super().__init__(msg or f"ERRNO {errno}"); self.errno = errno


class TaskStop(Exception):
    """Stop / EXIT / fatal motion error: the task ends."""
    def __init__(self, reason):
        super().__init__(reason); self.reason = reason


class _Return(Exception):
    def __init__(self, value=None): self.value = value


class _Retry(Exception): pass
class _Trynext(Exception): pass


def tokenize(src):
    toks, line = [], 1
    for m in _TOKEN.finditer(src):
        kind = m.lastgroup; text = m.group()
        if kind in ("ws", "comment"):
            line += text.count("\n"); continue
        if kind == "id" and text.upper() in KEYWORDS:
            kind, text = "kw", text.upper()
        toks.append((kind, text, line))
    return toks


# ---------------------------------------------------------------- parser
class Parser:
    def __init__(self, src):
        self.t, self.i = tokenize(src), 0

    def peek(self, k=0):
        j = self.i + k
        return self.t[j] if j < len(self.t) else ("eof", "", -1)

    def at(self, *vals):
        return self.peek()[1] in vals

    def at_kw(self, *vals):
        return self.peek()[0] == "kw" and self.peek()[1] in vals

    def next(self):
        tok = self.peek(); self.i += 1; return tok

    def expect(self, val):
        tok = self.next()
        if tok[1] != val: raise RapidSyntaxError(f"line {tok[2]}: expected {val!r}, got {tok[1]!r}")
        return tok

    def ident(self):
        tok = self.next()
        if tok[0] != "id": raise RapidSyntaxError(f"line {tok[2]}: expected identifier, got {tok[1]!r}")
        return tok[1]

    # module level
    def module(self):
        mod = dict(records={}, data=[], routines={})
        if self.at_kw("MODULE"):
            self.next(); mod["name"] = self.ident()
            if self.at("("):
                while not self.at(")"): self.next()
                self.next()
        while self.peek()[0] != "eof" and not self.at_kw("ENDMODULE"):
            if self.at_kw("LOCAL", "TASK"): self.next(); continue
            if self.at_kw("RECORD"):
                self.next(); name = self.ident(); fields = []
                while not self.at_kw("ENDRECORD"):
                    typ = self.ident(); fname = self.ident(); self.expect(";"); fields.append((typ, fname))
                self.next(); mod["records"][name] = fields
            elif self.at_kw("VAR", "PERS", "CONST"):
                mod["data"].append(self.decl())
            elif self.at_kw("PROC", "FUNC", "TRAP"):
                r = self.routine(); mod["routines"][r["name"]] = r
            else:
                tok = self.peek(); raise RapidSyntaxError(f"line {tok[2]}: unexpected {tok[1]!r} at module level")
        return mod

    def decl(self):
        storage = self.next()[1]; typ = self.ident(); line = self.peek()[2]; name = self.ident()
        dims = None
        if self.at("{"):
            self.next(); dims = [self.expr()]
            while self.at(","): self.next(); dims.append(self.expr())
            self.expect("}")
        init = None
        if self.at(":="): self.next(); init = self.expr()
        self.expect(";")
        return ("decl", line, storage, typ, name, dims, init)

    def routine(self):
        kind = self.next()[1]
        rtype = self.ident() if kind == "FUNC" else None
        name = self.ident(); params = []
        if self.at("("):
            self.next()
            while not self.at(")"):
                optional = False
                if self.at("\\"): self.next(); optional = True
                if self.at_kw("INOUT", "VAR", "PERS"): self.next()
                if self.at("|", ","): self.next(); continue
                typ = self.ident(); pname = self.ident()
                if self.at("{"):
                    while not self.at("}"): self.next()
                    self.next()
                params.append((typ, pname, optional))
                if self.at(",", "|"): self.next()
            self.next()
        line = self.peek()[2]
        locals_ = []
        while self.at_kw("VAR", "PERS", "CONST", "LOCAL"):
            if self.at_kw("LOCAL"): self.next()
            locals_.append(self.decl())
        end = {"PROC": "ENDPROC", "FUNC": "ENDFUNC", "TRAP": "ENDTRAP"}[kind]
        body = self.block(end, "ERROR", "UNDO", "BACKWARD")
        handler = None
        while not self.at_kw(end):
            sect = self.next()[1]
            blk = self.block(end, "ERROR", "UNDO", "BACKWARD")
            if sect == "ERROR": handler = blk
        self.next()
        return dict(kind=kind, name=name, rtype=rtype, params=params, locals=locals_, body=body, handler=handler, line=line)

    # statements
    def block(self, *enders):
        out = []
        while not self.at_kw(*enders):
            if self.peek()[0] == "eof": raise RapidSyntaxError(f"unexpected end of file, expected one of {enders}")
            out.append(self.stmt())
        return out

    def stmt(self):
        kind, val, line = self.peek()
        if kind == "kw":
            if val == "IF": return self.if_stmt()
            if val == "TEST": return self.test_stmt()
            if val == "WHILE":
                self.next(); c = self.expr(); self.expect("DO"); b = self.block("ENDWHILE"); self.next()
                return ("while", line, c, b)
            if val == "FOR":
                self.next(); v = self.ident(); self.expect("FROM"); a = self.expr(); self.expect("TO"); b = self.expr()
                step = None
                if self.at_kw("STEP"): self.next(); step = self.expr()
                self.expect("DO"); body = self.block("ENDFOR"); self.next()
                return ("for", line, v, a, b, step, body)
            if val in ("RETURN", "RAISE"):
                self.next(); e = None if self.at(";") else self.expr(); self.expect(";")
                return (val.lower(), line, e)
            if val in ("RETRY", "TRYNEXT", "EXIT"):
                self.next(); self.expect(";"); return (val.lower(), line)
            raise RapidSyntaxError(f"line {line}: unexpected keyword {val}")
        if kind == "id" and self.peek(1)[1] == ":" and self.peek(2)[1] != "=":  # label
            self.next(); self.next(); return ("nop", line)
        # assignment or call
        save = self.i
        target = self.lvalue()
        if self.at(":="):
            self.next(); e = self.expr(); self.expect(";")
            return ("assign", line, target, e)
        self.i = save
        name = self.ident()
        args, opts = self.call_args()
        self.expect(";")
        return ("call", line, name, args, opts)

    def lvalue(self):
        path = [("name", self.ident())]
        while True:
            if self.at("."): self.next(); path.append(("field", self.ident()))
            elif self.at("{"):
                self.next(); idx = [self.expr()]
                while self.at(","): self.next(); idx.append(self.expr())
                self.expect("}"); path.append(("index", idx))
            else: return path

    def call_args(self):
        args, opts = [], {}
        def options():
            while self.at("\\"):
                self.next(); oname = self.ident()
                if self.at(":="): self.next(); opts[oname] = self.expr()
                else: opts[oname] = True
        options()
        if self.at(","): self.next()
        while not self.at(";"):
            args.append(self.expr()); options()
            if self.at(","): self.next(); options()
            elif not self.at(";"):
                tok = self.peek(); raise RapidSyntaxError(f"line {tok[2]}: unexpected {tok[1]!r} in argument list")
        return args, opts

    def if_stmt(self):
        line = self.next()[2]; c = self.expr()
        if not self.at_kw("THEN"):  # compact IF: IF cond stmt;
            return ("if", line, [(c, [self.stmt()])], None)
        self.next(); branches = [(c, self.block("ELSEIF", "ELSE", "ENDIF"))]; else_ = None
        while self.at_kw("ELSEIF"):
            self.next(); c = self.expr(); self.expect("THEN"); branches.append((c, self.block("ELSEIF", "ELSE", "ENDIF")))
        if self.at_kw("ELSE"): self.next(); else_ = self.block("ENDIF")
        self.expect("ENDIF")
        return ("if", line, branches, else_)

    def test_stmt(self):
        line = self.next()[2]; e = self.expr(); cases, default = [], None
        while self.at_kw("CASE"):
            self.next(); vals = [self.expr()]
            while self.at(","): self.next(); vals.append(self.expr())
            self.expect(":"); cases.append((vals, self.block("CASE", "DEFAULT", "ENDTEST")))
        if self.at_kw("DEFAULT"): self.next(); self.expect(":"); default = self.block("ENDTEST")
        self.expect("ENDTEST")
        return ("test", line, e, cases, default)

    # expressions
    def expr(self): return self.or_()

    def or_(self):
        e = self.and_()
        while self.at_kw("OR", "XOR"): op = self.next()[1]; e = ("bin", op, e, self.and_())
        return e

    def and_(self):
        e = self.not_()
        while self.at_kw("AND"): self.next(); e = ("bin", "AND", e, self.not_())
        return e

    def not_(self):
        if self.at_kw("NOT"): self.next(); return ("not", self.not_())
        return self.cmp()

    def cmp(self):
        e = self.add()
        while self.at("=", "<>", "<", ">", "<=", ">="): op = self.next()[1]; e = ("bin", op, e, self.add())
        return e

    def add(self):
        e = self.mul()
        while self.at("+", "-"): op = self.next()[1]; e = ("bin", op, e, self.mul())
        return e

    def mul(self):
        e = self.unary()
        while self.at("*", "/") or self.at_kw("DIV", "MOD"): op = self.next()[1]; e = ("bin", op, e, self.unary())
        return e

    def unary(self):
        if self.at("-"): self.next(); return ("neg", self.unary())
        if self.at("+"): self.next(); return self.unary()
        return self.postfix()

    def postfix(self):
        kind, val, line = self.next()
        if kind == "num": e = ("num", float(val))
        elif kind == "str": e = ("str", val[1:-1].replace('""', '"'))
        elif kind == "kw" and val in ("TRUE", "FALSE"): e = ("bool", val == "TRUE")
        elif val == "(": e = self.expr(); self.expect(")")
        elif val == "[":
            items = [] if self.at("]") else [self.expr()]
            while self.at(","): self.next(); items.append(self.expr())
            self.expect("]"); e = ("agg", items)
        elif kind == "id":
            if self.at("("):
                self.next(); args, opts = [], {}
                while not self.at(")"):
                    if self.at("\\"):
                        self.next(); o = self.ident()
                        opts[o] = (self.next(), self.expr())[1] if self.at(":=") else True
                    else:
                        args.append(self.expr())
                    if self.at(","): self.next()
                self.next(); e = ("fcall", val, args, opts)
            else:
                e = ("name", val)
        else:
            raise RapidSyntaxError(f"line {line}: unexpected {val!r} in expression")
        while True:
            if self.at("."): self.next(); e = ("field", e, self.ident())
            elif self.at("{"):
                self.next(); idx = [self.expr()]
                while self.at(","): self.next(); idx.append(self.expr())
                self.expect("}"); e = ("index", e, idx)
            else: return e


def parse(src):
    return Parser(src).module()


# ---------------------------------------------------------------- values
def speed_named(name):
    m = re.fullmatch(r"v(\d+)", name)
    if m: return [float(m[1]), 500.0, 5000.0, 1000.0]
    if name == "vmax": return [7000.0, 500.0, 5000.0, 1000.0]
    return None


def zone_named(name):
    if name == "fine": return [0.0]
    m = re.fullmatch(r"z(\d+)", name)
    return [float(m[1])] if m else None


def default_value(typ, records):
    if typ in records: return {f: default_value(t, records) for t, f in records[typ]}
    if typ in ("num", "dnum", "errnum", "intnum"): return 0.0
    if typ == "bool": return False
    if typ == "string": return ""
    return None


class Task:
    """One RAPID task bound to a robot in the world."""

    def __init__(self, name, modules_src, world, robot_id):
        self.name, self.world, self.robot = name, world, robot_id
        self.records, self.routines, self.globals = {}, {}, {}
        mods = [parse(s) for s in modules_src]
        for m in mods:
            self.records.update(m["records"]); self.routines.update(m["routines"])
        for m in mods:
            for d in m["data"]: self._declare(d, self.globals)
        self.next_errno = 90
        self.log = []

    def _declare(self, d, scope):
        _, line, storage, typ, name, dims, init = d
        if dims is not None:
            n = int(self.eval(dims[0], [scope]))
            scope[name] = [default_value(typ, self.records) for _ in range(n)]
        else:
            scope[name] = default_value(typ, self.records)
        if init is not None:
            scope[name] = self._coerce(typ, self.eval(init, [scope]))

    def _coerce(self, typ, v):
        if typ in self.records and isinstance(v, list):
            return {f: self._coerce(t, x) for (t, f), x in zip(self.records[typ], v)}
        return v

    # ---- name resolution
    def lookup(self, name, scopes):
        for s in scopes:
            if name in s: return s[name]
        if name in self.globals: return self.globals[name]
        if name == "ERR_WAIT_MAXTIME": return float(ERR_WAIT_MAXTIME)
        v = speed_named(name) or zone_named(name)
        if v is not None: return v
        if name in ("wobj0", "tool0", "load0"): return name
        if self.world.has_signal(name): return float(self.world.read_signal(self, name))
        raise RapidError(-1, f"unknown name {name}")

    def store(self, path, value, scopes):
        root = path[0][1]
        scope = next((s for s in scopes if root in s), None)
        if scope is None:
            if root in self.globals: scope = self.globals
            else: raise RapidError(-1, f"assignment to undeclared {root}")
        value = copy.deepcopy(value) if isinstance(value, (list, dict)) else value  # RAPID assigns by value
        if len(path) == 1: scope[root] = value; return
        obj = scope[root]
        for kind, key in path[1:-1]:
            obj = (obj[key] if isinstance(obj, dict) else obj[_field_index(obj, key)]) if kind == "field" else obj[int(self.eval(key[0], scopes)) - 1]
        kind, key = path[-1]
        if kind == "field":
            if isinstance(obj, dict): obj[key] = value
            else: obj[_field_index(obj, key)] = value
        else: obj[int(self.eval(key[0], scopes)) - 1] = value

    # ---- expressions
    def eval(self, e, scopes):
        k = e[0]
        if k == "num": return e[1]
        if k in ("str", "bool"): return e[1]
        if k == "name": return self.lookup(e[1], scopes)
        if k == "agg": return [self.eval(x, scopes) for x in e[1]]
        if k == "neg": return -self.eval(e[1], scopes)
        if k == "not": return not self.eval(e[1], scopes)
        if k == "field":
            v = self.eval(e[1], scopes)
            if isinstance(v, dict): return v[e[2]]
            return _robtarget_field(v, e[2])
        if k == "index":
            v = self.eval(e[1], scopes); return v[int(self.eval(e[2][0], scopes)) - 1]
        if k == "bin":
            op = e[1]
            if op == "AND": return bool(self.eval(e[2], scopes)) and bool(self.eval(e[3], scopes))
            if op == "OR": return bool(self.eval(e[2], scopes)) or bool(self.eval(e[3], scopes))
            a, b = self.eval(e[2], scopes), self.eval(e[3], scopes)
            if op == "XOR": return bool(a) != bool(b)
            if op == "+": return a + b
            if op == "-": return a - b
            if op == "*": return a * b
            if op == "/": return a / b
            if op == "DIV": return float(int(a) // int(b))
            if op == "MOD": return float(int(a) % int(b))
            if op == "=": return a == b
            if op == "<>": return a != b
            if op == "<": return a < b
            if op == ">": return a > b
            if op == "<=": return a <= b
            if op == ">=": return a >= b
        if k == "fcall": return self.func(e[1], [self.eval(a, scopes) for a in e[2]], e[3], scopes)
        raise RapidError(-1, f"cannot evaluate {k}")

    def func(self, name, args, opts, scopes):
        if name == "Offs":
            p = [list(x) for x in args[0]]
            p[0] = [p[0][0] + args[1], p[0][1] + args[2], p[0][2] + args[3]]
            return p
        if name == "Abs": return abs(args[0])
        if name == "Round": return float(round(args[0], int(self.eval(opts["Dec"], scopes)) if "Dec" in opts else 0))
        if name == "Trunc": return float(int(args[0]))
        if name == "Sqrt": return float(np.sqrt(args[0]))
        if name in ("NumToStr", "ValToStr"): return str(args[0])
        if name in ("DOutput", "DInput"): return float(args[0])
        if name in self.routines and self.routines[name]["kind"] == "FUNC":
            return self.world.run_func(self, name, args)
        raise RapidError(-1, f"unknown function {name}")

    # ---- execution (generators)
    def run_main(self):
        """Continuous mode: call main() until Stop/EXIT/fatal error."""
        while True:
            yield from self.call("main", [], {}, 0)

    def call(self, name, args, opts, line):
        if name not in self.routines:
            yield from self.world.instruction(self, name, args, opts, line)
            return
        r = self.routines[name]
        scope = {}
        pos = [p for p in r["params"] if not p[2]]
        for (typ, pname, _), v in zip(pos, args): scope[pname] = v
        for typ, pname, optional in r["params"]:
            if optional: scope[pname] = opts.get(pname)
        for d in r["locals"]: self._declare(d, scope)
        try:
            yield from self.run_block_with_handler(r, scope)
        except _Return as ret:
            return ret.value

    def run_block_with_handler(self, r, scope):
        body, i, retries = r["body"], 0, 0
        while i < len(body):
            try:
                yield from self.exec(body[i], [scope])
                i += 1
            except RapidError as err:
                if r["handler"] is None: raise
                scope["ERRNO"] = float(err.errno)
                self.log.append(("error_handler", self.world.now, r["name"], err.errno))
                try:
                    for s in r["handler"]: yield from self.exec(s, [scope])
                    raise _Return()
                except _Retry:
                    retries += 1
                    if retries > MAX_RETRY: raise err
                except _Trynext:
                    i += 1

    def exec(self, s, scopes):
        k, line = s[0], s[1]
        self.world.current_line(self, line)
        if k == "assign":
            self.store(s[2], self.eval(s[3], scopes), scopes)
        elif k == "call":
            name = s[2]
            if name == "WaitUntil":
                args = [(lambda e=s[3][0], sc=scopes: bool(self.eval(e, sc)))]
            else:
                args = [self._arg(a, name, j, scopes) for j, a in enumerate(s[3])]
            opts = {o: (v if v is True else self._optarg(o, v, scopes)) for o, v in s[4].items()}
            yield from self.call(name, args, opts, line)
        elif k == "if":
            for cond, blk in s[2]:
                if self.eval(cond, scopes):
                    for x in blk: yield from self.exec(x, scopes)
                    break
            else:
                for x in (s[3] or []): yield from self.exec(x, scopes)
        elif k == "test":
            v = self.eval(s[2], scopes)
            for vals, blk in s[3]:
                if any(self.eval(x, scopes) == v for x in vals):
                    for x in blk: yield from self.exec(x, scopes)
                    break
            else:
                for x in (s[4] or []): yield from self.exec(x, scopes)
        elif k == "while":
            n = 0
            while self.eval(s[2], scopes):
                for x in s[3]: yield from self.exec(x, scopes)
                n += 1
                if n % 1000 == 0: yield ("sleep", 0.0)
        elif k == "for":
            a, b = self.eval(s[3], scopes), self.eval(s[4], scopes)
            step = self.eval(s[5], scopes) if s[5] else (1.0 if b >= a else -1.0)
            v = a
            while (v <= b) if step > 0 else (v >= b):
                scopes[0][s[2]] = v
                for x in s[6]: yield from self.exec(x, scopes)
                v += step
        elif k == "return":
            raise _Return(self.eval(s[2], scopes) if s[2] else None)
        elif k == "raise":
            if s[2] is None:
                errno = int(scopes[0].get("ERRNO", -1)) if scopes else -1
            else:
                errno = int(self.eval(s[2], scopes))
            raise RapidError(errno, "RAISE")
        elif k == "retry": raise _Retry()
        elif k == "trynext": raise _Trynext()
        elif k == "exit": raise TaskStop("EXIT")
        elif k == "nop": pass
        else: raise RapidError(-1, f"unsupported statement {k}")
        if False: yield  # keep this a generator

    def _arg(self, a, callee, j, scopes):
        if callee == "BookErrNo" and a[0] == "name": return Ref(self, a[1], scopes)
        if callee in SIGNAL_INSTR and j == 0 and a[0] == "name": return a[1]  # signal passed by name
        return self.eval(a, scopes)

    def _optarg(self, opt, v, scopes):
        if opt in REF_OPTS:  # output arguments, e.g. WaitDI ...\TimeFlag:=flag
            return Ref(self, v[1], scopes)
        return self.eval(v, scopes)

    def _is_var(self, name, scopes):
        return any(name in s for s in scopes) or name in self.globals


REF_OPTS = {"TimeFlag"}
SIGNAL_INSTR = {"SetDO", "PulseDO", "Set", "Reset", "WaitDI", "WaitDO", "InvertDO"}


class Ref:
    """Output argument: a variable the instruction writes back."""
    def __init__(self, task, name, scopes): self.task, self.name, self.scopes = task, name, scopes
    def set(self, value): self.task.store([("name", self.name)], value, self.scopes)


# Built-in RAPID records are held as aggregates (lists); component names map to positions.
BUILTIN_FIELDS = dict(trans=0, rot=1, robconf=2, robhold=0, ufprog=1, ufmec=2, uframe=3, oframe=4, tframe=1, tload=2,
                      x=0, y=1, z=2, q1=0, q2=1, q3=2, q4=3, cf1=0, cf4=1, cf6=2, cfx=3, robax=0, mass=0, cog=1, aom=2,
                      **{f"rax_{i}": i - 1 for i in range(1, 7)}, **{f"eax_{c}": i for i, c in enumerate("abcdef")})


def _field_index(v, f):
    if f == "extax": return 1 if len(v) == 2 else 3   # jointtarget.extax vs robtarget.extax
    if f in BUILTIN_FIELDS and BUILTIN_FIELDS[f] < len(v): return BUILTIN_FIELDS[f]
    raise RapidError(-1, f"no field {f}")


def _robtarget_field(v, f):
    return v[_field_index(v, f)]
