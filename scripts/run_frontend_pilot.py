"""Run the three existing services on localhost with isolated pilot data."""
import asyncio
import argparse
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
from pilot_launcher import LOCAL_PORTS, PilotLog, load_remote_config, redact_log, startup_status, unavailable_ports

ROOT = Path(__file__).resolve().parents[1]


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


def install_stop_signal(loop, stop_event, signal_module=signal):
    previous = signal_module.getsignal(signal_module.SIGINT)
    signal_module.signal(signal_module.SIGINT, lambda *_: loop.call_soon_threadsafe(stop_event.set))
    return previous


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


async def wait_for_safe_stop(stop_event, core_web_app, generation_web_app, validation_web_app, logs, bridge_web_app=None, remote_services=(), interval=5):
    """Log count-only execution changes and accept Ctrl+C only once pilot work is idle."""
    previous_status = None
    idle_ticks = 0
    while True:
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            try:
                status = service_status(core_web_app, generation_web_app, validation_web_app, bridge_web_app)
                for label, url, token in remote_services: status['remote_' + label] = await remote_queue_status(url, token, label)
            except RuntimeError as error:
                logs.write('status', f'remote queue status unavailable: {error}')
                continue
            idle_ticks += 1
            if status != previous_status or idle_ticks >= 12:
                logs.write('status', 'active work: ' + ', '.join(f'{key}={value}' for key, value in status.items()))
                previous_status, idle_ticks = status, 0
            continue
        try:
            status = service_status(core_web_app, generation_web_app, validation_web_app, bridge_web_app)
            for label, url, token in remote_services: status['remote_' + label] = await remote_queue_status(url, token, label)
        except RuntimeError as error:
            logs.write('launcher', f'Ctrl+C did not stop the pilot: {error}. Remote queue status must be readable first.')
            stop_event.clear()
            continue
        if any(value for value in status.values()):
            logs.write('launcher', 'Ctrl+C did not stop the pilot; active work: ' + ', '.join(f'{key}={value}' for key, value in status.items()) + '. Wait for completion, then press Ctrl+C again.')
            stop_event.clear()
            continue
        logs.write('launcher', 'Ctrl+C received; stopping only services started by this pilot.')
        return


async def main(standalone_config=None, bridge_config=None, remote_config=None):
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
    local_generation = remote_config['generation_url'] is None
    local_validation = remote_config['validation_url'] is None
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
    generation_token = os.environ.get(remote_config['generation_token_env'], '') if not local_generation else token
    validation_token = os.environ.get(remote_config['validation_token_env'], '') if not local_validation else token
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
        (data / 'frontend-connection.json') if (data / 'frontend-connection.json').is_file() else None))
    apps = [(core,8190)]
    generation_web_app = generation_app(data/'generation', 'http://127.0.0.1:8188', token, coordinator_url='http://127.0.0.1:8190') if local_generation else None
    validation_web_app = validation_app(data/'validation', token, config['providers'], config['generation_sources'], config['profiles'], coordinator_url='http://127.0.0.1:8190') if local_validation else None
    if generation_web_app is not None: apps.append((generation_web_app,8189))
    if validation_web_app is not None: apps.append((validation_web_app,8191))
    if bridge_config is not None:
        os.environ[bridge_config['core_token_env']] = token
        apps.append((discord_bridge_app(ROOT/'.atelierx/discord-bridge', bridge_config), 8192))
    runners=[]
    stop_event = asyncio.Event()
    previous_signal = None
    try:
        runners = await start_apps(apps, logs)
        logs.write('launcher', startup_status(RUNTIME_INFO))
        logs.write('launcher', 'Pilot UI: http://127.0.0.1:8190/ui/')
        logs.write('launcher', 'Local token file: '+str(token_path))
        logs.write('launcher', 'Press Ctrl+C to stop only this pilot instance.')
        previous_signal = install_stop_signal(asyncio.get_running_loop(), stop_event)
        remote_services = tuple((label, url, token) for label, url, token, is_local in (('generation', generation_url, generation_token, local_generation), ('validation', validation_url, validation_token, local_validation)) if not is_local)
        await wait_for_safe_stop(stop_event, core, generation_web_app, validation_web_app, logs, apps[-1][0] if bridge_config is not None else None, remote_services)
    finally:
        if previous_signal is not None:
            signal.signal(signal.SIGINT, previous_signal)
        await stop_apps(runners)
        if runners:
            logs.write('launcher', 'Pilot services stopped.')
        logs.close()


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--standalone-config', help='Optional group-independent generation and local planner JSON')
    parser.add_argument('--discord-bridge-config', help='Optional Discord delivery adapter JSON; requires standalone config')
    parser.add_argument('--launcher-config', help='Optional private local/remote-service launcher JSON; remote services are connected but never started or stopped')
    args = parser.parse_args()
    if args.discord_bridge_config and not args.standalone_config:
        parser.error('--discord-bridge-config requires --standalone-config')
    load = lambda path: json.loads(Path(path).read_text(encoding='utf-8')) if path else None
    try:
        remote = load_remote_config(args.launcher_config) if args.launcher_config else None
        asyncio.run(main(load(args.standalone_config), load(args.discord_bridge_config), remote))
    except (RuntimeError, ValueError, FileNotFoundError) as error:
        print(f'[launcher] {redact_log(error)}', file=sys.stderr, flush=True)
        raise SystemExit(1)
