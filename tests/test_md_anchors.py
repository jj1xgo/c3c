#!/usr/bin/env python3
"""lint.sh の Markdown のアンカーの検査（tests/md-anchors.py）の試験。

一時ディレクトリに Markdown を置き、lint.sh と同じく python3 -I で検査を起動して、rc と出力を見る。
"""

from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
CHECKER = REPO / 'tests' / 'md-anchors.py'


class MdAnchorsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return name

    def run_check(self, *names):
        return subprocess.run([sys.executable, '-I', str(CHECKER), *names], cwd=self.root,
                              capture_output=True, text=True, timeout=30)

    def assert_ok(self, *names):
        result = self.run_check(*names)
        self.assertEqual((result.returncode, result.stderr), (0, ''))

    def assert_broken(self, *names, expect):
        result = self.run_check(*names)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(expect, result.stderr)

    def test_same_file_anchor(self):
        self.assert_ok(self.write('a.md', '# 概要\n\n[上へ](#概要)\n'))

    def test_missing_heading_reports_file_and_line(self):
        self.assert_broken(self.write('a.md', '# 概要\n\n本文\n[上へ](#がいよう)\n'),
                           expect='a.md:4: (#がいよう)')

    def test_other_file_anchor(self):
        self.write('docs/b.md', '## 変更後の確認\n')
        self.assert_ok(self.write('a.md', '[確認](docs/b.md#変更後の確認)\n'))

    def test_other_file_missing_heading(self):
        self.write('docs/b.md', '## 変更後の確認\n')
        self.assert_broken(self.write('a.md', '[確認](docs/b.md#変更前の確認)\n'),
                           expect='a.md:1: (docs/b.md#変更前の確認)')

    def test_relative_to_linking_file(self):
        self.write('README.md', '## 表記\n')
        self.assert_ok(self.write('docs/a.md', '[表記](../README.md#表記)\n'))

    def test_target_file_missing(self):
        self.assert_broken(self.write('a.md', '[x](nothing.md#x)\n'), expect='a.md:1: (nothing.md#x)')

    def test_github_slug_rules(self):
        # 小文字にし、文字・数字・空白・- と _ 以外を消し、空白を - にする（全角の記号も消える）。
        text = ('# c3c — Claude Code & Codex Container\n'
                '## 「sandbox」から見えるもの（2026-11）。\n'
                '### Task 1: `lint.sh` に `LINT_SKIP_COMPOSE` を足す\n'
                '[a](#c3c--claude-code--codex-container) [b](#sandboxから見えるもの2026-11)\n'
                '[c](#task-1-lintsh-に-lint_skip_compose-を足す)\n')
        self.assert_ok(self.write('a.md', text))

    def test_link_to_heading_uses_link_text(self):
        self.assert_ok(self.write('a.md', '## [README](README.md) の節\n[x](#readme-の節)\n'))

    def test_emphasis_markers_dropped(self):
        self.assert_ok(self.write('a.md', '## **強い** と _斜め_ の節\n[x](#強い-と-斜め-の節)\n'))

    def test_duplicate_headings_get_suffix(self):
        text = '## 例\n## 例\n## 例\n[a](#例) [b](#例-1) [c](#例-2)\n'
        self.assert_ok(self.write('a.md', text))
        self.assert_broken(self.write('b.md', '## 例\n## 例\n[d](#例-2)\n'), expect='b.md:3: (#例-2)')

    def test_trailing_hashes_and_spaces_in_heading(self):
        self.assert_ok(self.write('a.md', '##   節の名前   ##\n[x](#節の名前)\n'))

    def test_heading_in_fence_is_not_a_heading(self):
        text = '```bash\n# コメント\n```\n[x](#コメント)\n'
        self.assert_broken(self.write('a.md', text), expect='a.md:4: (#コメント)')

    def test_links_in_code_are_ignored(self):
        text = ('# 節\n'
                '`[x](#無い節)` を足す\n'
                '```\n[y](#無い節)\n```\n'
                '~~~\n[z](#無い節)\n~~~\n'
                '````markdown\n```\n[w](#無い節)\n```\n````\n')
        self.assert_ok(self.write('a.md', text))

    def test_external_and_non_markdown_links_are_ignored(self):
        text = ('[a](https://github.com/x/y#readme) [b](compose.yml#L10) [c](mailto:x@example.com#y)\n'
                '[d](#)\n')
        self.assert_ok(self.write('a.md', text))

    def test_percent_encoded_anchor(self):
        self.assert_ok(self.write('a.md', '# 概要\n[x](#%E6%A6%82%E8%A6%81)\n'))

    def test_anchor_case_must_match(self):
        # GitHub の id は小文字なので、大文字の残るアンカーはページの中で飛ばない。
        self.assert_broken(self.write('a.md', '# Setup\n[x](#Setup)\n'), expect='a.md:2: (#Setup)')

    def test_reports_every_broken_link(self):
        result = self.run_check(self.write('a.md', '# 節\n[a](#x) [b](#y)\n'))
        self.assertEqual(result.returncode, 1)
        self.assertIn('(#x)', result.stderr)
        self.assertIn('(#y)', result.stderr)

    def test_angle_bracket_destination_is_checked(self):
        # [x](<#a>) も通常のリンクなので、切れていれば報告する。
        self.assert_broken(self.write('a.md', '# 節\n[x](<#無い節>)\n'), expect='a.md:2: (#無い節)')
        self.assert_ok(self.write('b.md', '# 節\n[x](<#節>) [y](<a.md#節>)\n'))

    def test_setext_candidate_does_not_cross_a_fence(self):
        # 段落とフェンスと --- の並びは、段落を見出しにしない（--- は水平線）。
        text = '本文\n```\ncode\n```\n---\n[x](#本文)\n'
        self.assert_broken(self.write('a.md', text), expect='a.md:6: (#本文)')

    def test_setext_heading_still_works_around_a_fence(self):
        text = '```\ncode\n```\n見出し\n---\n[x](#見出し)\n'
        self.assert_ok(self.write('a.md', text))

    def test_heading_in_blockquote_gets_an_id(self):
        self.assert_ok(self.write('a.md', '> # 引用の見出し\n\n[x](#引用の見出し)\n'))

    def test_unquoted_rule_after_quoted_paragraph_is_not_a_setext_underline(self):
        # 引用の外の --- は水平線で、引用の段落を見出しにしない。
        text = '> 引用の段落\n---\n[x](#引用の段落)\n'
        self.assert_broken(self.write('a.md', text), expect='a.md:3: (#引用の段落)')

    def test_quoted_setext_heading_still_works(self):
        self.assert_ok(self.write('a.md', '> 引用の見出し\n> ---\n\n[x](#引用の見出し)\n'))

    def test_rule_at_a_different_quote_depth_is_not_a_setext_underline(self):
        # 引用の深さが段落と違う --- は、段落の下線にならない（深さの組み合わせを全部見る）。
        for name, text in (
            ('deeper-paragraph.md', '> > 内側\n> ---\n[x](#内側)\n'),
            ('shallower-paragraph.md', '> 外側\n> > ---\n[x](#外側)\n'),
            ('two-to-none.md', '> > 内側\n---\n[x](#内側)\n'),
        ):
            with self.subTest(name):
                self.assert_broken(self.write(name, text), expect=f'{name}:3:')

    def test_rule_at_the_same_quote_depth_is_a_setext_underline(self):
        for name, text in (
            ('one.md', '> 見出し\n> ---\n[x](#見出し)\n'),
            ('two.md', '> > 見出し\n> > ---\n[x](#見出し)\n'),
            ('two-compact.md', '>> 見出し\n>> ===\n[x](#見出し)\n'),
        ):
            with self.subTest(name):
                self.assert_ok(self.write(name, text))

    def test_lazy_continuation_keeps_the_paragraph_quote_depth(self):
        # 段落の途中で引用が浅くなった行は lazy continuation で、段落の深さは元のまま。
        # その段落の下線は、元の深さの --- だけ（深さが違う --- は水平線）。
        # 引数は (名前, 本文, 切れているべきリンクの行)。
        for name, text, line in (
            ('m5.md', '> > b\n> c\n> ---\n[x](#c)\n', 4),
            ('m4.md', '> 段落\n続き\n---\n[x](#続き)\n', 4),
            ('m4-first.md', '> 段落\n続き\n---\n[x](#段落)\n', 4),
            ('two-one-one.md', '> > a\n> b\n> ---\n[x](#b)\n', 4),
            ('two-zero-zero.md', '> > a\nb\n---\n[x](#b)\n', 4),
            ('lazy-repeated.md', '> > a\n> b\nc\n> ---\n[x](#c)\n', 5),
            ('lazy-repeated-first.md', '> > a\n> b\nc\n> ---\n[x](#a)\n', 5),
            ('lazy-then-blank.md', '> > a\n> b\n\n> ---\n[x](#b)\n', 5),
        ):
            with self.subTest(name):
                self.assert_broken(self.write(name, text), expect=f'{name}:{line}:')

    def test_lazy_continuation_underline_at_the_paragraph_depth_still_works(self):
        # 段落は繋げて 1 つの見出しになる（GitHub の id は行を空白で繋いだ文から作る）。
        for name, text in (
            ('two-lazy-two.md', '> > a\n> b\n> > ---\n[x](#a-b)\n'),
            ('one-lazy-one.md', '> a\nb\n> ---\n[x](#a-b)\n'),
            ('three-lazy-three.md', '> > > a\n> b\n> > > ---\n[x](#a-b)\n'),
            ('plain.md', '平文\n---\n[x](#平文)\n'),
            ('plain-two-lines.md', 'a\nb\n---\n[x](#a-b)\n'),
            ('quoted-after-plain.md', '段落\n> 引用\n> ---\n[x](#引用)\n'),
            ('quoted-after-blank.md', '> a\n\n> b\n> ===\n[x](#b)\n'),
        ):
            with self.subTest(name):
                self.assert_ok(self.write(name, text))

    def test_heading_text_is_the_whole_paragraph(self):
        # 最後の行だけの id は、GitHub の id と違う（F2）。
        for name, text, line in (
            ('lazy-last-line.md', '> a\nb\n> ---\n[x](#b)\n', 4),
            ('lazy-last-line-nested.md', '> > a\n> b\n> > ---\n[x](#b)\n', 4),
            ('plain-last-line.md', 'a\nb\n---\n[x](#b)\n', 4),
        ):
            with self.subTest(name):
                self.assert_broken(self.write(name, text), expect=f'{name}:{line}:')

    def test_lazy_line_with_equals_is_paragraph_text(self):
        # === は lazy continuation の文字で、引用の外の下線にならない（M2）。
        self.assert_broken(self.write('eq.md', '> a\nb\n===\n[x](#b)\n'), expect='eq.md:4:')
        self.assert_broken(self.write('eq2.md', '> a\nb\n===\n[x](#a-b)\n'), expect='eq2.md:4:')

    def test_quoted_block_that_is_not_a_paragraph_is_not_lazy(self):
        # 引用の中のコードブロック・字下げのコード・HTML の後の引用の外の行は、新しい段落（I1）。
        # 引用の外の --- は、その段落の下線になる（正しいリンク）。
        for name, text in (
            ('fence-then-heading.md', '> ```\nc\n---\n[x](#c)\n'),
            ('indented-then-heading.md', '>     code\nc\n---\n[x](#c)\n'),
            ('html-comment-then-heading.md', '> <!-- x -->\nc\n---\n[x](#c)\n'),
        ):
            with self.subTest(name):
                self.assert_ok(self.write(name, text))
        # 引用の中の --- は、引用の外の段落の下線にならない。
        for name, text in (
            ('fence-then-quoted-rule.md', '> ```\nc\n> ---\n[x](#c)\n'),
            ('indented-then-quoted-rule.md', '>     code\nc\n> ---\n[x](#c)\n'),
            ('indented-then-quoted-rule2.md', '>     code\nc\n> ---\n[x](#code)\n'),
            ('html-then-quoted-rule.md', '> <div>\nc\n> ---\n[x](#c)\n'),
        ):
            with self.subTest(name):
                self.assert_broken(self.write(name, text), expect=f'{name}:4:')

    def test_html_block_line_does_not_continue_a_quoted_paragraph(self):
        # lazy の行が HTML ブロックを始めるなら、段落は続かない（F1）。HTML ブロックは空行まで続く。
        for name, text in (
            ('div.md', '> a\n<div>\n> ---\n[x](#div)\n'),
            ('div-a.md', '> a\n<div>\n> ---\n[x](#a)\n'),
            ('div-inside.md', '<div>\nfoo\n---\n[x](#foo)\n'),
            ('comment-inside.md', '<!--\nfoo\n---\n[x](#foo)\n'),
            ('script-blank-inside.md', '<script>\n\nfoo\n---\n[x](#foo)\n'),
        ):
            with self.subTest(name):
                self.assert_broken(self.write(name, text), expect=f'{name}:{text.count(chr(10))}:')

    def test_html_block_ends_and_text_after_it_is_a_paragraph(self):
        for name, text in (
            ('after-blank.md', '<div>\n\nfoo\n---\n[x](#foo)\n'),
            ('after-comment.md', '<!--\nx\n-->\n\nfoo\n---\n[x](#foo)\n'),
            ('type7-cannot-interrupt.md', 'foo\n<span>\n---\n[x](#foo-span)\n'),
        ):
            with self.subTest(name):
                self.assert_ok(self.write(name, text))

    def test_thematic_break_ends_a_quoted_paragraph(self):
        # ___ や *** は段落を中断して引用を閉じる。その後の --- は見出しにならない。
        for name, text in (
            ('underscores.md', '> a\n___\n> ---\n[x](#___)\n'),
            ('underscores-a.md', '> a\n___\n> ---\n[x](#a)\n'),
            ('spaced-dashes.md', '> a\n- - -\n> ---\n[x](#a)\n'),
        ):
            with self.subTest(name):
                self.assert_broken(self.write(name, text), expect=f'{name}:4:')

    def test_fence_in_blockquote_is_code(self):
        # 引用の中のコードブロックの中身は、段落でも見出しでもない。
        for name, text in (
            ('fence-atx.md', '> ```\n> # コメント\n> ```\n[x](#コメント)\n'),
            ('fence-setext.md', '> ```\n> c\n> ---\n> ```\n[x](#c)\n'),
            ('fence-quote-ends.md', '> ```\n> c\nd\n> ---\n[x](#d)\n'),
        ):
            with self.subTest(name):
                self.assert_broken(self.write(name, text), expect=f'{name}:{text.count(chr(10)) - 0}:')
        # フェンスが閉じた後は普通の行に戻る。
        self.assert_ok(self.write('after-fence.md', '> ```\n> x\n> ```\n> c\n> ---\n[x](#c)\n'))

    def test_greater_than_inside_a_line_is_not_a_quote_marker(self):
        # 行の途中の > は引用の記号ではない（深さを数えず、文字も消さない）。
        self.assert_ok(self.write('arrow.md', 'a > b\n---\n[x](#a--b)\n'))
        self.assert_ok(self.write('arrow2.md', '<!-- a -->\n\nfoo\n---\n[x](#foo)\n'))

    def test_indented_code_is_not_a_setext_candidate(self):
        # 段落でない字下げのコードは、見出しにならない。段落の途中の字下げは段落の続き。
        self.assert_broken(self.write('code.md', '    code\n---\n[x](#code)\n'), expect='code.md:3:')
        self.assert_ok(self.write('continued.md', 'a\n    b\n---\n[x](#a-b)\n'))

    def test_non_ascii_markdown_filename_is_found_by_git_mode(self):
        # lint.sh は --git で呼ぶ。git ls-files が引用する日本語のファイル名も検査に入る。
        env = {'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_SYSTEM': '/dev/null', 'PATH': os.environ['PATH']}
        subprocess.run(['git', 'init', '-q'], cwd=self.root, check=True, env=env)
        self.write('設計.md', '# 節\n[x](#無い節)\n')
        result = subprocess.run([sys.executable, '-I', str(CHECKER), '--git'], cwd=self.root,
                                capture_output=True, text=True, timeout=30, env=env)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('設計.md:2: (#無い節)', result.stderr)

    def test_no_files_is_ok(self):
        self.assert_ok()


if __name__ == '__main__':
    unittest.main()
