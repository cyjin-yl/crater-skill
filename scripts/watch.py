"""Observe one owned Crater job until a terminal status or deadline.

Exit codes:
  0: platform success terminal status (Completed/Succeeded) — verify artifacts next
  1: platform failure/stopped/freed terminal status (Failed/Aborted/Terminated/Cancelled/Evicted/Deleted/Freed)
  2: observation deadline reached while job is still active or unreachable
  3: authentication required (HTTP 401, expired token, or missing local credentials)
  4: CLI missing/incompatible, response schema/identity mismatch, or unknown status
"""
import argparse
from datetime import datetime, timezone
import json
import re
import subprocess
import time


ACTIVE = {'Prequeue', 'Pending', 'Running', 'Restarting', 'Completing', 'Terminating', 'Aborting'}
SUCCESS = {'Completed', 'Succeeded'}
FAILURE = {'Failed', 'Aborted', 'Terminated', 'Cancelled', 'Canceled', 'Evicted', 'Deleted', 'Freed'}
AUTH = re.compile(
    r'\b(?:HTTP(?: status)?\s*|status(?: code)?[ :=]+)401\b|'
    r'token (?:has invalid claims|is expired)|unauthori[sz]ed|ERR_AUTH|'
    r'no token saved for these credentials|no active credentials found|'
    r'未保存\s*token|未找到当前激活的账号',
    re.I,
)


def parse_path(value):
    if value == '':
        return ()  # Empty JSON Pointer selects the whole document.
    if value.startswith('/'):
        if re.search(r'~(?![01])', value):
            raise argparse.ArgumentTypeError('invalid JSON Pointer escape')
        return tuple(part.replace('~1', '/').replace('~0', '~') for part in value[1:].split('/'))
    parts = tuple(value.split('.'))
    if not all(parts):
        raise argparse.ArgumentTypeError('empty component in dotted path')
    path = []
    for part in parts:
        indexed = re.fullmatch(r'([^\[\]]*)((?:\[(?:0|[1-9][0-9]*)\])+)', part)
        if indexed is None:
            path.append(part)
        else:
            if indexed[1]:
                path.append(indexed[1])
            path.extend(re.findall(r'\[([0-9]+)\]', indexed[2]))
    return tuple(path)


def select(value, path):
    for part in path:
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and re.fullmatch(r'0|[1-9][0-9]*', part) and len(part) <= 18:
            index = int(part)
            if index >= len(value):
                return None
            value = value[index]
        else:
            return None
    return value


def decode(raw):
    try:
        return json.loads(raw)
    except (ValueError, RecursionError):
        return None


ERROR_CODES = ('status', 'statusCode', 'httpStatus', 'code')


def error_fields(value):
    return isinstance(value, dict) and (
        value.get('status') == 'ERROR'
        or bool(value.get('error') or value.get('errors'))
        or ('category' in value and 'code' in value)
        or any(value.get(key) in (401, '401') for key in ERROR_CODES)
    )


def auth_error(value):
    if isinstance(value, str):
        return bool(AUTH.search(value))
    if isinstance(value, list):
        return any(auth_error(item) for item in value)
    if isinstance(value, dict):
        for key in ERROR_CODES:
            field = value.get(key)
            if field in (401, '401') or auth_error(field):
                return True
        return any(
            auth_error(value[key])
            for key in ('category', 'message', 'error', 'errors', 'context')
            if key in value
        )
    return False


def stream_auth(raw, parsed):
    if parsed is None:
        return auth_error(raw.decode(errors='replace'))
    return error_fields(parsed) and auth_error(parsed)


