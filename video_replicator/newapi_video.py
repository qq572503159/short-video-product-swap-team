from __future__ import annotations

"""Client for the New API compatible video endpoint.

The provider is intentionally independent from the Ark/Seedance client.  New
API expects a top-level ``prompt`` and public reference URLs, and returns a
task that must be polled through ``/v1/videos/{id}``.
"""

import json
import os
import time
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen


DEFAULT_ENV_FILE = Path.home() / ".codex" / "secrets" / "newapi.env"


def _read_env_file(path: Path = DEFAULT_ENV_FILE) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key:
            values[key] = value
    return values


@dataclass(frozen=True)
class NewAPIConfig:
    base_url: str
    token: str
    model: str = "minimax-h3-f"
    env_file: Path = DEFAULT_ENV_FILE

    @classmethod
    def from_env(cls, env_file: Path = DEFAULT_ENV_FILE) -> "NewAPIConfig":
        file_values = _read_env_file(env_file)

        def value(name: str, default: str = "") -> str:
            return os.environ.get(name) or file_values.get(name) or default

        base_url = value("NEW_API_URL", "https://newapi.megabyai.cc").rstrip("/")
        token = value("NEW_API_TOKEN")
        model = value("NEW_API_MODEL", "minimax-h3-f")
        return cls(base_url=base_url, token=token, model=model, env_file=env_file)

    def validate(self, require_token: bool = True) -> None:
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("NEW_API_URL 必须是 http(s) URL")
        parsed = urlsplit(self.base_url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" and host not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("NEW_API_URL 远程地址必须使用 HTTPS；HTTP 仅允许本机回环地址")
        if require_token and not self.token:
            raise ValueError(f"未找到 NEW_API_TOKEN，请配置 {self.env_file}")


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("***REDACTED***" if k.lower() in {"token", "authorization", "api_key"} else _redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        parsed = urlsplit(value)
        query = [(key, "***REDACTED***") for key, _ in parse_qsl(parsed.query, keep_blank_values=True)]
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))
    return value


