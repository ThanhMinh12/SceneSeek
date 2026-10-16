export type SearchMode = "text" | "image" | "clip";

export interface Health {
  status: "ok";
  version: string;
  similarity_backend: "cpp" | "numpy";
  embedder: string;
  model_loaded: boolean;
  indexed_videos: number;
}

export interface Video {
  id: string;
  display_name: string;
  original_filename: string;
  status: "queued" | "processing" | "ready" | "failed";
  duration_seconds: number | null;
  frame_count: number | null;
  error: string | null;
  created_at: string;
}

export interface Job {
  id: string;
  video_id: string;
  status: "queued" | "processing" | "complete" | "failed";
  progress: number;
  message: string;
  error: string | null;
}

export interface SearchResult {
  video_id: string;
  title: string;
  timestamp_seconds: number;
  end_seconds: number;
  score: number;
  playback_rate: number;
  thumbnail_url: string;
  video_url: string;
}

export interface SearchResponse {
  query_type: SearchMode;
  elapsed_ms: number;
  results: SearchResult[];
}

