import { FormEvent, useEffect, useRef, useState } from "react";
import { api, type Runtime } from "./api";
import type { Health, Job, SearchMode, SearchResponse, SearchResult, Video } from "./types";

const MODES: { value: SearchMode; label: string }[] = [{ value: "text", label: "Text" }, { value: "image", label: "Image" }, { value: "clip", label: "Video clip" }];
const videoAccept = ".mp4,.mov,.mkv,.webm,.avi,.m4v";
const imageAccept = ".jpg,.jpeg,.png,.webp,.bmp";

function formatTime(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return "—";
  const whole = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  return `${hours ? `${hours}:${String(minutes).padStart(2, "0")}` : minutes}:${String(whole % 60).padStart(2, "0")}`;
}

function Icon({ name }: { name: "search" | "upload" | "play" | "film" | "close" }) {
  const paths = {
    search: <><circle cx="11" cy="11" r="7" /><path d="m20 20-4-4" /></>,
    upload: <><path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5" /><path d="M5 14v5h14v-5" /></>,
    play: <path d="m9 7 8 5-8 5Z" />,
    film: <><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M7 5v14M17 5v14M3 9h4m10 0h4M3 15h4m10 0h4" /></>,
    close: <path d="m6 6 12 12M18 6 6 18" />,
  };
  return <svg className="icon" viewBox="0 0 24 24" aria-hidden="true">{paths[name]}</svg>;
}

function ResultCard({ result, onPlay }: { result: SearchResult; onPlay: () => void }) {
  return <article className="result-card">
    <button className="result-visual" onClick={onPlay} aria-label={`Play ${result.title} at ${formatTime(result.timestamp_seconds)}`}><img src={result.thumbnail_url} alt="" loading="lazy" /><span className="play-button"><Icon name="play" /></span><span className="timecode">{formatTime(result.timestamp_seconds)}–{formatTime(result.end_seconds)}</span></button>
    <div className="result-copy"><h3>{result.title}</h3>{Math.abs(result.playback_rate - 1) > .01 && <p>Matched at {Number(result.playback_rate.toFixed(2))}× speed</p>}</div>
  </article>;
}

