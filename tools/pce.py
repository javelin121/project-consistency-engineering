#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pce — project consistency engineering.

单文件、Python 3.9+、只用标准库。用法见同目录上一层的 SKILL.md。
"""

import fnmatch
import hashlib
import datetime
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata

VERSION = "0.6.1"

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2

CONTRACT = "structure.yaml"
NAV = "navigation.md"
AGENTS = "AGENTS.md"
ARCHIVE_LOG = "ARCHIVE.md"
SHA = "pce.py.sha256"

DEFAULT_ROOT_ALLOW = [
    "README.md", "README.zh.md", "CHANGELOG.md", "CONTRIBUTING.md", "SECURITY.md",
    "LICENSE", "LICENSE.md", "AGENTS.md", "SKILL.md", "CLAUDE.md", "GEMINI.md", ".cursorrules",
    "structure.yaml", "navigation.md", ".gitignore", ".gitattributes", ".editorconfig",
    "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt",
    "uv.lock", "poetry.lock", "Pipfile", "Pipfile.lock",
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb",
    "tsconfig.json", "vite.config.ts", "next.config.js",
    "Cargo.toml", "Cargo.lock", "go.mod", "go.sum",
    "Makefile", "justfile", "Dockerfile", "docker-compose.yml", ".dockerignore",
    "mkdocs.yml",
]

DEFAULT_IGNORE = [
    ".git/", ".venv/", "node_modules/", "__pycache__/", ".pytest_cache/", "dist/",
    ".DS_Store",
]

TEXT_EXT = [".md", ".py", ".js", ".ts", ".json", ".yaml", ".yml", ".toml", ".txt"]
MAX_TEXT = 2 * 1024 * 1024

STYLES = ("snake", "kebab", "pascal", "camel")

VAGUE = {"其他", "其它", "杂项", "临时", "暂存", "待定", "别的", "等等",
         "other", "misc", "temp", "tmp", "todo", "tbd"}
STOP = {"的", "了", "和", "与", "及", "或", "等", "是", "在", "为", "把", "被",
        "the", "a", "an", "of", "for", "and", "or", "to", "in", "on", "is"}


# ---------------------------------------------------------------- YAML 子集

class YamlError(Exception):
    def __init__(self, line, msg):
        self.line = line
        self.msg = msg
        Exception.__init__(self, "第 %d 行：%s" % (line, msg))


def _strip_comment(line):
    out = []
    quote = None
    for ch in line:
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            out.append(ch)
        elif ch == "#":
            break
        else:
            out.append(ch)
    return "".join(out).rstrip()


def _scalar(text, line):
    t = text.strip()
    if not t:
        return ""
    if t[0] in "&*|>":
        raise YamlError(line, "不支持锚点、别名、块标量（%s 开头）；写法见 references/contract.md" % t[0])
    if t[0] == "{":
        raise YamlError(line, "不支持行内映射 {…}；写成多行")
    if t in ("---", "..."):
        raise YamlError(line, "不支持多文档（--- / ...）")
    if t[0] == "[" and t[-1] == "]":
        inner = t[1:-1].strip()
        if not inner:
            return []
        return [_scalar(part, line) for part in _split_commas(inner)]
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
        return t[1:-1]
    if t == "true":
        return True
    if t == "false":
        return False
    if re.match(r"^-?\d+$", t):
        return int(t)
    return t


def _split_commas(text):
    parts, buf, quote = [], [], None
    for ch in text:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch == ",":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return parts


def _tokenize(text):
    items = []
    for i, raw in enumerate(text.splitlines(), 1):
        if raw.strip() in ("---", "..."):
            raise YamlError(i, "不支持多文档（--- / ...）")
        body = _strip_comment(raw)
        if not body.strip():
            continue
        if "\t" in body[: len(body) - len(body.lstrip())]:
            raise YamlError(i, "缩进里不能用 tab，请用两个空格")
        indent = len(body) - len(body.lstrip(" "))
        items.append((i, indent, body.strip()))
    return items


def _block(items, pos, indent):
    if pos >= len(items):
        return {}, pos
    if items[pos][2].startswith("- "):
        return _block_list(items, pos, indent)
    return _block_map(items, pos, indent)


def _block_list(items, pos, indent):
    out = []
    while pos < len(items) and items[pos][1] == indent and items[pos][2].startswith("- "):
        line, _, body = items[pos]
        rest = body[2:].strip()
        if not rest:
            val, pos = _block(items, pos + 1, indent + 2) if (
                pos + 1 < len(items) and items[pos + 1][1] > indent) else ({}, pos + 1)
            out.append(val)
            continue
        if ":" in rest and not rest.startswith(("'", '"', "[")):
            key, _, tail = rest.partition(":")
            key = key.strip()
            item = {}
            if tail.strip():
                item[key] = _scalar(tail, line)
                pos += 1
            else:
                pos += 1
                if pos < len(items) and items[pos][1] > indent:
                    item[key], pos = _block(items, pos, items[pos][1])
                else:
                    item[key] = {}
            # 同层后续键
            while pos < len(items) and items[pos][1] == indent + 2 and not items[pos][2].startswith("- "):
                l2, _, b2 = items[pos]
                k2, _, t2 = b2.partition(":")
                if t2.strip():
                    item[k2.strip()] = _scalar(t2, l2)
                    pos += 1
                else:
                    pos += 1
                    if pos < len(items) and items[pos][1] > indent + 2:
                        item[k2.strip()], pos = _block(items, pos, items[pos][1])
                    else:
                        item[k2.strip()] = {}
            out.append(item)
            continue
        out.append(_scalar(rest, line))
        pos += 1
    return out, pos


def _block_map(items, pos, indent):
    out = {}
    while pos < len(items) and items[pos][1] >= indent:
        line, ind, body = items[pos]
        if ind > indent:
            raise YamlError(line, "缩进过深，这一行没有可归属的上级键")
        if body.startswith("- "):
            break
        key, sep, tail = body.partition(":")
        if not sep:
            raise YamlError(line, "缺少冒号，写法应为 `键: 值`")
        key = key.strip()
        if key in out:
            raise YamlError(line, "重复的键：%s" % key)
        if tail.strip():
            out[key] = _scalar(tail, line)
            pos += 1
        else:
            pos += 1
            if pos < len(items) and items[pos][1] > indent:
                out[key], pos = _block(items, pos, items[pos][1])
            else:
                out[key] = {}
    return out, pos


def parse_yaml(text):
    items = _tokenize(text)
    if not items:
        return {}
    value, pos = _block(items, 0, items[0][1])
    if pos != len(items):
        raise YamlError(items[pos][0], "这行没有归属，检查缩进或多余的键")
    return value


# ---------------------------------------------------------------- 工具函数

def norm(s):
    s = unicodedata.normalize("NFKC", s or "")
    s = re.sub(r"[\s\W_]+", "", s)
    return s.lower()


def words(s):
    parts = re.split(r"[^\w\u4e00-\u9fff]+", (s or "").lower())
    return [p for p in parts if p and p not in STOP]


def jaccard(a, b):
    sa, sb = set(words(a)), set(words(b))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / float(len(sa | sb))


def is_vague(s):
    w = words(s)
    if not w:
        return True
    return all(x in VAGUE for x in w)


def strip_dot(path):
    while path.startswith("./"):
        path = path[2:]
    return path


def match_any(name, patterns):
    return any(fnmatch.fnmatchcase(name, p) for p in patterns)


def to_posix(p):
    return p.replace(os.sep, "/")


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def git(root, *args):
    try:
        out = subprocess.run(["git"] + list(args), cwd=root,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             timeout=20)
        if out.returncode != 0:
            return None
        return out.stdout.decode("utf-8", "replace").strip()
    except (OSError, subprocess.SubprocessError):
        return None


def git_time(root, relpath):
    out = git(root, "log", "-1", "--format=%cs", "--", relpath)
    return out or ""


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_root():
    try:
        out = subprocess.check_output(["git", "rev-parse", "--show-toplevel"],
                                      stderr=subprocess.DEVNULL)
    except Exception:
        return None
    return out.decode("utf-8", "replace").strip() or None


def find_root(start=None):
    cur = os.path.abspath(start or os.getcwd())
    while True:
        if os.path.isfile(os.path.join(cur, CONTRACT)):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


# ---------------------------------------------------------------- 契约

class ContractError(Exception):
    pass


class Contract(object):
    def __init__(self, path, data):
        self.path = path
        self.data = data
        self.version = data.get("version")
        zones = data.get("zones") or {}
        self.zones = {}
        for name, body in zones.items():
            body = body or {}
            self.zones[name] = {
                "what": body.get("what", ""),
                "entry": body.get("entry", ""),
            }
        root = data.get("root") or {}
        allow = root.get("allow") if isinstance(root, dict) else None
        merged = list(DEFAULT_ROOT_ALLOW)
        for name in allow or []:
            if name not in merged:
                merged.append(name)
        self.root_allow = merged
        naming = data.get("naming") or {}
        self.naming_default = naming.get("default", "")
        self.naming_zones = dict(naming.get("zones") or {})
        self.naming_files = dict(naming.get("files") or {})
        archive = data.get("archive") or {}
        self.archive_path = (archive.get("path", "archive/") or "").rstrip("/")
        raw_ignore = data["ignore"] if "ignore" in data else DEFAULT_IGNORE
        self.ignore = [str(x) for x in (raw_ignore if isinstance(raw_ignore, list) else [])]

    def archive_dir(self):
        return self.archive_path

    def is_ignored(self, name):
        for item in self.ignore:
            if item.endswith("/"):
                if name == item[:-1]:
                    return True
            elif name == item:
                return True
        return False

    def style_for(self, relpath):
        base = os.path.basename(relpath)
        for pattern, style in self.naming_files.items():
            if fnmatch.fnmatchcase(base, pattern):
                return style
        first = relpath.split("/")[0]
        if first in self.naming_zones:
            return self.naming_zones[first]
        return self.naming_default


def load_contract(root):
    path = os.path.join(root, CONTRACT)
    if not os.path.isfile(path):
        raise ContractError("找不到 %s，先跑 `pce init`" % CONTRACT)
    text = read_text(path)
    try:
        data = parse_yaml(text)
    except YamlError as exc:
        raise ContractError("%s 解析失败：%s" % (CONTRACT, exc))
    if not isinstance(data, dict):
        raise ContractError("%s 的顶层必须是键值表" % CONTRACT)
    if data.get("version") != 1:
        raise ContractError("%s 的 version 必须是 1（读到 %r）" % (CONTRACT, data.get("version")))
    zones = data.get("zones")
    if not isinstance(zones, dict) or not zones:
        raise ContractError("%s 里 zones 至少写一个分区" % CONTRACT)
    for name, body in zones.items():
        if "/" in name or name in (".", "..") or not re.match(r"^[A-Za-z0-9._-]+$", name):
            raise ContractError("分区名 %r 只能是一级目录名（字母数字点横线下划线）" % name)
        if not isinstance(body, dict):
            raise ContractError("分区 %s 的写法应为 `名字:` 下面写 `what:`" % name)
        if not str(body.get("what", "")).strip():
            raise ContractError("分区 %s 没有写 what（这个分区负责什么）" % name)
    naming = data.get("naming") or {}
    for key in ["default"] + list((naming.get("zones") or {}).keys()):
        style = naming.get("default") if key == "default" else (naming.get("zones") or {})[key]
        if style and style not in STYLES:
            raise ContractError("命名风格 %r 不认识，只能用 %s" % (style, " / ".join(STYLES)))
    for pattern, style in (naming.get("files") or {}).items():
        if style not in STYLES:
            raise ContractError("命名风格 %r 不认识，只能用 %s" % (style, " / ".join(STYLES)))
    known = {"version", "zones", "root", "naming", "archive", "ignore"}
    for key in data:
        if key not in known:
            raise ContractError("不认识的字段 %r（顶层只允许 %s）" % (key, "、".join(sorted(known))))
    return Contract(path, data)


# ---------------------------------------------------------------- 扫描

class Scan(object):
    def __init__(self, root, contract):
        self.skipped = []
        self.root = root
        self.contract = contract
        self.files = []
        self.dirs = []
        self.texts = {}
        self._walk()

    def _is_tool_dir(self, name):
        """根下以 . 开头的目录是工具目录（.github/、.vscode/），整棵子树不参与结构检查。

        它们在根上是被放行的既有事实，但不该被要求配 navigation.md，也不该被当作分区。
        认了分区名就按分区算，不再当工具目录。
        """
        if not name.startswith("."):
            return False
        return name not in self.contract.zones

    def _walk(self):
        archive = self.contract.archive_dir()
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(d for d in dirnames
                                 if d != ".git" and not self.contract.is_ignored(d))
            rel = to_posix(os.path.relpath(dirpath, self.root))
            if rel != ".":
                self.dirs.append(rel)
            if rel == ".":
                base = ""
            else:
                base = rel + "/"
            for name in sorted(filenames):
                rp = base + name
                self.files.append(rp)
                if os.path.splitext(name)[1].lower() in TEXT_EXT:
                    full = os.path.join(dirpath, name)
                    try:
                        if os.path.getsize(full) > MAX_TEXT:
                            self.skipped.append((rp, os.path.getsize(full)))
                            continue
                    except OSError:
                        continue
                    self.texts[rp] = read_text(full)
        self.file_set = set(self.files)
        self.dir_set = set(self.dirs)
        self.tool_dirs = set(d for d in self.dirs
                             if d.startswith(".") and "/" not in d
                             and d not in self.contract.zones)

    def in_tool(self, relpath):
        """点开头的目录（.github/、.vscode/，任何层级）及其子树：不参与结构检查。"""
        for seg in relpath.split("/"):
            if seg.startswith(".") and seg not in self.contract.zones:
                return True
        return False

    def in_archive(self, relpath):
        a = self.contract.archive_dir()
        return bool(a) and (relpath == a or relpath.startswith(a + "/"))

    def subtree_files(self, reldir):
        prefix = reldir + "/"
        return [f for f in self.files if f.startswith(prefix)]

    def direct_subdirs(self, reldir):
        prefix = "" if reldir == "." else reldir + "/"
        out = []
        for d in self.dirs:
            if not d.startswith(prefix):
                continue
            rest = d[len(prefix):]
            if "/" not in rest:
                if rest.startswith(".") and d not in self.contract.zones:
                    continue
                out.append(rest)
        return sorted(out)


BASELINE_OF = {
    "S1": "I1", "S2": "I2", "S3": "I2", "S4": "I2", "S5": "I4", "S6": "I4",
    "S7": "I2", "S8": "I1", "S9": "I2", "S10": "I4", "S11": "I5", "S12": "I4",
}


class Finding(object):
    def __init__(self, rule, path, level, message):
        self.rule = rule
        self.path = path
        self.level = level
        self.message = message

    def line(self):
        return "%s  %s  %s  %s" % (self.path or ".", BASELINE_OF.get(self.rule, self.rule),
                                   self.level, self.message)

    def as_dict(self):
        return {"path": self.path, "rule": self.rule,
                "baseline": BASELINE_OF.get(self.rule, self.rule),
                "level": self.level, "message": self.message}


# ---------------------------------------------------------------- 规则

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
PATH_RE = re.compile(r"(?<![\w./-])((?:\.{0,2}/)?(?:[\w.-]+/)+[\w.-]+\.[A-Za-z0-9]{1,6})(?![\w/])")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _suggest_name(style, name):
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    words = [w for w in re.split(r"[_\-. ]+|(?<=[a-z0-9])(?=[A-Z])", stem) if w]
    if not words:
        return name
    if style == "snake":
        out = "_".join(w.lower() for w in words)
    elif style == "kebab":
        out = "-".join(w.lower() for w in words)
    elif style == "pascal":
        out = "".join(w[:1].upper() + w[1:].lower() for w in words)
    elif style == "camel":
        out = words[0].lower() + "".join(w[:1].upper() + w[1:].lower() for w in words[1:])
    else:
        return name
    return out + ("." + ext if ext else "")


def _is_pce_script(text):
    """按文件头特征认“这是 PCE 自己的脚本”，不认文件名；副本改名也躲不掉。"""
    head = text[:400]
    if "pce — project consistency engineering" in head:
        return True
    return 'CONTRACT = "structure.yaml"' in text and 'VERSION = "' in text


def rule_s1(scan, out):
    root = scan.root
    for name in sorted(os.listdir(root)):
        full = os.path.join(root, name)
        if os.path.isdir(full):
            if scan.contract.is_ignored(name):
                continue
            if name == scan.contract.archive_dir():
                continue
            if name in scan.contract.zones:
                continue
            if name.startswith("."):
                continue
            out.append(Finding("S1", name, "error",
                               "根目录下多了个目录 %s；它是分区就在 zones 里加一项，是工具目录就改成点开头，或者放进 ignore" % name))
        else:
            if scan.contract.is_ignored(name):
                continue
            if not match_any(name, scan.contract.root_allow):
                out.append(Finding("S1", name, "error",
                                   "根目录下多了个文件 %s；要么挪进某个分区，要么在 root.allow 里加一行并说明理由" % name))


MARK_BEGIN = "<!-- pce:begin -->"
MARK_END = "<!-- pce:end -->"


def replace_marked(text, block):
    pattern = re.compile(re.escape(MARK_BEGIN) + r".*?" + re.escape(MARK_END), re.S)
    if not pattern.search(text):
        return text
    return pattern.sub(lambda m: block, text, count=1)


def _nav_path(scan, reldir):
    prefix = "" if reldir == "." else reldir + "/"
    return prefix + NAV


def _has_subdirs(scan, reldir):
    return bool(scan.direct_subdirs(reldir))


def rule_s2(scan, out):
    layers = ["."] + [d for d in scan.dirs
                      if not scan.in_archive(d) and not scan.in_tool(d)]
    for d in layers:
        if scan.in_archive(d):
            continue
        if not _has_subdirs(scan, d):
            continue
        p = _nav_path(scan, d)
        if p not in scan.file_set:
            out.append(Finding("S2", d if d != "." else ".", "error",
                               "这一层有子目录，但没有 %s" % NAV))


TABLE_HEAD = "| 子目录 | 负责什么 | 入口 | 最后更新 |"
TABLE_SEP = "|---|---|---|---|"
MAP_BEGIN = "<!-- pce:map:begin -->"
MAP_END = "<!-- pce:map:end -->"


def parse_nav(text):
    """返回 (首句, 行列表, 是否有 map 段)。行是 dict(name, what, entry, updated)。"""
    first = ""
    rows = []
    has_block = MAP_BEGIN in text
    in_block = not has_block  # 没有标记段时，整篇都当表格读（兼容手写的旧表）
    lines = text.splitlines()
    for i, raw in enumerate(lines):
        line = raw.strip()
        if line == MAP_BEGIN:
            in_block = True
            continue
        if line == MAP_END:
            in_block = False
            continue
        if not first and line and not line.startswith("#") and not line.startswith("|") and not line.startswith("<!--"):
            first = line
        if not in_block:
            continue
        if not line.startswith("|"):
            continue
        if set(line) <= set("|:- "):
            continue
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        if nxt.startswith("|") and set(nxt) <= set("|:- "):
            continue  # 表头行（下一行是分隔线），不是数据
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        rows.append({
            "name": cells[0],
            "what": cells[1] if len(cells) > 1 else "",
            "entry": cells[2] if (has_block and len(cells) > 2) else "",
            "updated": cells[3] if (has_block and len(cells) > 3) else "",
        })
    return first, rows, has_block


def rule_s3(scan, out):
    layers = ["."] + [d for d in scan.dirs
                      if not scan.in_archive(d) and not scan.in_tool(d)]
    for d in layers:
        if scan.in_archive(d):
            continue
        subs = scan.direct_subdirs(d)
        if not subs:
            continue
        p = _nav_path(scan, d)
        if p not in scan.texts:
            continue
        _, rows, _ = parse_nav(scan.texts[p])
        byname = dict((r["name"].rstrip("/"), r) for r in rows)
        for sub in subs:
            row = byname.get(sub)
            where = (d + "/" if d != "." else "") + sub
            if row is None:
                out.append(Finding("S3", where, "error",
                                   "这一层的 %s 里没有 %s 这一行" % (NAV, sub)))
            elif not row["what"].strip():
                out.append(Finding("S3", where, "error", "这一行没写“负责什么”"))
        for row in rows:
            name = row["name"].rstrip("/")
            if name and name not in subs:
                base = "" if d == "." else d + "/"
                out.append(Finding("S3", base + name, "error",
                                   "表里有这一行，但磁盘上没有这个子目录（过期行）"))


def rule_s4(scan, out):
    layers = ["."] + [d for d in scan.dirs
                      if not scan.in_archive(d) and not scan.in_tool(d)]
    for d in layers:
        if scan.in_archive(d):
            continue
        subs = scan.direct_subdirs(d)
        if not subs:
            continue
        p = _nav_path(scan, d)
        if p not in scan.texts:
            continue
        _, rows, _ = parse_nav(scan.texts[p])
        byname = dict((r["name"].rstrip("/"), r) for r in rows)
        for sub in subs:
            if d == "." and sub == scan.contract.archive_dir():
                continue
            base = "" if d == "." else d + "/"
            rel = base + sub
            row = byname.get(sub)
            if row is None:
                continue
            w = row["what"].strip()
            own = scan.texts.get(rel + "/" + NAV)
            s = ""
            if own:
                s, _, _ = parse_nav(own)
                if not s.strip():
                    out.append(Finding("S4", rel + "/" + NAV, "warn",
                                       "第一句没写“这一层是干什么的”"))
            zone = scan.contract.zones.get(sub) if d == "." else None
            if zone:
                what = norm(zone["what"])
                if what:
                    if w and what not in norm(w):
                        out.append(Finding("S4", rel, "warn",
                                           "父表这行与分区说明不一致（应以 zones 里的 what 为准）"))
                    if s and what not in norm(s):
                        out.append(Finding("S4", rel, "warn",
                                           "%s 的首句与分区说明不一致（应以 zones 里的 what 为准）" % NAV))
            else:
                if s and w:
                    nw, ns = norm(w), norm(s)
                    if nw not in ns and ns not in nw:
                        out.append(Finding("S4", rel, "warn",
                                           "父表这行与 %s 的首句对不上" % NAV))


def _style_ok(style, name):
    stem = name
    if style in ("snake", "kebab", "pascal", "camel") and name in ("__init__.py", "__main__.py"):
        return True
    base = stem.split(".", 1)[0]
    if style == "snake":
        return bool(re.match(r"^[a-z0-9]+(_[a-z0-9]+)*$", base))
    if style == "kebab":
        return bool(re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", base))
    if style == "pascal":
        return bool(re.match(r"^[A-Z][A-Za-z0-9]*$", base))
    if style == "camel":
        return bool(re.match(r"^[a-z][A-Za-z0-9]*$", base))
    return True


def _resolve_link(scan, base_rel, target):
    if target.startswith(("http://", "https://", "mailto:", "#")):
        return None
    target = target.split("#")[0].split("?")[0]
    if not target:
        return None
    clean = strip_dot(target)
    base = os.path.dirname(base_rel)
    cand = os.path.normpath(os.path.join(base, target)).replace(os.sep, "/")
    if cand.startswith("../"):
        return False
    return cand


FENCE_RE = re.compile(r"```.*?```", re.S)


def rule_s5(scan, out):
    for rel, text in scan.texts.items():
        if _is_pce_script(text):
            continue
        text = FENCE_RE.sub("", text)
        for m in LINK_RE.finditer(text):
            target = m.group(1)
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            resolved = _resolve_link(scan, rel, target)
            if resolved is None:
                continue
            if resolved is False or resolved not in scan.file_set and resolved not in scan.dir_set:
                arch = scan.contract.archive_dir()
                if arch and isinstance(resolved, str) and (arch + "/" + strip_dot(resolved)) in scan.file_set:
                    continue
                out.append(Finding("S5", rel, "error",
                                   "链接指向的 %s 不存在" % target))
        if rel.endswith(".md"):
            continue
        for m in PATH_RE.finditer(text):
            cand = strip_dot(m.group(1))
            if "/" not in cand:
                continue
            if _path_exists(scan, rel, cand):
                continue
            if cand.startswith(("/", "../", "~")):
                continue
            arch = scan.contract.archive_dir()
            if arch and (cand.startswith(arch + "/") or (arch + "/" + cand) in scan.file_set):
                continue
            if scan.in_archive(rel):
                continue
            out.append(Finding("S5", rel, "warn",
                               "提到了 %s，但仓库里没有这个文件" % cand))


def _path_exists(scan, rel, cand):
    """路径提到的东西，按仓库根、提到它的文件所在目录、最近的内层契约根 各试一次。"""
    if cand in scan.file_set or cand in scan.dir_set:
        return True
    base = os.path.dirname(rel)
    root = scan.root
    cands = [os.path.join(base, cand)] if base else []
    d = base
    while d:
        cands.append(os.path.join(d, cand))
        if os.path.isfile(os.path.join(root, d, CONTRACT)):
            break
        d = os.path.dirname(d)
    for c in cands:
        c = os.path.normpath(c)
        if os.path.exists(os.path.join(root, c)):
            return True
    return False


def rule_s6(scan, out):
    archive = scan.contract.archive_dir()
    if not archive:
        return
    for rel in sorted(scan.files):
        if not scan.in_archive(rel):
            continue
        old = rel[len(archive) + 1:]
        if not old or old == ARCHIVE_LOG:
            continue
        pat = re.compile(r"(?<![\w/.-])" + re.escape(old) + r"(?![\w/.-])")
        for other, text in scan.texts.items():
            if other == rel or scan.in_archive(other):
                continue
            if pat.search(text):
                out.append(Finding("S6", other, "error",
                                   "还按旧路径引用 %s；它现在是 %s" % (old, rel)))


def rule_s7(scan, out):
    layers = ["."] + [d for d in scan.dirs
                      if not scan.in_archive(d) and not scan.in_tool(d)]
    for d in layers:
        if scan.in_archive(d):
            continue
        for sub in scan.direct_subdirs(d):
            base = "" if d == "." else d + "/"
            rel = base + sub
            if rel == scan.contract.archive_dir():
                continue
            files = [f for f in scan.subtree_files(rel) if not scan.in_archive(f)]
            if not files:
                out.append(Finding("S7", rel, "info",
                                   "这个子目录还空着；规划中的就忽略，清理后留下的就删行或删目录"))


def rule_s8(scan, out):
    names = sorted(scan.contract.zones)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            wa = scan.contract.zones[a]["what"]
            wb = scan.contract.zones[b]["what"]
            if a in b or b in a:
                out.append(Finding("S8", "." , "warn",
                                   "分区 %s 与 %s 的名字互相包含，容易放错" % (a, b)))
            elif jaccard(wa, wb) >= 0.6:
                out.append(Finding("S8", ".", "warn",
                                   "分区 %s 与 %s 的职责说明很像（%r / %r）" % (a, b, wa, wb)))


def rule_s9(scan, out):
    for name, body in scan.contract.zones.items():
        if is_vague(body["what"]):
            out.append(Finding("S9", name, "warn",
                               "分区的 what 等于没说：%r" % body["what"]))
    layers = ["."] + [d for d in scan.dirs
                      if not scan.in_archive(d) and not scan.in_tool(d)]
    for d in layers:
        if scan.in_archive(d):
            continue
        p = _nav_path(scan, d)
        if p not in scan.texts:
            continue
        _, rows, _ = parse_nav(scan.texts[p])
        for row in rows:
            if row["what"] and is_vague(row["what"]):
                base = "" if d == "." else d + "/"
                out.append(Finding("S9", base + row["name"], "warn",
                                   "这一行的“负责什么”等于没说：%r" % row["what"]))


def rule_s10(scan, out):
    archive = scan.contract.archive_dir()
    if not archive:
        return
    log = scan.texts.get(archive + "/" + ARCHIVE_LOG, "")
    registered = set()
    for line in log.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells and cells[0] not in ("原路径", "") and set(cells[0]) - set("-: "):
            registered.add(cells[0].strip("`"))
    for rel in sorted(scan.files):
        if not scan.in_archive(rel):
            continue
        old = rel[len(archive) + 1:]
        if old == ARCHIVE_LOG:
            continue
        if rel not in registered and old not in registered:
            out.append(Finding("S10", rel, "warn",
                               "归档区里的文件没在 %s 里登记" % ARCHIVE_LOG))


def rule_s11(scan, out):
    text = scan.texts.get(AGENTS)
    if text is None:
        return
    lines = len(text.splitlines())
    dates = set(DATE_RE.findall(text))
    if lines > 120:
        out.append(Finding("S11", AGENTS, "warn",
                           "入口文件 %d 行，超过建议的 120 行；日志、台账、进度搬家" % lines))
    if len(dates) >= 10:
        out.append(Finding("S11", AGENTS, "warn",
                           "入口文件里有 %d 个不同日期，像台账；入口只留怎么干活" % len(dates)))
    begins = text.count(MARK_BEGIN)
    ends = text.count(MARK_END)
    if begins > 1:
        out.append(Finding("S11", AGENTS, "warn",
                           "PCE 段出现了 %d 次；同一段只该有一个" % begins))
    if begins != ends:
        out.append(Finding("S11", AGENTS, "warn",
                           "PCE 段的标记没闭合（begin %d 个、end %d 个）" % (begins, ends)))
    if begins == 1 and ends == 1:
        parsed = _agents_block(text)
        if parsed:
            body, version, digest = parsed
            tpl_body = AGENTS_BODY.strip("\n")
            if version and digest == _agents_hash(body):
                if body != tpl_body:
                    out.append(Finding("S11", AGENTS, "warn",
                                       "PCE 段还是 %s 版模板，当前检查器是 %s；跑 `pce init` 更新"
                                       % (version, VERSION)))
            elif body != tpl_body:
                out.append(Finding("S11", AGENTS, "warn",
                                   "PCE 段和当前模板不一样，也没有可信的版本记录（改过或手加的标记）；"
                                   "确认要接管跑 `pce init --reset-agents`"))


def rule_s12(scan, out):
    for rel in sorted(scan.files):
        if scan.in_archive(rel):
            continue
        base = rel.split("/")[-1]
        if base == "pce.py" or not base.startswith("pce") or not base.endswith(".py"):
            continue
        if _is_pce_script(scan.texts.get(rel, "")):
            out.append(Finding("S12", rel, "warn",
                               "看起来是 pce.py 的副本；tools/ 下只该留一份，要留凭据用 pce archive"))


RULES = [rule_s1, rule_s2, rule_s3, rule_s4, rule_s5, rule_s6,
         rule_s7, rule_s8, rule_s9, rule_s10, rule_s11, rule_s12]


def run_rules(scan):
    out = []
    for fn in RULES:
        try:
            fn(scan, out)
        except Exception as exc:  # 单条规则炸了不能拖垮整次检查
            out.append(Finding("S?", ".", "error", "规则 %s 执行出错：%s" % (fn.__name__, exc)))
    seen = set()
    uniq = []
    for f in out:
        key = (f.rule, f.path, f.message)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(f)
    return uniq


def sort_findings(items):
    order = {"error": 0, "warn": 1, "info": 2}
    return sorted(items, key=lambda f: (order.get(f.level, 9), f.path or ""))


# ---------------------------------------------------------------- 输出

def emit(text):
    sys.stdout.write(text + "\n")


def emit_findings(items, as_json=False):
    if as_json:
        emit(json.dumps([f.as_dict() for f in items], ensure_ascii=False, indent=2))
        return
    for f in items:
        emit(f.line())


def summary_line(items):
    e = len([f for f in items if f.level == "error"])
    w = len([f for f in items if f.level == "warn"])
    i = len([f for f in items if f.level == "info"])
    if i:
        return "%d error, %d warn, %d info" % (e, w, i)
    return "%d error, %d warn" % (e, w)


# ---------------------------------------------------------------- 命令：check

def cmd_check(root, args):
    as_json = "--json" in args
    strict = "--strict" in args
    paths = []
    if "--paths" in args:
        i = args.index("--paths")
        paths = [a for a in args[i + 1:] if not a.startswith("-")]
        for p in paths:
            full = os.path.join(root, strip_dot(p.replace(os.sep, "/")))
            if not os.path.exists(full):
                emit("--paths 里的 %s 不存在" % p)
                return EXIT_USAGE
    try:
        contract = load_contract(root)
    except ContractError as exc:
        item = Finding("S0", CONTRACT, "error", str(exc))
        emit_findings([item], as_json)
        return EXIT_FAIL
    recorded = _generated_by(read_text(os.path.join(root, CONTRACT)))
    if recorded and _version_key(recorded) < _version_key(VERSION):
        emit("这个仓库按 %s 建的，当前 %s（跑 `pce upgrade-repo` 看要改什么）" % (recorded, VERSION))
    scan = Scan(root, contract)
    items = run_rules(scan)
    for rel, size in scan.skipped:
        items.append(Finding("S0", rel, "info",
                             "文件 %.1f MB，超过 2 MB，跳过内容检查" % (size / 1024.0 / 1024.0)))
    if paths:
        wanted = [strip_dot(p.replace(os.sep, "/")) for p in paths]
        def hit(f):
            for w in wanted:
                if f.path == w or f.path.startswith(w.rstrip("/") + "/"):
                    return True
                if w.startswith(f.path + "/") or w == f.path:
                    return True
            return False
        items = [f for f in items if hit(f)]
    items = sort_findings(items)
    if as_json:
        emit(json.dumps({"summary": {"error": len([f for f in items if f.level == "error"]),
                                     "warn": len([f for f in items if f.level == "warn"]),
                                     "info": len([f for f in items if f.level == "info"])},
                         "items": [f.as_dict() for f in items]},
                        ensure_ascii=False, indent=2))
    else:
        emit_findings(items, as_json)
        emit("")
        emit(summary_line(items))
    errors = [f for f in items if f.level == "error"]
    if errors:
        return EXIT_FAIL
    if strict and any(f.level == "warn" for f in items):
        return EXIT_FAIL
    return EXIT_OK


# ---------------------------------------------------------------- 命令：audit

def cmd_audit(root, args):
    as_json = "--json" in args
    try:
        contract = load_contract(root)
    except ContractError as exc:
        if "找不到" in str(exc):
            emit("没有 %s：只报现状，不判违规。" % CONTRACT)
        else:
            emit("契约有问题：%s" % exc)
        contract = None
    data = {}
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel = to_posix(os.path.relpath(dirpath, root))
        if rel == ".":
            base = ""
        else:
            base = rel + "/"
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for name in filenames:
            files.append(base + name)
    data["files"] = len(files)
    if files:
        biggest = max(files, key=lambda p: os.path.getsize(os.path.join(root, p)))
        data["biggest"] = [biggest, os.path.getsize(os.path.join(root, biggest))]
    gitdir = os.path.join(root, ".git")
    data["git_size"] = _dir_size(gitdir) if os.path.isdir(gitdir) else 0
    data["big_objects"] = _big_objects(root)
    try:
        data["contract"] = load_contract(root)
    except ContractError:
        data["contract"] = None
    data["root_entries"] = sorted(n for n in os.listdir(root) if n != ".git")
    data["layers"] = sorted(set(d.split("/")[0] for d in data["root_entries"]
                               if os.path.isdir(os.path.join(root, d))))
    agents = os.path.join(root, AGENTS)
    data["agents_lines"] = len(read_text(agents).splitlines()) if os.path.isfile(agents) else 0
    if as_json:
        emit(json.dumps(data, ensure_ascii=False, indent=2, default=str))
        return EXIT_OK
    emit("仓库多大")
    emit("  文件数        %d" % data["files"])
    if "biggest" in data:
        emit("  最大的文件    %s（%.1f KB）" % (data["biggest"][0], data["biggest"][1] / 1024.0))
    emit("  .git 目录     %.1f MB" % (data["git_size"] / 1024.0 / 1024.0))
    emit("  历史大文件    %s" % ("、".join(g[1] for g in data["big_objects"]) or "（取不到或没有）"))
    emit("")
    emit("根目录")
    allow = data["contract"].root_allow if data.get("contract") else []
    for name in data["root_entries"]:
        mark = ""
        if allow and os.path.isfile(os.path.join(root, name)) and not match_any(name, allow):
            mark = "   ← 不在白名单里"
        emit("  " + name + mark)
    emit("")
    emit("层级现状")
    for name in data["layers"]:
        sub = sorted(os.listdir(os.path.join(root, name)))
        emit("  %s/  %d 项" % (name, len(sub)))
    emit("")
    emit("明显的坏味道")
    smells = _smells(root, data)
    for s in smells:
        emit("  " + s)
    if not smells:
        emit("  （没看出来）")
    emit("")
    emit("入口文件")
    emit("  %s  %d 行" % (AGENTS, data["agents_lines"]))
    skill = os.path.join(root, "SKILL.md")
    if os.path.isfile(skill):
        emit("  SKILL.md  %d 行" % len(open(skill, encoding="utf-8", errors="replace").read().splitlines()))
    if contract is None:
        emit("")
        emit("（没有可用的 structure.yaml，本次只报事实，不判违规）")
    return EXIT_OK


def _dir_size(path):
    total = 0
    for dirpath, _, filenames in os.walk(path):
        for name in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, name))
            except OSError:
                pass
    return total


def _big_objects(root):
    try:
        rev = subprocess.check_output(["git", "rev-list", "--objects", "--all", "--max-count=5000"],
                                      cwd=root, stderr=subprocess.DEVNULL)
        proc = subprocess.run(["git", "cat-file", "--batch-check=%(objecttype) %(objectsize) %(rest)"],
                              cwd=root, input=rev, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL)
    except Exception:
        return []
    sizes = []
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        parts = line.split(" ", 2)
        if len(parts) != 3 or parts[0] != "blob":
            continue
        try:
            sizes.append((int(parts[1]), parts[2]))
        except ValueError:
            continue
    sizes.sort(reverse=True)
    return sizes[:5]


def _smells(root, data=None):
    out = []
    for name in sorted(os.listdir(root)):
        full = os.path.join(root, name)
        if os.path.isfile(full) and os.path.getsize(full) == 0:
            out.append("%s 是空文件" % name)
        if name == ".DS_Store":
            out.append(".DS_Store（Finder 生成的，建议进 ignore）")
        if name.endswith((".bak", ".old", ".tmp")) or name.endswith("~"):
            out.append("%s 像是备份或临时文件" % name)
    for name in ("_archive", "old", "deprecated", "legacy"):
        if os.path.isdir(os.path.join(root, name)):
            out.append("%s/ 像是旧的归档区，跑 pce init 时会问要不要认领" % name)
    empty, big = [], []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in (".git", "__pycache__", "node_modules")]
        rel = to_posix(os.path.relpath(dirpath, root))
        if rel != "." and not filenames and not dirnames:
            empty.append(rel)
        for name in filenames:
            full = os.path.join(dirpath, name)
            try:
                if os.path.getsize(full) > 1024 * 1024:
                    big.append((name, os.path.getsize(full)))
            except OSError:
                pass
    if empty:
        out.append("空目录 %d 个：%s" % (len(empty), "、".join(empty[:5])))
    if big:
        big.sort(key=lambda x: -x[1])
        out.append("大文件 %d 个：%s" % (len(big), "、".join("%s（%.1f MB）" % (n, sz / 1048576.0) for n, sz in big[:5])))
    if data and data.get("agents_lines") is not None:
        navs = 0
        layers = 0
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d != ".git"]
            rel = to_posix(os.path.relpath(dirpath, root))
            if rel == "." or rel.split("/")[0] == "__pycache__":
                continue
            if any(os.path.isdir(os.path.join(dirpath, d)) for d in dirnames):
                layers += 1
                if "navigation.md" not in filenames:
                    navs += 1
        if navs:
            out.append("有 %d 层有子目录却没有 navigation.md（共 %d 层）" % (navs, layers))
    return out


# ---------------------------------------------------------------- 命令：explain

def cmd_explain(root, args):
    if not args:
        emit("用法：pce explain <路径>")
        return EXIT_USAGE
    rel = strip_dot(args[0].replace(os.sep, "/"))
    try:
        contract = load_contract(root)
    except ContractError as exc:
        emit("契约有问题：%s" % exc)
        return EXIT_FAIL
    scan = Scan(root, contract)
    if rel not in scan.file_set and rel not in scan.dir_set:
        emit("%s 不存在" % rel)
        return EXIT_USAGE
    is_dir = rel in scan.dir_set
    emit(rel)
    if scan.in_archive(rel) or rel == contract.archive_dir():
        emit("  归属    归档区（%s）" % contract.archive_dir())
    elif is_dir and rel in contract.zones:
        emit("  归属    分区 %s（%s）" % (rel, contract.zones[rel]["what"]))
    elif "/" in rel:
        zone = rel.split("/")[0]
        emit("  归属    分区 %s（%s）" % (zone, contract.zones.get(zone, {}).get("what", "未登记")))
    else:
        ok = match_any(rel, contract.root_allow)
        emit("  归属    根目录（%s）" % ("在白名单里" if ok else "不在白名单里"))
    if not is_dir:
        style = contract.style_for(rel)
        name = rel.split("/")[-1]
        if style and not _style_ok(style, name):
            emit("  命名    建议 %s 风格，例如 %s（只是建议，不拦你）"
                 % (style, _suggest_name(style, name)))
        elif style:
            emit("  命名    符合建议的 %s 风格" % style)
        else:
            emit("  命名    没有建议，随你")
    parts = rel.split("/")
    found = False
    while parts:
        layer = "/".join(parts[:-1]) or "."
        navp = _nav_path(scan, layer)
        if navp in scan.texts:
            _, rows, _ = parse_nav(scan.texts[navp])
            hit = [r for r in rows if r["name"].rstrip("/") == parts[-1]]
            emit("  导航    %s %s" % (navp, "有这一行" if hit else "没有这一行"))
            found = True
            break
        parts = parts[:-1]
    if not found:
        emit("  导航    这一层的上级没有 %s" % NAV)
    refs = []
    pat = re.compile(r"(?<![\w/.-])" + re.escape(rel) + r"(?![\w/.-])")
    for other, text in scan.texts.items():
        if other == rel or other.endswith("tools/pce.py"):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if pat.search(line):
                refs.append("%s:%d" % (other, n))
    emit("  引用    %s" % ("、".join(refs[:5]) + ("　等 %d 处" % len(refs) if len(refs) > 5 else "")
                           if refs else "没有"))
    items = run_rules(scan)
    mine = [f for f in items if f.path == rel]
    for f in mine:
        emit("  检查    %s %s: %s" % (f.rule, f.level, f.message))
    if not mine:
        emit("  检查    没有发现问题")
    emit("  结论    %s" % ("合规" if not [f for f in mine if f.level == "error"] else "不合规"))
    return EXIT_OK


# ---------------------------------------------------------------- 交互

def interactive():
    return sys.stdin.isatty() and "--yes" not in sys.argv


def ask(prompt, default=""):
    if not interactive():
        return default
    try:
        got = input("%s%s " % (prompt, "[%s] " % default if default else "")).strip()
    except EOFError:
        return default
    return got or default


# ---------------------------------------------------------------- 命令：init

AGENTS_BODY = """# 怎么在这个仓库里干活

