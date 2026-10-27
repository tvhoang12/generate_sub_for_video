import { useEffect, useRef, useState, type DragEvent } from "react";
import { Link, useNavigate } from "react-router";
import { FileVideo, Languages, Play, Upload, X } from "lucide-react";
import { api, formatBytes, uploadJob, type Film } from "../api";
import { useMeta } from "../meta";
import { Alert, Button, Card, Field, PageHeader, ProgressBar } from "../components/ui";

const ACCEPT = ".mp4,.mov,.mkv,.webm,.m4v";
const LAST_LANGS_KEY = "substudio:last-languages";

function loadLastLanguages(): string[] {
  try {
    return JSON.parse(localStorage.getItem(LAST_LANGS_KEY) || "[]");
  } catch {
    return [];
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
    if (filmId) form.append("film_id", filmId);
    setError(null);
    setUpload(0);
    try {
      localStorage.setItem(LAST_LANGS_KEY, JSON.stringify(languages));
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
                <dd className="text-right font-semibold">{languages.length ? `${languages.length} video đầu ra` : "—"}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">Phim</dt>
                <dd className="truncate text-right font-semibold">{film?.name ?? "—"}</dd>
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
