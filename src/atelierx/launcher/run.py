"""Run the existing services on localhost with isolated pilot data."""
import asyncio
import argparse
from datetime import datetime, timezone
import inspect
import json
import os
from pathlib import Path
import secrets
import signal
import sys
import webbrowser

import aiohttp
from aiohttp import web
from atelierx.core import CORE, create_app as core_app
from atelierx.generation import SERVICE as GENERATION_SERVICE, TERMINAL as GENERATION_TERMINAL, create_app as generation_app
from atelierx.validation import SERVICE as VALIDATION_SERVICE, TERMINAL as VALIDATION_TERMINAL, create_app as validation_app
from atelierx.discord_bridge import BRIDGE, TERMINAL as BRIDGE_TERMINAL, create_app as discord_bridge_app
from atelierx.runtime_info import RUNTIME_INFO
from .helpers import PilotLog, load_remote_config, redact_log, startup_status, unavailable_ports

ROOT = Path(__file__).resolve().parents[3]
CONTROL_DIR = ROOT / '.atelierx' / 'control'
CONTROL_URL = 'http://127.0.0.1:8180'


async def start_apps(apps, logs, runner_factory=web.AppRunner, site_factory=web.TCPSite):
    """Start only the supplied pilot apps; used with fakes by launcher tests."""
    runners = []
    names = {8190: 'core', 8189: 'generation', 8191: 'validation', 8192: 'discord'}
    try:
        for app, port in apps:
            runner = runner_factory(app, access_log=None)
            await runner.setup()
            runners.append(runner)
            await site_factory(runner, '127.0.0.1', port).start()
            logs.write(names.get(port, 'service'), f'listening on 127.0.0.1:{port}')
        return runners
    except BaseException:
        for runner in reversed(runners):
            await runner.cleanup()
        raise


async def stop_apps(runners):
    for runner in reversed(runners):
        await runner.cleanup()


def active_pilot_work(core):
    """Return count-only local state, never request bodies, URLs, or credentials."""
    pending = len(core.store.pending())
    standalone = core.store.db.execute("SELECT count(*) FROM standalone_jobs WHERE state NOT IN ('completed','failed')").fetchone()[0]
    plans = core.plans.db.execute("SELECT count(*) FROM production_plans WHERE state NOT IN ('draft','completed','failed','cancelled','insufficient_images')").fetchone()[0]
    postprocess = core.store.db.execute("SELECT count(*) FROM postprocess_jobs WHERE state NOT IN ('completed','failed','cancelled')").fetchone()[0]
    validation = core.store.db.execute("SELECT count(*) FROM validation_runs WHERE state NOT IN ('completed','failed','cancelled')").fetchone()[0]
    group_runs = sum(run.get('state') not in {'completed', 'failed', 'cancelled'} for run in core.groups.runs())
    batches = sum(batch.get('state') not in {'completed', 'failed', 'cancelled', 'insufficient_images'} for batch in core.batches.list())
    gpu = core.gpu.state()
    return {'core_tasks': pending, 'standalone': standalone, 'plans': plans, 'postprocess': postprocess,
            'validation_runs': validation, 'group_runs': group_runs, 'batches': batches,
            'gpu_active': bool(gpu.get('owner') or gpu.get('waiting'))}


def service_status(core_web_app, generation_web_app, validation_web_app, bridge_web_app=None):
    status = active_pilot_work(core_web_app[CORE])
    if generation_web_app is not None:
        generation = generation_web_app[GENERATION_SERVICE]
        status['generation'] = sum(job.get('state') not in GENERATION_TERMINAL for job in generation.jobs.values())
    if validation_web_app is not None:
        validation = validation_web_app[VALIDATION_SERVICE]
        status['validation'] = sum(job.get('state') not in VALIDATION_TERMINAL for job in validation.jobs.values())
    if bridge_web_app is not None:
        bridge = bridge_web_app[BRIDGE]
        status['discord_delivery'] = sum(record.get('state') not in BRIDGE_TERMINAL or record.get('delivery') == 'pending' for record in bridge.records.values())
    return status


def stop_signals(signal_module=signal):
    return [signal_module.SIGINT] + ([signal_module.SIGBREAK] if hasattr(signal_module, 'SIGBREAK') else [])