这个仓库的目录结构由 PCE 管：文件放哪、导航怎么写都有规则，`pce check` 会告诉你哪儿不对。

1. 放东西之前，先看这一层的 `navigation.md`，表里写着每个子目录负责什么。
2. 新建走 `pce new <路径>`，不要直接在编辑器里丢文件；建目录要给它一句“负责什么”。
3. 移动、改名、删除、归档，先出计划等人确认；要留凭据的旧文件用 `pce archive <路径> --reason "为什么"`。
4. 改完跑 `pce check`，error 清零；导航和磁盘对不上时跑 `pce map`。
5. 没有 `pce` 命令时：仓库里有 `tools/pce.py` 就用它，没有就用 `python3 ~/.agents/skills/project-consistency-engineering/tools/pce.py`。
"""


META_RE = re.compile(r"<!--\s*pce:template\s+([0-9][^\s]*)\s+sha256:([0-9a-f]+)\s*-->")


def _agents_hash(body):
    norm = "\n".join(line.rstrip() for line in body.strip("\n").splitlines())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def agents_template():
    body = AGENTS_BODY.strip("\n")
    return "%s\n<!-- pce:template %s sha256:%s -->\n%s\n%s\n" % (
        MARK_BEGIN, VERSION, _agents_hash(body), body, MARK_END)


NAV_TPL = """这一层是仓库根。分区和入口在下面这张表里。

