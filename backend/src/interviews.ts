import { randomUUID } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { InterviewRecord, InterviewState } from "./types.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const TRANSCRIPTS_DIR = path.resolve(__dirname, "../../transcripts");

function ensureDir(dir: string) {
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
}

function transcriptPath(id: string) {
  return path.join(TRANSCRIPTS_DIR, `${id}.json`);
}

function sanitizeRoomName(name: string): string {
  return name.replace(/[^a-zA-Z0-9-_]/g, "-").replace(/-+/g, "-").replace(/^-|-$/g, "") || "taptalent-interview";
}

// In-memory store — PRD explicitly says no DB required (architecture.md §5)
const store = new Map<string, InterviewRecord>();

// Hydrate from disk on startup (so restarts don't lose transcripts)
function hydrate() {
  try {
    ensureDir(TRANSCRIPTS_DIR);
    for (const file of fs.readdirSync(TRANSCRIPTS_DIR)) {
      if (!file.endsWith(".json") || file === ".gitkeep") continue;
      const id = path.basename(file, ".json");
      try {
        const raw = fs.readFileSync(path.join(TRANSCRIPTS_DIR, file), "utf-8");
        const data = JSON.parse(raw);
        // Backfill InterviewRecord fields if file was written by agent (which writes InterviewState)
        const rec: InterviewRecord = {
          id,
          roomName: data.roomName ?? sanitizeRoomName(id),
          candidateName: data.candidateName ?? "",
          jobTitle: data.jobTitle ?? "",
          questions: data.questions ?? [],
          currentQuestionIndex: data.currentQuestionIndex ?? 0,
          conversationHistory: data.conversationHistory ?? [],
          status: data.status ?? "in_progress",
          audioRecordingPath: data.audioRecordingPath ?? "",
          startedAt: data.startedAt ?? new Date().toISOString(),
          durationSeconds: data.durationSeconds ?? 0,
          createdAt: data.createdAt ?? data.startedAt ?? new Date().toISOString(),
          updatedAt: data.updatedAt ?? new Date().toISOString(),
        };
        if (!store.has(id)) store.set(id, rec);
      } catch {
        // ignore corrupt file
      }
    }
  } catch {
    // ignore
  }
}

hydrate();

export function createInterview(params: {
  candidateName: string;
  jobTitle: string;
  questions: string[];
  roomName?: string;
}): InterviewRecord {
  const id = randomUUID();
  const now = new Date().toISOString();
  const roomName = sanitizeRoomName(params.roomName || `taptalent-${id.slice(0, 8)}`);
  const rec: InterviewRecord = {
    id,
    roomName,
    candidateName: params.candidateName,
    jobTitle: params.jobTitle,
    questions: params.questions,
    currentQuestionIndex: 0,
    conversationHistory: [],
    status: "in_progress",
    audioRecordingPath: `recordings/${id}.webm`,
    startedAt: now,
    durationSeconds: 0,
    createdAt: now,
    updatedAt: now,
  };
  store.set(id, rec);
  persistToDisk(rec);
  return rec;
}

export function getInterview(id: string): InterviewRecord | undefined {
  return store.get(id);
}

export function listInterviews(): InterviewRecord[] {
  return [...store.values()].sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}

export function updateTranscript(id: string, state: InterviewState & { roomName?: string }): InterviewRecord | undefined {
  const existing = store.get(id);
  if (!existing) {
    // Agent may POST before backend created the record (e.g., pure worker mode)
    // Create a minimal record from the agent's state
    const now = new Date().toISOString();
    const rec: InterviewRecord = {
      id,
      roomName: state.roomName ?? sanitizeRoomName(id),
      candidateName: state.candidateName,
      jobTitle: state.jobTitle,
      questions: state.questions,
      currentQuestionIndex: state.currentQuestionIndex,
      conversationHistory: state.conversationHistory,
      status: state.status,
      audioRecordingPath: state.audioRecordingPath,
      startedAt: state.startedAt,
      durationSeconds: state.durationSeconds,
      createdAt: state.startedAt ?? now,
      updatedAt: now,
    };
    store.set(id, rec);
    persistToDisk(rec);
    return rec;
  }
  const updated: InterviewRecord = {
    ...existing,
    candidateName: state.candidateName ?? existing.candidateName,
    jobTitle: state.jobTitle ?? existing.jobTitle,
    questions: state.questions ?? existing.questions,
    currentQuestionIndex: state.currentQuestionIndex ?? existing.currentQuestionIndex,
    conversationHistory: state.conversationHistory ?? existing.conversationHistory,
    status: state.status ?? existing.status,
    audioRecordingPath: state.audioRecordingPath ?? existing.audioRecordingPath,
    durationSeconds: state.durationSeconds ?? existing.durationSeconds,
    updatedAt: new Date().toISOString(),
  };
  store.set(id, updated);
  persistToDisk(updated);
  return updated;
}

export function persistToDisk(rec: InterviewRecord) {
  try {
    ensureDir(TRANSCRIPTS_DIR);
    fs.writeFileSync(transcriptPath(rec.id), JSON.stringify(rec, null, 2), "utf-8");
  } catch (e) {
    console.error(`[interviews] persist failed for ${rec.id}:`, e);
  }
}

export function deleteInterview(id: string): boolean {
  const ok = store.delete(id);
  try {
    const p = transcriptPath(id);
    if (fs.existsSync(p)) fs.unlinkSync(p);
  } catch {}
  return ok;
}