def install_stop_signal(loop, stop_event, signal_module=signal):
    """Route SIGINT and Windows SIGBREAK (Ctrl+Break / CTRL_BREAK_EVENT) to the same safe-stop path."""
    previous = {}
    for number in stop_signals(signal_module):
        previous[number] = signal_module.getsignal(number)
        signal_module.signal(number, lambda *_: loop.call_soon_threadsafe(stop_event.set))
    return previous


def restore_stop_signal(previous, signal_module=signal):
    for number, handler in previous.items():
        signal_module.signal(number, handler)


class StopRequestFiles:
    """File-based stop request from the local control panel; checked on the status interval."""
    def __init__(self, directory):
        self.directory = Path(directory)
        self.request = self.directory / 'bundle-stop-request.json'
        self.response = self.directory / 'bundle-stop-response.json'

    def discard_stale(self):
        self.request.unlink(missing_ok=True)

    def take(self):
        """Return (found, request_id, valid); the request file is always consumed."""
        try:
            raw = self.request.read_text(encoding='utf-8')
        except OSError:
            return False, None, False
        self.request.unlink(missing_ok=True)
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            return True, None, False
        request_id = body.get('request_id') if isinstance(body, dict) else None
        return True, request_id if isinstance(request_id, str) else None, isinstance(request_id, str)

    def respond(self, request_id, accepted, active_work, reason=None):
        self.directory.mkdir(parents=True, exist_ok=True)
        body = {'request_id': request_id, 'accepted': accepted, 'active_work': active_work,
                'at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
        if reason:
            body['reason'] = reason
        temporary = self.response.with_suffix('.tmp')
        temporary.write_text(json.dumps(body, ensure_ascii=False), encoding='utf-8')
        os.replace(temporary, self.response)


async def remote_queue_status(url, token, label):
    headers = {"Authorization": "Bearer " + token}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            offset, total, active = 0, None, 0
            while total is None or offset < total:
                async with session.get(url + f'/v1/queue?limit=200&offset={offset}', headers=headers, allow_redirects=False) as response:
                    if response.status != 200:
                        raise RuntimeError(f'{label} queue read returned HTTP {response.status}')
                    body = await response.json()
                page_active, page_total = remote_queue_count(body, label, offset)
                if total is None:
                    total = page_total
                    if total > 10_000:
                        raise RuntimeError(f'{label} queue exceeds safe read limit')
                elif page_total != total:
                    raise RuntimeError(f'{label} queue total changed during read')
                active += page_active
                page_size = len(body['items'])
                if page_size == 0 and offset < total:
                    raise RuntimeError(f'{label} queue pagination did not advance')
                offset += page_size
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as error:
        raise RuntimeError(f'{label} queue read failed: {type(error).__name__}') from error
    return active


def remote_queue_count(body, label, offset=0):
    if (not isinstance(body, dict) or not isinstance(body.get('items'), list) or type(body.get('total')) is not int or body['total'] < offset or
            any(not isinstance(item, dict) or not isinstance(item.get('state'), str) for item in body['items'])):
        raise RuntimeError(f'{label} queue response is malformed')
    return sum(item['state'] not in {'completed', 'failed', 'cancelled'} for item in body['items']), body['total']


def core_connection_options(generation_token, core_config, validation_token, gpu, standalone_config, frontend_connection_path):
    return {"generation_token": generation_token, "validation_config": core_config, "validation_token": validation_token,
            "gpu_config": gpu, "standalone_config": standalone_config, "frontend_connection_path": frontend_connection_path}


def operations_status_option(create_app, control_dir=CONTROL_DIR, url=CONTROL_URL):
    """Pass the control panel lookup only to a Core build that supports it."""
    try:
        parameters = inspect.signature(create_app).parameters
    except (TypeError, ValueError):
        return {}
    if 'operations_status' not in parameters:
        return {}
    return {'operations_status': {'url': url, 'token_file': str(Path(control_dir) / 'token.txt')}}


async def wait_for_safe_stop(stop_event, core_web_app, generation_web_app, validation_web_app, logs, bridge_web_app=None, remote_services=(), interval=5, stop_requests=None):
    """Log count-only execution changes and stop (Ctrl+C / Ctrl+Break / panel request) only once pilot work is idle."""
    async def current_status():
        status = service_status(core_web_app, generation_web_app, validation_web_app, bridge_web_app)
        for label, url, token in remote_services:
            status['remote_' + label] = await remote_queue_status(url, token, label)
        return status

    def summary(status):
        return ', '.join(f'{key}={value}' for key, value in status.items())

    previous_status = None
    idle_ticks = 0
    while True:
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            found, request_id, valid = stop_requests.take() if stop_requests is not None else (False, None, False)
            if found and not valid:
                stop_requests.respond(request_id, False, {}, 'malformed stop request')
                logs.write('launcher', 'Control panel stop request was malformed; services keep running.')
                found = False
            try:
                status = await current_status()
            except RuntimeError as error:
                logs.write('status', f'remote queue status unavailable: {error}')
                if found:
                    stop_requests.respond(request_id, False, {}, 'remote queue status unavailable')
                    logs.write('launcher', 'Control panel stop request refused; remote queue status must be readable first.')
                continue
            if found:
                accepted = not any(status.values())
                stop_requests.respond(request_id, accepted, status)
                if accepted:
                    logs.write('launcher', 'Control panel stop request accepted; stopping only services started by this pilot.')
                    return
                logs.write('launcher', 'Control panel stop request refused; active work: ' + summary(status) + '.')
            idle_ticks += 1
            if status != previous_status or idle_ticks >= 12:
                logs.write('status', 'active work: ' + summary(status))
                previous_status, idle_ticks = status, 0
            continue
        try:
            status = await current_status()
        except RuntimeError as error:
            logs.write('launcher', f'Ctrl+C did not stop the pilot: {error}. Remote queue status must be readable first.')
            stop_event.clear()
            continue
        if any(value for value in status.values()):
            logs.write('launcher', 'Ctrl+C did not stop the pilot; active work: ' + summary(status) + '. Wait for completion, then press Ctrl+C again.')
            stop_event.clear()
            continue
        logs.write('launcher', 'Ctrl+C received; stopping only services started by this pilot.')
        return


async def run(standalone_config=None, bridge_config=None, remote_config=None, start_generation=True, start_validation=True, control_dir=CONTROL_DIR):
    data = ROOT / '.atelierx' / 'pilot'
    data.mkdir(parents=True, exist_ok=True)
    logs = PilotLog(data)
    remote_config = remote_config or {"mode": "local", "generation_url": None, "validation_url": None,
                                      "generation_token_env": None, "validation_token_env": None}
    if remote_config['mode'] == 'remote-ui':
        logs.write('remote', startup_status(RUNTIME_INFO))
        logs.write('remote', f"Configured UI target: {remote_config['ui_url']}")
        opened = webbrowser.open(remote_config['ui_url'])
        logs.write('remote', f"Opened existing UI in the default browser: {opened}.")
        logs.write('remote', 'This mode does not configure, health-check, authenticate to, or control a remote backend.')
        logs.close()
        return
    remote_generation = remote_config['generation_url'] is not None
    remote_validation = remote_config['validation_url'] is not None
    local_generation = not remote_generation and start_generation
    local_validation = not remote_validation and start_validation
    ports = (8190,) + ((8189,) if local_generation else ()) + ((8191,) if local_validation else ()) + ((8192,) if bridge_config is not None else ())
    blocked = unavailable_ports(ports)
    if blocked:
        logs.write('launcher', 'Pilot was not started; required local ports are already in use: ' + ', '.join(map(str, blocked)))
        logs.write('launcher', 'No service resources were created and existing processes were left untouched.')
        logs.close()
        raise RuntimeError('required pilot ports are in use')
    token_path = data / 'token.txt'
    if not token_path.exists():
        token_path.write_text(secrets.token_urlsafe(32), encoding='utf-8')
    token = token_path.read_text(encoding='utf-8').strip()
    config = json.loads((ROOT / '.atelierx/validation-coordinated-config.json').read_text(encoding='utf-8'))
    generation_url = remote_config['generation_url'] or 'http://127.0.0.1:8189'
    validation_url = remote_config['validation_url'] or 'http://127.0.0.1:8191'
    generation_token = os.environ.get(remote_config['generation_token_env'], '') if remote_generation else token
    validation_token = os.environ.get(remote_config['validation_token_env'], '') if remote_validation else token
    if not generation_token or not validation_token:
        raise ValueError('configured remote service token environment variable is missing or empty')
    for source in config.get('generation_sources', {}).values():
        source['token'] = generation_token
        source['url'] = generation_url
    config['coordinator_url'] = 'http://127.0.0.1:8190'
    # Only public provider configuration belongs to Core.
    core_config = dict(config.get('core', {}), url=validation_url, profiles=config['profiles'],
        providers={key: {field: value for field, value in provider.items() if field not in {'api_key','api_key_env'}}
                   for key, provider in config['providers'].items()})
    for key, provider in core_config['providers'].items():
        provider['provider_id'] = key
    gpu = json.loads((ROOT / '.atelierx/gpu-config.json').read_text(encoding='utf-8'))
    core = core_app(data/'core.sqlite3', generation_url, token, **core_connection_options(
        generation_token, core_config, validation_token, gpu, standalone_config,
        (data / 'frontend-connection.json') if (data / 'frontend-connection.json').is_file() else None),
        **operations_status_option(core_app, control_dir))
    apps = [(core,8190)]
    generation_web_app = generation_app(data/'generation', 'http://127.0.0.1:8188', token, coordinator_url='http://127.0.0.1:8190') if local_generation else None
    validation_web_app = validation_app(data/'validation', token, config['providers'], config['generation_sources'], config['profiles'], coordinator_url='http://127.0.0.1:8190') if local_validation else None
    if generation_web_app is not None: apps.append((generation_web_app,8189))
    if validation_web_app is not None: apps.append((validation_web_app,8191))
    if bridge_config is not None:
        os.environ[bridge_config['core_token_env']] = token
        apps.append((discord_bridge_app(ROOT/'.atelierx/discord-bridge', bridge_config), 8192))
    stop_requests = StopRequestFiles(control_dir)
    stop_requests.discard_stale()
    runners=[]
    stop_event = asyncio.Event()
    previous_signals = {}
    try:
        runners = await start_apps(apps, logs)
        logs.write('launcher', startup_status(RUNTIME_INFO))
        if not local_generation and not remote_generation:
            logs.write('launcher', 'Local Generation was not started by option.')
        if not local_validation and not remote_validation:
            logs.write('launcher', 'Local Validation was not started by option.')
        logs.write('launcher', 'Pilot UI: http://127.0.0.1:8190/ui/')
        logs.write('launcher', 'Local token file: '+str(token_path))
        logs.write('launcher', 'Press Ctrl+C to stop only this pilot instance.')
        previous_signals = install_stop_signal(asyncio.get_running_loop(), stop_event)
        remote_services = tuple((label, url, token) for label, url, token, is_remote in (('generation', generation_url, generation_token, remote_generation), ('validation', validation_url, validation_token, remote_validation)) if is_remote)
        await wait_for_safe_stop(stop_event, core, generation_web_app, validation_web_app, logs, apps[-1][0] if bridge_config is not None else None, remote_services, stop_requests=stop_requests)
    finally:
        restore_stop_signal(previous_signals)
        await stop_apps(runners)
        if runners:
            logs.write('launcher', 'Pilot services stopped.')
        logs.close()


def main(argv=None):
    parser = argparse.ArgumentParser(prog='python -m atelierx.launcher', description=__doc__)
    parser.add_argument('--standalone-config', help='Optional group-independent generation and local planner JSON')
    parser.add_argument('--discord-bridge-config', help='Optional Discord delivery adapter JSON; requires standalone config')
    parser.add_argument('--launcher-config', help='Optional private local/remote-service launcher JSON; remote services are connected but never started or stopped')
    parser.add_argument('--no-generation', action='store_true', help='Do not start local Generation; Core still points at 127.0.0.1:8189')
    parser.add_argument('--no-validation', action='store_true', help='Do not start local Validation; Core still points at 127.0.0.1:8191')
    parser.add_argument('--control-dir', default=str(CONTROL_DIR), help='Control panel data folder checked for stop requests (default: .atelierx/control)')
    args = parser.parse_args(argv)
    if args.discord_bridge_config and not args.standalone_config:
        parser.error('--discord-bridge-config requires --standalone-config')
    load = lambda path: json.loads(Path(path).read_text(encoding='utf-8')) if path else None
    try:
        remote = load_remote_config(args.launcher_config) if args.launcher_config else None
        asyncio.run(run(load(args.standalone_config), load(args.discord_bridge_config), remote,
                        start_generation=not args.no_generation, start_validation=not args.no_validation, control_dir=Path(args.control_dir)))
    except (RuntimeError, ValueError, FileNotFoundError) as error:
        print(f'[launcher] {redact_log(error)}', file=sys.stderr, flush=True)
        return 1
    return 0
