import "dotenv/config";
import cors from "cors";
import express from "express";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createAccessToken, getLiveKitUrl, ensureRoom } from "./livekit.js";
import { createInterview, getInterview, listInterviews, updateTranscript } from "./interviews.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const app = express();
const PORT = Number(process.env.PORT || 3000);
const FRONTEND_URL = process.env.FRONTEND_URL || "http://localhost:5173";

// ---------------------------------------------------------------- middleware
app.use(cors({ origin: [FRONTEND_URL, "http://localhost:5173", "http://localhost:3000"], credentials: true }));
app.use(express.json({ limit: "2mb" }));

// Serve transcripts + recordings as static (R-03/R-04) — local FS per PRD §4
const transcriptsDir = path.resolve(__dirname, "../../transcripts");
const recordingsDir = path.resolve(__dirname, "../../recordings");
app.use("/transcripts", express.static(transcriptsDir));
app.use("/recordings", express.static(recordingsDir));

// ---------------------------------------------------------------- health
app.get("/health", (_req, res) => {
  res.json({ ok: true, livekitUrl: process.env.LIVEKIT_URL ? "configured" : "missing" });
});

app.get("/api/health", (_req, res) => {
  res.json({ ok: true });
});

// ---------------------------------------------------------------- token — PRD A-01
// POST /api/token  { identity, roomName, metadata? } -> { token, url }
// metadata is InterviewConfig JSON stringified — forwarded to LiveKit room metadata
// NOTE: createAccessToken is async in livekit-server-sdk v2 (agents.md §6 #7)
app.post("/api/token", async (req, res) => {
  try {
    const { identity, roomName, metadata } = req.body as {
      identity?: string;
      roomName?: string;
      metadata?: string;
    };

    if (!identity || !roomName) {
      return res.status(400).json({ error: "identity and roomName are required" });
    }

    // identity must be unique per participant — prefix candidate vs agent
    // Ensure room exists on LiveKit with interview metadata so agent can read ctx.room.metadata
    await ensureRoom(String(roomName).trim(), metadata ? String(metadata) : undefined);

    const token = await createAccessToken({
      identity: String(identity).trim(),
      roomName: String(roomName).trim(),
      metadata: metadata ? String(metadata) : undefined,
    });

    res.json({
      token,
      url: getLiveKitUrl(),
      roomName: String(roomName).trim(),
      identity: String(identity).trim(),
    });
  } catch (e: any) {
    console.error("[POST /api/token]", e);
    res.status(500).json({ error: e.message ?? "token generation failed" });
  }
});

// ---------------------------------------------------------------- interviews — PRD R-01..R-05, NF-01
// POST /api/interviews  { candidateName, jobTitle, questions[], roomName? }
app.post("/api/interviews", (req, res) => {
  const { candidateName, jobTitle, questions, roomName } = req.body as {
    candidateName?: string;
    jobTitle?: string;
    questions?: string[];
    roomName?: string;
  };

  const errors: string[] = [];
  if (!candidateName?.trim()) errors.push("candidateName is required (C-01)");
  if (!jobTitle?.trim()) errors.push("jobTitle is required (C-01)");
  if (!Array.isArray(questions) || questions.length === 0) errors.push("questions[] must not be empty (C-01)");
  if (Array.isArray(questions) && questions.some((q) => !String(q).trim())) errors.push("questions[] must not contain empty strings");

  if (errors.length) return res.status(400).json({ errors });

  const rec = createInterview({
    candidateName: String(candidateName).trim(),
    jobTitle: String(jobTitle).trim(),
    questions: (questions as string[]).map((q) => String(q).trim()),
    roomName: roomName?.trim(),
  });

  res.status(201).json(rec);
});

app.get("/api/interviews", (_req, res) => {
  res.json(listInterviews());
});

app.get("/api/interviews/:id", (req, res) => {
  const rec = getInterview(req.params.id);
  if (!rec) return res.status(404).json({ error: "interview not found" });
  res.json(rec);
});

// Agent posts incremental + final transcript (architecture.md §4.3, F-02)
app.post("/api/interviews/:id/transcript", (req, res) => {
  const id = req.params.id;
  const body = req.body as any;

  // Accept both InterviewState and InterviewRecord shapes
  if (!body || typeof body.candidateName !== "string") {
    return res.status(400).json({ error: "invalid transcript body — expected InterviewState" });
  }

  const updated = updateTranscript(id, body);
  res.json(updated);
});

// Lightweight audio URL helper — R-04
app.get("/api/interviews/:id/audio", (req, res) => {
  const rec = getInterview(req.params.id);
  if (!rec) return res.status(404).json({ error: "interview not found" });
  // Local FS path — frontend can fetch /recordings/{id}.webm directly
  // If LiveKit Egress is configured, this would return an Egress URL instead
  const audioUrl = rec.audioRecordingPath ? `/${rec.audioRecordingPath}` : null;
  res.json({ audioUrl, recordingPath: rec.audioRecordingPath });
});

// ---------------------------------------------------------------- 404
app.use((_req, res) => res.status(404).json({ error: "not found" }));

// ---------------------------------------------------------------- start
app.listen(PORT, () => {
  console.log(`[backend] listening on http://localhost:${PORT}`);
  console.log(`[backend] frontend CORS: ${FRONTEND_URL}`);
  console.log(`[backend] livekit url: ${process.env.LIVEKIT_URL ?? "(not set)"}`);
  console.log(`[backend] transcripts: ${transcriptsDir}`);
  console.log(`[backend] recordings: ${recordingsDir}`);
});
