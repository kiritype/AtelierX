"""Read-only dependency checks; details never include tokens, prompts or file contents."""
from __future__ import annotations

import asyncio
import json
import re
import subprocess

from . import procs
from .config import read_json

_NODE_ID = re.compile(r"""node_id\s*=\s*["'](AtelierX\w+)["']""")
_MAPPING_KEY = re.compile(r"""["'](AtelierX\w+)["']\s*:""")
KNOWN_PORTS = {8180: "제어판", 8188: "ComfyUI", 8189: "Generation", 8190: "Core", 8191: "Validation", 8192: "Discord Bridge", 1234: "LM Studio"}


def expected_node_ids(custom_nodes) -> list[str]:
    """Static scan of AtelierX node registrations (V3 node_id or NODE_CLASS_MAPPINGS keys) without importing ComfyUI code."""
    found = set()
    if not custom_nodes.is_dir():
        return []
    for path in custom_nodes.glob("atelierx_*/*.py"):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        found.update(_NODE_ID.findall(text))
        if "NODE_CLASS_MAPPINGS" in text:
            for block in re.findall(r"NODE_CLASS_MAPPINGS\s*=\s*\{(.*?)\}", text, re.S):
                found.update(_MAPPING_KEY.findall(block))
    return sorted(found)


def combo_options(spec):
    if not isinstance(spec, list) or not spec:
        return None
    if isinstance(spec[0], list):
        return spec[0]
    if spec[0] == "COMBO" and len(spec) > 1 and isinstance(spec[1], dict):
        return spec[1].get("options")
    return None


def empty_model_inputs(node_info) -> tuple[int, list[str]]:
    inputs = (node_info or {}).get("input") or {}
    total, empty = 0, []
    for group in ("required", "optional"):
        for name, spec in (inputs.get(group) or {}).items():
            options = combo_options(spec)
            if options is None:
                continue
            total += 1
            if not options:
                empty.append(name)
    return total, empty


def lms_has_model(listing, model) -> bool:
    for entry in listing if isinstance(listing, list) else []:
        if isinstance(entry, dict) and model in {entry.get(key) for key in ("modelKey", "path", "indexedModelIdentifier", "id")}:
            return True
    return False


def check(id_, label, status, detail):
    return {"id": id_, "label": label, "status": status, "detail": detail}


async def collect(panel) -> list[dict]:
    paths, items, urls = panel.paths, panel.items, panel.urls
    results = []
    stats = await panel.http_status(urls["comfyui"] + "/system_stats")
    reachable = stats == 200
    results.append(check("comfyui_reachable", "ComfyUI 응답", "ok" if reachable else "missing",
                         "127.0.0.1:8188 응답" if reachable else "응답 없음"))
    expected = expected_node_ids(paths.custom_nodes)
    if not reachable:
        results.append(check("atelierx_nodes", "AtelierX Node 등록", "unknown", "ComfyUI 응답 없음"))
        results.append(check("anima_models", "Anima 모델 목록", "unknown", "ComfyUI 응답 없음"))
    else:
        info = await panel.http_json(urls["comfyui"] + "/object_info", timeout=20)
        if not isinstance(info, dict):
            results.append(check("atelierx_nodes", "AtelierX Node 등록", "unknown", "/object_info를 읽을 수 없음"))
        else:
            missing = [name for name in expected if name not in info]
            results.append(check("atelierx_nodes", "AtelierX Node 등록", "warning" if missing else "ok",
                                 ("누락: " + ", ".join(missing)) if missing else f"{len(expected)}개 등록"))
        anima = await panel.http_json(urls["comfyui"] + "/object_info/AtelierXAnimaGenerate")
        node = anima.get("AtelierXAnimaGenerate") if isinstance(anima, dict) else None
        if not node:
            results.append(check("anima_models", "Anima 모델 목록", "missing", "AtelierXAnimaGenerate Node 없음"))
        else:
            total, empty = empty_model_inputs(node)
            status = "warning" if empty or not total else "ok"
            detail = ("빈 목록: " + ", ".join(empty)) if empty else (f"선택 목록 {total}개 확인" if total else "선택 목록 없음")
            results.append(check("anima_models", "Anima 모델 목록", status, detail))
    lms = items["lmstudio"].lms() if "lmstudio" in items else None
    results.append(check("lmstudio_installed", "LM Studio CLI(lms)", "ok" if lms else "missing", "설치됨" if lms else "lms를 찾을 수 없음"))
    gpu = read_json(paths.gpu_config)
    model = gpu.get("model") if isinstance(gpu, dict) else None
    if not lms or not isinstance(model, str) or not model:
        results.append(check("lmstudio_model", "LM Studio 설정 모델", "unknown", "lms 또는 gpu-config 모델 설정 없음"))
    elif not await items["lmstudio"].is_ready():
        # `lms ls` wakes the LM Studio app and its server, so a read-only check runs it only when LM Studio is already up.
        results.append(check("lmstudio_model", "LM Studio 설정 모델", "unknown", "LM Studio 서버가 꺼져 있어 확인 생략"))
    else:
        try:
            listed = await asyncio.to_thread(subprocess.run, [lms, "ls", "--json"], capture_output=True, timeout=30, creationflags=procs.NO_WINDOW)
            listing = json.loads(listed.stdout) if listed.returncode == 0 else None
        except (OSError, ValueError, subprocess.TimeoutExpired):
            listing = None
        if listing is None:
            results.append(check("lmstudio_model", "LM Studio 설정 모델", "unknown", "lms ls 실행 실패"))
        else:
            present = lms_has_model(listing, model)
            results.append(check("lmstudio_model", "LM Studio 설정 모델", "ok" if present else "missing", model + (" 있음" if present else " 없음")))
    cloudflared = items["tunnel"].cloudflared() if "tunnel" in items else None
    results.append(check("cloudflared", "cloudflared 실행 파일", "ok" if cloudflared else "missing", "있음" if cloudflared else "찾을 수 없음"))
    results.append(check("tunnel_token", "Tunnel token 파일", "ok" if paths.tunnel_token.is_file() else "missing",
                         "있음" if paths.tunnel_token.is_file() else "없음"))
    for id_, label, path in (("validation_config", "Validation 연결 설정", paths.validation_config), ("gpu_config", "GPU 조정 설정", paths.gpu_config)):
        results.append(check(id_, label, "ok" if path.is_file() else "missing", "있음" if path.is_file() else "없음"))
    results.extend(await asyncio.to_thread(port_checks, panel))
    return results


def port_checks(panel) -> list[dict]:
    owners, table = procs.listening_ports(), procs.process_table()
    managed = {item_id: item.observed.get("pid") for item_id, item in panel.items.items() if item.observed.get("managed")}
    results = []
    for port in sorted(set(range(8180, 8193)) | {1234}):
        owner = owners.get(port)
        label = f"포트 {port}" + (f" ({KNOWN_PORTS[port]})" if port in KNOWN_PORTS else "")
        if owner is None:
            if port in KNOWN_PORTS:
                results.append(check(f"port_{port}", label, "ok", "사용 안 함"))
            continue
        name = table.get(owner, (0, ""))[1] or "알 수 없음"
        if port == panel.port and owner == panel.pid:
            who = "제어판"
        else:
            who = next((panel.items[item_id].label + " (제어판 관리)" for item_id, pid in managed.items() if pid and procs.descends_from(owner, pid, table)), "외부 프로세스")
        results.append(check(f"port_{port}", label, "ok" if port in KNOWN_PORTS else "warning", f"pid {owner} {name} · {who}"))
    return results
