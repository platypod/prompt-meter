"""Claude Code provider.

Reads the on-disk session transcripts Claude Code writes to
``~/.claude/projects/<slug>/<session>.jsonl`` (one JSON object per line) and
normalizes them into `Event`s.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterator

from ..events import Event, ToolCall, ToolResult, Usage
from .base import Provider, Session

PROJECTS_DIR = Path(os.environ.get(
    "CLAUDE_PROJECTS_DIR", str(Path.home() / ".claude" / "projects")))

CONTENT_TYPES = {"user", "assistant", "system"}


def _to_epoch_ns(ts: str | None) -> int | None:
    if not ts:
        return None
    try:
        from datetime import datetime
        return int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1e9)
    except (ValueError, TypeError):
        return None


def _session_titles(path: Path) -> dict[str, str]:
    """Map of session_id → a human title.

    Prefers Claude Code's own AI-inferred title (``ai-title`` lines, which it
    keeps refreshed as the session evolves — last one in the file wins). Falls
    back to the first user prompt, truncated, for sessions too young to have
    one yet.
    """
    titles: dict[str, str] = {}
    fallback: dict[str, str] = {}
    try:
        with path.open() as fh:
            for line in fh:
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:
                    continue
                sid = o.get("sessionId", "")
                if not sid:
                    continue
                if o.get("type") == "ai-title" and o.get("aiTitle"):
                    titles[sid] = o["aiTitle"]
                elif sid not in fallback and o.get("type") == "user":
                    msg = o.get("message", {})
                    content = msg.get("content")
                    text = content if isinstance(content, str) else ""
                    if isinstance(content, list):
                        text = " ".join(
                            b.get("text", "") for b in content
                            if isinstance(b, dict) and b.get("type") == "text")
                    text = text.strip().replace("\n", " ")
                    if text:
                        fallback[sid] = text[:80]
    except OSError:
        pass
    return {**fallback, **titles}


def _render_body(o: dict) -> str:
    """A compact, human-readable rendering of a transcript line for the log."""
    msg = o.get("message", {})
    content = msg.get("content")
    if isinstance(content, str):
        return content
    parts: list[str] = []
    if isinstance(content, list):
        for blk in content:
            if not isinstance(blk, dict):
                continue
            t = blk.get("type")
            if t == "text":
                parts.append(blk.get("text", ""))
            elif t == "tool_use":
                parts.append(f"[tool_use {blk.get('name','')}] {json.dumps(blk.get('input', {}))}")
            elif t == "tool_result":
                c = blk.get("content")
                parts.append(f"[tool_result] {c if isinstance(c, str) else json.dumps(c)}")
    return "\n".join(p for p in parts if p)


class ClaudeCodeProvider(Provider):
    name = "claude-code"
    description = "Anthropic Claude Code CLI (~/.claude/projects/*.jsonl)"
    implemented = True

    def discover(self, projects: str = "*"):
        files = sorted(
            PROJECTS_DIR.glob(f"{projects}/*.jsonl"),
            key=lambda f: f.stat().st_mtime,
        )
        for f in files:
            yield Session(path=f, key=str(f))

    def parse(self, session: Session, start_offset: int = 0) -> Iterator[tuple[int, Event]]:
        titles = _session_titles(session.path)
        project = session.path.parent.name
        with session.path.open() as fh:
            fh.seek(start_offset)
            while True:
                line = fh.readline()
                if not line:
                    break
                offset = fh.tell()  # readline() (unlike `for line in fh`) allows tell()
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:
                    continue
                typ = o.get("type")
                if typ not in CONTENT_TYPES:
                    continue
                ev = self._to_event(o, project, titles)
                if ev is not None:
                    yield offset, ev

    def _to_event(self, o: dict, project: str, titles: dict[str, str]) -> Event | None:
        sid = o.get("sessionId", "")
        msg = o.get("message", {}) or {}
        ev = Event(
            provider=self.name,
            session_id=sid,
            session_title=titles.get(sid, ""),
            project=project,
            timestamp_ns=_to_epoch_ns(o.get("timestamp")),
            role=o.get("type", ""),
            model=str(msg.get("model", "") or ""),
            stop_reason=str(msg.get("stop_reason", "") or ""),
            body=_render_body(o),
            raw=o,
            metadata={
                "session_id": sid,
                "type": o.get("type", ""),
                "uuid": o.get("uuid", ""),
                "parent_uuid": o.get("parentUuid", "") or "",
            },
        )

        content = msg.get("content")
        if ev.role == "assistant":
            u = msg.get("usage") or {}
            cc = u.get("cache_creation") or {}
            # 5m and 1h writes cost differently (1.25x vs 2x input) — keep them
            # separate. Older transcript shape has only a flat
            # cache_creation_input_tokens; treat that as a 5m write.
            w5m = cc.get("ephemeral_5m_input_tokens", 0) or 0
            w1h = cc.get("ephemeral_1h_input_tokens", 0) or 0
            if not cc:
                w5m = u.get("cache_creation_input_tokens", 0) or 0
            ev.usage = Usage(
                input=u.get("input_tokens", 0) or 0,
                output=u.get("output_tokens", 0) or 0,
                cache_read=u.get("cache_read_input_tokens", 0) or 0,
                cache_write_5m=w5m,
                cache_write_1h=w1h,
            )
            if isinstance(content, list):
                for blk in content:
                    if isinstance(blk, dict) and blk.get("type") == "tool_use":
                        ev.tool_calls.append(
                            ToolCall(tool_use_id=str(blk.get("id", "")),
                                     name=str(blk.get("name", ""))))
        elif ev.role == "user":
            results = ([b for b in content if isinstance(b, dict)
                        and b.get("type") == "tool_result"]
                       if isinstance(content, list) else [])
            for b in results:
                ev.tool_results.append(ToolResult(
                    tool_use_id=str(b.get("tool_use_id", "")),
                    is_error=bool(b.get("is_error"))))
            # A human turn = a user message that isn't purely tool_result plumbing.
            ev.is_human_turn = not (
                isinstance(content, list) and results and len(results) == len(content))
        return ev
