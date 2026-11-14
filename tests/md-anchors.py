#!/usr/bin/env python3
"""Markdown のリンクのアンカー（#見出し）が、リンク先の見出しに当たるか検査する。lint.sh が python3 -I で呼ぶ。

使い方: python3 -I tests/md-anchors.py FILE...
        python3 -I tests/md-anchors.py --git   （git ls-files -z の追跡済み・未追跡の .md を全部見る。lint.sh が使う）
  FILE の中の [text](#anchor) と [text](相対パス.md#anchor) を見て、リンク先の Markdown の見出しから
  GitHub と同じ規則で作った id に anchor が無ければ、標準エラー出力に 1 行ずつ出して rc 1。全部当たれば rc 0。
  外のリンク（スキームの付いたもの、/ で始まるもの）と、.md でないファイルへのリンクは見ない。
  コードブロックとインラインコードの中は、リンクとも見出しとも読まない。

見出しの id（GitHub の規則）: 見出しの文から Markdown の記法を外し、小文字にし、文字・数字・結合文字・
空白・- ・_ 以外を消して、空白を - にする。同じ id が続けば -1、-2 … を付ける。標準ライブラリだけを使う。
"""

import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path
from urllib.parse import unquote

FENCE_RE = re.compile(r' {0,3}(`{3,}|~{3,})(.*)')
ATX_RE = re.compile(r' {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*')
ATX_CLOSE_RE = re.compile(r'(?:^|[ \t]+)#+[ \t]*$')
SETEXT_RE = re.compile(r' {0,3}(=+|-+)[ \t]*')
NOT_PARAGRAPH_RE = re.compile(r' {0,3}(?:[-*+>|]|[0-9]+[.)])')
CODE_SPAN_RE = re.compile(r'(`+)(.+?)(?<!`)\1(?!`)')
LINK_RE = re.compile(r'!?\[([^\]]*)\]\(\s*(?:<([^<>]*)>|([^()\s]*))(?:\s+"[^"]*")?\s*\)')
QUOTE_RE = re.compile(r'(?: {0,3}>[ \t]?)+')
SCHEME_RE = re.compile(r'[A-Za-z][A-Za-z0-9+.-]*:')
EMPHASIS_RE = re.compile(r'(\*{1,3}|_{1,3})(?=\S)(.+?)(?<=\S)\1(?![\w*])')


def _content_lines(text):
    """(行番号, 行) を、コードブロックの中の行を除いて返す。

    コードブロックの開始と終了の行では (行番号, None) を返す（段落をまたいだ setext の見出しを作らないため）。
    """
    fence = None
    for number, line in enumerate(text.split('\n'), 1):
        match = FENCE_RE.fullmatch(line)
        if fence is None:
            if match and not (match.group(1)[0] == '`' and '`' in match.group(2)):
                fence = match.group(1)
                yield number, None
                continue
            yield number, line
        elif match and match.group(1)[0] == fence[0] and len(match.group(1)) >= len(fence) \
                and not match.group(2).strip():
            fence = None
            yield number, None


def _plain(text):
    """見出しの文から Markdown の記法を外す（インラインコードの中身はそのまま残す）。"""
    parts = []
    last = 0
    for match in CODE_SPAN_RE.finditer(text):
        parts.append(_unmark(text[last:match.start()]))
        parts.append(match.group(2).strip(' ') or match.group(2))
        last = match.end()
    parts.append(_unmark(text[last:]))
    return ''.join(parts)


def _unmark(text):
    text = LINK_RE.sub(lambda m: m.group(1), text)
    previous = None
    while previous != text:
        previous = text
        text = EMPHASIS_RE.sub(lambda m: m.group(2), text)
    return text


def _slug(heading):
    kept = []
    for char in _plain(heading).strip().lower():
        category = unicodedata.category(char)
        if char in ' -' or category[0] in 'LMN' or category == 'Pc':
            kept.append(char)
    return ''.join(kept).replace(' ', '-')


def heading_ids(text):
    ids = set()
    seen = {}
    previous = None  # 直前の段落の行（setext の見出しの候補）
    for _, line in _content_lines(text):
        if line is None:
            previous = None
            continue
        stripped = QUOTE_RE.sub('', line, count=1)  # 引用の中の見出しにも id が付く
        quoted = line[:len(line) - len(stripped)].count('>')  # 引用の深さ（入れ子の `>` の数）
        line = stripped
        title = None
        atx = ATX_RE.fullmatch(line)
        if atx:
            title = ATX_CLOSE_RE.sub('', atx.group(2) or '')
            previous = None
        elif previous is not None and previous[1] == quoted and SETEXT_RE.fullmatch(line):
            title, previous = previous[0], None  # 引用の深さが違う --- は、段落の下線にならない
        else:
            previous = (line, quoted) if line.strip() and not NOT_PARAGRAPH_RE.match(line) else None
            continue
        base = _slug(title)
        slug = base
        while slug in seen or slug in ids:
            seen[base] = seen.get(base, 0) + 1
            slug = f'{base}-{seen[base]}'
        seen.setdefault(slug, 0)
        ids.add(slug)
    return ids


def links(text):
    """(行番号, リンク先) を、コードの外のリンクについて返す。"""
    for number, line in _content_lines(text):
        if line is None:
            continue
        for match in LINK_RE.finditer(CODE_SPAN_RE.sub('', line)):
            yield number, match.group(2) if match.group(2) is not None else match.group(3)


def check(paths):
    cache = {}

    def ids_of(path):
        key = path.resolve()
        if key not in cache:
            try:
                cache[key] = heading_ids(path.read_text(encoding='utf-8'))
            except (OSError, UnicodeDecodeError):
                cache[key] = None
        return cache[key]

    problems = []
    for name in paths:
        source = Path(name)
        try:
            text = source.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError) as error:
            problems.append(f'{name}: 読めない: {error}')
            continue
        for number, target in links(text):
            path, sep, anchor = target.partition('#')
            if not sep or not anchor or SCHEME_RE.match(path) or path.startswith('/'):
                continue
            if path and not unquote(path).endswith('.md'):
                continue
            dest = source.parent / unquote(path) if path else source
            ids = ids_of(dest) if dest.is_file() else None
            if ids is None:
                problems.append(f'{name}:{number}: ({target}) のファイルが無い')
            elif unquote(anchor) not in ids:
                problems.append(f'{name}:{number}: ({target}) の見出しが無い')
    return problems


def git_markdown_files():
    # -z で NUL 区切りにする（既定の出力は日本語などのパスを引用符で囲み、実在しないパスになる）。
    out = subprocess.run(['git', 'ls-files', '-z', '-co', '--exclude-standard', '--', '*.md'],
                         capture_output=True, check=True).stdout
    names = [os.fsdecode(name) for name in out.split(b'\0') if name]
    return [name for name in names if os.path.isfile(name)]


def main(argv):
    if argv == ['--git']:
        argv = git_markdown_files()
    problems = check(argv)
    for problem in problems:
        print(f'ERROR: {problem}', file=sys.stderr)
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