%s
| 子目录 | 负责什么 | 入口 | 最后更新 |
|---|---|---|---|
%s
%s
"""


def _write_if_absent(path, content, mode="w"):
    if os.path.exists(path):
        return False
    with open(path, mode, encoding="utf-8") as f:
        f.write(content)
    return True


def _agents_block(text):
    """返回 (段内正文, 版本, 记录哈希)；没有段返回 None。"""
    i = text.find(MARK_BEGIN)
    j = text.find(MARK_END, i + 1)
    if i < 0 or j < 0:
        return None
    inner = text[i + len(MARK_BEGIN):j]
    lines = inner.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    version = digest = None
    if lines:
        m = META_RE.search(lines[0])
        if m:
            version, digest = m.group(1), m.group(2)
            lines = lines[1:]
    body = "\n".join(line.rstrip() for line in lines).strip("\n")
    return body, version, digest


def _agents_replace(text, block_text):
    i = text.find(MARK_BEGIN)
    j = text.find(MARK_END, i + 1) + len(MARK_END)
    return text[:i] + block_text.rstrip("\n") + text[j:]


def apply_agents(root, targets, reset=False):
    """AGENTS.md：没有就写整份；有段就按版本记录判断能不能安全替换。"""
    path = os.path.join(root, AGENTS)
    tpl = agents_template()
    if not os.path.isfile(path):
        targets.append((AGENTS, tpl))
        return
    current = read_text(path)
    begins = current.count(MARK_BEGIN)
    ends = current.count(MARK_END)
    if begins == 0:
        emit("%s 已存在且没有 PCE 段，整份不动（要接管就自己加 %s）" % (AGENTS, MARK_BEGIN))
        return
    if begins > 1:
        emit("%s 里有 %d 个 PCE 段，不猜哪个是对的，不动它" % (AGENTS, begins))
        return
    if begins != ends:
        emit("%s 里的 PCE 标记没闭合，不动它" % AGENTS)
        return
    parsed = _agents_block(current)
    if parsed is None:
        emit("%s 的 PCE 段读不出来，不动它" % AGENTS)
        return
    body, recorded_version, recorded_hash = parsed
    tpl_body = AGENTS_BODY.strip("\n")
    changed = _agents_diff_lines(body, tpl_body)

    def write(status):
        new_text = _agents_replace(current, tpl)
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_text)
        emit(status)

    if body == tpl_body:
        if recorded_version == VERSION and recorded_hash == _agents_hash(body):
            emit("%s 的 PCE 段已经是最新的" % AGENTS)
            return
        write("%s 的 PCE 段内容没变，只把版本记录更新到 %s" % (AGENTS, VERSION))
        return
    trusted = bool(recorded_version) and recorded_hash == _agents_hash(body)
    if trusted:
        write("%s 的 PCE 段从 %s 更新到 %s（%d 行有变化）"
              % (AGENTS, recorded_version, VERSION, changed))
        return
    if reset:
        write("替换了 %s 的 PCE 段（%d 行有变化）" % (AGENTS, changed))
        return
    if recorded_version:
        emit("%s 的 PCE 段被改过（和安装时记的 %s 不一致），保留原样；要换成新版跑 `pce init --reset-agents`"
             % (AGENTS, recorded_version))
    else:
        emit("%s 的 PCE 段没有版本记录（老版本写的，或手加的标记），不猜它有没有被改过；"
             "确认要接管跑 `pce init --reset-agents`" % AGENTS)


def _agents_diff_lines(a, b):
    first, last = len(a.splitlines()), len(b.splitlines())
    al, bl = a.splitlines(), b.splitlines()
    diff = sum(1 for i in range(max(first, last))
               if i >= first or i >= last or al[i] != bl[i])
    return diff


def _contract_body(zones, allow, archive_path):
    """zones: [(名字, what)]；allow: 根白名单；archive_path: 空字符串表示没有归档区。"""
    body = ["# generated by pce %s" % VERSION, "version: 1", "", "zones:"]
    for name, what in zones:
        body += ["  %s:" % name, "    what: %s" % what, ""]
    body += ["root:", "  allow:"]
    body += ["    - %s" % e for e in allow]
    body += ["", "naming:", '  default: ""', "",
             "archive:", '  path: "%s"' % archive_path, "", "ignore:"]
    body += ["  - %s" % e for e in DEFAULT_IGNORE]
    body.append("")
    return "\n".join(body)


def _register_preexisting_archive(root, archive):
    """接管一个已经有文件的归档区（如老仓库的 old/）：把存量文件登记进 ARCHIVE.md。

    否则 S11 会对每个存量文件报“没登记”，一装完就是一片 warn。
    """
    adir = os.path.join(root, archive)
    if not os.path.isdir(adir):
        return
    log = os.path.join(adir, ARCHIVE_LOG)
    registered = set()
    if os.path.exists(log):
        for line in read_text(log).splitlines():
            if not line.strip().startswith("|"):
                continue
            cells = [x.strip() for x in line.strip().strip("|").split("|")]
            if cells and cells[0] not in ("原路径", "") and set(cells[0]) - set("-: "):
                registered.add(cells[0].strip("`"))
    rows = []
    for dirpath, dirnames, filenames in os.walk(adir):
        dirnames[:] = sorted(d for d in dirnames if d != ".git")
        for n in sorted(filenames):
            rel = to_posix(os.path.relpath(os.path.join(dirpath, n), root))
            if rel.endswith("/" + ARCHIVE_LOG) or rel == ARCHIVE_LOG or rel in registered:
                continue
            rows.append(rel)
    if not rows:
        return
    if not os.path.exists(log):
        with open(log, "w", encoding="utf-8") as f:
            f.write("# 归档记录\n\n| 原路径 | 归档时间 | 原因 | 谁提的 |\n|---|---|---|---|\n")
    date = datetime.date.today().isoformat()
    with open(log, "a", encoding="utf-8") as f:
        for rel in rows:
            f.write("| %s | %s | %s | %s |\n" % (rel, date, "接管时已在归档区", "init"))
    emit("归档区里原有 %d 个文件，已登记到 %s" % (len(rows), archive + "/" + ARCHIVE_LOG))


def cmd_init(root, args):
    targets = []
    contract_path = os.path.join(root, CONTRACT)
    zone_name, zone_what, tools_what = "src", "程序源码", "脚本与工具"
    vendor = "--vendor" in args
    archive_path = ""
    extras = []
    if not os.path.isfile(contract_path):
        try:
            for name in sorted(os.listdir(root)):
                if name.startswith("."):
                    continue
                if os.path.isfile(os.path.join(root, name)) and name not in DEFAULT_ROOT_ALLOW:
                    extras.append(name)
        except OSError:
            pass
        found_old = ""
        for cand in ("archive", "_archive", "old", "deprecated", "legacy"):
            if os.path.isdir(os.path.join(root, cand)):
                found_old = cand
                break
        want_archive = True
        if interactive():
            zone_name = ask("通用区叫什么名字？", "src") or "src"
            zone_what = ask("%s/ 负责什么？" % zone_name, "程序源码") or "程序源码"
            if "--vendor" not in args:
                vendor = ask("要把校验器复制一份进仓库吗（给 CI / 没装 skill 的机器用）？(y/n)",
                             "n").lower().startswith("y")
            if vendor:
                tools_what = ask("tools/ 负责什么？", "脚本与工具") or "脚本与工具"
            if found_old:
                want_archive = ask("发现 %s/，它是归档区吗？(y/n)" % found_old, "y").lower().startswith("y")
            else:
                want_archive = ask("建归档区 archive/ 吗？(y/n)", "y").lower().startswith("y")
            kept = [n for n in extras
                    if ask("根目录的 %s 要放进白名单吗？(y/n)" % n, "y").lower().startswith("y")]
            extras = kept
        archive_path = (found_old if found_old and want_archive else ("archive" if want_archive else ""))
        zones = ([("tools", tools_what)] if vendor else []) + [(zone_name, zone_what)]
        targets.append((CONTRACT, _contract_body(zones, extras, archive_path)))
    else:
        try:
            old = load_contract(root)
        except ContractError as e:
            emit("%s 读不懂：%s" % (CONTRACT, e))
            emit("先把它修好，或者备份走再跑一次 init。")
            return EXIT_FAIL
        action = "k"
        if interactive():
            action = ask("%s 已存在，怎么办？(k) 保留原样 / (b) 备份到临时目录后重写 / (d) 只看差异"
                         % CONTRACT, "k").strip().lower()[:1] or "k"
        if action == "d":
            emit("%s 现在是这样：" % CONTRACT)
            for line in old.raw.splitlines():
                emit("  " + line)
            emit("要改就自己改；或者选 (b) 备份后按现在的目录重写。")
            return EXIT_OK
        if action == "b":
            tmpdir = tempfile.mkdtemp(prefix="pce-init-")
            backup = os.path.join(tmpdir, CONTRACT)
            shutil.copyfile(contract_path, backup)
            emit("原契约备份到 %s" % backup)
            zones = [(n, z.get("what", "")) for n, z in old.zones.items()]
            allow = list(old.root_allow)
            targets.append((CONTRACT, _contract_body(zones, allow, old.archive_dir())))
        else:
            emit("%s 已存在，保留原样（要改就跑 init 选 (b)，或自己改）" % CONTRACT)

    apply_agents(root, targets, reset="--reset-agents" in args)
    if not os.path.isfile(os.path.join(root, "README.md")):
        targets.append(("README.md",
                        "# %s\n\n一句话说明这个项目是做什么的。\n\n## 怎么跑\n\n（写清楚跑起来的命令）\n"
                        % os.path.basename(root)))
    src = os.path.abspath(__file__)
    dst = os.path.join(root, "tools", "pce.py")
    sha_path = os.path.join(root, "tools", SHA)
    vendor = vendor or os.path.exists(dst)
    if vendor:
        os.makedirs(os.path.join(root, "tools"), exist_ok=True)
    same_file = vendor and os.path.exists(dst) and os.path.samefile(src, dst)
    if vendor and not same_file:
        if os.path.exists(dst):
            if sha256_file(dst) == sha256_file(src):
                if not os.path.isfile(sha_path):
                    with open(sha_path, "w", encoding="utf-8") as f:
                        f.write(sha256_file(dst) + "\n")
            else:
                emit("tools/pce.py 已存在且和这份不同，不覆盖（本地改过；要更新跑 `pce upgrade`）")
                if not os.path.isfile(sha_path):
                    emit("  没有 %s，这次也不补：补了就会把本地改动记成官方版" % SHA)
        else:
            shutil.copyfile(src, dst)
            with open(sha_path, "w", encoding="utf-8") as f:
                f.write(sha256_file(dst) + "\n")
    if not os.path.isfile(os.path.join(root, NAV)):
        rows = ([("tools", tools_what)] if vendor else []) + [(zone_name, zone_what)]
        if archive_path:
            rows.append((archive_path, "不再使用、但想留个凭据的文件"))
        targets.append((NAV, NAV_TPL % (MAP_BEGIN,
                                        "\n".join("| %s | %s | | |" % r for r in rows),
                                        MAP_END)))
    emit("会生成：")
    extra = ["tools/pce.py", "tools/" + SHA] if vendor else []
    for rel in [r for r, _ in targets] + extra:
        emit("  " + rel)
    for rel, body in targets:
        path = os.path.join(root, rel)
        if os.path.exists(path):
            emit("%s 已存在，跳过" % rel)
            continue
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        emit("写了 %s" % rel)
    try:
        c = load_contract(root)
        if c.archive_dir():
            _register_preexisting_archive(root, c.archive_dir())
        for zname in list(c.zones) + ([c.archive_dir()] if c.archive_dir() else []):
            zdir = os.path.join(root, zname)
            if not os.path.isdir(zdir):
                os.makedirs(zdir, exist_ok=True)
                emit("建了目录 %s/" % zname)
    except ContractError:
        pass
    emit("")
    if vendor:
        emit("下一步：`python3 tools/pce.py check`")
    else:
        emit("下一步：`python3 %s check`" % src)
        emit("（校验器不复制进仓库；要复制给 CI 用，跑 `pce init --vendor`）")
    return EXIT_OK


# ---------------------------------------------------------------- 导航表的读写

def nav_render(rows):
    body = ["| 子目录 | 负责什么 | 入口 | 最后更新 |", "|---|---|---|---|"]
    for r in rows:
        body.append("| %s | %s | %s | %s |" % (r["name"], r["what"], r["entry"], r["updated"]))
    return "\n".join(body)


def _wrap_existing_table(text):
    """没有标记但有表格：把第一张表整段包进标记，返回 (text, 是否包了)。"""
    lines = text.splitlines()
    start = None
    for i in range(len(lines) - 1):
        head = lines[i].strip()
        sep = lines[i + 1].strip()
        if head.startswith("|") and sep.startswith("|") and set(sep) <= set("|-: "):
            start = i
            break
    if start is None:
        return text, False
    end = start
    while end + 1 < len(lines) and lines[end + 1].strip().startswith("|"):
        end += 1
    head = lines[:start]
    tail = lines[end + 1:]
    body = "\n".join(lines[start:end + 1])
    new = head + [MAP_BEGIN, body, MAP_END] + tail
    return "\n".join(new), True


def _table_columns(text):
    """旧表有几列、多出来的列有没有内容；没有表就是 (0, False)。"""
    cols = 0
    extra = False
    for line in text.splitlines():
        t = line.strip()
        if not t.startswith("|") or set(t) <= set("|:- "):
            continue
        cells = [c.strip() for c in t.strip("|").split("|")]
        cols = max(cols, len(cells))
        if any(cells[2:]):
            extra = True
    return cols, extra


def nav_replace_block(text, rows):
    begin = text.find(MAP_BEGIN)
    end = text.find(MAP_END)
    if begin < 0 or end < 0:
        old_cols, extra = _table_columns(text)
        text, wrapped = _wrap_existing_table(text)
        if wrapped:
            if extra:
                emit("  旧表有 %d 列，这次只保留前两列（子目录、负责什么）；其余列的内容没搬过来，原样在 git 历史里，要看用 git show" % old_cols)
            begin = text.find(MAP_BEGIN)
            end = text.find(MAP_END)
            return text[:begin] + MAP_BEGIN + "\n" + nav_render(rows) + "\n" + MAP_END + text[end + len(MAP_END):]
        block = MAP_BEGIN + "\n" + nav_render(rows) + "\n" + MAP_END
        return text.rstrip() + "\n\n" + block + "\n"
    return text[:begin] + MAP_BEGIN + "\n" + nav_render(rows) + "\n" + MAP_END + text[end + len(MAP_END):]


def ensure_nav_row(scan, layer, name, what):
    """在 layer 的 navigation.md 里确保有一行；没有就加。返回是否改动。"""
    navp = _nav_path(scan, layer)
    text = scan.texts.get(navp)
    if text is None:
        return False
    _, rows, _ = parse_nav(text)
    if any(r["name"].rstrip("/") == name for r in rows):
        return False
    rows.append({"name": name, "what": what, "entry": "", "updated": ""})
    with open(os.path.join(scan.root, navp), "w", encoding="utf-8") as f:
        f.write(nav_replace_block(text, rows))
    return True


def nav_put_row(root, layer, name, what, first_line=None):
    """确保 layer 的 navigation.md 存在、且表里有 name 这一行。"""
    layer_dir = root if layer == "." else os.path.join(root, layer)
    navp = os.path.join(layer_dir, NAV)
    created = False
    if not os.path.isfile(navp):
        head = first_line or "这一层放什么，一句话说明。"
        body = head + "\n\n" + MAP_BEGIN + "\n" + nav_render([]) + "\n" + MAP_END + "\n"
        with open(navp, "w", encoding="utf-8") as f:
            f.write(body)
        created = True
    text = read_text(navp)
    _, rows, _ = parse_nav(text)
    if any(r["name"].rstrip("/") == name for r in rows):
        return created, False
    rows.append({"name": name, "what": what, "entry": "", "updated": ""})
    with open(navp, "w", encoding="utf-8") as f:
        f.write(nav_replace_block(text, rows))
    return created, True


def nav_drop_row(root, layer, name):
    layer_dir = root if layer == "." else os.path.join(root, layer)
    navp = os.path.join(layer_dir, NAV)
    if not os.path.isfile(navp):
        return False
    text = read_text(navp)
    _, rows, _ = parse_nav(text)
    kept = [r for r in rows if r["name"].rstrip("/") != name]
    if len(kept) == len(rows):
        return False
    with open(navp, "w", encoding="utf-8") as f:
        f.write(nav_replace_block(text, kept))
    return True


def contract_add_zone(root, name, what):
    path = os.path.join(root, CONTRACT)
    text = read_text(path)
    if re.search(r"(?m)^  %s:\s*$" % re.escape(name), text):
        return False
    m = re.search(r"(?m)^zones:\s*$", text)
    if not m:
        return False
    block = "\n  %s:\n    what: %s" % (name, what)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text[:m.end()] + block + text[m.end():])
    return True


# ---------------------------------------------------------------- 命令：map

def cmd_map(root, args):
    """两阶段：先把每一层算完，全部成功才落盘。任何一层卡住，整个命令什么都不写。"""
    apply_now = "--apply" in args or interactive()
    try:
        contract = load_contract(root)
    except ContractError as exc:
        emit("契约有问题：%s" % exc)
        return EXIT_FAIL
    scan = Scan(root, contract)
    layers = ["."] + [d for d in scan.dirs
                      if not scan.in_archive(d) and not scan.in_tool(d)]
    writes = []      # (navp, new_text, created)
    blocked = False
    for d in layers:
        subs = scan.direct_subdirs(d)
        if not subs:
            continue
        navp = _nav_path(scan, d)
        text = scan.texts.get(navp)
        base = "" if d == "." else d + "/"
        created = False
        if text is None:
            if not interactive():
                emit("会新建 %s（缺“这一层是干什么的”，非交互不动）" % navp)
                blocked = True
                continue
            default_first = contract.zones.get(d, {}).get("what", "") if d != "." else ""
            first = ask("%s 这一层是干什么的？" % (base or "仓库根"), default_first) or ""
            if not first.strip():
                first = ask("这一层到底放什么？再想一句，短点也行") or ""
            if not first.strip():
                first = "（待补）"
            text = "%s\n\n%s\n| 子目录 | 负责什么 | 入口 | 最后更新 |\n|---|---|---|---|\n%s\n" % (
                first, MAP_BEGIN, MAP_END)
            created = True
        _, rows, has_block = parse_nav(text)
        byname = dict((r["name"].rstrip("/"), r) for r in rows)
        new_rows = []
        changed = created
        missing = []
        for sub in subs:
            row = byname.pop(sub, None)
            updated = git_time(root, base + sub)
            if row is None:
                what = ask("%s/%s 负责什么？" % (d.rstrip("/") or ".", sub), "")
                if not what.strip() and not interactive():
                    missing.append(sub)
                    continue
                row = {"name": sub, "what": what, "entry": "", "updated": updated}
                changed = True
                emit("%s 加一行：%s（%s）" % (navp, sub, what or "待补"))
            else:
                if updated and row["updated"] != updated:
                    row["updated"] = updated
                    changed = True
            new_rows.append(row)
        if missing:
            emit("%s 缺“负责什么”：%s（非交互，停在这里）" % (navp, "、".join(missing)))
            blocked = True
            continue
        for stale in byname.values():
            if ask("表里的 %s 已经没有对应目录了，删掉这行？(y/n)" % stale["name"], "y").lower().startswith("y"):
                changed = True
                emit("%s 删掉一行：%s" % (navp, stale["name"]))
            else:
                new_rows.append(stale)
        if not has_block:
            changed = True
        if changed:
            writes.append((navp, nav_replace_block(text, new_rows), created))
    if blocked:
        if writes:
            emit("有层没算完，以下这些层这次也不改：%s" % "、".join(w[0] for w in writes))
        else:
            emit("有层没算完，这次什么都没写")
        return EXIT_FAIL
    for navp, new_text, created in writes:
        if apply_now:
            path = os.path.join(root, navp)
            parent = os.path.dirname(path)
            if parent and not os.path.isdir(parent):
                os.makedirs(parent, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_text)
            emit("新建 %s" % navp if created else "写了 %s" % navp)
        else:
            emit("会新建 %s" % navp if created else "会改写 %s" % navp)
    return EXIT_OK


# ---------------------------------------------------------------- 命令：new

def _zone_of(rel):
    return rel.split("/")[0] if "/" in rel else None


def _name_similar(a, b):
    a, b = a.lower(), b.lower()
    if a == b:
        return True
    if a.startswith(b) or b.startswith(a):
        return True
    if a.rstrip("s") == b.rstrip("s"):
        return True
    if a.replace("-", "").replace("_", "") == b.replace("-", "").replace("_", ""):
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.8


def _lookalike_dirs(root, rel, what):
    """兄弟目录里，名字像或职责像的。返回 [(名字, 为什么像)]。"""
    parent = os.path.dirname(rel)
    base = os.path.join(root, parent) if parent else root
    name = os.path.basename(rel)
    out = []
    try:
        entries = sorted(os.listdir(base))
    except OSError:
        return out
    for e in entries:
        if not os.path.isdir(os.path.join(base, e)) or e == name:
            continue
        if _name_similar(name, e):
            out.append((e, "名字很像"))
            continue
        if what and jaccard(what, e) >= 0.6:
            out.append((e, "说明用词重叠"))
    return out


def cmd_new(root, args):
    paths = []
    as_dir = "--dir" in args
    what_arg = ""
    skip_next = False
    for a in args:
        if skip_next:
            skip_next = False
            continue
        if a == "--what":
            skip_next = True
            continue
        if not a.startswith("-"):
            paths.append(a)
    if "--what" in args:
        k = args.index("--what")
        if k + 1 < len(args):
            what_arg = args[k + 1]
    if not paths:
        emit("用法：pce new <路径…> [--dir] [--apply]")
        return EXIT_USAGE
    try:
        contract = load_contract(root)
    except ContractError as exc:
        emit("契约有问题：%s" % exc)
        return EXIT_FAIL
    apply_now = "--apply" in args or interactive()
    plan = []
    bad = []
    for raw in paths:
        want_dir = as_dir or raw.endswith("/")
        rel = strip_dot(raw.replace(os.sep, "/").rstrip("/"))
        if not rel or rel.startswith("/") or ".." in rel.split("/"):
            bad.append("%s：必须是仓库内的相对路径" % raw)
            continue
        if want_dir and not what_arg and not interactive() and not os.path.isdir(os.path.join(root, rel)):
            bad.append("%s：非交互建目录要给“负责什么”，加 --what \"说明\"" % raw)
            continue
        if rel in plan_names(plan):
            bad.append("%s：同一个路径在计划里出现了两次" % raw)
            continue
        first = rel.split("/")[0]
        if contract.is_ignored(first):
            bad.append("%s：落在 ignore 里，pce 不管这块" % raw)
            continue
        if rel in plan_names(plan):
            bad.append("%s：重复" % raw)
            continue
        parent = os.path.dirname(rel) or "."
        if parent != "." and parent not in [d for d in _all_dirs(root)]:
            bad.append("%s：父目录 %s 不存在，先建父目录" % (raw, parent))
            continue
        if os.path.exists(os.path.join(root, rel)):
            bad.append("%s：已经存在（这是往里写，不是新建）" % raw)
            continue
        zone = _zone_of(rel)
        note = ""
        if zone is None and not want_dir:
            if not match_any(rel, contract.root_allow):
                bad.append("%s：根目录不收这个文件；挪进分区，或在 root.allow 里加一行" % raw)
                continue
        elif zone is not None and zone not in contract.zones and zone != contract.archive_dir():
            bad.append("%s：%s 不是已登记的分区；先 pce new %s/ 建分区，或换个位置" % (raw, zone, zone))
            continue
        if want_dir:
            looks = _lookalike_dirs(root, rel, what_arg or "")
            if looks:
                hint = "、".join("%s（%s）" % (n, why) for n, why in looks[:3])
                if not interactive():
                    bad.append("%s：和已有目录 %s 像，先想清楚是不是重复（非交互，停下）" % (raw, hint))
                    continue
                if zone is None and rel not in contract.zones:
                    bad.append("%s：要新建分区，又和已有目录 %s 像；分区必须是人明确要的，先确认不重复" % (raw, hint))
                    continue
                choice = ask("%s 和已有目录 %s 像：(a) 还是建 / (b) 换个名字 / (x) 不建" % (raw, hint), "x")
                if not choice.strip().lower().startswith("a"):
                    continue
        if want_dir and zone is None and rel not in contract.zones:
            note = "新分区（要写进 structure.yaml）"
        if not want_dir:
            style = contract.style_for(rel)
            if style and not _style_ok(style, rel.split("/")[-1]):
                note = "名字建议改成 %s（%s 风格，只是建议）" % (
                    _suggest_name(style, rel.split("/")[-1]), style)
        plan.append((rel, want_dir, note))
    if bad:
        emit("这批不能建：")
        for b in bad:
            emit("  " + b)
        return EXIT_FAIL
    emit("计划：")
    for rel, want_dir, note in plan:
        emit("  %s %s%s" % ("建目录" if want_dir else "建文件", rel, ("  — " + note) if note else ""))
    if not apply_now:
        emit("（非交互环境：加 --apply 才真的建）")
        return EXIT_OK
    files = [p for p in plan if not p[1]]
    if interactive() and files:
        if not ask("建这 %d 个文件？(y/n)" % len(files), "y").lower().startswith("y"):
            plan = [p for p in plan if p[1]]
    for rel, want_dir, _ in plan:
        if interactive() and want_dir:
            if not ask("建目录 %s？(y/n)" % rel, "y").lower().startswith("y"):
                emit("跳过 %s" % rel)
                continue
        full = os.path.join(root, rel)
        if not want_dir:
            os.makedirs(os.path.dirname(full) or root, exist_ok=True)
            open(full, "a", encoding="utf-8").close()
            emit("建了文件 %s" % rel)
            continue
        os.makedirs(full, exist_ok=True)
        emit("建了目录 %s" % rel)
        parent = os.path.dirname(rel) or "."
        name = rel.split("/")[-1]
        what = what_arg or ask("「%s」负责什么？" % rel, "") or "待补"
        first = None
        if parent != ".":
            head = contract.zones.get(parent)
            if head:
                first = head.get("what")
        created, changed = nav_put_row(root, parent, name, what, first)
        if created:
            emit("  建了 %s 的导航 %s" % (parent if parent != "." else "根", os.path.join(parent if parent != "." else "", NAV)))
        if changed:
            emit("  在导航表里加了一行 %s" % name)
        if parent == "." and name not in contract.zones:
            if contract_add_zone(root, name, what):
                emit("  在 structure.yaml 的 zones 里登记了 %s" % name)
    try:
        left = run_rules(Scan(root, load_contract(root)))
    except ContractError:
        left = []
    bad = [f for f in left if f.level == "error"]
    emit("")
    if bad:
        emit("建完了，但 check 还有 %d 条 error：" % len(bad))
        for f in sort_findings(bad)[:10]:
            emit("  " + f.line())
        return EXIT_FAIL
    emit("建完了，check 没有 error。")
    return EXIT_OK


def plan_names(plan):
    return [p[0] for p in plan]


def _all_dirs(root):
    out = []
    for dirpath, dirnames, _ in os.walk(root):
        rel = to_posix(os.path.relpath(dirpath, root))
        if rel != ".":
            out.append(rel)
    return out


# ---------------------------------------------------------------- 命令：archive

def cmd_archive(root, args):
    paths, reason = [], ""
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--reason" and i + 1 < len(args):
            reason = args[i + 1]
            i += 2
            continue
        if not a.startswith("-"):
            paths.append(a)
        i += 1
    if not reason:
        emit("用法：pce archive <路径…> --reason \"为什么归档\"")
        return EXIT_USAGE
    try:
        contract = load_contract(root)
    except ContractError as exc:
        emit("契约有问题：%s" % exc)
        return EXIT_FAIL
    if not contract.archive_dir():
        emit("这个仓库没有归档区（structure.yaml 的 archive.path 是空的）")
        return EXIT_USAGE
    apply_now = "--apply" in args or interactive()
    scan = Scan(root, contract)
    archive = contract.archive_dir()
    moves = []
    for raw in paths:
        rel = strip_dot(raw.replace(os.sep, "/"))
        if rel not in scan.file_set and rel not in scan.dir_set:
            emit("%s 不存在" % rel)
            return EXIT_USAGE
        if rel == archive or rel.startswith(archive + "/"):
            emit("%s 已经在归档区里了，不能再归档一次" % rel)
            return EXIT_FAIL
        dest = archive + "/" + rel
        full_dest = os.path.join(root, dest)
        if os.path.exists(full_dest):
            if not interactive():
                emit("%s 目标已存在：%s（非交互，停下）" % (rel, dest))
                return EXIT_FAIL
            choice = ask("目标 %s 已存在：(t) 加日期后缀 / (n) 自己取名 / (s) 跳过 / (x) 取消" % dest, "t")
            c = choice.strip().lower()[:1]
            if c == "x":
                return EXIT_FAIL
            if c == "s":
                continue
            if c == "n":
                new_name = ask("新名字（放在 %s/ 下面，只写这一段）" % archive, os.path.basename(rel))
                dest = archive + "/" + strip_dot(new_name)
                full_dest = os.path.join(root, dest)
                if os.path.exists(full_dest):
                    emit("%s 也存在，这次先跳过 %s" % (dest, rel))
                    continue
            else:
                dest = "%s/%s-%s" % (archive, rel, datetime.date.today().isoformat())
                full_dest = os.path.join(root, dest)
                if os.path.exists(full_dest):
                    emit("%s 也存在，这次先跳过 %s" % (dest, rel))
                    continue
        moves.append((rel, dest, rel in scan.dir_set))
    emit("计划：")
    for rel, dest, _ in moves:
        emit("  %s → %s" % (rel, dest))
    refs = []
    for rel, dest, _ in moves:
        old = rel
        pat = re.compile(r"(?<![\w/.-])" + re.escape(old) + r"(?![\w/.-])")
        for other, text in scan.texts.items():
            if other == rel:
                continue
            for n, line in enumerate(text.splitlines(), 1):
                if pat.search(line):
                    refs.append("%s:%d" % (other, n))
    if refs:
        emit("")
        emit("还有 %d 处按旧路径引用，归档后要一起改：" % len(refs))
        for where in refs:
            emit("  " + where)
    if not apply_now:
        emit("（非交互环境：加 --apply 才真的动）")
        return EXIT_OK
    for rel, dest, was_dir in moves:
        full_src = os.path.join(root, rel)
        full_dst = os.path.join(root, dest)
        os.makedirs(os.path.dirname(full_dst), exist_ok=True)
        moved = False
        if git(root, "rev-parse", "--is-inside-work-tree"):
            moved = subprocess.call(["git", "mv", rel, dest], cwd=root,
                                    stderr=subprocess.DEVNULL) == 0
        if not moved:
            shutil.move(full_src, full_dst)
        emit("移了 %s → %s" % (rel, dest))
        log = os.path.join(root, archive, ARCHIVE_LOG)
        if not os.path.exists(log):
            with open(log, "w", encoding="utf-8") as f:
                f.write("# 归档记录\n\n| 原路径 | 归档时间 | 原因 | 谁提的 |\n|---|---|---|---|\n")
        if was_dir:
            parent = os.path.dirname(rel) or "."
            if nav_drop_row(root, parent, rel.split("/")[-1]):
                emit("  从 %s 的导航里删了 %s 这一行" % (parent, rel.split("/")[-1]))
            src_dir = os.path.join(root, rel)
            if os.path.isdir(src_dir) and not os.listdir(src_dir):
                if ask("原目录 %s 空了，删掉吗？(y/n)" % rel, "y").lower().startswith("y"):
                    os.rmdir(src_dir)
                    emit("  删了空目录 %s" % rel)
        date = datetime.date.today().isoformat()
        who = ask("谁提的？", "") or "未记"
        entries = []
        if was_dir:
            for f in scan.subtree_files(rel):
                entries.append(dest + "/" + f[len(rel) + 1:])
        else:
            entries.append(dest)
        with open(log, "a", encoding="utf-8") as f:
            for new_path in entries:
                f.write("| %s | %s | %s | %s |\n" % (new_path, date, reason, who))
    left = run_rules(Scan(root, load_contract(root)))
    bad = [f for f in left if f.level == "error"]
    emit("")
    if bad:
        emit("归档后仍有 %d 条 error（引用还没改）：" % len(bad))
        for f in sort_findings(bad)[:10]:
            emit("  " + f.line())
    else:
        emit("归档完成，check 没有 error。")
    fresh = Scan(root, contract)
    if ensure_nav_row(fresh, ".", contract.archive_dir(), "不再使用、但想留个凭据的文件"):
        emit("在根导航里加了一行 %s" % contract.archive_dir())
    if refs:
        emit("")
        emit("还剩 %d 处引用要改；改完跑 `pce check`" % len(refs))
    return EXIT_OK


# ---------------------------------------------------------------- 命令：upgrade

UPSTREAM_HINTS = [
    os.path.expanduser("~/.agents/skills/project-consistency-engineering/tools/pce.py"),
    os.path.expanduser("~/.claude/skills/project-consistency-engineering/tools/pce.py"),
]


def _find_upstream():
    for path in UPSTREAM_HINTS:
        if os.path.isfile(path):
            return path
    return None


def _read_version(path):
    text = read_text(path)
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("VERSION"):
            m = re.search(r'"([0-9][^"]*)"', line)
            if m:
                return m.group(1)
    return ""


def _version_key(text):
    parts = []
    for piece in re.split(r"[.\-]", text or "0"):
        parts.append(int(piece) if piece.isdigit() else 0)
    return tuple(parts)


GENERATED_RE = re.compile(r"^#\s*generated by pce\s+([0-9][0-9A-Za-z.\-]*)\s*$", re.M)


def _generated_by(text):
    """structure.yaml 头部那行生成记录里的版本号；没有就返回 None。"""
    m = GENERATED_RE.search(text or "")
    return m.group(1) if m else None


def _agents_state(root):
    """missing / none / broken / current / outdated / edited"""
    path = os.path.join(root, AGENTS)
    if not os.path.isfile(path):
        return "missing", None
    text = read_text(path)
    if MARK_BEGIN not in text:
        return "none", None
    if text.count(MARK_BEGIN) != 1 or text.count(MARK_END) != 1:
        return "broken", None
    parsed = _agents_block(text)
    if parsed is None:
        return "broken", None
    body, version, digest = parsed
    if body == AGENTS_BODY.strip("\n"):
        return "current", version
    if version and digest == _agents_hash(body):
        return "outdated", version
    return "edited", version


def cmd_upgrade_repo(root, args):
    """把仓库里的产物迁到当前版本：先出计划，确认后才写。"""
    cpath = os.path.join(root, CONTRACT)
    if not os.path.isfile(cpath):
        emit("这里没有 %s——先跑 `pce init`。" % CONTRACT)
        return EXIT_FAIL
    raw = read_text(cpath)
    have = _generated_by(raw)
    if have and _version_key(have) > _version_key(VERSION):
        emit("这个仓库按 %s 建的，比当前 %s 还新，不动它。" % (have, VERSION))
        return EXIT_OK

    emit("这个仓库按 %s 建的，当前 %s。计划：" % (have or "未知（0.4.1 之前没有记录）", VERSION))
    todo, commands, skipped = [], [], []
    state, version = _agents_state(root)
    if state == "missing":
        todo.append("补 AGENTS.md（带 PCE 段）")
    elif state == "outdated":
        todo.append("AGENTS.md 的 PCE 段：%s → %s" % (version or "旧版", VERSION))
    elif state == "edited":
        skipped.append("AGENTS.md 的 PCE 段被改过或没有版本记录，保留（要重置：`pce init --reset-agents`）")
    elif state == "none":
        skipped.append("AGENTS.md 是手写入口、没有 PCE 段，不碰（要接管：`pce init --reset-agents`）")
    elif state == "broken":
        skipped.append("AGENTS.md 的 PCE 标记重复或没闭合，不动它，先手工看")
    if not have:
        todo.append("structure.yaml 头部补一行 `# generated by pce %s`" % VERSION)
    nav = os.path.join(root, NAV)
    if os.path.isfile(nav):
        if "最后更新" not in read_text(nav):
            commands.append("根 navigation.md 的表少“最后更新”一列 → 跑 `pce map`")
    else:
        commands.append("缺根 navigation.md → 跑 `pce init`")
    if not os.path.isfile(os.path.join(root, "README.md")):
        commands.append("缺根 README.md → 跑 `pce init`")

    for line in todo:
        emit("  [要改] " + line)
    for line in commands:
        emit("  [跑命令] " + line)
    for line in skipped:
        emit("  [跳过] " + line)
    if not todo and not commands:
        emit("这个仓库按 %s 建的，当前 %s，没有要迁的。" % (have or "未知", VERSION))
        return EXIT_OK
    if not todo:
        emit("没有能自动改的；上面 [跑命令] 的照做就行。")
        return EXIT_OK

    if "--apply" not in args:
        if not sys.stdin.isatty():
            emit("要执行上面的改动，加 `--apply`。")
            return EXIT_OK
        emit("执行？(y/N)")
        answer = sys.stdin.readline().strip().lower()
        if answer not in ("y", "yes"):
            emit("没改。")
            return EXIT_OK

    targets = []
    apply_agents(root, targets)
    for rel, text in targets:
        full = os.path.join(root, rel)
        parent = os.path.dirname(full)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(text if text.endswith("\n") else text + "\n")
    if not have:
        with open(cpath, "w", encoding="utf-8") as f:
            f.write("# generated by pce %s\n%s" % (VERSION, raw))
    emit("改完了，跑 `pce check` 复查。")
    return EXIT_OK


PLAN_EXAMPLE = """zones:
  src:
    what: 程序源码
    children:
      auth:
        what: 认证、会话、权限
      billing:
        what: 计费与账期
  docs:
    what: 说明文档
    children:
      adr:
        what: 架构决策记录