def observe(
    job,
    owner,
    timeout,
    record_path=None,
    job_key=('jobName',),
    owner_key=('username',),
    status_key=('status',),
    podgroup_key=('podGroupPhase',),
):
    try:
        call = subprocess.run(
            ['crater', 'job', 'get', job, '--json', '--no-interactive'],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=timeout,
            check=False,
            shell=False,
        )
    except FileNotFoundError:
        return 'cli-missing', None, None
    except (subprocess.TimeoutExpired, OSError):
        return 'read-failed', None, None

    envelope = decode(call.stdout)
    diagnostic = decode(call.stderr)
    if stream_auth(call.stdout, envelope) or stream_auth(call.stderr, diagnostic):
        return 'auth-required', None, None
    for reply in (diagnostic, envelope):
        if isinstance(reply, dict) and (
            reply.get('category') == 'usage_error'
            or reply.get('code') in ('ERR_UNKNOWN_COMMAND', 'ERR_API_VERSION_MISMATCH')
        ):
            return 'cli-incompatible', None, None
    if call.returncode and re.search(
        rb'(?im)^(?:error:\s*)?(?:unknown (?:command|flag|option)\b|unrecognized arguments:)',
        call.stderr,
    ):
        return 'cli-incompatible', None, None
    if call.returncode or error_fields(envelope) or error_fields(diagnostic):
        return 'read-failed', None, None

    if record_path is None:
        if not isinstance(envelope, dict) or envelope.get('status') != 'OK':
            return 'schema-mismatch', None, None
        record_path = ('data', 'job')
    record = select(envelope, record_path)
    if not isinstance(record, dict):
        return 'schema-mismatch', None, None

    name, username, status = (select(record, path) for path in (job_key, owner_key, status_key))
    if any(not isinstance(field, str) or not field.strip() for field in (name, username, status)):
        return 'schema-mismatch', None, None
    if name != job or username != owner:
        return 'identity-mismatch', None, None

    podgroup_phase = select(record, podgroup_key) if podgroup_key else None
    if not isinstance(podgroup_phase, str) or not podgroup_phase.strip():
        podgroup_phase = None

    if status in ACTIVE | SUCCESS | FAILURE:
        return 'platform-status', status, podgroup_phase
    return 'unknown-status', None, None


def emit(event, status=None, podgroup_phase=None):
    record = {'time': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'event': event}
    if status:
        record['status'] = status
    if podgroup_phase and status == 'Pending':
        record['podGroupPhase'] = podgroup_phase
    print(json.dumps(record), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', required=True, help='platform jobName from the creation record')
    parser.add_argument('--owner', required=True, help='expected username in the private record')
    parser.add_argument('--minutes', required=True, type=int, help='observation deadline in minutes')
    parser.add_argument('--interval', default=60, type=int, help='seconds between reads (default 60)')
    parser.add_argument(
        '--record-path',
        type=parse_path,
        help='path from JSON root (default data.job in OK envelope)',
    )
    parser.add_argument('--job-key', type=parse_path, default=('jobName',), help='path from record to job name')
    parser.add_argument('--owner-key', type=parse_path, default=('username',), help='path from record to owner')
    parser.add_argument('--status-key', type=parse_path, default=('status',), help='path from record to status')
    parser.add_argument(
        '--podgroup-key',
        type=parse_path,
        default=('podGroupPhase',),
        help='optional path from record to Volcano podGroupPhase',
    )
    args = parser.parse_args()
    if (
        args.minutes < 1
        or args.interval < 1
        or not args.job.strip()
        or args.job.startswith('-')
        or '\x00' in args.job
        or not args.owner.strip()
    ):
        parser.error('use a platform job name and positive time limits')

    deadline = time.monotonic() + args.minutes * 60
    while (remaining := deadline - time.monotonic()) > 0:
        event, status, podgroup_phase = observe(
            args.job,
            args.owner,
            min(30, remaining),
            args.record_path,
            args.job_key,
            args.owner_key,
            args.status_key,
            args.podgroup_key,
        )
        emit(event, status, podgroup_phase)
        if status in SUCCESS:
            return 0
        if status in FAILURE:
            return 1
        if event == 'auth-required':
            return 3
        if event in {'cli-missing', 'cli-incompatible', 'schema-mismatch', 'identity-mismatch', 'unknown-status'}:
            return 4
        time.sleep(max(0, min(args.interval, deadline - time.monotonic())))
    emit('observation-deadline')
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
