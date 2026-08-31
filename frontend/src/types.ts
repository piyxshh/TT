export type Speaker = "AI" | "Candidate";
export type InterviewStatus = "in_progress" | "completed" | "abandoned" | "failed";

export interface Turn {
  speaker: Speaker;
  text: string;
  timestamp: string;
}

export interface InterviewRecord {
  id: string;
  roomName: string;
  candidateName: string;
  jobTitle: string;
  questions: string[];
  currentQuestionIndex: number;
  conversationHistory: Turn[];
  status: InterviewStatus;
  audioRecordingPath: string;
  startedAt: string;
  durationSeconds: number;
  createdAt: string;
  updatedAt: string;
}
