"""Offline regressions for Crater watcher response handling."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch


script = Path(__file__).resolve().parents[1] / 'scripts/watch.py'
spec = importlib.util.spec_from_file_location('crater_watch', script)
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)


def response(status, name='demo-job', owner='tester', podgroup_phase=None):
    job = {'jobName': name, 'username': owner, 'status': status}
    if podgroup_phase is not None:
        job['podGroupPhase'] = podgroup_phase
    return subprocess.CompletedProcess([], 0, json.dumps({'status': 'OK', 'data': {'job': job}}).encode(), b'')


class WatchTests(unittest.TestCase):
    def run_sequence(self, calls, clock=None, options=()):
        output = io.StringIO()
        clock = clock or [0] * (4 * len(calls) + 1)
        with patch.object(watch.subprocess, 'run', side_effect=calls) as invoke, \
             patch.object(watch.time, 'monotonic', side_effect=clock), \
             patch.object(watch.time, 'sleep'), \
             patch('sys.argv', ['watch', '--job', 'demo-job', '--owner', 'tester', '--minutes', '1', *options]), \
             redirect_stdout(output):
            code = watch.main()
        for call in invoke.call_args_list:
            self.assertEqual(call.args[0], ['crater', 'job', 'get', 'demo-job', '--json', '--no-interactive'])
            self.assertFalse(call.kwargs['shell'])
            self.assertEqual(call.kwargs['stdin'], subprocess.DEVNULL)
        records = [json.loads(line) for line in output.getvalue().splitlines()]
        return code, records

    def test_temporary_read_failures_can_recover(self):
        calls = [
            response('Pending', podgroup_phase='Inqueue'),
            subprocess.TimeoutExpired('crater', 30),
            subprocess.CompletedProcess([], 1, b'', b'connection refused'),
            response('Running'),
            response('Completed'),
        ]
        code, records = self.run_sequence(calls)
        self.assertEqual(code, 0)
        self.assertEqual(
            [(r['event'], r.get('status'), r.get('podGroupPhase')) for r in records],
            [
                ('platform-status', 'Pending', 'Inqueue'),
                ('read-failed', None, None),
                ('read-failed', None, None),
                ('platform-status', 'Running', None),
                ('platform-status', 'Completed', None),
            ],
        )

    def test_expired_or_missing_local_auth_in_either_stream(self):
        for call in [
            subprocess.CompletedProcess([], 1, b'{"status":"ERROR","code":"ERR_AUTH"}', b''),
            subprocess.CompletedProcess([], 1, b'', b'HTTP 401'),
            subprocess.CompletedProcess(
                [],
                4,
                b'',
                b'{"category":"api_error","code":"ERR_UNAUTHORIZED_401","message":"token has invalid claims"}',
            ),
            subprocess.CompletedProcess([], 0, b'{"errors":[{"status":"401","message":"private"}]}', b''),
            subprocess.CompletedProcess(
                [],
                2,
                b'',
                b'{"category":"usage_error","code":"ERR_NOT_FOUND",'
                b'"message":"no token saved for these credentials; please log in again"}',
            ),
            subprocess.CompletedProcess(
                [],
                2,
                b'',
                b'{"category":"usage_error","code":"ERR_NOT_FOUND","message":"no active credentials found"}',
            ),
        ]:
            with self.subTest(call=call):
                code, records = self.run_sequence([call])
                self.assertEqual((code, [(r['event'], r.get('status')) for r in records]), (3, [('auth-required', None)]))

    def test_success_with_native_error_cannot_complete(self):
        call = response('Completed')
        call.stderr = b'{"category":"api_error","code":"ERR_API","message":"private"}'
        code, records = self.run_sequence([call, response('Failed')])
        self.assertEqual(
            (code, [(r['event'], r.get('status')) for r in records]),
            (1, [('read-failed', None), ('platform-status', 'Failed')]),
        )

    def test_removed_command_flag_or_api_stops_for_rediscovery(self):
        for stdout, stderr in [
            (b'', b'{"category":"usage_error","code":"ERR_UNKNOWN_COMMAND"}'),
            (b'', b'{"category":"usage_error","code":"ERR_INVALID_FLAG_VALUE","message":"unknown flag: --json"}'),
            (b'{"status":"ERROR","code":"ERR_API_VERSION_MISMATCH"}', b''),
            (b'', b'Error: unknown command "get"'),
        ]:
            with self.subTest(stdout=stdout, stderr=stderr):
                call = subprocess.CompletedProcess([], 2, stdout, stderr)
                code, records = self.run_sequence([call])
                self.assertEqual(
                    (code, [(r['event'], r.get('status')) for r in records]),
                    (4, [('cli-incompatible', None)]),
                )

    def test_zero_exit_schema_mismatch_stops(self):
        for body in [
            b'not json',
            b'{}',
            b'{"status":"OK","data":{}}',
            b'{"status":"OK","data":{"job":{"jobName":"demo-job","status":"Completed"}}}',
        ]:
            with self.subTest(body=body):
                call = subprocess.CompletedProcess([], 0, body, b'')
                code, records = self.run_sequence([call])
                self.assertEqual(
                    (code, [(r['event'], r.get('status')) for r in records]),
                    (4, [('schema-mismatch', None)]),
                )

    def test_explicit_selectors_accept_only_the_selected_record(self):
        payload = {'results': [{'job/name': 'demo-job', 'user': {'id': 'tester'}, 'phase': 'Completed'}]}
        call = subprocess.CompletedProcess([], 0, json.dumps(payload).encode(), b'')
        options = (
            '--record-path', '/results/0',
            '--job-key', '/job~1name',
            '--owner-key', 'user.id',
            '--status-key', 'phase',
        )
        code, records = self.run_sequence([call], options=options)
        self.assertEqual((code, [(r['event'], r.get('status')) for r in records]), (0, [('platform-status', 'Completed')]))

        code, records = self.run_sequence([call], options=(*options, '--record-path', '/results/1'))
        self.assertEqual((code, [(r['event'], r.get('status')) for r in records]), (4, [('schema-mismatch', None)]))

    def test_bracket_index_keeps_owner_binding(self):
        payload = {
            'items': [
                {'resourceId': 'demo-job', 'createdBy': {'user': 'tester'}, 'life': {'phase': 'Completed'}},
                {'resourceId': 'demo-job', 'createdBy': {'user': 'other'}, 'life': {'phase': 'Completed'}},
            ]
        }
        call = subprocess.CompletedProcess([], 0, json.dumps(payload).encode(), b'')
        options = ('--job-key', 'resourceId', '--owner-key', 'createdBy.user', '--status-key', 'life.phase')
        code, records = self.run_sequence([call], options=(*options, '--record-path', 'items[0]'))
        self.assertEqual((code, [(r['event'], r.get('status')) for r in records]), (0, [('platform-status', 'Completed')]))

        code, records = self.run_sequence([call], options=(*options, '--record-path', 'items[1]'))
        self.assertEqual((code, [(r['event'], r.get('status')) for r in records]), (4, [('identity-mismatch', None)]))

    def test_foreign_or_unknown_record_cannot_finish_the_job(self):
        for record, event in [
            (response('Completed', name='other'), 'identity-mismatch'),
            (response('Completed', owner='other'), 'identity-mismatch'),
            (response('NewPhase'), 'unknown-status'),
        ]:
            with self.subTest(event=event):
                code, records = self.run_sequence([record])
                self.assertEqual((code, [(r['event'], r.get('status')) for r in records]), (4, [(event, None)]))

    def test_platform_failure_freed_and_observation_deadline_are_distinct(self):
        for terminal in ('Failed', 'Freed', 'Deleted', 'Aborted', 'Terminated'):
            with self.subTest(terminal=terminal):
                code, records = self.run_sequence([response(terminal)])
                self.assertEqual((code, [(r['event'], r.get('status')) for r in records]), (1, [('platform-status', terminal)]))
        code, records = self.run_sequence([response('Running')], [0, 0, 59, 60])
        self.assertEqual(
            (code, [(r['event'], r.get('status')) for r in records]),
            (2, [('platform-status', 'Running'), ('observation-deadline', None)]),
        )


if __name__ == '__main__':
    unittest.main()
