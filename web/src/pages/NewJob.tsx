import { useEffect, useRef, useState, type DragEvent } from "react";
import { Link, useNavigate } from "react-router";
import { FileVideo, Languages, Play, Upload, X } from "lucide-react";
import { api, formatBytes, uploadJob, type Film, type SubtitleConfig } from "../api";
import { useMeta } from "../meta";
import { Alert, Button, Card, Field, PageHeader, ProgressBar } from "../components/ui";
import { DEFAULT_SUBTITLE_CONFIG, SubtitleConfigCard } from "../components/SubtitleConfigCard";

const ACCEPT = ".mp4,.mov,.mkv,.webm,.m4v";
const LAST_LANGS_KEY = "substudio:last-languages";
const LAST_SUB_CONFIG_KEY = "substudio:last-subtitle-config";

function loadLastLanguages(): string[] {
  try {
    return JSON.parse(localStorage.getItem(LAST_LANGS_KEY) || "[]");
  } catch {
    return [];
  }
}

function loadLastSubtitleConfig(): SubtitleConfig {
  try {
    const raw = localStorage.getItem(LAST_SUB_CONFIG_KEY);
    return raw ? { ...DEFAULT_SUBTITLE_CONFIG, ...JSON.parse(raw) } : DEFAULT_SUBTITLE_CONFIG;
  } catch {
    return DEFAULT_SUBTITLE_CONFIG;
  }
}

