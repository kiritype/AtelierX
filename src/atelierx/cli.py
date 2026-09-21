"""JSON command line client for an AtelierX Core service."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from .api_client import CoreClient
from .common import ApiError


DEFAULT_CORE_URL = "http://127.0.0.1:8190"


class CliArgumentError(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise CliArgumentError(message)


def _page(parser):
    parser.add_argument("--limit", type=int)
    parser.add_argument("--offset", type=int)


def _list_command(parent, name, filters):
    command = parent.add_parser(name)
    actions = command.add_subparsers(dest=name.replace("-", "_") + "_action", required=True)
    listing = actions.add_parser("list")
    for field in filters:
        listing.add_argument("--" + field.replace("_", "-"), dest=field)
    _page(listing)
    detail = actions.add_parser("get")
    detail.add_argument("id")
    return command, actions


def _input(parser):
    parser.add_argument("--input", dest="input_path", required=True,
                        help="UTF-8 JSON object file, or - for standard input")


def _idempotency_key(parser):
    parser.add_argument("--idempotency-key", required=True)


def build_parser(core_url=None):
    parser = Parser(prog="atelierx", description=__doc__)
    parser.add_argument("--core-url", default=core_url if core_url is not None else os.environ.get("ATELIERX_CORE_URL", DEFAULT_CORE_URL))
    commands = parser.add_subparsers(dest="command", required=True)
    _list_command(commands, "groups", ("work_id", "character_id", "outfit_id"))
    images, image_actions = _list_command(commands, "images", ("work_id", "character_id", "outfit_id", "group_id", "task_id", "media_type", "single_outcome", "group_status"))
    validate = image_actions.add_parser("validate")
    validate.add_argument("id")
    _input(validate)
    _idempotency_key(validate)

    tasks, task_actions = _list_command(commands, "tasks", ("work_id", "character_id", "outfit_id", "group_id", "state"))
    create = task_actions.add_parser("create")
    _input(create)
    _idempotency_key(create)
    by_key = task_actions.add_parser("by-key")
    _idempotency_key(by_key)
    regenerate = task_actions.add_parser("regenerate")
    regenerate.add_argument("id")
    _input(regenerate)
    _idempotency_key(regenerate)
    cancel_task = task_actions.add_parser("cancel")
    cancel_task.add_argument("id")
    attempts = task_actions.add_parser("attempts")
    attempts.add_argument("id")
    _page(attempts)

    batches, batch_actions = _list_command(commands, "group-batches", ("group_id", "state"))
    batch_create = batch_actions.add_parser("create")
    batch_create.add_argument("group_id")
    _input(batch_create)
    _idempotency_key(batch_create)
    batch_cancel = batch_actions.add_parser("cancel")
    batch_cancel.add_argument("id")
    batch_confirm = batch_actions.add_parser("confirm-reference")
    batch_confirm.add_argument("id")
    _input(batch_confirm)
    _idempotency_key(batch_confirm)
    prompts = commands.add_parser("prompts")
    prompt_actions = prompts.add_subparsers(dest="prompts_action", required=True)
    preview = prompt_actions.add_parser("preview")
    _input(preview)

    validations = commands.add_parser("validations")
    validation_actions = validations.add_subparsers(dest="validations_action", required=True)
    validation_get = validation_actions.add_parser("get")
    validation_get.add_argument("id")
    validation_cancel = validation_actions.add_parser("cancel")
    validation_cancel.add_argument("id")

    cycles = commands.add_parser("cycles")
    cycle_actions = cycles.add_subparsers(dest="cycles_action", required=True)
    cycle_get = cycle_actions.add_parser("get")
    cycle_get.add_argument("id")
    cycle_stop = cycle_actions.add_parser("stop")
    cycle_stop.add_argument("id")
    commands.add_parser("health")
    queue = commands.add_parser("queue")
    queue.add_argument("--state")
    _page(queue)
    settings = commands.add_parser("settings")
    settings_actions = settings.add_subparsers(dest="settings_action", required=True)
    settings_actions.add_parser("get")
    settings_update = settings_actions.add_parser("update")
    _input(settings_update)
    return parser


def _filters(args):
    return {name: value for name, value in vars(args).items()
            if name in {"work_id", "character_id", "outfit_id", "group_id", "task_id", "media_type", "single_outcome", "group_status", "state", "limit", "offset"}
            and value is not None}


def _input_object(path, stdin):
    try:
        text = stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        raise ApiError("CLI_INPUT_UNREADABLE", "Input JSON could not be read", 400) from None
    try:
        value = json.loads(text.lstrip("\ufeff"), parse_constant=lambda _: (_ for _ in ()).throw(ValueError))
    except (TypeError, ValueError, json.JSONDecodeError):
        raise ApiError("CLI_INPUT_INVALID", "Input must be a UTF-8 JSON object", 400) from None
    if not isinstance(value, dict):
        raise ApiError("CLI_INPUT_INVALID", "Input must be a UTF-8 JSON object", 400)
    return value


async def execute(args, token, stdin=None):
    if not isinstance(token, str) or not token:
        raise ApiError("CLI_TOKEN_MISSING", "ATELIERX_CORE_TOKEN is required", 400)
    body = _input_object(args.input_path, sys.stdin if stdin is None else stdin) if hasattr(args, "input_path") else None
    async with CoreClient(args.core_url, token) as client:
        if args.command == "health":
            return await client.health()
        if args.command == "queue":
            return await client.queue(**_filters(args))
        if args.command == "settings":
            return await (client.get_settings() if args.settings_action == "get" else client.update_settings(body))
        if args.command == "prompts":
            return await client.preview_prompt(body)
        if args.command == "validations":
            return await (client.get_validation_run(args.id) if args.validations_action == "get"
                          else client.cancel_validation(args.id))
        if args.command == "cycles":
            return await (client.get_cycle(args.id) if args.cycles_action == "get" else client.stop_cycle(args.id))
        action = getattr(args, args.command.replace("-", "_") + "_action")
        if args.command == "groups":
            return await (client.list_groups(**_filters(args)) if action == "list" else client.get_group(args.id))
        if args.command == "images":
            if action == "list":
                return await client.list_images(**_filters(args))
            if action == "get":
                return await client.get_image(args.id)
            return await client.validate_image(args.id, body, args.idempotency_key)
        if args.command == "tasks":
            if action == "list":
                return await client.list_tasks(**_filters(args))
            if action == "get":
                return await client.get_task(args.id)
            if action == "create":
                return await client.create_task(body, args.idempotency_key)
            if action == "by-key":
                return await client.get_task_by_key(args.idempotency_key)
            if action == "regenerate":
                return await client.regenerate_task(args.id, body, args.idempotency_key)
            if action == "cancel":
                return await client.cancel_task(args.id)
            return await client.list_task_attempts(args.id, **_filters(args))
        if args.command == "group-batches":
            if action == "list":
                return await client.list_group_batches(**_filters(args))
            if action == "get":
                return await client.get_group_batch(args.id)
            if action == "create":
                return await client.create_group_batch(args.group_id, body, args.idempotency_key)
            if action == "cancel":
                return await client.cancel_group_batch(args.id)
            return await client.confirm_group_batch_reference(args.id, body, args.idempotency_key)
    raise ApiError("CLI_INVALID_COMMAND", "Unsupported command", 400)


def _write(stream, value):
    stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


def main(argv=None, environ=None, stdin=None):
    try:
        config = os.environ if environ is None else environ
        args = build_parser(config.get("ATELIERX_CORE_URL", DEFAULT_CORE_URL)).parse_args(argv)
        token = config.get("ATELIERX_CORE_TOKEN")
        _write(sys.stdout, asyncio.run(execute(args, token, stdin)))
        return 0
    except CliArgumentError:
        _write(sys.stderr, {"error": {"code": "CLI_INVALID_ARGUMENT", "message": "Invalid command arguments"}})
    except ApiError as exc:
        _write(sys.stderr, {"error": {"code": exc.code, "message": exc.message, "status": exc.status}})
    except ValueError:
        _write(sys.stderr, {"error": {"code": "CLI_INVALID_CONFIGURATION", "message": "Invalid CLI configuration"}})
    except Exception:
        _write(sys.stderr, {"error": {"code": "CLI_INTERNAL_ERROR", "message": "CLI request failed"}})
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
