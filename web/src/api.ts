export type JobStatus = "queued" | "running" | "done" | "failed";

export interface Option {
  code: string;
  label: string;
}

export interface Meta {
  languages: Option[];
  source_languages: Option[];
  provider: string;
  model: string;
  steps: string[];
}

export interface Film {
  id: number;
  name: string;
  source_language: string;
  synopsis: string;
  characters: string;
  style_notes: string;
  term_count?: number;
  suggested_count?: number;
}

export interface Term {
  id: number;
  film_id: number;
  term: string;
  note: string;
  translations: Record<string, string>;
  suggested: boolean;
}

export interface FilmDetail extends Film {
  terms: Term[];
}

export interface JobOutput {
  file: string;
  kind: "srt" | "video";
  lang: string;
}

export interface SubtitleConfig {
  font?: string;
  font_size?: number;
  color?: string;
  color_border?: string;
  has_border?: boolean;
  has_shadow?: boolean;
  color_shadow?: string;
  bold?: boolean;
  italic?: boolean;
  margin_l?: number;
  margin_r?: number;
  margin_v?: number;
  /** Which edge margin_v is measured from: bottom = lines grow upward, top = lines grow downward. */
  v_anchor?: "bottom" | "top";
  /** Frame (video px) the pixel values above were set on; the backend rescales them to the real video. */
  ref_width?: number;
  ref_height?: number;
  outline?: number;
  shadow?: number;
  line_spacing?: number;
  mask_padding_x?: number;
  burn_video?: boolean;
  mask_enabled?: boolean;
  mask_color?: string;
  mask_blur?: number;
  mask_opacity?: number;
  mask_shape?: "pill" | "rounded" | "rectangle" | "bar";
  mask_by_text?: boolean;
}

export interface Job {
  id: number;
  film_id: number | null;
  title: string;
  video_filename: string;
  languages: string[];
  episode_notes: string;
  subtitle_config?: SubtitleConfig;
  status: JobStatus;
  step: string | null;
  progress: number;
  error: string | null;
  provider: string | null;
  report: {
    source_language?: string;
    dropped?: { id: number; start: string; end: string; text: string }[];
    warnings?: string[];
    outputs?: JobOutput[];
    suggested_terms?: { term: string; note: string }[];
    homophone_corrections?: {
      id: number;
      original: string;
      corrected: string;
      pinyin: string;
      explanation: string;
    }[];
  };
  created_at: string;
  finished_at: string | null;
}

export class ApiError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const url = path.startsWith("/api") ? path : `/api${path.startsWith("/") ? path : `/${path}`}`;
  const res = await fetch(url, {
    ...init,
    headers: init?.body && !(init.body instanceof FormData) ? { "Content-Type": "application/json" } : undefined,
  });
  if (!res.ok) {
    let message = `Lỗi ${res.status}`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") message = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(message);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

const json = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body) });

export const api = {
  meta: () => request<Meta>("/meta"),
  films: () => request<Film[]>("/films"),
  film: (id: number) => request<FilmDetail>(`/films/${id}`),
  createFilm: (body: Partial<Film>) => request<Film>("/films", json("POST", body)),
  updateFilm: (id: number, body: Partial<Film>) => request<Film>(`/films/${id}`, json("PUT", body)),
  deleteFilm: (id: number) => request<void>(`/films/${id}`, { method: "DELETE" }),
  addTerm: (filmId: number, body: Partial<Term>) => request<Term>(`/films/${filmId}/terms`, json("POST", body)),
  updateTerm: (id: number, body: Partial<Term>) => request<Term>(`/terms/${id}`, json("PUT", body)),
  deleteTerm: (id: number) => request<void>(`/terms/${id}`, { method: "DELETE" }),
  jobs: () => request<Job[]>("/jobs"),
  job: (id: number) => request<Job>(`/jobs/${id}`),
  retryJob: (id: number) => request<Job>(`/jobs/${id}/retry`, { method: "POST" }),
  deleteJob: (id: number) => request<void>(`/jobs/${id}`, { method: "DELETE" }),
  fileUrl: (jobId: number, name: string) => `/api/jobs/${jobId}/files/${encodeURIComponent(name)}`,
  zipUrl: (jobId: number) => `/api/jobs/${jobId}/download`,
  getQueueStatus: () =>
    request<{ running: number; queued: number; max_concurrent: number }>("/api/queue"),
};

export type HlsJobStatus = "uploading" | "uploaded" | "queued" | "processing" | "done" | "error";