export function NewJobPage() {
  const meta = useMeta();
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const [films, setFilms] = useState<Film[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [title, setTitle] = useState("");
  const [filmId, setFilmId] = useState<string>("");
  const [languages, setLanguages] = useState<string[]>(loadLastLanguages);
  const [notes, setNotes] = useState("");
  const [subConfig, setSubConfig] = useState<SubtitleConfig>(loadLastSubtitleConfig);
  const [burnVideo, setBurnVideo] = useState(true);
  const [upload, setUpload] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [touched, setTouched] = useState(false);

  useEffect(() => {
    api.films().then(setFilms).catch(() => setFilms([]));
  }, []);

  const pick = (f: File | undefined) => {
    if (!f) return;
    setFile(f);
    if (!title) setTitle(f.name.replace(/\.[^.]+$/, ""));
    setError(null);
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    pick(e.dataTransfer.files[0]);
  };

  const toggle = (code: string) =>
    setLanguages((prev) => (prev.includes(code) ? prev.filter((c) => c !== code) : [...prev, code]));

  const film = films.find((f) => String(f.id) === filmId);
  const problems = { file: !file ? "Chọn một file video" : "", languages: languages.length ? "" : "Chọn ít nhất một ngôn ngữ" };

  const submit = async () => {
    setTouched(true);
    if (!file || !languages.length) return;
    const form = new FormData();
    form.append("file", file);
    form.append("languages", languages.join(","));
    form.append("title", title);
    form.append("episode_notes", notes);
    const payloadConfig = { ...subConfig, burn_video: burnVideo };
    form.append("subtitle_config", JSON.stringify(payloadConfig));
    if (filmId) form.append("film_id", filmId);
    setError(null);
    setUpload(0);
    try {
      localStorage.setItem(LAST_LANGS_KEY, JSON.stringify(languages));
      localStorage.setItem(LAST_SUB_CONFIG_KEY, JSON.stringify(payloadConfig));
    } catch {
      /* storage unavailable: nothing to remember */
    }
    try {
      const job = await uploadJob(form, setUpload);
      navigate(`/jobs/${job.id}`);
    } catch (e) {
      setError((e as Error).message);
      setUpload(null);
    }
  };

  return (
    <>
      <PageHeader
        title="Tạo phụ đề cho video"
        description="Tải video lên, chọn ngôn ngữ. Hệ thống tự nhận dạng lời thoại, dịch và gắn phụ đề — mỗi ngôn ngữ ra một video riêng."
      />

      <div className="grid gap-6 lg:grid-cols-[1fr_340px]">
        <div className="flex flex-col gap-6">
          <Card title="1. Video gốc">
            {!file ? (
              <button
                type="button"
                onClick={() => inputRef.current?.click()}
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragging(true);
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={onDrop}
                className={`flex w-full flex-col items-center gap-3 rounded-xl border-2 border-dashed px-6 py-12 text-center transition-colors duration-200 ${
                  dragging ? "border-primary bg-primary/5" : "border-slate-300 hover:border-primary hover:bg-primary/5"
                }`}
              >
                <Upload className="size-10 text-primary" aria-hidden />
                <span className="font-semibold">Kéo thả video vào đây hoặc bấm để chọn file</span>
                <span className="text-sm text-muted-foreground">MP4, MOV, MKV, WEBM</span>
              </button>
            ) : (
              <div className="flex items-center gap-4 rounded-xl bg-muted px-4 py-3">
                <FileVideo className="size-8 shrink-0 text-primary" aria-hidden />
                <div className="min-w-0 flex-1">
                  <p className="truncate font-semibold">{file.name}</p>
                  <p className="text-sm text-muted-foreground">{formatBytes(file.size)}</p>
                </div>
                <Button variant="ghost" icon={X} onClick={() => setFile(null)} disabled={upload !== null} aria-label="Bỏ chọn video">
                  Đổi file
                </Button>
              </div>
            )}
            <input ref={inputRef} type="file" accept={ACCEPT} className="sr-only" tabIndex={-1} aria-hidden
              onChange={(e) => pick(e.target.files?.[0])} />
            {touched && problems.file && <p className="mt-2 text-sm text-destructive">{problems.file}</p>}

            <div className="mt-5">
              <Field label="Tên hiển thị" helper="Dùng để đặt tên các file kết quả.">
                {(p) => <input {...p} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="VD: The Mirror Between (Ep3)" />}
              </Field>
            </div>
          </Card>

          <Card title="2. Ngôn ngữ phụ đề" description="Mỗi ngôn ngữ được chọn sẽ cho ra một video riêng.">
            <fieldset>
              <legend className="sr-only">Ngôn ngữ phụ đề</legend>
              <div className="flex flex-wrap gap-2">
                {meta?.languages.map((l) => {
                  const on = languages.includes(l.code);
                  return (
                    <label key={l.code}
                      className={`inline-flex min-h-11 items-center gap-2 rounded-full border-2 px-4 text-sm font-semibold transition-colors duration-200 has-focus-visible:outline-2 has-focus-visible:outline-ring ${
                        on ? "border-primary bg-primary text-on-primary" : "border-slate-300 bg-white hover:border-primary"
                      }`}>
                      <input type="checkbox" className="sr-only" checked={on} onChange={() => toggle(l.code)} />
                      <Languages className="size-4" aria-hidden />
                      {l.label}
                    </label>
                  );
                })}
              </div>
            </fieldset>
            {touched && problems.languages && <p className="mt-2 text-sm text-destructive">{problems.languages}</p>}
          </Card>

          <Card title="3. Ngữ cảnh để dịch chuẩn hơn" description="Không bắt buộc, nhưng giúp AI dịch đúng tên nhân vật, xưng hô và giọng văn.">
            <div className="flex flex-col gap-5">
              <Field label="Thuộc bộ phim" helper={film ? `Dùng ngữ cảnh và ${film.term_count ?? 0} thuật ngữ của phim này.` : "Gắn vào phim để dùng chung bảng thuật ngữ cho mọi tập."}>
                {(p) => (
                  <select {...p} value={filmId} onChange={(e) => setFilmId(e.target.value)}>
                    <option value="">Không gắn phim</option>
                    {films.map((f) => (
                      <option key={f.id} value={f.id}>{f.name}</option>
                    ))}
                  </select>
                )}
              </Field>
              <p className="-mt-3 text-sm">
                <Link to="/films" className="font-semibold text-primary-strong underline-offset-2 hover:underline">
                  Thêm phim hoặc sửa thuật ngữ
                </Link>
              </p>
              <Field label="Ghi chú cho tập này" helper="VD: tóm tắt tập, nhân vật mới xuất hiện, ai đang nói với ai.">
                {(p) => <textarea {...p} rows={4} value={notes} onChange={(e) => setNotes(e.target.value)} />}
              </Field>
            </div>
          </Card>

          {/* 4. Subtitle Configuration Card */}
          <SubtitleConfigCard value={subConfig} onChange={setSubConfig} />

          {/* 5. Tùy chọn xuất file */}
          <Card title="5. Tùy chọn xuất file" description="Tối ưu thời gian xử lý tùy theo nhu cầu sử dụng thực tế.">
            <div className="flex flex-col gap-4">
              <label className="flex items-start gap-3.5 cursor-pointer rounded-xl border border-slate-200 bg-white p-4 transition-colors hover:border-primary/50">
                <input
                  type="checkbox"
                  checked={burnVideo}
                  onChange={(e) => setBurnVideo(e.target.checked)}
                  className="mt-1 size-5 rounded border-slate-300 text-primary focus:ring-primary"
                />
                <div className="flex flex-col gap-1">
                  <span className="font-semibold text-foreground">
                    Render video kèm phụ đề cứng (MP4)
                  </span>
                  <p className="text-sm text-muted-foreground leading-relaxed">
                    {burnVideo ? (
                      <>
                        Hệ thống sẽ encode phụ đề dính vào video MP4. Đã tối ưu tốc độ nhanh hơn bằng preset <code>veryfast</code>.
                      </>
                    ) : (
                      <>
                        <strong className="text-emerald-600 font-semibold">⚡ Chế độ Siêu Tốc (~3 - 5 phút):</strong> Bỏ qua bước encode video, chỉ nhận dạng và dịch để xuất file phụ đề chuẩn <strong>SRT & ASS</strong>. Rất phù hợp nếu bạn muốn import phụ đề vào Premiere/CapCut hoặc tải lên YouTube/Facebook.
                      </>
                    )}
                  </p>
                </div>
              </label>
            </div>
          </Card>
        </div>

        <aside className="lg:sticky lg:top-10 lg:self-start">
          <Card title="Tóm tắt">
            <dl className="flex flex-col gap-3 text-sm">
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">Video</dt>
                <dd className="truncate text-right font-semibold">{file ? file.name : "—"}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">Ngôn ngữ</dt>
                <dd className="text-right font-semibold">
                  {languages.length ? (burnVideo ? `${languages.length} video đầu ra` : `${languages.length} bản phụ đề`) : "—"}
                </dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">Chế độ xuất</dt>
                <dd className="text-right font-semibold">
                  {burnVideo ? "Video MP4 + SRT" : "⚡ Chỉ xuất SRT/ASS"}
                </dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">Phim</dt>
                <dd className="truncate text-right font-semibold">{film?.name ?? "—"}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">Phụ đề</dt>
                <dd className="flex items-center gap-1.5 text-right font-semibold">
                  <span
                    className="size-3 shrink-0 rounded-full border border-slate-400"
                    style={{ backgroundColor: subConfig.color || "#FFFFFF" }}
                    title={`Màu chữ: ${subConfig.color || "#FFFFFF"}`}
                  />
                  <span
                    className="size-3 shrink-0 rounded-full border border-slate-400"
                    style={{ backgroundColor: subConfig.color_border || "#000000" }}
                    title={`Màu viền: ${subConfig.color_border || "#000000"}`}
                  />
                  <span>{subConfig.font_size || 25}px</span>
                  {(subConfig.bold || subConfig.italic) && (
                    <span className="text-xs font-normal text-muted-foreground">
                      ({[subConfig.bold ? "Đậm" : "", subConfig.italic ? "Nghiêng" : ""].filter(Boolean).join(", ")})
                    </span>
                  )}
                </dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">Lề dọc</dt>
                <dd className="text-right font-semibold">{subConfig.margin_v ?? 12}px</dd>
              </div>
            </dl>
            {error && <div className="mt-4"><Alert tone="error" title="Không tải lên được">{error}</Alert></div>}
            {upload !== null && (
              <div className="mt-4 flex flex-col gap-2">
                <p className="text-sm font-semibold">Đang tải lên… {upload}%</p>
                <ProgressBar value={upload} label="Tiến độ tải lên" />
              </div>
            )}
            <Button variant="primary" icon={Play} className="mt-5 w-full" onClick={submit} loading={upload !== null}>
              Bắt đầu xử lý
            </Button>
          </Card>
        </aside>
      </div>
    </>
  );
}
