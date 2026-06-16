"""
Solidity contract parser — adapted for BNB Chain / BSC contracts.
Extracts: state variables, functions, events, modifiers, errors, inheritance.
"""
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class StateVar:
    line: int
    name: str
    type_: str
    visibility: str
    is_constant: bool
    is_immutable: bool
    raw: str


@dataclass
class Function:
    line: int
    name: str
    visibility: str
    mutability: str
    modifiers: List[str]
    params: str
    returns: str
    body_lines: List[Tuple[int, str]]
    is_constructor: bool
    is_fallback: bool
    is_receive: bool
    raw: str

    def body_text(self) -> str:
        return "\n".join(t for _, t in self.body_lines)

    def body_range(self) -> Tuple[int, int]:
        if not self.body_lines:
            return (self.line, self.line)
        return (self.body_lines[0][0], self.body_lines[-1][0])


@dataclass
class Event:
    line: int
    name: str
    params: str
    raw: str


@dataclass
class CustomError:
    line: int
    name: str
    raw: str


@dataclass
class ModifierDef:
    line: int
    name: str
    raw: str


@dataclass
class Contract:
    name: str
    line: int
    kind: str
    inheritance: List[str]
    state_vars: List[StateVar]
    functions: List[Function]
    events: List[Event]
    errors: List[CustomError]
    modifiers: List[ModifierDef]
    using_directives: List[str]


@dataclass
class ParsedFile:
    source: str
    lines: List[str]
    pragma: Optional[str]
    imports: List[str]
    contracts: List[Contract]
    parse_warnings: List[str]


def _strip_comments(source: str) -> Tuple[str, List[str]]:
    source = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group().count("\n"), source, flags=re.DOTALL)
    lines = []
    for line in source.splitlines():
        idx = line.find("//")
        if idx >= 0:
            before = line[:idx]
            if before.count('"') % 2 == 0 and before.count("'") % 2 == 0:
                line = line[:idx]
        lines.append(line)
    return "\n".join(lines), lines


def _find_block_end(lines: List[str], start_line: int) -> int:
    depth = 0
    for i in range(start_line, len(lines)):
        depth += lines[i].count("{") - lines[i].count("}")
        if depth <= 0 and i >= start_line:
            return i
    return len(lines) - 1


_PRAGMA_RE    = re.compile(r"^\s*pragma\s+solidity\s+([^;]+);", re.MULTILINE)
_IMPORT_RE    = re.compile(r'^\s*import\s+["\']([^"\']+)["\']', re.MULTILINE)
_CONTRACT_RE  = re.compile(
    r"^[ \t]*(abstract\s+contract|contract|interface|library)\s+(\w+)"
    r"(?:\s+is\s+([\w\s,]+?))?\s*\{",
    re.MULTILINE,
)
_FUNC_RE = re.compile(
    r"^\s*function\s+(\w+)\s*\(([^)]*)\)"
    r"((?:\s+(?:public|private|internal|external|payable|view|pure|virtual|override|[\w]+))*)"
    r"(?:\s+returns\s*\(([^)]*)\))?\s*[{;]"
)
_CONSTRUCTOR_RE = re.compile(
    r"^\s*constructor\s*\(([^)]*)\)"
    r"((?:\s+(?:public|payable|internal|[\w]+))*)"
    r"\s*\{"
)
_FALLBACK_RE  = re.compile(r"^\s*(?:fallback|receive)\s*\(")
_EVENT_RE     = re.compile(r"^\s*event\s+(\w+)\s*\(([^)]*)\)\s*;")
_ERROR_RE     = re.compile(r"^\s*error\s+(\w+)\s*\([^)]*\)\s*;")
_MODIFIER_RE  = re.compile(r"^\s*modifier\s+(\w+)\s*\(")
_USING_RE     = re.compile(r"^\s*using\s+(\w+)\s+for\s+")


