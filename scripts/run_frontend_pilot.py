"""Run the three existing services on localhost with isolated pilot data."""
import asyncio
import argparse
import json
import os
from pathlib import Path
import secrets

from aiohttp import web
from atelierx.core import CORE, create_app as core_app
from atelierx.generation import create_app as generation_app
from atelierx.validation import create_app as validation_app
from atelierx.discord_bridge import create_app as discord_bridge_app

ROOT = Path(__file__).resolve().parents[1]


async def main(standalone_config=None, bridge_config=None):
    data = ROOT / '.atelierx' / 'pilot'
    data.mkdir(parents=True, exist_ok=True)
    token_path = data / 'token.txt'
    if not token_path.exists():
        token_path.write_text(secrets.token_urlsafe(32), encoding='utf-8')
    token = token_path.read_text(encoding='utf-8').strip()
    config = json.loads((ROOT / '.atelierx/validation-coordinated-config.json').read_text(encoding='utf-8'))
    for source in config.get('generation_sources', {}).values():
        source['token'] = token
        source['url'] = 'http://127.0.0.1:8189'
    config['coordinator_url'] = 'http://127.0.0.1:8190'
    # Only public provider configuration belongs to Core.
    core_config = dict(config.get('core', {}), url='http://127.0.0.1:8191', profiles=config['profiles'],
        providers={key: {field: value for field, value in provider.items() if field not in {'api_key','api_key_env'}}
                   for key, provider in config['providers'].items()})
    for key, provider in core_config['providers'].items():
        provider['provider_id'] = key
    gpu = json.loads((ROOT / '.atelierx/gpu-config.json').read_text(encoding='utf-8'))
    core = core_app(data/'core.sqlite3', 'http://127.0.0.1:8189', token,
                    validation_config=core_config, validation_token=token, gpu_config=gpu,
                    standalone_config=standalone_config,
                    frontend_connection_path=(data / 'frontend-connection.json') if (data / 'frontend-connection.json').is_file() else None)
    apps = [(core,8190),
            (generation_app(data/'generation', 'http://127.0.0.1:8188', token,
                            coordinator_url='http://127.0.0.1:8190'),8189),
            (validation_app(data/'validation', token, config['providers'], config['generation_sources'], config['profiles'],
                            coordinator_url='http://127.0.0.1:8190'),8191)]
    if bridge_config is not None:
        os.environ[bridge_config['core_token_env']] = token
        apps.append((discord_bridge_app(ROOT/'.atelierx/discord-bridge', bridge_config), 8192))
    runners=[]
    try:
        for app, port in apps:
            runner=web.AppRunner(app); await runner.setup();runners.append(runner)
            await web.TCPSite(runner,'127.0.0.1',port).start()
        print('AtelierX pilot: http://127.0.0.1:8190/ui/',flush=True)
        print('Local token file: '+str(token_path),flush=True)
        await asyncio.Event().wait()
    finally:
        for runner in reversed(runners):await runner.cleanup()


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--standalone-config', help='Optional group-independent generation and local planner JSON')
    parser.add_argument('--discord-bridge-config', help='Optional Discord delivery adapter JSON; requires standalone config')
    args = parser.parse_args()
    if args.discord_bridge_config and not args.standalone_config:
        parser.error('--discord-bridge-config requires --standalone-config')
    load = lambda path: json.loads(Path(path).read_text(encoding='utf-8')) if path else None
    asyncio.run(main(load(args.standalone_config), load(args.discord_bridge_config)))
