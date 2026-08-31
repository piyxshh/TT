// Mirrors agent/state.py — single source of truth for InterviewState shape (architecture.md §5.1)

export type Speaker = "AI" | "Candidate";
export type InterviewStatus = "in_progress" | "completed" | "abandoned" | "failed";

export interface Turn {
  speaker: Speaker;
  text: string;
  timestamp: string; // ISO 8601
}

export interface InterviewState {
  candidateName: string;
  jobTitle: string;
  questions: string[];
  currentQuestionIndex: number;
  conversationHistory: Turn[];
  status: InterviewStatus;
  audioRecordingPath: string;
  startedAt: string;
  durationSeconds: number;
}

// Extended with backend-only fields
export interface InterviewRecord extends InterviewState {
  id: string;
  roomName: string;
  createdAt: string;
  updatedAt: string;
}

export interface CreateInterviewBody {
  candidateName: string;
  jobTitle: string;
  questions: string[];
  roomName?: string;
}

export interface TokenRequestBody {
  identity: string;
  roomName: string;
  metadata?: string;
}

export interface TokenResponse {
  token: string;
  url: string;
  roomName: string;
  identity: string;
}
