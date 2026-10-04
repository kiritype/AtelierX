"""Start the AtelierX server: ``python -m atelierx [--dev] [--port N] [--root PATH]``."""

import argparse
import socket

import uvicorn

from .api.app import build_app
from .core.paths import AppPaths


def free_port(preferred):
    with socket.socket() as sock:
        try:
            sock.bind(('127.0.0.1', preferred))
            return preferred
        except OSError:
            sock.bind(('127.0.0.1', 0))
            return sock.getsockname()[1]


def main():
    parser = argparse.ArgumentParser(prog='atelierx')
    parser.add_argument('--dev', action='store_true', help='allow the Vite dev server origin')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--root', help='app folder (default: the repository in development)')
    args = parser.parse_args()
    paths = AppPaths.for_dev(args.root)
    port = args.port if args.dev else free_port(args.port)
    print(f'AtelierX on http://127.0.0.1:{port}  (app folder: {paths.root})')
    uvicorn.run(build_app(paths, dev=args.dev), host='127.0.0.1', port=port, log_level='warning')


if __name__ == '__main__':
    main()
