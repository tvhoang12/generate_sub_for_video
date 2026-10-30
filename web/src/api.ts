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
  bold?: boolean;
  italic?: boolean;
  margin_l?: number;
  margin_r?: number;
  margin_v?: number;
  outline?: number;
  shadow?: number;
  burn_video?: boolean;
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
  const res = await fetch(`/api${path}`, {
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
