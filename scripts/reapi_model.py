#!/usr/bin/env python3
"""CLI helper for a model-specific reAPI skill."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_BASE_URL = "https://reapi.ai"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
SKILL_DIR = Path(__file__).resolve().parents[1]
MODEL_JSON = SKILL_DIR / "model.json"


def load_env_file() -> None:
    for path in [Path.cwd() / ".env", SKILL_DIR / ".env"]:
        if not path.exists():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not key.startswith("REAPI_"):
                continue
            os.environ.setdefault(key, value.strip().strip('"').strip("'"))


def load_model_config() -> dict[str, Any]:
    try:
        data = json.loads(MODEL_JSON.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"Missing model config: {MODEL_JSON}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid model config JSON: {exc}") from exc
    required = ["skill_name", "display_name", "endpoint", "default_model", "models"]
    missing = [key for key in required if key not in data]
    if missing:
        raise SystemExit(f"Invalid model config, missing: {', '.join(missing)}")
    return data


def env_api_key() -> str | None:
    return os.environ.get("REAPI_API_KEY") or os.environ.get("REAPI_KEY")


def normalize_base_url(raw: str | None) -> str:
    return (raw or os.environ.get("REAPI_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")


def request_user_agent() -> str:
    return os.environ.get("REAPI_USER_AGENT") or DEFAULT_USER_AGENT


def endpoint_path(endpoint: str) -> str:
    if endpoint == "images":
        return "/api/v1/images/generations"
    if endpoint == "videos":
        return "/api/v1/videos/generations"
    raise SystemExit(f"Unsupported endpoint: {endpoint}")


def load_payload(args: argparse.Namespace, cfg: dict[str, Any]) -> dict[str, Any]:
    if args.json and args.json_file:
        raise SystemExit("Use either --json or --json-file, not both")
    if args.json_file:
        text = Path(args.json_file).read_text(encoding="utf-8")
    elif args.json:
        text = args.json
    else:
        if not args.prompt:
            raise SystemExit("Pass --prompt, --json, or --json-file")
        payload = dict(cfg.get("default_payload") or {})
        payload["prompt"] = args.prompt
        return apply_set_values(payload, args.set_values or [])
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON payload: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("Payload must be a JSON object")
    if args.prompt:
        payload["prompt"] = args.prompt
    return apply_set_values(payload, args.set_values or [])


def parse_scalar(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def apply_set_values(payload: dict[str, Any], pairs: list[str]) -> dict[str, Any]:
    for item in pairs:
        if "=" not in item:
            raise SystemExit(f"Invalid --set value {item!r}; use key=value")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise SystemExit("Invalid --set value with empty key")
        payload[key] = parse_scalar(value)
    return payload


def request_json(
    method: str,
    url: str,
    api_key: str,
    payload: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> tuple[int, dict[str, str], Any]:
    body = None
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "User-Agent": request_user_agent(),
    }
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as res:
            text = res.read().decode("utf-8")
            data = json.loads(text) if text else None
            return res.status, dict(res.headers.items()), data
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8")
        try:
            data = json.loads(text) if text else {"error": {"message": text}}
        except json.JSONDecodeError:
            data = {"error": {"message": text}}
        return exc.code, dict(exc.headers.items()), data
    except urllib.error.URLError as exc:
        raise SystemExit(f"Network error calling reAPI: {exc}") from exc


def print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def require_api_key(args: argparse.Namespace) -> str:
    api_key = args.api_key or env_api_key()
    if not api_key:
        raise SystemExit(
            "Missing API key. Get one at https://reapi.ai -> Dashboard -> "
            "API Keys, then set REAPI_API_KEY."
        )
    return api_key


def is_terminal(task: Any) -> bool:
    return isinstance(task, dict) and task.get("status") in {"completed", "failed"}


def wait_for_task(base_url: str, api_key: str, task_id: str, interval: float, timeout: float) -> Any:
    deadline = time.monotonic() + timeout
    last: Any = None
    while True:
        status, headers, data = request_json("GET", f"{base_url}/api/v1/tasks/{task_id}", api_key)
        last = data
        if status == 429:
            retry_after = headers.get("Retry-After")
            sleep_for = float(retry_after) if retry_after else interval
            time.sleep(max(1.0, sleep_for))
            continue
        if status in {500, 502, 503, 504}:
            if time.monotonic() >= deadline:
                return data
            time.sleep(interval)
            continue
        if status != 200:
            return data
        if is_terminal(data):
            return data
        if time.monotonic() >= deadline:
            return {"status": "timeout", "message": f"Timed out waiting for task {task_id}", "last": last}
        time.sleep(interval)


def cmd_config(args: argparse.Namespace) -> int:
    cfg = load_model_config()
    api_key = args.api_key or env_api_key()
    result = {
        "skill": cfg["skill_name"],
        "display_name": cfg["display_name"],
        "base_url": normalize_base_url(args.base_url),
        "api_key": "set" if api_key else "missing",
        "default_model": cfg["default_model"],
        "endpoint": cfg["endpoint"],
        "docs": cfg.get("docs_url", "https://reapi.ai/docs"),
    }
    if not api_key:
        result["how_to_get_key"] = "Open https://reapi.ai, sign in, go to Dashboard -> API Keys, create a key, then set REAPI_API_KEY."
    print_json(result)
    return 0 if api_key else 1


def cmd_models(_args: argparse.Namespace) -> int:
    cfg = load_model_config()
    print_json({"default_model": cfg["default_model"], "models": cfg["models"], "endpoint": cfg["endpoint"]})
    return 0


def cmd_example(_args: argparse.Namespace) -> int:
    cfg = load_model_config()
    payload = dict(cfg.get("default_payload") or {})
    payload["model"] = cfg["default_model"]
    print_json(payload)
    return 0


def cmd_submit(args: argparse.Namespace) -> int:
    cfg = load_model_config()
    api_key = require_api_key(args)
    model = args.model or cfg["default_model"]
    if model not in cfg["models"]:
        raise SystemExit(f"Unsupported model {model!r}. Run `reapi_model.py models`.")
    payload = load_payload(args, cfg)
    payload["model"] = model
    base_url = normalize_base_url(args.base_url)
    url = base_url + endpoint_path(cfg["endpoint"])
    status, _headers, data = request_json("POST", url, api_key, payload, args.idempotency_key)
    if status < 200 or status >= 300:
        print_json(data)
        return 1
    if not args.wait:
        print_json(data)
        return 0
    if not isinstance(data, dict) or not isinstance(data.get("id"), str):
        print_json(data)
        return 1
    final = wait_for_task(base_url, api_key, data["id"], args.poll_interval, args.timeout)
    print_json(final)
    return 0 if isinstance(final, dict) and final.get("status") == "completed" else 1


def cmd_get(args: argparse.Namespace) -> int:
    api_key = require_api_key(args)
    base_url = normalize_base_url(args.base_url)
    status, _headers, data = request_json("GET", f"{base_url}/api/v1/tasks/{args.task_id}", api_key)
    print_json(data)
    return 0 if status == 200 else 1


def cmd_wait(args: argparse.Namespace) -> int:
    api_key = require_api_key(args)
    base_url = normalize_base_url(args.base_url)
    final = wait_for_task(base_url, api_key, args.task_id, args.poll_interval, args.timeout)
    print_json(final)
    return 0 if isinstance(final, dict) and final.get("status") == "completed" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Call the public reAPI API for this model skill")
    parser.add_argument("--api-key", help="reAPI API key; defaults to REAPI_API_KEY or REAPI_KEY")
    parser.add_argument("--base-url", help=f"API base URL; defaults to REAPI_BASE_URL or {DEFAULT_BASE_URL}")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("config", help="Check configuration").set_defaults(func=cmd_config)
    sub.add_parser("models", help="List supported canonical model IDs").set_defaults(func=cmd_models)
    sub.add_parser("example", help="Print an example payload").set_defaults(func=cmd_example)
    submit = sub.add_parser("submit", help="Submit a generation task")
    submit.add_argument("--prompt", help="Prompt to use when not passing a complete JSON payload")
    submit.add_argument("--model", help="Canonical reAPI model ID override")
    submit.add_argument("--json", help="Request payload JSON object")
    submit.add_argument("--json-file", help="Path to request payload JSON file")
    submit.add_argument("--set", dest="set_values", action="append", help="Set or override a payload field as key=value. JSON values are accepted.")
    submit.add_argument("--idempotency-key", help="Optional Idempotency-Key header")
    submit.add_argument("--wait", action="store_true", help="Poll until terminal")
    submit.add_argument("--poll-interval", type=float, default=2.5)
    submit.add_argument("--timeout", type=float, default=900)
    submit.set_defaults(func=cmd_submit)
    get = sub.add_parser("get", help="Get task status once")
    get.add_argument("task_id")
    get.set_defaults(func=cmd_get)
    wait = sub.add_parser("wait", help="Poll task until terminal")
    wait.add_argument("task_id")
    wait.add_argument("--poll-interval", type=float, default=2.5)
    wait.add_argument("--timeout", type=float, default=900)
    wait.set_defaults(func=cmd_wait)
    return parser


def main() -> int:
    load_env_file()
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