class NewAPIVideoClient:
    def __init__(self, config: NewAPIConfig | None = None, timeout: int = 60):
        self.config = config or NewAPIConfig.from_env()
        self.timeout = timeout

    @staticmethod
    def build_payload(
        prompt: str,
        *,
        model: str,
        duration: int = 10,
        ratio: str = "9:16",
        resolution: str = "768p",
        reference_images: Iterable[str] = (),
        reference_videos: Iterable[str] = (),
        reference_audios: Iterable[str] = (),
        **extra: Any,
    ) -> dict[str, Any]:
        if not prompt.strip():
            raise ValueError("prompt 不能为空")
        if not 1 <= duration <= 15:
            raise ValueError("minimax-h3-f 的 duration 应在 1-15 秒之间")

        def urls(items: Iterable[str]) -> list[str]:
            result = []
            for item in items:
                if not item.startswith(("http://", "https://")):
                    raise ValueError(f"参考素材必须是公网 http(s) URL: {item}")
                result.append(item)
            return result

        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "duration": duration,
            "ratio": ratio,
            "resolution": resolution,
        }
        images, videos, audios = urls(reference_images), urls(reference_videos), urls(reference_audios)
        if images:
            payload["referenceImages"] = images
        if videos:
            payload["referenceVideos"] = videos
        if audios:
            payload["referenceAudios"] = audios
        payload.update(extra)
        return payload

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        self.config.validate(require_token=True)
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            f"{self.config.base_url}{path}",
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.config.token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"New API HTTP {exc.code}: {detail[:500]}") from exc
        except URLError as exc:
            raise RuntimeError(f"无法连接 New API: {exc.reason}") from exc
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"New API 返回非 JSON: {raw[:500]}") from exc
        if not isinstance(data, dict):
            raise RuntimeError("New API 返回格式不是 JSON object")
        return data

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/videos", payload)

    def status(self, task_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/videos/{task_id}")

    @staticmethod
    def task_id(response: dict[str, Any]) -> str:
        task_id = response.get("task_id") or response.get("id")
        if not task_id:
            raise RuntimeError(f"创建响应缺少 task_id/id: {response}")
        return str(task_id)

    @staticmethod
    def result_url(response: dict[str, Any]) -> str | None:
        data = response.get("data")
        if isinstance(data, dict):
            return response.get("video_url") or response.get("url") or data.get("video_url") or data.get("url")
        return response.get("video_url") or response.get("url")

    def wait_for_completion(self, task_id: str, *, interval: float = 3.0, timeout: float = 900.0) -> dict[str, Any]:
        if interval <= 0:
            raise ValueError("轮询间隔必须大于 0 秒")
        if timeout <= 0:
            raise ValueError("轮询超时必须大于 0 秒")
        deadline = time.monotonic() + timeout
        success_states = {"completed", "succeeded", "success"}
        terminal = success_states | {"failed", "cancelled", "canceled", "error", "expired"}
        while True:
            response = self.status(task_id)
            state = str(response.get("status", "")).lower()
            if state in terminal:
                if state not in success_states:
                    raise RuntimeError(f"视频任务失败（{state}）: {response}")
                if not self.result_url(response):
                    raise RuntimeError(f"任务已完成但响应缺少视频 URL: {response}")
                return response
            if time.monotonic() >= deadline:
                raise TimeoutError(f"轮询任务超时: {task_id}")
            time.sleep(interval)

    def download(self, url: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        request = Request(url, headers={"Accept": "video/mp4,application/octet-stream"})
        try:
            with urlopen(request, timeout=self.timeout) as response, destination.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
        except (HTTPError, URLError) as exc:
            raise RuntimeError(f"下载生成视频失败: {exc}") from exc
        return destination


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def run_newapi(
    *,
    project_dir: Path,
    prompt: str,
    model: str | None = None,
    duration: int = 10,
    ratio: str = "9:16",
    resolution: str = "768p",
    reference_images: Iterable[str] = (),
    reference_videos: Iterable[str] = (),
    generate_audio: bool = False,
    dry_run: bool = True,
    confirm_billing: bool = False,
    poll_interval: float = 3.0,
    qa_file: Path | None = None,
    require_compiled_prompt: bool = True,
) -> dict[str, Any]:
    client = NewAPIVideoClient()
    selected_model = model or client.config.model or "minimax-h3-f"
    payload = client.build_payload(
        prompt,
        model=selected_model,
        duration=duration,
        ratio=ratio,
        resolution=resolution,
        reference_images=reference_images,
        reference_videos=reference_videos,
        generate_audio=generate_audio,
    )
    output_dir = project_dir / "outputs" / "newapi"
    output_dir.mkdir(parents=True, exist_ok=True)
    if dry_run:
        write_json(output_dir / "request.redacted.json", _redact(payload))
        return {"status": "dry_run", "model": selected_model, "request": str(output_dir / "request.redacted.json")}
    if not confirm_billing:
        raise ValueError("真实提交会产生费用，请同时传入 --confirm-billing")
    qa_path = qa_file or project_dir / "outputs" / "qa.json"
    if not qa_path.is_file():
        raise ValueError(f"真实提交前必须存在 QA 文件且状态为 approved: {qa_path}")
    qa = json.loads(qa_path.read_text(encoding="utf-8-sig"))
    if qa.get("status") != "approved":
        raise ValueError(f"QA 未通过，禁止真实提交: status={qa.get('status')!r}")
    if require_compiled_prompt:
        compiled = project_dir / "outputs" / "final_product_swap_prompt.md"
        if not compiled.is_file() or not compiled.read_text(encoding="utf-8-sig").strip():
            raise ValueError(f"真实提交前必须存在已编译提示词: {compiled}")
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    output_dir = output_dir / f"run-{run_id}"
    output_dir.mkdir(parents=True, exist_ok=False)
    write_json(output_dir / "request.redacted.json", _redact(payload))
    created = client.create(payload)
    write_json(output_dir / "create_response.json", _redact(created))
    task_id = client.task_id(created)
    completed = client.wait_for_completion(task_id, interval=poll_interval)
    write_json(output_dir / "status.json", _redact(completed))
    video_url = client.result_url(completed)
    assert video_url
    destination = client.download(video_url, output_dir / "generated.mp4")
    return {"status": "completed", "task_id": task_id, "video_url": _redact(video_url), "output": str(destination)}
