import { AccessToken, RoomServiceClient } from "livekit-server-sdk";

export interface TokenParams {
  identity: string;
  roomName: string;
  metadata?: string;
  ttlSeconds?: number;
}

function getRoomService(): RoomServiceClient {
  const url = process.env.LIVEKIT_URL;
  const apiKey = process.env.LIVEKIT_API_KEY;
  const apiSecret = process.env.LIVEKIT_API_SECRET;
  if (!url || !apiKey || !apiSecret) {
    throw new Error("LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET not set");
  }
  // RoomServiceClient wants an HTTP(S) URL — convert wss:// to https://
  const httpUrl = url.replace(/^wss:\/\//, "https://").replace(/^ws:\/\//, "http://");
  return new RoomServiceClient(httpUrl, apiKey, apiSecret);
}

/**
 * Ensure the LiveKit room exists with interview metadata set on it.
 * This allows the agent worker to read config from ctx.room.metadata.
 */
export async function ensureRoom(roomName: string, metadata?: string): Promise<void> {
  try {
    const svc = getRoomService();
    await svc.createRoom({
      name: roomName,
      metadata: metadata || "",
      emptyTimeout: 600, // 10 min
    });
    console.log(`[livekit] ensureRoom OK: ${roomName}`);
  } catch (e: any) {
    // Room may already exist — that's fine
    console.log(`[livekit] ensureRoom (may already exist): ${e.message ?? e}`);
  }
}

export async function createAccessToken(params: TokenParams): Promise<string> {
  const apiKey = process.env.LIVEKIT_API_KEY;
  const apiSecret = process.env.LIVEKIT_API_SECRET;

  if (!apiKey || !apiSecret) {
    throw new Error("LIVEKIT_API_KEY / LIVEKIT_API_SECRET not set — see backend/.env.example");
  }

  const at = new AccessToken(apiKey, apiSecret, {
    identity: params.identity,
    ttl: params.ttlSeconds ?? 60 * 60, // 1h
    metadata: params.metadata,
  });

  at.addGrant({
    room: params.roomName,
    roomJoin: true,
    canPublish: true,
    canSubscribe: true,
    canPublishData: true,
  });

  // livekit-server-sdk v2: toJwt() returns Promise<string> (agents.md §6 #7)
  return await at.toJwt();
}

export function getLiveKitUrl(): string {
  const url = process.env.LIVEKIT_URL;
  if (!url) throw new Error("LIVEKIT_URL not set");
  return url;
}
