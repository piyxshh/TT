"""InterviewConfig — structured metadata for the Interviewer Agent (PRD C-01..C-04).

Questions are NEVER hardcoded — always sourced from config (C-02), asked in array order (C-03).
Transport: LiveKit room metadata / dispatch payload — room metadata is simplest for single-room demo.
Falls back to env vars CANDIDATE_NAME / JOB_TITLE / QUESTIONS_JSON / ROOM_NAME for local dev.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field


@dataclass
class InterviewConfig:
    candidateName: str
    jobTitle: str
    questions: list[str]
    roomName: str = "taptalent-interview"
    interviewId: str = ""  # backend-generated UUID — used for persist_remote so frontend polling matches

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.candidateName or not self.candidateName.strip():
            errors.append("candidateName is required (C-01)")
        if not self.jobTitle or not self.jobTitle.strip():
            errors.append("jobTitle is required (C-01)")
        if not self.questions or len(self.questions) == 0:
            errors.append("questions[] must not be empty (C-01)")
        else:
            for i, q in enumerate(self.questions):
                if not q or not q.strip():
                    errors.append(f"questions[{i}] must not be empty")
        if not self.roomName or not self.roomName.strip():
            errors.append("roomName is required (A-01)")
        return errors

    @property
    def is_valid(self) -> bool:
        return len(self.validate()) == 0

    # ------------------------------------------------------------------ loaders

    @classmethod
    def from_env(cls) -> "InterviewConfig":
        """Load from env vars — convenient for `python agent.py dev` local runs."""
        raw = os.getenv("QUESTIONS_JSON", "[]")
        try:
            questions = json.loads(raw) if raw.strip().startswith("[") else [s.strip() for s in raw.split("|") if s.strip()]
            if isinstance(questions, str):
                questions = [questions]
        except json.JSONDecodeError:
            questions = []

        return cls(
            candidateName=os.getenv("CANDIDATE_NAME", "").strip(),
            jobTitle=os.getenv("JOB_TITLE", "").strip(),
            questions=[q.strip() for q in questions if q and q.strip()],
            roomName=os.getenv("ROOM_NAME", "taptalent-interview").strip(),
            interviewId="",
        )

    @classmethod
    def from_room_metadata(cls, metadata: str | dict | None, room_name: str | None = None) -> "InterviewConfig":
        """Parse LiveKit room metadata (JSON string or dict). Falls back to env."""
        if not metadata:
            return cls.from_env()

        data: dict = {}
        if isinstance(metadata, str):
            try:
                data = json.loads(metadata)
            except json.JSONDecodeError:
                data = {}
        elif isinstance(metadata, dict):
            data = metadata

        # Support both camelCase (frontend) and snake_case
        candidate = data.get("candidateName") or data.get("candidate_name") or os.getenv("CANDIDATE_NAME", "")
        job = data.get("jobTitle") or data.get("job_title") or os.getenv("JOB_TITLE", "")
        qs = data.get("questions") or data.get("questionsJson") or []
        if isinstance(qs, str):
            try:
                qs = json.loads(qs)
            except json.JSONDecodeError:
                qs = []
        room = data.get("roomName") or data.get("room_name") or room_name or os.getenv("ROOM_NAME", "taptalent-interview")
        interview_id = data.get("interviewId") or data.get("interview_id") or ""

        # If metadata was empty, fall back to env loader that also parses QUESTIONS_JSON
        if not candidate and not job and not qs:
            return cls.from_env()

        return cls(
            candidateName=str(candidate).strip(),
            jobTitle=str(job).strip(),
            questions=[str(q).strip() for q in (qs or []) if str(q).strip()],
            roomName=str(room).strip() or "taptalent-interview",
            interviewId=str(interview_id).strip(),
        )

    def to_dict(self) -> dict:
        d = {
            "candidateName": self.candidateName,
            "jobTitle": self.jobTitle,
            "questions": self.questions,
            "roomName": self.roomName,
        }
        if self.interviewId:
            d["interviewId"] = self.interviewId
        return d
