#!/usr/bin/env python3
"""欠落プロジェクト清掃の回帰試験。実ファイルとプロセス境界で検証する。"""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
HELPER = REPO / 'project-images.py'
LABEL = 'claude-container.project-'
IMAGE_A = 'a' * 64
IMAGE_B = 'b' * 64

# 実 Podman の JSON 形状と更新を模す。削除要求と状態変化の両方を検査する。
PODMAN = '''#!/usr/bin/env python3
import json, os, sys, time
from pathlib import Path
root = Path(os.environ['FAKE_STORAGE'])
args = sys.argv[1:]
with (root / 'raw-calls').open('a') as out:
    out.write(json.dumps(args) + '\\n')
if args[:1] == ['--remote=false']:
    args = args[1:]
with (root / 'calls').open('a') as out:
    out.write(json.dumps(args) + '\\n')
state = json.loads((root / 'state').read_text())
key = ' '.join(args[:2])
failure = state.get('failure', {})
if key == failure.get('command'):
    print(failure.get('output', '検査用エラー'), file=sys.stderr)
    sys.exit(failure.get('code', 125))
if args == ['images', '--all', '--format', 'json']:
    print(state.get('raw_images', json.dumps(state['images'])))
elif args[:2] == ['image', 'inspect']:
    if state.get('create_path_on_inspect'):
        Path(state['create_path_on_inspect']).mkdir(exist_ok=True)
    item = next((i for i in state['images'] if i['Id'] == args[-1]), None)
    if item is None:
        sys.exit(125)
    item = dict(item)
    item['RepoTags'] = item.get('Names') or []
    item['Config'] = {'Labels': item.get('Labels')}
    item['History'] = [{'created': '2026-09-16T00:00:00Z', 'created_by': 'LABEL', 'empty_layer': True}]
    item.update(state.get('inspect_override', {}))
    print(json.dumps([item]))
elif args == ['ps', '--all', '--external', '--no-trunc', '--format', 'json']:
    count = sum(json.loads(line)[:1] == ['ps'] for line in (root / 'calls').read_text().splitlines())
    containers = state.get('containers', [])
    if count > 1:
        containers = state.get('late_containers', containers)
    print(state.get('raw_containers', json.dumps(containers)))
elif args[:2] == ['rmi', '--no-prune'] and len(args) == 3:
    time.sleep(state.get('remove_delay', 0))
    if state.get('move_directory_on_remove'):
        os.rename(state['move_directory_on_remove'], state['move_directory_on_remove'] + '-moved')
    if not state.get('keep_after_remove'):
        state['images'] = [i for i in state['images'] if i['Id'] != args[2]]
        (root / 'state').write_text(json.dumps(state))
elif args[:2] == ['image', 'exists']:
    sys.exit(0 if any(i['Id'] == args[-1] or args[-1] in (i.get('Names') or []) for i in state['images']) else 1)
elif args[:1] == ['compose']:
    with (root / 'compose-metadata').open('a') as out:
        out.write(json.dumps({k: os.environ.get(k) for k in ('CC_PROJECT_METADATA', 'CC_PROJECT_PATH', 'CC_PROJECT_NAME')}) + '\\n')
else:
    print('想定外の Podman 呼び出し: ' + repr(args), file=sys.stderr)
    sys.exit(125)
'''


def reference_key(path):
    """既存 Bash のキー算出を独立した期待値として使う。"""
    source = (REPO / 'claude-container').read_text()
    func = source.split('compute_project_name() {', 1)[1].split('\n}', 1)[0]
    result = subprocess.run(['bash', '-c', 'WORKING_DIR=$1\n'
                             'compute_project_name() {' + func + '\n}\n'
                             'compute_project_name\nprintf %s "$PROJECT_NAME"',
                             '_', path], capture_output=True, check=True)
    return os.fsdecode(result.stdout)


class ImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='cc-images-', dir='/tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'home'
        self.home.mkdir()
        self.ledger = self.home / '.local/state/claude-container/projects'
        self.ledger.parent.mkdir(parents=True)
        self.missing = str(self.root / '旧 project')
        self.live = str(self.root / 'new project')
        Path(self.live).mkdir()
        self.ledger.write_text(self.missing + '\n' + self.live + '\n')
        self.ledger.chmod(0o600)
        self.before = self.ledger.read_bytes(), self.ledger.stat().st_mode
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        (self.bin / 'podman').write_text(PODMAN)
        (self.bin / 'podman').chmod(0o755)
        self.env = {'PATH': str(self.bin) + ':' + os.environ['PATH'],
                    'HOME': str(self.home), 'FAKE_STORAGE': str(self.root),
                    'PYTHONDONTWRITEBYTECODE': '1', 'LC_ALL': 'C.UTF-8'}
        self.state = {'images': [self.item(self.missing)], 'containers': []}

    def item(self, path, image_id=IMAGE_A, labels=True):
        key = reference_key(path)
        metadata = {LABEL + 'metadata': '1', LABEL + 'path': path,
                    LABEL + 'name': key} if labels else {'claude-container.asset-hash': 'old'}
        return {'Id': image_id, 'Names': [f'localhost/{key}_claude-auth-workspace:latest'],
                'RepoTags': None, 'Labels': metadata, 'History': [], 'Containers': 0}

    def run_helper(self, clean=False, paths=()):
        (self.root / 'state').write_text(json.dumps(self.state))
        (self.root / 'calls').write_text('')
        args = [sys.executable, '-I', str(HELPER), '--ledger', str(self.ledger)]
        if clean:
            args.append('--clean-missing')
        args.extend('--project=' + p for p in paths)
        result = subprocess.run(args, env=self.env, capture_output=True, text=True)
        self.assertEqual((self.ledger.read_bytes(), self.ledger.stat().st_mode), self.before)
        self.state = json.loads((self.root / 'state').read_text())
        self.calls = [json.loads(line) for line in (self.root / 'calls').read_text().splitlines()]
        return result

    def assert_kept(self, result, fail=True):
        if fail:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(any(c[0] in ('rmi', 'prune', 'rm', 'network')
                             or c[:2] in (['image', 'rm'], ['image', 'prune']) for c in self.calls))
        self.assertIn(IMAGE_A, [i['Id'] for i in self.state['images']])

    def test_diagnosis_never_deletes(self):
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(self.missing, result.stdout)
        self.assert_kept(result, fail=False)

    def test_cleanup_removes_only_verified_id_and_preserves_ledger(self):
        self.state['images'].append(self.item(self.live, IMAGE_B))
        result = self.run_helper(clean=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([i['Id'] for i in self.state['images']], [IMAGE_B])
        self.assertIn(['rmi', '--no-prune', IMAGE_A], self.calls)
        self.assertEqual(self.run_helper(clean=True).returncode, 0)

    def test_identical_multitag_rows_do_not_block_other_cleanup(self):
        other = self.item(self.live, IMAGE_B)
        other['Names'].append('localhost/shared:latest')
        self.state['images'].extend([other, dict(other)])
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = self.run_helper(clean=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn(IMAGE_A, [i['Id'] for i in self.state['images']])
        self.assertIn(IMAGE_B, [i['Id'] for i in self.state['images']])

    def test_identical_missing_multitag_rows_remain_protected(self):
        self.state['images'][0]['Names'].append('localhost/shared:latest')
        self.state['images'].append(dict(self.state['images'][0]))
        self.assert_kept(self.run_helper(clean=True))

    def test_conflicting_duplicate_rows_fail_before_any_removal(self):
        duplicate = dict(self.state['images'][0])
        duplicate['Names'] = ['localhost/unrelated:latest']
        self.state['images'].append(duplicate)
        self.assert_kept(self.run_helper(clean=True))

    def test_slow_removal_is_not_killed_by_inspection_deadline(self):
        spec = importlib.util.spec_from_file_location('slow_images', HELPER)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.state['remove_delay'] = 1.0
        (self.root / 'state').write_text(json.dumps(self.state))
        (self.root / 'calls').write_text('')
        original_run = subprocess.run

        def short_deadline(*args, **kwargs):
            # 実子プロセスを使い、読み取りの上限だけを試験用に短縮する。
            if kwargs.get('timeout') is not None:
                kwargs['timeout'] = 0.5
            return original_run(*args, **kwargs)

        with patch.dict(os.environ, self.env), patch.object(mod.subprocess, 'run', short_deadline):
            mod.remove_image(mod.parse_image(self.state['images'][0]), self.missing)
        self.assertEqual(json.loads((self.root / 'state').read_text())['images'], [])

    def test_legacy_image_matches_ledger_despite_old_labels(self):
        self.state['images'] = [self.item(self.missing, labels=False)]
        result = self.run_helper(clean=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.state['images'], [])

    def test_rewritten_ledger_still_finds_old_labeled_image(self):
        self.ledger.write_text(self.live + '\n')
        self.before = self.ledger.read_bytes(), self.ledger.stat().st_mode
        result = self.run_helper(clean=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.state['images'], [])

    def test_legacy_orphan_is_report_only(self):
        self.state['images'] = [self.item(self.missing, labels=False)]
        self.ledger.write_text(self.live + '\n')
        self.before = self.ledger.read_bytes(), self.ledger.stat().st_mode
        result = self.run_helper(clean=True)
        self.assertIn(IMAGE_A, result.stdout)
        self.assert_kept(result, fail=False)

    def test_explicit_scope_preserves_other_missing_project(self):
        other = str(self.root / 'other-missing')
        self.state['images'].append(self.item(other, IMAGE_B))
        result = self.run_helper(clean=True, paths=[self.missing])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([i['Id'] for i in self.state['images']], [IMAGE_B])
        self.assertNotIn(other, result.stdout)

    def test_reference_protection_all_container_states(self):
        for status in ('running', 'exited', 'storage'):
            with self.subTest(status=status):
                self.state['containers'] = [{'Id': 'c' * 64, 'ImageID': IMAGE_A, 'State': status}]
                self.assert_kept(self.run_helper(clean=True))

    def test_rootfs_container_with_explicit_empty_image_id_is_not_a_reference(self):
        self.state['containers'] = [{'Id': 'c' * 64, 'ImageID': '', 'Image': '', 'State': 'created'}]
        result = self.run_helper(clean=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.state['images'], [])

    def test_carriage_return_in_ledger_path_is_not_a_line_separator(self):
        path = str(self.root / 'with\rcarriage')
        self.ledger.write_bytes(os.fsencode(path) + b'\n')
        self.before = self.ledger.read_bytes(), self.ledger.stat().st_mode
        self.state['images'] = [self.item(path, labels=False)]
        result = self.run_helper(clean=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.state['images'], [])

    def test_unverifiable_path_kinds_are_not_missing(self):
        for kind in ('file', 'broken', 'loop', 'permission'):
            with self.subTest(kind=kind):
                path = self.root / kind
                if kind == 'file':
                    path.write_text('x')
                elif kind == 'broken':
                    path.symlink_to(self.root / 'absent')
                elif kind == 'loop':
                    path.symlink_to(path)
                else:
                    path.mkdir()
                    path.chmod(0)
                    self.addCleanup(path.chmod, 0o700)
                    if os.geteuid() == 0:
                        continue
                target = str(path / 'child') if kind == 'permission' else str(path)
                self.state['images'] = [self.item(target)]
                self.assert_kept(self.run_helper(clean=True, paths=[target]))

    def test_removed_symlink_spelling_is_preserved(self):
        link = self.root / 'old-link'
        link.symlink_to(self.live)
        self.state['images'] = [self.item(str(link))]
        link.unlink()
        self.assertEqual(self.run_helper(clean=True, paths=[str(link)]).returncode, 0)
        self.assertEqual(self.state['images'], [])

    def test_malformed_provenance_cannot_fall_back_to_ledger(self):
        for field, value in (('metadata', '2'), ('path', '../relative'), ('name', 'wrong')):
            with self.subTest(field=field):
                self.state['images'] = [self.item(self.missing)]
                self.state['images'][0]['Labels'][LABEL + field] = value
                self.assert_kept(self.run_helper(clean=True))

    def test_colliding_legacy_keys_do_not_choose_one_ledger_path(self):
        # SHA256 の先頭8文字が 748505ae で一致する独立した固定ベクタ。
        first = '/cc118-collision/15829/project'
        second = '/cc118-collision/33274/project'
        self.ledger.write_text(first + '\n' + second + '\n')
        self.before = self.ledger.read_bytes(), self.ledger.stat().st_mode
        self.state['images'] = [self.item(first, labels=False)]
        result = self.run_helper(clean=True)
        self.assert_kept(result, fail=False)
        self.assertNotIn(['rmi', '--no-prune', IMAGE_A], self.calls)

    def test_dangling_and_foreign_alias_protection(self):
        for names in ([], ['localhost/unrelated:latest']):
            with self.subTest(names=names):
                self.state['images'] = [self.item(self.missing)]
                self.state['images'][0]['Names'] += names if names else []
                if not names:
                    self.state['images'][0]['Names'] = []
                result = self.run_helper(clean=True)
                self.assert_kept(result, fail=bool(names))

    def test_inspect_changed_image_names_aborts_removal(self):
        self.state['inspect_override'] = {'RepoTags': ['localhost/new-owner:latest']}
        self.assert_kept(self.run_helper(clean=True))

    def test_podman_failures_never_become_empty_success(self):
        for command, code in (('images --all', 125), ('image inspect', 125),
                              ('ps --all', 125), ('rmi --no-prune', 125), ('rmi --no-prune', 2)):
            with self.subTest(command=command, code=code):
                self.state['failure'] = {'command': command, 'code': code}
                result = self.run_helper(clean=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(IMAGE_A, [i['Id'] for i in self.state['images']])

    def test_malformed_inventory_and_reference_json_fail_closed(self):
        for field, raw in (('raw_images', '{}'), ('raw_images', '[{}]'),
                           ('raw_images', 'bad'), ('raw_containers', '[{}]')):
            with self.subTest(field=field, raw=raw):
                self.state.pop('raw_images', None)
                self.state.pop('raw_containers', None)
                self.state[field] = raw
                self.assert_kept(self.run_helper(clean=True))

    def test_removal_requires_disappearance(self):
        self.state['keep_after_remove'] = True
        result = self.run_helper(clean=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(IMAGE_A, [i['Id'] for i in self.state['images']])

    def test_remote_configuration_cannot_change_cleanup_host(self):
        self.env['CONTAINER_HOST'] = 'ssh://invalid.example/run/podman.sock'
        result = self.run_helper(clean=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        raw = [json.loads(line) for line in (self.root / 'raw-calls').read_text().splitlines()]
        self.assertTrue(raw)
        self.assertTrue(all(c[0] == '--remote=false' for c in raw))

    def test_malformed_label_type_does_not_enable_legacy_cleanup(self):
        self.state['images'][0]['Labels'] = []
        self.assert_kept(self.run_helper(clean=True))

    def test_live_dangling_and_intermediates_are_counted_without_id_noise(self):
        self.state['images'] = [self.item(self.live), self.item(self.live, IMAGE_B, labels=False)]
        for item in self.state['images']:
            item['Names'] = []
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn(IMAGE_A, result.stdout)
        self.assertNotIn(IMAGE_B, result.stdout)

    def run_launcher(self, *args, missing_helper=False, cwd=None):
        runner = self.root / 'runner'
        runner.mkdir(exist_ok=True)
        for source in REPO.iterdir():
            if source.is_file() and not source.name.startswith('.'):
                if missing_helper and source.name == HELPER.name:
                    continue
                shutil.copy2(source, runner / source.name)
        (self.root / 'state').write_text(json.dumps(self.state))
        (self.root / 'calls').write_text('')
        result = subprocess.run(['bash', str(runner / 'claude-container'), *args],
                                cwd=cwd or self.root, env=self.env, capture_output=True, text=True)
        self.calls = [json.loads(line) for line in (self.root / 'calls').read_text().splitlines()]
        self.state = json.loads((self.root / 'state').read_text())
        return result

    def test_cli_rejects_ambiguous_cleanup_before_any_podman_call(self):
        for args in (['--clean-missing'], ['--clean-missing', self.missing],
                     ['--check', '--clean'], ['--clean', '--check', self.missing],
                     ['--check', '--clean-missing', '--clean']):
            with self.subTest(args=args):
                result = self.run_launcher(*args)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertEqual(self.calls, [])

    def test_launcher_cleanup_success_does_not_repeat_missing_failure(self):
        result = self.run_launcher('--check', '--clean-missing', self.missing)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.state['images'], [])
        self.assertEqual((self.ledger.read_bytes(), self.ledger.stat().st_mode), self.before)
        self.assertNotIn('[FAIL]', result.stdout)

    def test_launcher_empty_ledger_still_discovers_old_images(self):
        self.ledger.write_text('')
        result = self.run_launcher('--check')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(IMAGE_A, result.stdout)
        self.assertFalse(any(c[0] == 'rmi' for c in self.calls))

    def test_launcher_relative_logical_scope(self):
        result = self.run_launcher('--check', '--clean-missing', './旧 project/')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.state['images'], [])

    def test_launcher_relative_scope_preserves_trailing_newlines(self):
        for suffix, arg in (('\n', '.'), ('\n\n', '.'), ('\n', '..')):
            with self.subTest(suffix=suffix, arg=arg):
                self.state['images'] = [self.item(self.missing)]
                live = Path(self.missing + suffix)
                live.mkdir(exist_ok=True)
                cwd = live
                if arg == '..':
                    cwd = live / 'child'
                    cwd.mkdir()
                result = self.run_launcher('--check', '--clean-missing', arg, cwd=cwd)
                self.assert_kept(result)
                self.assertEqual((self.ledger.read_bytes(), self.ledger.stat().st_mode), self.before)

    def test_launcher_cdpath_does_not_corrupt_resolved_path(self):
        self.env['CDPATH'] = str(self.root)
        result = self.run_launcher('--check', 'new project')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_missing_helper_skips_diagnosis_but_fails_cleanup(self):
        for extra, expected in (([], 0), (['--clean-missing'], 1)):
            with self.subTest(extra=extra):
                result = self.run_launcher('--check', *extra, self.live, missing_helper=True)
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                self.assertFalse(any(c[0] == 'rmi' for c in self.calls))

    def test_launcher_inventory_failure_does_not_emit_result_file_traceback(self):
        self.state['raw_images'] = 'broken-json'
        result = self.run_launcher('--check', '--clean-missing', self.missing)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('Traceback', result.stderr)
        self.assertFalse(any(c[0] == 'rmi' for c in self.calls))

    def test_label_metadata_reaches_run_and_build_without_env_override(self):
        conf = Path(self.live) / '.claude-container.d'
        conf.mkdir()
        (conf / 'env').write_text('CC_PROJECT_METADATA=2\nCC_PROJECT_PATH=/wrong\nCC_PROJECT_NAME=wrong\n')
        self.state['images'] = [self.item(self.live)]
        curl = self.bin / 'curl'
        curl.write_text('''#!/bin/sh
while [ "$#" -gt 0 ]; do
  if [ "$1" = --output ]; then
    printf '%s\\n' '{"web":[],"api":[],"git":[]}' > "$2"
    exit 0
  fi
  shift
done
exit 2
''')
        curl.chmod(0o755)
        expected = {'CC_PROJECT_METADATA': '1', 'CC_PROJECT_PATH': self.live,
                    'CC_PROJECT_NAME': reference_key(self.live)}
        for extra, count in (([], 1), (['-b'], 2)):
            with self.subTest(extra=extra):
                log = self.root / 'compose-metadata'
                log.write_text('')
                result = self.run_launcher(*extra, self.live)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual([json.loads(line) for line in log.read_text().splitlines()], [expected] * count)

    def test_disappearance_check_error_keeps_failure_after_removal(self):
        self.state['failure'] = {'command': 'image exists', 'code': 125}
        result = self.run_helper(clean=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.state['images'], [])

    def test_partial_cleanup_reports_failure_and_preserves_other_images(self):
        other = str(self.root / 'other')
        protected = self.item(other, IMAGE_B)
        protected['Names'].append('localhost/shared:latest')
        self.state['images'].append(protected)
        result = self.run_helper(clean=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual([i['Id'] for i in self.state['images']], [IMAGE_B])

    def test_ledger_symlink_is_not_a_cleanup_authority(self):
        data = self.root / 'ledger-data'
        self.ledger.rename(data)
        self.ledger.symlink_to(data)
        self.assert_kept(self.run_helper(clean=True))

    def test_ledger_read_error_does_not_become_missing(self):
        if os.geteuid() == 0:
            self.skipTest('root は chmod で読み取り拒否を再現できない')
        self.ledger.chmod(0)
        try:
            (self.root / 'state').write_text(json.dumps(self.state))
            result = subprocess.run([sys.executable, '-I', str(HELPER), '--ledger', str(self.ledger),
                                     '--clean-missing'], env=self.env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((self.root / 'calls').exists())
        finally:
            self.ledger.chmod(0o600)

    def test_legacy_no_metadata_and_three_empty_metadata_labels_are_equivalent(self):
        self.state['images'] = [self.item(self.missing, labels=False)]
        self.state['images'][0]['Labels'].update({LABEL + k: '' for k in ('metadata', 'path', 'name')})
        result = self.run_helper(clean=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.state['images'], [])

    def test_direct_build_with_empty_provenance_is_not_an_orphan_warning(self):
        self.state['images'] = [self.item(self.live, labels=False)]
        self.state['images'][0]['Names'] = ['localhost/claude-test:latest']
        self.state['images'][0]['Labels'].update({LABEL + k: '' for k in ('metadata', 'path', 'name')})
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn(IMAGE_A, result.stdout)

    def test_path_recreated_before_removal_is_protected(self):
        self.state['create_path_on_inspect'] = self.missing
        self.assert_kept(self.run_helper(clean=True))

    def test_reference_created_before_removal_is_protected(self):
        self.state['late_containers'] = [{'Id': 'c' * 64, 'ImageID': IMAGE_A}]
        self.assert_kept(self.run_helper(clean=True))

    def test_directory_disappearing_after_helper_cannot_be_reported_as_success(self):
        self.state['move_directory_on_remove'] = self.live
        result = self.run_launcher('--check', '--clean-missing')
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.state['images'], [])

    def test_readonly_ledger_does_not_prevent_image_cleanup(self):
        self.ledger.chmod(0o400)
        self.before = self.ledger.read_bytes(), self.ledger.stat().st_mode
        result = self.run_helper(clean=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.state['images'], [])


class PathTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(HELPER.is_file(), 'パス診断のヘルパーは未実装')
        spec = importlib.util.spec_from_file_location('project_images', HELPER)
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def test_keys_match_existing_bash_for_byte_sensitive_names(self):
        for path in ('/', '/tmp/Kİ A', '/tmp/日本語', '/tmp/a_' + 'b' * 60,
                     os.fsdecode(b'/tmp/invalid-\xff')):
            with self.subTest(path=path):
                self.assertEqual(self.mod.project_key(path), reference_key(path))

    def test_permission_error_is_unverifiable_even_under_root(self):
        with patch.object(self.mod.os, 'lstat', side_effect=PermissionError(13, '拒否')):
            self.assertEqual(self.mod.path_state('/tmp/private/child'), 'unverifiable')

    def test_invalid_paths_are_never_missing(self):
        for path in ('', '../relative', '//server/project', '/tmp/a\n', '/tmp/a/../b'):
            with self.subTest(path=path):
                self.assertEqual(self.mod.path_state(path), 'unverifiable')


if __name__ == '__main__':
    unittest.main()