def parse(source: str) -> ParsedFile:
    warnings: List[str] = []
    clean_source, raw_lines = _strip_comments(source)
    lines = raw_lines

    pragma = None
    m = _PRAGMA_RE.search(clean_source)
    if m:
        pragma = m.group(1).strip()

    imports = _IMPORT_RE.findall(clean_source)
    contracts: List[Contract] = []

    for cm in _CONTRACT_RE.finditer(clean_source):
        kind_raw = cm.group(1).strip()
        kind = "abstract" if "abstract" in kind_raw else kind_raw
        name = cm.group(2)
        inheritance_raw = cm.group(3) or ""
        inheritance = [x.strip() for x in inheritance_raw.split(",") if x.strip()]

        start_lineno = clean_source[: cm.start()].count("\n")
        end_lineno   = _find_block_end(lines, start_lineno)
        contract_lines = list(enumerate(lines[start_lineno : end_lineno + 1], start=start_lineno))

        state_vars: List[StateVar] = []
        functions:  List[Function] = []
        events:     List[Event] = []
        errors:     List[CustomError] = []
        modifiers:  List[ModifierDef] = []
        using:      List[str] = []

        i = 0
        while i < len(contract_lines):
            abs_lineno, text = contract_lines[i]

            em = _EVENT_RE.match(text)
            if em:
                events.append(Event(abs_lineno + 1, em.group(1), em.group(2), text.strip()))
                i += 1
                continue

            erm = _ERROR_RE.match(text)
            if erm:
                errors.append(CustomError(abs_lineno + 1, erm.group(1), text.strip()))
                i += 1
                continue

            um = _USING_RE.match(text)
            if um:
                using.append(text.strip())
                i += 1
                continue

            mm = _MODIFIER_RE.match(text)
            if mm:
                modifiers.append(ModifierDef(abs_lineno + 1, mm.group(1), text.strip()))
                if "{" in text:
                    rel_end = _find_block_end(lines, abs_lineno) - start_lineno
                    i = rel_end + 1
                else:
                    i += 1
                continue

            cm2 = _CONSTRUCTOR_RE.match(text)
            if cm2:
                params   = cm2.group(1)
                mods_raw = cm2.group(2).strip()
                mods = [w for w in mods_raw.split() if w not in
                        ("public", "private", "internal", "external", "payable", "view", "pure", "virtual", "override")]
                body_end_abs = _find_block_end(lines, abs_lineno)
                body_lines = [(n, lines[n]) for n in range(abs_lineno, body_end_abs + 1)]
                functions.append(Function(
                    line=abs_lineno + 1, name="constructor", visibility="public",
                    mutability="payable" if "payable" in mods_raw else "",
                    modifiers=mods, params=params, returns="",
                    body_lines=body_lines, is_constructor=True,
                    is_fallback=False, is_receive=False, raw=text.strip(),
                ))
                i = body_end_abs - start_lineno + 1
                continue

            fb = _FALLBACK_RE.match(text)
            if fb:
                is_receive   = "receive" in text
                body_end_abs = _find_block_end(lines, abs_lineno) if "{" in text else abs_lineno
                body_lines   = [(n, lines[n]) for n in range(abs_lineno, body_end_abs + 1)]
                functions.append(Function(
                    line=abs_lineno + 1,
                    name="receive" if is_receive else "fallback",
                    visibility="external", mutability="payable" if "payable" in text else "",
                    modifiers=[], params="", returns="",
                    body_lines=body_lines, is_constructor=False,
                    is_fallback=not is_receive, is_receive=is_receive, raw=text.strip(),
                ))
                i = body_end_abs - start_lineno + 1
                continue

            fm = _FUNC_RE.match(text)
            if fm:
                fname     = fm.group(1)
                fparams   = fm.group(2)
                fmods_raw = fm.group(3).strip()
                freturns  = fm.group(4) or ""
                vis, mut, mods = "public", "", []
                for word in fmods_raw.split():
                    if word in ("public", "private", "internal", "external"):
                        vis = word
                    elif word in ("payable", "view", "pure"):
                        mut = word
                    elif word not in ("virtual", "override", ""):
                        mods.append(word)

                if "{" in text and not text.strip().endswith(";"):
                    body_end_abs = _find_block_end(lines, abs_lineno)
                    body_lines   = [(n, lines[n]) for n in range(abs_lineno, body_end_abs + 1)]
                    i = body_end_abs - start_lineno + 1
                else:
                    body_lines = [(abs_lineno, text)]
                    i += 1

                functions.append(Function(
                    line=abs_lineno + 1, name=fname, visibility=vis,
                    mutability=mut, modifiers=mods, params=fparams,
                    returns=freturns, body_lines=body_lines,
                    is_constructor=False, is_fallback=False, is_receive=False,
                    raw=text.strip(),
                ))
                continue

            sv_skip = re.match(
                r"^\s*(return|emit|require|revert|assert|if|for|while|else|"
                r"mapping|address|uint|int|bool|bytes|string|\/\/)",
                text,
            )
            if (text.strip().endswith(";") and not sv_skip
                    and not text.strip().startswith("//")
                    and "(" not in text.split("=")[0]):
                svm = re.match(
                    r"^\s*([\w\[\]<>(),\.\s]+?)\s+"
                    r"(?:(public|private|internal)\s+)?"
                    r"(?:(constant|immutable)\s+)?"
                    r"(\w+)\s*(?:=.*)?;",
                    text,
                )
                if svm:
                    state_vars.append(StateVar(
                        line=abs_lineno + 1,
                        name=svm.group(4),
                        type_=svm.group(1).strip(),
                        visibility=svm.group(2) or "internal",
                        is_constant="constant" in text.lower(),
                        is_immutable="immutable" in text.lower(),
                        raw=text.strip(),
                    ))
            i += 1

        contracts.append(Contract(
            name=name, line=start_lineno + 1, kind=kind,
            inheritance=inheritance, state_vars=state_vars,
            functions=functions, events=events,
            errors=errors, modifiers=modifiers,
            using_directives=using,
        ))

    return ParsedFile(
        source=source, lines=lines, pragma=pragma,
        imports=imports, contracts=contracts, parse_warnings=warnings,
    )
