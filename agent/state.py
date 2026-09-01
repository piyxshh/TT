"""InterviewState — per-session state machine (PRD §5, F-02).

- Held in memory on the worker; persisted incrementally so F-02 is satisfiable.
- No DB required — local JSON + optional backend POST.
- Critical ordering: Candidate turn is appended BEFORE the LLM call (see agent.py).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

Status = Literal["in_progress", "completed", "abandoned", "failed"]
Speaker = Literal["AI", "Candidate"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Turn:
    speaker: Speaker
    text: str
    timestamp: str = field(default_factory=_now_iso)


@dataclass
class InterviewState:
    candidateName: str
    jobTitle: str
    questions: list[str]
    currentQuestionIndex: int = 0
    conversationHistory: list[Turn] = field(default_factory=list)
    status: Status = "in_progress"
    audioRecordingPath: str = ""
    startedAt: str = field(default_factory=_now_iso)
    durationSeconds: int = 0

    # derived helpers (agents.md §2.6)
    @property
    def totalQuestions(self) -> int:
        return len(self.questions)

    @property
    def isLastQuestion(self) -> bool:
        return self.currentQuestionIndex >= self.totalQuestions - 1

    @property
    def isComplete(self) -> bool:
        return self.currentQuestionIndex >= self.totalQuestions

    def current_question(self) -> str | None:
        if 0 <= self.currentQuestionIndex < len(self.questions):
            return self.questions[self.currentQuestionIndex]
        return None

    def next_question(self) -> str | None:
        nxt = self.currentQuestionIndex + 1
        if 0 <= nxt < len(self.questions):
            return self.questions[nxt]
        return None

    # serialization
    def to_dict(self) -> dict:
        d = asdict(self)
        # ensure Turn list is plain dicts
        d["conversationHistory"] = [asdict(t) if isinstance(t, Turn) else t for t in self.conversationHistory]
        return d

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict) -> "InterviewState":
        hist = []
        for t in data.get("conversationHistory", []):
            if isinstance(t, dict):
                hist.append(Turn(speaker=t["speaker"], text=t["text"], timestamp=t.get("timestamp", _now_iso())))
            elif isinstance(t, Turn):
                hist.append(t)
        return cls(
            candidateName=data.get("candidateName", ""),
            jobTitle=data.get("jobTitle", ""),
            questions=list(data.get("questions", [])),
            currentQuestionIndex=int(data.get("currentQuestionIndex", 0)),
            conversationHistory=hist,
            status=data.get("status", "in_progress"),
            audioRecordingPath=data.get("audioRecordingPath", ""),
            startedAt=data.get("startedAt", _now_iso()),
            durationSeconds=int(data.get("durationSeconds", 0)),
        )

    # duration helper
    def compute_duration(self) -> int:
        try:
            start = datetime.fromisoformat(self.startedAt)
            delta = datetime.now(timezone.utc) - start
            return max(0, int(delta.total_seconds()))
        except Exception:
            return self.durationSeconds


# ---------------------------------------------------------------- persistence

def _transcript_path(interview_id: str) -> Path:
    # repo root is one level above agent/
    root = Path(__file__).resolve().parent.parent
    return root / "transcripts" / f"{interview_id}.json"


def persist_local(state: InterviewState, interview_id: str) -> Path:
    """Write state to transcripts/{id}.json — synchronous, never throws to caller.

    Caller should wrap in try/except; this function also catches internally and logs.
    """
    path = _transcript_path(interview_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    # update duration before persisting
    state.durationSeconds = state.compute_duration()
    try:
        path.write_text(state.to_json(), encoding="utf-8")
    except Exception as e:
        # Use print as fallback logger if structured logger not yet initialized
        print(f"[persist_local] failed for {interview_id}: {e}")
    return path


async def persist_remote(state: InterviewState, interview_id: str, backend_url: str | None = None) -> None:
    """POST transcript to backend if BACKEND_URL is configured. Best-effort."""
    url = backend_url or os.getenv("BACKEND_URL") or os.getenv("BACKEND_INTERNAL_URL")
    if not url:
        return
    endpoint = url.rstrip("/") + f"/api/interviews/{interview_id}/transcript"
    try:
        import httpx  # lazy import so agent still runs without httpx for local-only mode

        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(endpoint, json=state.to_dict())
    except Exception as e:
        print(f"[persist_remote] POST {endpoint} failed: {e}")


async def persist(state: InterviewState, interview_id: str) -> Path:
    """Persist locally and remotely (best-effort). Returns local path."""
    path = persist_local(state, interview_id)
    try:
        await persist_remote(state, interview_id)
    except Exception:
        pass
    return path
