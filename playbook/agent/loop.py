"""The bounded tool-calling loop over the Anthropic Messages API, producing a full trace."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

import anthropic

from playbook.agent.tools import API_TO_DOTTED, TOOL_SCHEMAS, ToolExecutor
from playbook.config import Settings


@dataclass
class ToolCall:
    turn: int
    tool_use_id: str
    name: str
    args: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    duration_ms: int


@dataclass
class ModelTurn:
    turn: int
    stop_reason: str | None
    text: str
    tool_uses: list[dict[str, Any]]
    input_tokens: int
    output_tokens: int


@dataclass
class RunTrace:
    run_id: str
    procedure_slug: str
    prompt_version: int
    scenario_id: str
    mode: str
    model: str
    system_prompt: str
    user_message: str
    started_at: str
    finished_at: str = ""
    turns: list[ModelTurn] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    final_text: str = ""
    status: str = "running"
    error: str | None = None

    def tool_names(self) -> list[str]:
        return [c.name for c in self.tool_calls]

    def calls(self, name: str) -> list[ToolCall]:
        return [c for c in self.tool_calls if c.name == name]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RunTrace:
        turns = [ModelTurn(**t) for t in d.get("turns", [])]
        calls = [ToolCall(**c) for c in d.get("tool_calls", [])]
        return cls(**{**d, "turns": turns, "tool_calls": calls})


def make_client(settings: Settings) -> anthropic.Anthropic:
    kwargs: dict[str, Any] = {"api_key": settings.anthropic_api_key, "max_retries": 2}
    if settings.anthropic_base_url:
        kwargs["base_url"] = settings.anthropic_base_url
    return anthropic.Anthropic(**kwargs)


def _text_of(content: list[Any]) -> str:
    return "".join(getattr(b, "text", "") for b in content if getattr(b, "type", "") == "text")


def run_agent(
    settings: Settings,
    system_prompt: str,
    user_message: str,
    executor: ToolExecutor,
    *,
    procedure_slug: str,
    prompt_version: int,
    scenario_id: str,
    client: anthropic.Anthropic | None = None,
) -> RunTrace:
    """Drive the model until it stops calling tools or the step budget is exhausted."""
    client = client or make_client(settings)
    trace = RunTrace(
        run_id=uuid.uuid4().hex[:12],
        procedure_slug=procedure_slug,
        prompt_version=prompt_version,
        scenario_id=scenario_id,
        mode="live" if settings.live else "offline",
        model=settings.model,
        system_prompt=system_prompt,
        user_message=user_message,
        started_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_message}]

    try:
        for turn in range(1, settings.max_steps + 1):
            response = client.messages.create(
                model=settings.model,
                max_tokens=1024,
                system=system_prompt,
                tools=TOOL_SCHEMAS,
                messages=messages,
            )
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            trace.turns.append(
                ModelTurn(
                    turn=turn,
                    stop_reason=response.stop_reason,
                    text=_text_of(response.content),
                    tool_uses=[{"id": b.id, "name": b.name, "input": b.input} for b in tool_uses],
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                )
            )
            if response.stop_reason != "tool_use" or not tool_uses:
                trace.final_text = _text_of(response.content)
                trace.status = "completed"
                break

            messages.append({"role": "assistant", "content": [b.model_dump() for b in response.content]})
            results: list[dict[str, Any]] = []
            for block in tool_uses:
                started = time.perf_counter()
                result: dict[str, Any] | None = None
                error: str | None = None
                try:
                    result = executor.execute(block.name, dict(block.input))
                except Exception as exc:  # tool failures are data, not crashes
                    error = f"{type(exc).__name__}: {exc}"
                elapsed = int((time.perf_counter() - started) * 1000)
                trace.tool_calls.append(
                    ToolCall(
                        turn=turn,
                        tool_use_id=block.id,
                        name=API_TO_DOTTED.get(block.name, block.name),
                        args=dict(block.input),
                        result=result,
                        error=error,
                        duration_ms=elapsed,
                    )
                )
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": _json_text(result if error is None else {"error": error}),
                        "is_error": error is not None,
                    }
                )
            messages.append({"role": "user", "content": results})
        else:
            trace.status = "max_steps"
    except Exception as exc:
        trace.status = "error"
        trace.error = f"{type(exc).__name__}: {exc}"
    trace.finished_at = datetime.now(UTC).isoformat(timespec="seconds")
    return trace


def _json_text(obj: Any) -> str:
    import json

    return json.dumps(obj, default=str)