export interface HlsJob {
  id: string;
  filename: string;
  original_name: string;
  source_size: number | null;
  status: HlsJobStatus;
  progress: number;
  current_rendition: string | null;
  selected_renditions: string[];
  skipped_renditions: string[];
  completed_renditions: string[];
  logs: string[];
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
  src_height: number | null;
  output_dir: string | null;
  queue_position: number | null;
}

export interface RenditionInfo {
  label: string;
  resolution: string;
  bitrateLabel: string;
}

export const HLS_RENDITIONS: RenditionInfo[] = [
  { label: "360p", resolution: "640×360", bitrateLabel: "~800 Kbps" },
  { label: "480p", resolution: "842×480", bitrateLabel: "~1.4 Mbps" },
  { label: "720p", resolution: "1280×720", bitrateLabel: "~2.8 Mbps" },
  { label: "1080p", resolution: "1920×1080", bitrateLabel: "~5.0 Mbps" },
];

export const hlsApi = {
  initUpload: (filename: string, fileSize: number, renditions: string[]) =>
    request<{ id: string; filename: string }>("/hls/upload/init", {
      method: "POST",
      body: JSON.stringify({ filename, fileSize, renditions }),
    }),
  uploadFile: (
    jobId: string,
    file: File,
    onProgress: (percent: number) => void,
    onAbortRef?: (abort: () => void) => void,
  ): Promise<void> => {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      if (onAbortRef) onAbortRef(() => xhr.abort());
      xhr.open("PUT", `/api/hls/upload/${jobId}`);
      xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(Math.round((e.loaded / e.total) * 100));
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          onProgress(100);
          resolve();
        } else {
          let msg = "Upload thất bại";
          try {
            const body = JSON.parse(xhr.responseText);
            msg = body.detail || body.message || msg;
          } catch {
            if (xhr.responseText) msg = xhr.responseText;
          }
          reject(new ApiError(msg));
        }
      };
      xhr.onerror = () => reject(new ApiError("Mất kết nối tới máy chủ trong lúc upload"));
      xhr.onabort = () => reject(new ApiError("Upload đã bị hủy"));
      xhr.send(file);
    });
  },
  startJobs: (ids: string[]) =>
    request<{ started: number; reused: string[] }>("/hls/jobs/start", {
      method: "POST",
      body: JSON.stringify({ ids }),
    }),
  listJobs: () => request<{ jobs: HlsJob[] }>("/hls/jobs"),
  getJob: (jobId: string) => request<HlsJob>(`/hls/jobs/${jobId}`),
  deleteJob: (jobId: string) =>
    request<{ success: boolean; message: string }>(`/hls/jobs/${jobId}`, { method: "DELETE" }),
  deleteJobs: (ids?: string[], all?: boolean) =>
    request<{ success: boolean; count: number; message: string }>("/hls/jobs", {
      method: "DELETE",
      body: JSON.stringify({ ids, all }),
    }),
  downloadUrl: (jobId: string, rendition?: string) =>
    `/api/hls/download/${jobId}${rendition ? `?rendition=${encodeURIComponent(rendition)}` : ""}`,
  batchDownloadUrl: (ids?: string[], all?: boolean) =>
    `/api/hls/download/batch?${all ? "all=true" : `ids=${ids?.join(",") || ""}`}`,
  streamUrl: (jobId: string) => `/hls/${jobId}/master.m3u8`,
  getQueueStatus: () =>
    request<{ running: number; queued: number; max_concurrent: number; active_job_ids?: string[] }>(
      "/hls/queue"
    ),
};

/** Multipart upload through XHR, the only browser API that reports upload progress. */
export function uploadJob(form: FormData, onProgress: (percent: number) => void): Promise<Job> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/jobs");
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(Math.round((e.loaded / e.total) * 100));
    xhr.onload = () => {
      let body: { detail?: unknown } & Partial<Job> = {};
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* keep empty */
      }
      if (xhr.status === 201) resolve(body as Job);
      else reject(new ApiError(typeof body.detail === "string" ? body.detail : `Lỗi ${xhr.status}`));
    };
    xhr.onerror = () => reject(new ApiError("Mất kết nối tới máy chủ"));
    xhr.send(form);
  });
}

export const STEP_LABELS: Record<string, string> = {
  extract: "Tách âm thanh",
  transcribe: "Nhận dạng giọng nói",
  clean: "Soát lỗi bản gốc",
  translate: "Dịch",
  render: "Gắn phụ đề",
};

export function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

export function formatTime(iso: string): string {
  // The API stores UTC; SQLite drops the offset, so mark it explicitly before converting.
  const date = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`);
  return date.toLocaleString("vi-VN", { dateStyle: "short", timeStyle: "short" });
}
