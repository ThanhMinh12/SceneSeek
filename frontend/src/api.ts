import type { Health, Job, SearchMode, SearchResponse, Video } from "./types";

async function parse<T>(response: Response): Promise<T> {
  if (response.ok) return (await response.json()) as T;
  let message = `Request failed (${response.status})`;
  try {
    const body = (await response.json()) as { detail?: string };
    if (body.detail) message = body.detail;
  } catch {
    // Keep the status-based fallback when the response is not JSON.
  }
  throw new Error(message);
}

export const api = {
  health: () => fetch("/api/health").then((response) => parse<Health>(response)),

  videos: () => fetch("/api/videos").then((response) => parse<Video[]>(response)),

  job: (id: string) =>
    fetch(`/api/jobs/${id}`).then((response) => parse<Job>(response)),

  async uploadVideo(file: File): Promise<{ video: Video; job: Job }> {
    const form = new FormData();
    form.append("file", file);
    return fetch("/api/videos", { method: "POST", body: form }).then((response) =>
      parse<{ video: Video; job: Job }>(response),
    );
  },

  async removeVideo(id: string): Promise<void> {
    const response = await fetch(`/api/videos/${id}`, { method: "DELETE" });
    if (!response.ok) await parse(response);
  },

  async search(mode: SearchMode, query: string, file: File | null): Promise<SearchResponse> {
    if (mode === "text") {
      return fetch("/api/search/text", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, top_k: 12 }),
      }).then((response) => parse<SearchResponse>(response));
    }
    if (!file) throw new Error(`Choose an ${mode === "image" ? "image" : "example clip"} first`);
    const form = new FormData();
    form.append("file", file);
    return fetch(`/api/search/${mode}?top_k=12`, { method: "POST", body: form }).then(
      (response) => parse<SearchResponse>(response),
    );
  },
};