"""

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _plan_walk(name, node, base, depth, limit, out, errors):
    if not isinstance(node, dict):
        errors.append("%s：要写成 {what: …, children: …}" % (name or "根"))
        return
    what = node.get("what")
    if not isinstance(what, str) or not what.strip():
        errors.append("%s：缺一句“负责什么”（what）" % (name or "根"))
        return
    what = what.strip()
    if is_vague(what):
        errors.append("%s：负责什么写成了空话（%r）" % (name or "根", what))
    if name is not None:
        if not NAME_RE.match(name):
            errors.append("%s：目录名只能用字母、数字、点、横线、下划线，且不能以符号开头" % name)
        if depth > limit:
            errors.append("%s：第 %d 层超过上限 %d 层；先建到第 %d 层，用到再加"
                          % (name, depth, limit, limit))
    rel = name if base is None else (base + "/" + name if base else name)
    if name is not None:
        out.append((rel, what, depth))
    children = node.get("children") or {}
    if not isinstance(children, dict):
        errors.append("%s：children 要写成“名字: {what: …}”的块" % (name or "根"))
        return
    kids = []
    for child_name, child in children.items():
        _plan_walk(child_name, child, rel if rel else "", depth + 1, limit, out, errors)
        kids.append((child_name, (child or {}).get("what", "") if isinstance(child, dict) else ""))
    for i in range(len(kids)):
        for j in range(i + 1, len(kids)):
            a, wa = kids[i]
            b, wb = kids[j]
            if _name_similar(a, b):
                errors.append("%s 与 %s 的名字太像，容易放错" % (a, b))
            elif wa and wb and jaccard(wa, wb) >= 0.6:
                errors.append("%s 与 %s 的职责说明几乎一样（%r / %r），合并还是分开？" % (a, b, wa, wb))


def cmd_scaffold(root, args):
    """按一份 plan 预先把目录层级建出来（模型给方案，pce 校验并落地）。"""
    if "--example" in args:
        emit(PLAN_EXAMPLE.rstrip("\n"))
        return EXIT_OK

    src = None
    positional = [a for a in args if not a.startswith("-")]
    if positional:
        src = positional[0]
    if src is None:
        emit("给一份 plan：`pce scaffold plan.yaml`，或者从输入读 `pce scaffold -`。")
        emit("不知道格式就先看样例：`pce scaffold --example`。")
        return EXIT_USAGE
    if src == "-":
        text = sys.stdin.read()
    else:
        path = src if os.path.isabs(src) else os.path.join(os.getcwd(), src)
        if not os.path.isfile(path):
            emit("找不到 %s" % src)
            return EXIT_USAGE
        text = read_text(path)
    try:
        data = parse_yaml(text)
    except YamlError as exc:
        emit("plan 读不了：%s" % exc)
        return EXIT_FAIL

    limit = 3
    if "--depth" in args:
        i = args.index("--depth")
        if i + 1 < len(args) and args[i + 1].isdigit():
            limit = int(args[i + 1])
    errors = []
    if not isinstance(data, dict) or "zones" not in data:
        emit("plan 里要有 zones:（根下一级的分区）")
        return EXIT_FAIL
    extra = [k for k in data if k != "zones"]
    if extra:
        errors.append("plan 里只能有 zones，不认识：%s" % ", ".join(extra))
    zones = data.get("zones") or {}
    if not isinstance(zones, dict) or not zones:
        emit("plan 里的 zones 是空的")
        return EXIT_FAIL
    nodes = []
    for zone_name, node in zones.items():
        _plan_walk(zone_name, node, "", 1, limit, nodes, errors)

    try:
        contract = load_contract(root)
    except ContractError as exc:
        emit("先解决契约问题：%s" % exc)
        return EXIT_FAIL
    for rel, what, depth in nodes:
        head = rel.split("/")[0]
        if depth == 1:
            if _name_similar(head, contract.archive_dir()) if contract.archive_dir() else False:
                errors.append("%s 和归档区同名" % head)
            for other, info in contract.zones.items():
                if other == head:
                    continue
                if _name_similar(head, other):
                    errors.append("%s 与已有分区 %s 的名字太像" % (head, other))
                elif jaccard(what, info.get("what", "")) >= 0.6:
                    errors.append("%s 与已有分区 %s 的职责说明几乎一样（%r / %r）"
                                  % (head, other, what, info.get("what", "")))
    if errors:
        emit("这份 plan 不能直接用：")
        for e in errors:
            emit("  - " + e)
        return EXIT_FAIL

    emit("会建 %d 个目录，并在每层 navigation.md 里登记：" % len(nodes))
    for rel, what, depth in nodes:
        full = os.path.join(root, rel)
        state = "已存在，跳过" if os.path.isdir(full) else "新建"
        emit("  %-28s %-24s %s" % (rel + "/", what, state))
    if "--apply" not in args:
        if not sys.stdin.isatty():
            emit("要执行就加 `--apply`。")
            return EXIT_OK
        emit("执行？(y/N)")
        if sys.stdin.readline().strip().lower() not in ("y", "yes"):
            emit("没改。")
            return EXIT_OK

    for rel, what, depth in nodes:
        os.makedirs(os.path.join(root, rel), exist_ok=True)
    whats = {(rel): what for rel, what, depth in nodes}
    for rel, what, depth in nodes:
        parent = os.path.dirname(rel) or "."
        nav_put_row(root, parent, os.path.basename(rel), what,
                    first_line=whats.get(parent))
    new_zones = [(rel, what) for rel, what, depth in nodes if depth == 1 and rel not in contract.zones]
    if new_zones:
        cpath = os.path.join(root, CONTRACT)
        raw = read_text(cpath)
        lines = raw.splitlines()
        for i, line in enumerate(lines):
            if line.strip() == "zones:":
                add = []
                for name, what in new_zones:
                    add += ["  %s:" % name, "    what: %s" % what]
                lines[i + 1:i + 1] = add
                break
        with open(cpath, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    emit("建好了。空目录不会进 git——clone 下来后重跑一次 `pce scaffold` 就补齐。")
    emit("下一步：`pce check`。")
    return EXIT_OK


def cmd_upgrade(root, args):
    target = os.path.join(root, "tools", "pce.py")
    record = os.path.join(root, "tools", SHA)
    if not os.path.isfile(target):
        emit("这个仓库没有 vendored 副本（tools/pce.py）——升级 skill 本身就够了，这里不用动。")
        emit("要给 CI 留一份，跑 `pce init --vendor`。")
        return EXIT_OK
    src = None
    if "--from" in args:
        i = args.index("--from")
        if i + 1 < len(args):
            src = os.path.abspath(args[i + 1])
    if src is None:
        src = _find_upstream()
    if src is None or not os.path.isfile(src):
        emit("不知道上游那份在哪。用 `pce upgrade --from <路径>` 指一下 skill 里的 tools/pce.py。")
        return EXIT_USAGE
    if os.path.abspath(src) == os.path.abspath(target):
        emit("仓库里的这份就是安装源，没有更新的版本")
        return EXIT_OK
    old = sha256_file(target)
    new = sha256_file(src)
    recorded = read_text(record).strip() if os.path.isfile(record) else ""
    if old == new:
        emit("已经是最新")
        return EXIT_OK
    here = _read_version(target)
    there = _read_version(src)
    if there and here and _version_key(there) < _version_key(here):
        emit("上游那份是 %s，比仓库里的 %s 旧，不降级。" % (there, here))
        emit("比一下：pce upgrade --from <更新的那份>，或者把上游指向开发仓库。")
        return EXIT_FAIL
    if there and here and _version_key(there) == _version_key(here):
        emit("两边都是 %s，但内容不一样——可能是仓库里这份被改过，也可能上游没发布。" % there)
        emit("不覆盖。确认要换，就 pce upgrade --from <那份> --force。")
        return EXIT_FAIL
    if recorded and recorded != old:
        emit("本地这份被改过（和安装时记录的不一致），不覆盖。")
        try:
            diff = subprocess.run(["git", "diff", "--no-index", "--stat", "--", target, src],
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20)
            text = diff.stdout.decode("utf-8", "replace").strip()
            if text:
                emit("差多少：")
                for line in text.splitlines()[-3:]:
                    emit("  " + line)
        except (OSError, subprocess.SubprocessError):
            pass
        emit("自己合：把新版的改动并进 tools/pce.py，再覆盖 tools/%s 后重跑。" % SHA)
        return EXIT_FAIL
    if not recorded:
        emit("没有 tools/%s，无法判断本地有没有改过，不覆盖。" % SHA)
        return EXIT_FAIL
    if "--check" in args:
        emit("有新版本可用（%s → %s）" % (here or "?", there or "?"))
        return EXIT_OK
    if "--force" not in args and recorded != old:
        emit("本地这份和安装记录不一致，不覆盖。")
        return EXIT_FAIL
    shutil.copyfile(src, target)
    with open(record, "w", encoding="utf-8") as f:
        f.write(new + "\n")
    emit("已升级到 %s（原来是 %s）" % (there or "?", here or "?"))
    return EXIT_OK


# ---------------------------------------------------------------- 命令：hook

HOOK_BODY = """#!/bin/sh
# 由 pce hook install 生成；要撤掉就 pce hook uninstall
cd "$(git rev-parse --show-toplevel)" || exit 0
python3 tools/pce.py check
"""


def cmd_hook(root, args):
    action = args[0] if args else ""
    gitdir = os.path.join(root, ".git")
    if not os.path.isdir(gitdir):
        emit("这个目录不是 git 仓库（没有 .git），钩子装不了")
        return EXIT_FAIL
    hooks = os.path.join(gitdir, "hooks")
    os.makedirs(hooks, exist_ok=True)
    path = os.path.join(hooks, "pre-commit")
    backup = path + ".pce-bak"
    if action == "install":
        if os.path.exists(path) and "pce.py check" not in read_text(path):
            if not os.path.exists(backup):
                shutil.copyfile(path, backup)
                emit("先把原来的 pre-commit 备份成 %s" % os.path.basename(backup))
            else:
                emit("%s 已经存在别的钩子，备份也在，不覆盖。" % path)
                return EXIT_FAIL
        with open(path, "w", encoding="utf-8") as f:
            f.write(HOOK_BODY)
        os.chmod(path, 0o755)
        emit("装了 pre-commit：提交前跑 `pce check`（只拦 error，不拦 warn）")
        return EXIT_OK
    if action == "uninstall":
        if os.path.exists(path) and "pce.py check" in read_text(path):
            os.remove(path)
            if os.path.exists(backup):
                shutil.move(backup, path)
                emit("撤了 pce 的 pre-commit，恢复了原来那个")
            else:
                emit("撤了 pre-commit")
        else:
            emit("没有装过")
        return EXIT_OK
    emit("用法：pce hook install | pce hook uninstall")
    return EXIT_USAGE


# ---------------------------------------------------------------- main

USAGE = """pce %s — 项目一致性工程

