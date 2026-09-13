"""Run existing checks sequentially and retain per-command evidence.

GPU model lifecycle is managed separately after checking local server queues.
"""
import argparse
import json
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / '.venv/Scripts/python.exe'
COMFY_PYTHON = Path('C:/StabilityMatrix/Packages/ComfyUI/venv/Scripts/python.exe')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', choices=['cpu', 'generation', 'vision'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    commands = []
    if args.phase == 'cpu':
        commands.append(('backends', [PYTHON, '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-v']))
        for package in sorted((ROOT / 'custom_nodes').glob('atelierx_*')):
            if (package / 'tests').exists():
                commands.append((package.name, [COMFY_PYTHON, '-B', '-m', 'unittest', 'discover', '-s', package / 'tests', '-v']))
            validator = package / 'scripts/validate_examples.py'
            if validator.exists():
                commands.append((package.name + '-examples', [COMFY_PYTHON, '-B', validator]))
        commands.append(('draft-contract', [COMFY_PYTHON, '-B', ROOT / 'docs/contracts/validation/check_contract.py']))
    else:
        names = (['generation_rest', 'core_rest', 'postprocess_rest', 'reference_detectors_rest', 'backend_pipeline_rest']
                 if args.phase == 'generation' else ['lmstudio_validation', 'validation_generalization'])
        commands = [(name, [PYTHON, '-B', ROOT / 'scripts' / f'test_{name}.py']) for name in names]
    results = []
    for name, command in commands:
        command = list(map(str, command))
        log = args.output / f'{name}.log'
        print(f'START {name}', flush=True)
        start = time.monotonic()
        with log.open('w', encoding='utf-8') as stream:
            result = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        content = log.read_text(encoding='utf-8', errors='replace')
        counts = re.findall(r'Ran (\d+) tests?', content)
        reports = re.findall(r'[A-Za-z]:[\\/][^\r\n]*report\.json', content)
        row = dict(name=name, command=command, exit_code=result.returncode,
                   seconds=round(time.monotonic() - start, 2), log=str(log.resolve()),
                   unittest_count=int(counts[-1]) if counts else None, reports=reports)
        results.append(row)
        (args.output / f'{args.phase}.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'END {name}: exit={result.returncode}, seconds={row["seconds"]}, tests={row["unittest_count"]}', flush=True)
        if result.returncode:
            print(content[-5000:], flush=True)
    return int(any(row['exit_code'] for row in results))


if __name__ == '__main__':
    raise SystemExit(main())