function Player({ result, onClose }: { result: SearchResult; onClose: () => void }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); onClose(); }
      if (event.key === "Tab") {
        const focusable = dialogRef.current?.querySelectorAll<HTMLElement>("button, video, [href], [tabindex='0']");
        if (!focusable?.length) return;
        const first = focusable[0], last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", keydown);
    return () => { document.body.style.overflow = previousOverflow; document.removeEventListener("keydown", keydown); previousFocus?.focus(); };
  }, [result]);
  return <div className="player-backdrop" onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <div ref={dialogRef} className="player-shell" role="dialog" aria-modal="true" aria-labelledby="player-title">
      <div className="player-heading"><h2 id="player-title">{result.title}</h2><button ref={closeRef} className="icon-button" onClick={onClose} aria-label="Close player"><Icon name="close" /></button></div>
      <video ref={videoRef} src={result.video_url} controls autoPlay tabIndex={0} onError={() => setError(true)} onLoadedMetadata={() => { if (videoRef.current) videoRef.current.currentTime = result.timestamp_seconds; }} />
      {error && <p className="player-error" role="alert">This video could not be played. Try uploading it again to create a new preview.</p>}
      <p className="player-caption">{formatTime(result.timestamp_seconds)}–{formatTime(result.end_seconds)}{Math.abs(result.playback_rate - 1) > .01 ? ` · ${Number(result.playback_rate.toFixed(2))}× reference speed` : ""}</p>
    </div>
  </div>;
}

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [runtime, setRuntime] = useState<Runtime | null>(null);
  const [loading, setLoading] = useState(true);
  const [videos, setVideos] = useState<Video[]>([]);
  const [mode, setMode] = useState<SearchMode>("text");
  const [query, setQuery] = useState("");
  const [queryFile, setQueryFile] = useState<File | null>(null);
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [searching, setSearching] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [jobs, setJobs] = useState<Record<string, Job>>({});
  const [error, setError] = useState<string | null>(null);
  const [playing, setPlaying] = useState<SearchResult | null>(null);
  const uploadInput = useRef<HTMLInputElement>(null);
  const queryFileInput = useRef<HTMLInputElement>(null);
  const readyVideos = videos.filter((video) => video.status === "ready");
  const preparing = videos.some((video) => ["queued", "processing"].includes(video.status));

  const refresh = async () => {
    try {
      const [nextHealth, nextVideos] = await Promise.all([api.health(), api.videos()]);
      setHealth(nextHealth); setVideos(nextVideos);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Could not reach SceneSeek"); }
    finally { setLoading(false); }
  };
  useEffect(() => {
    void refresh(); void api.runtime().then(setRuntime).catch(() => undefined);
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    const active = Object.values(jobs).filter((job) => ["queued", "processing"].includes(job.status));
    if (!active.length) return;
    const timer = window.setInterval(async () => {
      try {
        const updates = await Promise.all(active.map((job) => api.job(job.id)));
        setJobs((current) => ({ ...current, ...Object.fromEntries(updates.map((job) => [job.id, job])) }));
        if (updates.some((job) => ["complete", "failed"].includes(job.status))) void refresh();
      } catch (caught) { setError(caught instanceof Error ? caught.message : "Could not refresh video progress"); }
    }, 1500);
    return () => window.clearInterval(timer);
  }, [jobs]);

  const upload = async (file: File | undefined) => {
    if (!file || uploading) return;
    if (!/\.(mp4|mov|mkv|webm|avi|m4v)$/i.test(file.name)) { setError("Choose an MP4, MOV, MKV, WebM, AVI, or M4V video."); return; }
    if (!file.size) { setError("This video is empty. Choose another file."); return; }
    if (runtime && file.size > runtime.max_upload_mb * 1024 ** 2) { setError(`Choose a video smaller than ${runtime.max_upload_mb} MB.`); return; }
    setUploading(true); setError(null);
    try {
      const created = await api.uploadVideo(file);
      setJobs((current) => ({ ...current, [created.job.id]: created.job }));
      setVideos((current) => [created.video, ...current]); setLibraryOpen(true);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Upload failed"); }
    finally { setUploading(false); if (uploadInput.current) uploadInput.current.value = ""; }
  };
  const search = async (event: FormEvent) => {
    event.preventDefault();
    if (searching || !readyVideos.length || (mode === "text" ? query.trim().length < 2 : !queryFile)) return;
    setSearching(true); setError(null); setLibraryOpen(false); setResponse(null);
    try { setResponse(await api.search(mode, query.trim(), queryFile)); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Search failed"); }
    finally { setSearching(false); }
  };
  const switchMode = (next: SearchMode) => {
    setMode(next); setQueryFile(null); setResponse(null);
    if (queryFileInput.current) queryFileInput.current.value = "";
  };
  const chooseQuery = (file: File | undefined) => {
    if (!file) return;
    const valid = mode === "image" ? /\.(jpg|jpeg|png|webp|bmp)$/i.test(file.name) : /\.(mp4|mov|mkv|webm|avi|m4v)$/i.test(file.name);
    if (!valid || !file.size) { setError(`Choose a non-empty ${mode === "image" ? "image" : "video clip"} in a supported format.`); return; }
    setQueryFile(file); setError(null);
  };
  const remove = async (video: Video) => {
    if (!window.confirm(`Remove “${video.display_name}” and its files?`)) return;
    setDeleting(video.id);
    try { await api.removeVideo(video.id); setResponse(null); await refresh(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Could not remove the video"); }
    finally { setDeleting(null); }
  };

  return <div className="app-shell">
    <a className="skip-link" href="#workspace">Skip to workspace</a>
    <header className="topbar"><a className="brand" href="#top"><span className="brand-mark"><Icon name="play" /></span>SceneSeek</a><div className="top-actions">{videos.length > 0 && <button className="button secondary" onClick={() => uploadInput.current?.click()} disabled={uploading}><Icon name="upload" />{uploading ? "Uploading…" : "Add video"}</button>}<a className="text-link" href="https://github.com/ThanhMinh12/SceneSeek" target="_blank" rel="noreferrer">GitHub ↗</a></div></header>
    <input ref={uploadInput} className="sr-only" aria-label="Upload video" type="file" accept={videoAccept} onChange={(event) => void upload(event.target.files?.[0])} />
    <main id="top">
      <section className="intro"><h1>Find a moment in your videos.</h1><p>Add a video, then search with text, an image, or a clip.</p></section>
      {error && <div className="error-banner" role="alert"><span>{error}</span><button onClick={() => setError(null)} aria-label="Dismiss error">×</button></div>}
      <div id="workspace">
        {loading ? <div className="loading-state" role="status">Loading your library…</div> : !videos.length ? <section className={`upload-empty panel ${dragging ? "dragging" : ""}`} aria-label="Add your first video" onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={(event) => { event.preventDefault(); setDragging(false); void upload(event.dataTransfer.files[0]); }}>
          <span className="empty-icon"><Icon name="film" /></span><h2>Add your first video</h2><p>Choose a video to make its moments searchable.</p><button className="button primary" disabled={uploading} onClick={() => uploadInput.current?.click()}><Icon name="upload" />{uploading ? "Uploading…" : "Choose video"}</button><span className="upload-help">or drag and drop · MP4, MOV, MKV, WebM, AVI, M4V{runtime ? ` · Up to ${runtime.max_video_seconds}s / ${runtime.max_upload_mb} MB` : ""}</span>
        </section> : <>
          <section className="search-panel panel" aria-label="Search your videos">
            <form onSubmit={(event) => void search(event)}>
              <div className="search-heading"><h2>Search your videos</h2><span>{readyVideos.length} ready</span></div>
              <div className="mode-tabs" role="group" aria-label="Search input type">{MODES.map((item) => <button key={item.value} type="button" aria-pressed={mode === item.value} disabled={searching} onClick={() => switchMode(item.value)}>{item.label}</button>)}</div>
              <div className="query-row">{mode === "text" ? <label className="query-input"><Icon name="search" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="A red car on a rainy street" aria-label="Describe the scene to find" minLength={2} required disabled={searching} /></label> : <button type="button" className="file-query" disabled={searching} onClick={() => queryFileInput.current?.click()}><Icon name="upload" /><span>{queryFile ? queryFile.name : mode === "image" ? "Choose a reference image" : "Choose a reference clip"}</span></button>}
                <input ref={queryFileInput} className="sr-only" aria-label={mode === "image" ? "Upload reference image" : "Upload reference clip"} type="file" accept={mode === "image" ? imageAccept : videoAccept} onChange={(event) => { chooseQuery(event.target.files?.[0]); event.target.value = ""; }} />
                <button className="button primary search-button" disabled={searching || !readyVideos.length || (mode === "text" ? query.trim().length < 2 : !queryFile)}>{searching ? "Searching…" : "Search"}</button>
              </div>
              <p className="search-hint" role="status">{!readyVideos.length ? preparing ? "Preparing your video. Search will be ready when processing finishes." : "Add a video that can be processed to start searching." : searching ? "Searching your videos. GPU queues may take a moment." : mode === "text" ? "Describe something visible: a person, place, object, or action." : mode === "image" ? "Use a JPG, PNG, WebP, or BMP image to find similar moments." : "Use a 4–60 second clip. Matching supports different playback speeds."}</p>
            </form>
          </section>
          {response && <section className="results-section" aria-live="polite"><div className="section-heading"><h2>{response.results.length ? `${response.results.length} matching moment${response.results.length === 1 ? "" : "s"}` : "No matching moments"}</h2>{response.results.length > 0 && <span>Click a moment to play</span>}</div>{response.results.length ? <div className="results-grid">{response.results.map((result, index) => <ResultCard key={`${result.video_id}-${result.timestamp_seconds}-${index}`} result={result} onPlay={() => setPlaying(result)} />)}</div> : <div className="no-results"><p>Try a broader description or a different reference.</p></div>}</section>}
          <details className="library panel" open={libraryOpen} onToggle={(event) => setLibraryOpen(event.currentTarget.open)}><summary>Your videos <span className="count">{videos.length}</span>{preparing && <span className="preparing-label">Preparing…</span>}</summary><div className="library-list">{videos.map((video) => {
            const job = Object.values(jobs).find((item) => item.video_id === video.id);
            const active = ["queued", "processing"].includes(video.status);
            const progress = job ? Math.min(100, Math.max(0, Math.round(job.progress * 100))) : 0;
            return <article className="library-row" key={video.id}><div className="video-glyph"><Icon name="film" /></div><div className="video-info"><h3>{video.display_name}</h3><p>{video.status === "ready" ? `${formatTime(video.duration_seconds)} · Ready to search` : video.status === "failed" ? video.error ?? job?.error ?? "Could not process this video. Try a different file." : job?.message ?? "Preparing your video…"}</p>{active && job && <div className="progress" role="progressbar" aria-label={`Preparing ${video.display_name}`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}><span style={{ width: `${progress}%` }} /></div>}</div><button className="text-link remove" disabled={active || deleting === video.id} aria-label={`Remove ${video.display_name}`} onClick={() => void remove(video)}>{deleting === video.id ? "Removing…" : "Remove"}</button></article>;
          })}</div></details>
        </>}
      </div>
      {runtime?.queued_inference && <p className="demo-note">Free demo · Up to 3 videos, {runtime.max_video_seconds}s / {runtime.max_upload_mb} MB each. GPU queues and daily limits apply.<br />Files expire after an hour. Use non-sensitive videos.</p>}
    </main>
    <footer><span>SceneSeek · Video search</span><details><summary>Technical details</summary><p>{health ? `${health.embedder === "clip" ? "CLIP / PyTorch" : "Test embedder"} · ${health.similarity_backend === "cpp" ? "C++" : "NumPy"} similarity search` : "Connecting to the search service…"}</p><a href="/api/docs">API docs ↗</a></details></footer>
    {playing && <Player result={playing} onClose={() => setPlaying(null)} />}
  </div>;
}
