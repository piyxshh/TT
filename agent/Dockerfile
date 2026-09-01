FROM python:3.11-slim

WORKDIR /app

# System deps (for audio / VAD if needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py state.py prompts.py agent.py ./

# Transcripts/recordings are written to mounted volumes or local FS (PRD §4)
# Ensure directories exist
RUN mkdir -p /app/transcripts /app/recordings

# livekit-agents cli handles `dev` / `start` subcommands
# Default: single-room start (override ROOM_NAME via env or --room flag)
CMD ["python", "agent.py", "start"]