用法：pce <命令> [参数]

  init                  建骨架（structure.yaml / AGENTS.md / navigation.md / tools/pce.py）
  audit [--json]        只读体检，给现状不给方案
  check [--paths …] [--strict] [--json]   跑 12 条规则
  map [--apply]         让每层 navigation.md 与磁盘对齐
  new <路径…> [--dir] [--apply]           新建文件或目录
  archive <路径…> --reason "…" [--apply]  归档
  explain <路径>        解释某个路径为什么被判成这样
  upgrade [--check]     把仓库里的 tools/pce.py 换成本机这一份
  upgrade-repo [--apply] 把仓库里的 AGENTS.md 段、生成记录迁到当前版本
  scaffold <plan.yaml|-> [--apply] [--depth N] [--example]  按 plan 预建目录层级
  hook install|uninstall                  装/撤 git pre-commit 钩子
""" % VERSION


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        emit(USAGE)
        return EXIT_OK if argv else EXIT_USAGE
    if argv[0] == "--version":
        emit(VERSION)
        return EXIT_OK
    cmd, rest = argv[0], argv[1:]
    if cmd == "init":
        cwd = os.path.abspath(os.getcwd())
        found = find_root()
        if found and os.path.abspath(found) != cwd:
            emit("这里在 %s 下面，不是仓库根。init 只在你要初始化的那个目录里跑。" % found)
            return EXIT_USAGE
        root = cwd
    elif cmd == "audit":
        root = find_root() or _git_root() or os.getcwd()
    else:
        root = find_root()
        if root is None:
            emit("这里不是 PCE 仓库（找不到 %s）。先进入仓库根，或先跑 `pce init`。" % CONTRACT)
            return EXIT_FAIL
    table = {
        "init": cmd_init, "audit": cmd_audit, "check": cmd_check, "map": cmd_map,
        "new": cmd_new, "archive": cmd_archive, "explain": cmd_explain,
        "upgrade": cmd_upgrade, "upgrade-repo": cmd_upgrade_repo, "scaffold": cmd_scaffold, "hook": cmd_hook,
    }
    if "--json" in rest and cmd not in ("audit", "check"):
        emit("--json 只给 audit 和 check 用")
        return EXIT_USAGE
    fn = table.get(cmd)
    if fn is None:
        emit("不认识的命令：%s" % cmd)
        emit("")
        emit(USAGE)
        return EXIT_USAGE
    try:
        return fn(root, rest)
    except KeyboardInterrupt:
        emit("")
        emit("中止了，没有继续写。")
        return EXIT_FAIL
    except OSError as exc:
        emit("写不进去：%s" % exc)
        emit("（目标目录没有写权限，或者被沙箱/编辑器占住了）")
        return EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
