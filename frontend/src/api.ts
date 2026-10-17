import type { Health, Job, SearchMode, SearchResponse, Video } from "./types";
import { runDispatch, type Dispatch } from "./dispatch";

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

let runtimePromise: Promise<{queued_inference: boolean; frame_interval_seconds: number}> | undefined;
function runtime() {
  return runtimePromise ??= fetch('/api/runtime', {cache:'no-store'}).then(r => parse<{queued_inference: boolean; frame_interval_seconds: number}>(r));
}
async function request(path: string, options?: RequestInit) {
  await runtime(); // Establish exactly one signed session before parallel calls.
  return fetch(path, options);
}

export const api = {
  runtime,
  health: () => request("/api/health").then((response) => parse<Health>(response)),

  videos: () => request("/api/videos").then((response) => parse<Video[]>(response)),

  job: (id: string) =>
    request(`/api/jobs/${id}`).then((response) => parse<Job>(response)),

  async uploadVideo(file: File): Promise<{ video: Video; job: Job }> {
    const form = new FormData();
    form.append("file", file);
    const result = await request("/api/videos", { method: "POST", body: form }).then((response) =>
      parse<{ video: Video; job: Job; dispatch?: Dispatch }>(response));
    if (result.dispatch) void runDispatch(result.dispatch).catch(() => undefined);
    return result;
  },

  async removeVideo(id: string): Promise<void> {
    const response = await request(`/api/videos/${id}`, { method: "DELETE" });
    if (!response.ok) await parse(response);
  },

  async search(mode: SearchMode, query: string, file: File | null): Promise<SearchResponse> {
    if (mode === "text") {
      const result = await request("/api/search/text", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, top_k: 12 }),
      }).then((response) => parse<SearchResponse | { dispatch: Dispatch }>(response));
      return "dispatch" in result ? runDispatch<SearchResponse>(result.dispatch) : result;
    }
    if (!file) throw new Error(`Choose an ${mode === "image" ? "image" : "example clip"} first`);
    const form = new FormData();
    form.append("file", file);
    const result = await request(`/api/search/${mode}?top_k=12`, { method: "POST", body: form }).then(
      (response) => parse<SearchResponse | { dispatch: Dispatch }>(response),
    );
    return "dispatch" in result ? runDispatch<SearchResponse>(result.dispatch) : result;
  },
};

