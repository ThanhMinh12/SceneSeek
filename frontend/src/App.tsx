import { FormEvent, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { Health, Job, SearchMode, SearchResponse, SearchResult, Video } from "./types";

const MODES: { value: SearchMode; label: string; hint: string }[] = [
  { value: "text", label: "Describe", hint: "A red car turning onto a rainy street" },
  { value: "image", label: "Use image", hint: "Drop a reference image" },
  { value: "clip", label: "Match clip", hint: "A 4–60 second reference clip" },
];

const videoAccept = ".mp4,.mov,.mkv,.webm,.avi,.m4v";
const imageAccept = ".jpg,.jpeg,.png,.webp,.bmp";

function formatTime(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return "—";
  const whole = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const remaining = whole % 60;
  return hours
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(remaining).padStart(2, "0")}`
    : `${minutes}:${String(remaining).padStart(2, "0")}`;
}

function Icon({ name }: { name: "search" | "upload" | "play" | "film" | "close" }) {
  const paths = {
    search: <><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></>,
    upload: <><path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5"/><path d="M5 14v5h14v-5"/></>,
    play: <path d="m9 7 8 5-8 5Z"/>,
    film: <><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 5v14M17 5v14M3 9h4m10 0h4M3 15h4m10 0h4"/></>,
    close: <path d="m6 6 12 12M18 6 6 18"/>,
  };
  return <svg className="icon" viewBox="0 0 24 24" aria-hidden="true">{paths[name]}</svg>;
}

function ResultCard({ result, onPlay }: { result: SearchResult; onPlay: () => void }) {
  return (
    <article className="result-card">
      <button className="result-visual" onClick={onPlay} aria-label={`Play ${result.title} at ${formatTime(result.timestamp_seconds)}`}>
        <img src={result.thumbnail_url} alt="" loading="lazy" />
        <span className="play-button"><Icon name="play" /></span>
        <span className="timecode">{formatTime(result.timestamp_seconds)}</span>
      </button>
      <div className="result-copy">
        <div>
          <h3>{result.title}</h3>
          <p>{formatTime(result.timestamp_seconds)}–{formatTime(result.end_seconds)}</p>
        </div>
        <span className="score">{Math.round(Math.max(0, result.score) * 100)}%</span>
      </div>
      {Math.abs(result.playback_rate - 1) > 0.01 && (
        <p className="rate-note">Source advances {result.playback_rate.toFixed(2)}× the reference speed</p>
      )}
    </article>
  );
}

function Player({ result, onClose }: { result: SearchResult; onClose: () => void }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [error, setError] = useState(false);
  return (
    <div className="player-backdrop" role="dialog" aria-modal="true" aria-label={`Playing ${result.title}`}>
      <div className="player-shell">
        <div className="player-heading">
          <div><span>NOW PLAYING</span><h2>{result.title}</h2></div>
          <button className="icon-button" onClick={onClose} aria-label="Close player"><Icon name="close" /></button>
        </div>
        <video
          ref={videoRef}
          src={result.video_url}
          controls
          autoPlay
          onError={() => setError(true)}
          onLoadedMetadata={() => {
            if (videoRef.current) videoRef.current.currentTime = result.timestamp_seconds;
          }}
        />
        {error && <p role="alert">This browser could not play the video. Re-index it with FFmpeg enabled to create a compatible WebM preview.</p>}
        <p className="player-caption">Jumped to {formatTime(result.timestamp_seconds)} · similarity {Math.round(result.score * 100)}%</p>
      </div>
    </div>
  );
}

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [hosted, setHosted] = useState(false);
  const [frameInterval, setFrameInterval] = useState(2);
  const [videos, setVideos] = useState<Video[]>([]);
  const [mode, setMode] = useState<SearchMode>("text");
  const [query, setQuery] = useState("");
  const [queryFile, setQueryFile] = useState<File | null>(null);
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [searching, setSearching] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [jobs, setJobs] = useState<Record<string, Job>>({});
  const [error, setError] = useState<string | null>(null);
  const [playing, setPlaying] = useState<SearchResult | null>(null);
  const uploadInput = useRef<HTMLInputElement>(null);
  const queryFileInput = useRef<HTMLInputElement>(null);

  const refresh = async () => {
    try {
      const [nextHealth, nextVideos] = await Promise.all([api.health(), api.videos()]);
      setHealth(nextHealth);
      setVideos(nextVideos);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not reach SceneSeek");
    }
  };

  useEffect(() => {
    void refresh();
    void fetch('/api/runtime').then(r => r.json()).then(r => {setHosted(Boolean(r.queued_inference)); setFrameInterval(r.frame_interval_seconds ?? 2);}).catch(() => undefined);
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const active = Object.values(jobs).filter((job) => ["queued", "processing"].includes(job.status));
    if (!active.length) return;
    const timer = window.setInterval(async () => {
      const updates = await Promise.all(active.map((job) => api.job(job.id)));
      setJobs((current) => ({ ...current, ...Object.fromEntries(updates.map((job) => [job.id, job])) }));
      if (updates.some((job) => ["complete", "failed"].includes(job.status))) void refresh();
    }, 1500);
    return () => window.clearInterval(timer);
  }, [jobs]);

  const upload = async (file: File | undefined) => {
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const created = await api.uploadVideo(file);
      setJobs((current) => ({ ...current, [created.job.id]: created.job }));
      setVideos((current) => [created.video, ...current]);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Upload failed");
    } finally {
      setUploading(false);
      if (uploadInput.current) uploadInput.current.value = "";
    }
  };

  const search = async (event: FormEvent) => {
    event.preventDefault();
    setSearching(true);
    setError(null);
    try {
      setResponse(await api.search(mode, query.trim(), queryFile));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Search failed");
    } finally {
      setSearching(false);
    }
  };

  const switchMode = (next: SearchMode) => {
    setMode(next);
    setQueryFile(null);
    setResponse(null);
  };

  const currentMode = MODES.find((item) => item.value === mode)!;
  const activeJobs = Object.values(jobs).filter((job) => job.status !== "complete");
  const readyVideos = videos.filter((video) => video.status === "ready");

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="SceneSeek home"><span className="brand-mark"><i /></span>SceneSeek</a>
        <nav aria-label="Primary navigation">
          <a href="#search">Search</a>
          <a href="#library">Library</a>
          <a href="/api/docs">API</a>
        </nav>
        <div className="top-actions">
          <span className={`system-status ${health ? "online" : ""}`}><i />{health ? `${health.similarity_backend.toUpperCase()} INDEX` : "CONNECTING"}</span>
          <button className="button small" onClick={() => uploadInput.current?.click()} disabled={uploading}>
            <Icon name="upload" />{uploading ? "Uploading…" : "Add video"}
          </button>
          <input ref={uploadInput} className="sr-only" type="file" accept={videoAccept} onChange={(event) => void upload(event.target.files?.[0])} />
        </div>
      </header>

      <main id="top">
        {hosted && <p style={{padding:'16px 0',fontSize:13}}>Free hosted demo · Three videos, up to 60 seconds / 40 MB each. GPU queues and daily limits apply. Use non-sensitive media; libraries expire after an hour.</p>}
        <section className="hero" id="search">
          <div className="eyebrow"><span>01</span> MULTIMODAL VIDEO RETRIEVAL</div>
          <h1>Find the <em>exact</em><br />moment.</h1>
          <p className="hero-copy">Search an entire video collection with a sentence, a still image, or a short clip—even when the matching scene plays at a different speed.</p>

          <form className="search-panel" onSubmit={(event) => void search(event)}>
            <div className="mode-tabs" role="tablist" aria-label="Search input type">
              {MODES.map((item) => (
                <button key={item.value} type="button" role="tab" aria-selected={mode === item.value} onClick={() => switchMode(item.value)}>{item.label}</button>
              ))}
            </div>
            <div className="query-row">
              <Icon name="search" />
              {mode === "text" ? (
                <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={currentMode.hint} aria-label="Describe the scene to find" minLength={2} required />
              ) : (
                <button type="button" className="file-query" onClick={() => queryFileInput.current?.click()}>
                  {queryFile ? queryFile.name : currentMode.hint}
                </button>
              )}
              <input ref={queryFileInput} className="sr-only" type="file" accept={mode === "image" ? imageAccept : videoAccept} onChange={(event) => setQueryFile(event.target.files?.[0] ?? null)} />
              <button className="search-button" disabled={searching || !readyVideos.length}>
                {searching ? "Searching…" : "Search"}<span>↗</span>
              </button>
            </div>
            <div className="search-meta">
              <span>{readyVideos.length} video{readyVideos.length === 1 ? "" : "s"} indexed</span>
              <span>Frames sampled every {frameInterval} second{frameInterval === 1 ? '' : 's'}</span>
              <span>{health?.embedder === "clip" ? "CLIP · PyTorch" : "Deterministic test model"}</span>
            </div>
          </form>

          {error && <div className="error-banner" role="alert"><strong>Something went wrong.</strong> {error}<button onClick={() => setError(null)} aria-label="Dismiss error">×</button></div>}
        </section>

        {response && (
          <section className="results-section" aria-live="polite">
            <div className="section-heading">
              <div><span>SEARCH RESULTS</span><h2>{response.results.length ? `${response.results.length} moments found` : "No matching moments"}</h2></div>
              <p>{Math.round(response.elapsed_ms)} ms</p>
            </div>
            {response.results.length ? (
              <div className="results-grid">{response.results.map((result, index) => <ResultCard key={`${result.video_id}-${result.timestamp_seconds}-${index}`} result={result} onPlay={() => setPlaying(result)} />)}</div>
            ) : (
              <div className="empty-state"><Icon name="film" /><h3>Try a broader description</h3><p>Search works best with visible subjects, environments, colors, actions, and composition.</p></div>
            )}
          </section>
        )}

        <section className="workflow-strip" aria-label="How SceneSeek works">
          <div><span>01 / INGEST</span><h3>Sample</h3><p>Decode videos into timestamped frames.</p></div>
          <div><span>02 / UNDERSTAND</span><h3>Embed</h3><p>Project text and pixels into one CLIP space.</p></div>
          <div><span>03 / RETRIEVE</span><h3>Match</h3><p>Rank moments and align clip sequences in C++.</p></div>
        </section>

        <section className="library-section" id="library">
          <div className="section-heading">
            <div><span>VIDEO LIBRARY</span><h2>Your searchable collection</h2></div>
            <button className="text-button" onClick={() => uploadInput.current?.click()}>Add another video ↗</button>
          </div>
          {activeJobs.map((job) => (
            <div className="job-row" key={job.id}>
              <div className="job-pulse" />
              <div><strong>{job.message}</strong><span>{job.error ?? "Embedding and indexing in the background"}</span></div>
              <div className="progress"><i style={{ width: `${Math.round(job.progress * 100)}%` }} /></div>
              <b>{Math.round(job.progress * 100)}%</b>
            </div>
          ))}
          <div className="library-table">
            {videos.length ? videos.map((video) => (
              <article className="library-row" key={video.id}>
                <div className="video-glyph"><Icon name="film" /></div>
                <div className="video-name"><h3>{video.display_name}</h3><p>{video.original_filename}</p></div>
                <div><span className="label">DURATION</span><strong>{formatTime(video.duration_seconds)}</strong></div>
                <div><span className="label">MOMENTS</span><strong>{video.frame_count ?? "—"}</strong></div>
                <span className={`status-pill ${video.status}`}>{video.status}</span>
                <button className="remove-button" onClick={async () => { if (window.confirm(`Remove ${video.display_name} from the index?`)) { await api.removeVideo(video.id); void refresh(); } }} aria-label={`Remove ${video.display_name}`}>Remove</button>
              </article>
            )) : (
              <button className="library-empty" onClick={() => uploadInput.current?.click()}>
                <Icon name="upload" /><strong>Build your first index</strong><span>Upload an MP4, MOV, MKV, WebM, AVI, or M4V file.</span>
              </button>
            )}
          </div>
        </section>
      </main>

      <footer><a className="brand" href="#top"><span className="brand-mark"><i /></span>SceneSeek</a><p>Multimodal retrieval for the moments you can picture but can’t locate.</p><span>v{health?.version ?? "0.1.0"}</span></footer>
      {playing && <Player result={playing} onClose={() => setPlaying(null)} />}
    </div>
  );
}
