"""Portable desktop entry point; --headless supports packaged API smoke checks."""

import argparse
import logging
import multiprocessing
import os
import signal
import socket
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn

from .api.app import build_app
from .core.fsutil import read_json, write_json
from .core.paths import AppPaths

logger = logging.getLogger(__name__)


def bind_loopback(port=0):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(('127.0.0.1', port))
        sock.listen(128)
    except BaseException:
        sock.close()
        raise
    return sock


def unblock_bundle(folder):
    """Remove the "downloaded from the internet" mark (Zone.Identifier) from the bundled DLLs; returns how many.

    Windows marks every file unpacked from a downloaded ZIP. .NET then refuses to load the marked DLLs, and the window
    library (pythonnet) fails with "Failed to resolve Python.Runtime.Loader.Initialize". This is what "Unblock" in the
    ZIP's properties would have done, limited to the app's own files.
    """
    count = 0
    for dll in Path(folder).rglob('*.dll'):
        try:
            os.remove(f'{dll}:Zone.Identifier')
        except OSError:  # not marked, or the folder is read-only
            continue
        count += 1
    return count


def check_resources(paths):
    required = [
        paths.web / 'index.html',
        paths.web / 'preview.html',
        paths.defaults / 'guidelines' / 'compression.md',
        paths.samples,
        paths.defaults.parent / 'comfy_nodes' / 'nodes.json',
        paths.defaults.parent / 'trainer' / 'anima_lora' / 'preprocess-model-paths.patch',
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError('Missing packaged resources: ' + ', '.join(missing))


def configure_logging(root):
    logs = root / 'state' / 'logs'
    logs.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(logs / 'desktop.log', maxBytes=2_000_000, backupCount=2, encoding='utf-8')
    logging.basicConfig(
        level=logging.INFO,
        handlers=[handler],
        format='%(asctime)s %(levelname)s %(name)s %(message)s',
        force=True,
    )
    # Windowed executables do not have stdout/stderr; third-party libraries may still write to them.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, 'w', encoding='utf-8')  # noqa: SIM115 - process lifetime stream
    if sys.stderr is None:
        sys.stderr = open(logs / 'stderr.log', 'a', encoding='utf-8')  # noqa: SIM115 - process lifetime stream


def show_error(message):
    if sys.platform == 'win32':
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, 'AtelierX', 0x10)
    elif sys.stderr:
        print(message, file=sys.stderr)


def main():
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser(description='AtelierX portable desktop')
    parser.add_argument('--root', help='Optional separate portable data folder')
    parser.add_argument('--headless', action='store_true', help='Run only the local HTTP server')
    parser.add_argument('--port', type=int, default=0, help='Loopback port (0 chooses an available port)')
    parser.add_argument('--ready-file', type=Path, help='Write startup status JSON for diagnostics')
    args = parser.parse_args()
    paths = AppPaths.for_runtime(args.root)
    ready = args.ready_file or paths.state / 'desktop.json'
    server = thread = sock = lock_file = None
    try:
        configure_logging(paths.root)
        # A portable data folder must never have two servers writing to it concurrently.
        lock_file = open(paths.state / 'desktop.lock', 'a+b')  # noqa: SIM115 - released in finally
        if sys.platform == 'win32':
            import msvcrt

            lock_file.seek(0)
            if not lock_file.read(1):
                lock_file.write(b'0')
                lock_file.flush()
            lock_file.seek(0)
            try:
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError('이 폴더의 AtelierX가 이미 실행 중입니다.') from exc
        check_resources(paths)
        app = build_app(paths, dev=False, desktop=not args.headless)
        sock = bind_loopback(args.port)
        port = sock.getsockname()[1]
        url = f'http://127.0.0.1:{port}'
        server = uvicorn.Server(
            uvicorn.Config(app, log_config=None, access_log=False, loop='asyncio', http='h11', ws='none')
        )
        thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
        thread.start()
        deadline = time.monotonic() + 30
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError('앱 서버를 시작하지 못했습니다. state/logs/desktop.log를 확인하세요.')
            time.sleep(0.05)
        write_json(ready, {'url': url, 'pid': os.getpid(), 'root': str(paths.root)})
        logger.info('Desktop ready at %s', url)
        if args.headless:

            def stop(_signum, _frame):
                server.should_exit = True

            for sig in (signal.SIGINT, signal.SIGTERM):
                signal.signal(sig, stop)
            if hasattr(signal, 'SIGBREAK'):
                signal.signal(signal.SIGBREAK, stop)
            while thread.is_alive():
                thread.join(0.25)
        else:
            if sys.platform == 'win32' and getattr(sys, 'frozen', False):
                if unblocked := unblock_bundle(sys._MEIPASS):
                    logger.info('Removed the download mark from %d bundled DLLs', unblocked)
            import webview

            webview.settings['ALLOW_DOWNLOADS'] = True
            webview.settings['ALLOW_FILE_URLS'] = False
            webview.create_window(
                'AtelierX',
                url,
                width=1440,
                height=960,
                min_size=(960, 640),
                text_select=True,
                confirm_close=True,
                localization={
                    'global.quitConfirmation': (
                        'AtelierX를 종료할까요? 저장하지 않은 변경 사항이 사라질 수 있습니다.\n'
                        '진행 중인 LoRA 학습·설치와 앱에서 시작한 ComfyUI도 함께 종료됩니다.'
                    )
                },
            )
            webview.start(gui='edgechromium', private_mode=True, storage_path=str(paths.state / 'webview'))
        return 0
    except Exception:
        logger.exception('Desktop startup or runtime failed')
        if not args.headless:
            show_error(
                'AtelierX를 실행하지 못했습니다.\nWindows WebView2 Runtime 설치 여부와 '
                '앱 폴더 쓰기 권한을 확인하세요.\n자세한 내용: state/logs/desktop.log'
            )
        return 1
    finally:
        if server is not None:
            server.should_exit = True
        if thread is not None:
            thread.join(10)
        if sock is not None:
            sock.close()
        if (read_json(ready) or {}).get('pid') == os.getpid():
            ready.unlink(missing_ok=True)
        if lock_file is not None:
            lock_file.close()


if __name__ == '__main__':
    raise SystemExit(main())
