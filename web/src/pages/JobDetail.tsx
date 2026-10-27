import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { ArrowLeft, Check, Download, FileText, RotateCcw, Trash2 } from "lucide-react";
import { api, formatTime, STEP_LABELS, type Job } from "../api";
import { useLanguageLabel, useMeta } from "../meta";
import { Alert, Button, Card, LinkButton, PageHeader, ProgressBar, StatusBadge } from "../components/ui";

interface PreviewCue {
  time: string;
  text: string;
}

function parseSrt(text: string): PreviewCue[] {
  return text
    .replace(/\r\n/g, "\n")
    .trim()
    .split(/\n\s*\n/)
    .map((block) => {
      const lines = block.split("\n");
      const i = lines.findIndex((l) => l.includes("-->"));
      return i < 0 ? null : { time: lines[i].split(" --> ")[0].slice(0, 8), text: lines.slice(i + 1).join("\n") };
    })
    .filter((c): c is PreviewCue => c !== null);
}

function Stepper({ job, steps }: { job: Job; steps: string[] }) {
  const current = job.status === "done" ? steps.length : job.step ? steps.indexOf(job.step) : -1;
  return (
    <ol className="grid gap-3 sm:grid-cols-5">
      {steps.map((step, i) => {
        const done = i < current;
        const active = i === current && job.status === "running";
        const failed = i === current && job.status === "failed";
        return (
          <li key={step} aria-current={active ? "step" : undefined} className="flex items-center gap-2 sm:flex-col sm:items-start">
            <span className={`grid size-8 shrink-0 place-items-center rounded-full text-sm font-bold ${
              done ? "bg-primary text-on-primary" : active ? "bg-accent text-on-accent" : failed ? "bg-destructive text-white" : "bg-muted text-muted-foreground"
            }`}>
              {done ? <Check className="size-4" aria-label="Xong" /> : i + 1}
            </span>
            <span className={`text-sm ${active || failed ? "font-semibold text-foreground" : "text-muted-foreground"}`}>
              {STEP_LABELS[step] ?? step}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

export function JobDetailPage() {
  const { id } = useParams();
  const jobId = Number(id);
  const meta = useMeta();
  const navigate = useNavigate();
  const langLabel = useLanguageLabel();
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lang, setLang] = useState<string | null>(null);
  const [cues, setCues] = useState<PreviewCue[]>([]);
  const [busy, setBusy] = useState(false);
  const [pollKey, setPollKey] = useState(0);

  useEffect(() => {
    let timer: number;
    let alive = true;
    const load = async () => {
      try {
        const data = await api.job(jobId);
        if (!alive) return;
        setJob(data);
        if (data.status === "queued" || data.status === "running") timer = window.setTimeout(load, 2000);
      } catch (e) {
        if (alive) setError((e as Error).message);
      }
    };
    load();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [jobId, pollKey]);

  const outputs = job?.report.outputs ?? [];
  const videoFor = (code: string) => outputs.find((o) => o.kind === "video" && o.lang === code);
  const srtFor = (code: string) => outputs.find((o) => o.kind === "srt" && o.lang === code);
  const selected = lang ?? job?.languages.find((c) => videoFor(c)) ?? null;
  const selectedSrt = selected ? srtFor(selected) : undefined;

  useEffect(() => {
    if (!selectedSrt) return setCues([]);
    fetch(api.fileUrl(jobId, selectedSrt.file))
      .then((r) => r.text())
      .then((t) => setCues(parseSrt(t)))
      .catch(() => setCues([]));
  }, [jobId, selectedSrt?.file]);

  const sourceSrt = useMemo(() => outputs.find((o) => o.kind === "srt" && !job?.languages.includes(o.lang)), [outputs, job]);

  if (error) return <Alert tone="error" title="Không tải được công việc">{error}</Alert>;
  if (!job) return <p className="text-muted-foreground">Đang tải…</p>;

  const retry = async () => {
    setBusy(true);
    try {
      setJob(await api.retryJob(job.id));
      setLang(null);
      setPollKey((k) => k + 1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!window.confirm(`Xoá "${job.title}" và toàn bộ file kết quả? Không thể hoàn tác.`)) return;
    setBusy(true);
    try {
      await api.deleteJob(job.id);
      navigate("/jobs");
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  const dropped = job.report.dropped ?? [];
  const suggested = job.report.suggested_terms ?? [];
  const homophones = job.report.homophone_corrections ?? [];
  const finished = job.status === "done" || job.status === "failed";

  return (
    <>
      <Link to="/jobs" className="mb-4 inline-flex min-h-11 items-center gap-2 text-sm font-semibold text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" aria-hidden /> Tất cả công việc
      </Link>
      <PageHeader
        title={job.title}
        description={`${job.languages.map(langLabel).join(", ")} · tạo lúc ${formatTime(job.created_at)}${job.provider ? ` · dịch bằng ${job.provider}` : ""}`}
        actions={<StatusBadge status={job.status} />}
      />

      <div className="flex flex-col gap-6">
        <Card title="Tiến trình">
          {meta && <Stepper job={job} steps={meta.steps} />}
          {job.status !== "done" && (
            <div className="mt-5 flex items-center gap-3">
              <ProgressBar value={job.progress} label="Tiến độ xử lý" />
              <span className="shrink-0 text-sm font-semibold">{job.progress}%</span>
            </div>
          )}
          {job.status === "queued" && <p className="mt-3 text-sm text-muted-foreground">Đang chờ các video trước xử lý xong.</p>}
          {job.status === "failed" && (
            <div className="mt-5 flex flex-col gap-3">
              <Alert tone="error" title="Xử lý thất bại">{job.error}</Alert>
              <div><Button icon={RotateCcw} onClick={retry} loading={busy}>Chạy lại</Button></div>
            </div>
          )}
        </Card>

        {job.status === "done" && (
          <Card
            title="Kết quả"
            description="Tải về để đăng lên các nền tảng khác."
            actions={<LinkButton href={api.zipUrl(job.id)} variant="primary" icon={Download} download>Tải tất cả (.zip)</LinkButton>}
          >
            <ul className="divide-y divide-border">
              {job.languages.map((code) => {
                const video = videoFor(code);
                const srt = srtFor(code);
                return (
                  <li key={code} className="flex flex-wrap items-center justify-between gap-3 py-3">
                    <div>
                      <p className="font-semibold">{langLabel(code)}</p>
                      {video && <p className="text-xs text-muted-foreground font-mono">{video.file}</p>}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {video && <LinkButton href={api.fileUrl(job.id, video.file)} icon={Download} download>Video ({langLabel(code)})</LinkButton>}
                      {srt && <LinkButton href={api.fileUrl(job.id, srt.file)} icon={FileText} variant="ghost" download>Phụ đề .srt</LinkButton>}
                    </div>
                  </li>
                );
              })}
              {sourceSrt && (
                <li className="flex flex-wrap items-center justify-between gap-3 py-3">
                  <p className="text-muted-foreground">Bản gốc đã soát lỗi ({sourceSrt.lang})</p>
                  <LinkButton href={api.fileUrl(job.id, sourceSrt.file)} icon={FileText} variant="ghost" download>Phụ đề .srt</LinkButton>
                </li>
              )}
            </ul>
          </Card>
        )}

        {job.status === "done" && selected && (
          <Card title="Xem trước">
            <div role="tablist" aria-label="Chọn ngôn ngữ xem trước" className="mb-4 flex flex-wrap gap-2">
              {job.languages.map((code) => (
                <button key={code} role="tab" aria-selected={code === selected} onClick={() => setLang(code)}
                  className={`min-h-11 rounded-lg px-4 text-sm font-semibold transition-colors duration-200 ${
                    code === selected ? "bg-primary text-on-primary" : "bg-muted text-muted-foreground hover:text-foreground"
                  }`}>
                  {langLabel(code)}
                </button>
              ))}
            </div>
            <div className="grid gap-4 lg:grid-cols-[3fr_2fr]">
              {videoFor(selected) && (
                <video key={selected} controls preload="metadata" className="aspect-video w-full rounded-lg bg-black"
                  src={`${api.fileUrl(job.id, videoFor(selected)!.file)}#t=1`} />
              )}
              <ol className="max-h-[420px] overflow-y-auto rounded-lg border border-border" aria-label="Danh sách phụ đề">
                {cues.map((c, i) => (
                  <li key={i} className="flex gap-3 border-b border-border px-3 py-2 last:border-0">
                    <span className="shrink-0 font-mono text-xs text-muted-foreground">{c.time}</span>
                    <span className="whitespace-pre-line text-sm">{c.text}</span>
                  </li>
                ))}
              </ol>
            </div>
          </Card>
        )}

        {(dropped.length > 0 || suggested.length > 0 || homophones.length > 0) && (
          <Card title="Ghi chú từ AI">
            {dropped.length > 0 && (
              <div className="mb-5">
                <Alert tone="warning" title={`${dropped.length} câu bị bỏ qua vì không nghe rõ`}>
                  Những câu này không xuất hiện trong video. Nếu cần, thêm câu đúng vào ghi chú tập rồi chạy lại.
                </Alert>
                <ul className="mt-3 flex flex-col gap-2 text-sm">
                  {dropped.map((d) => (
                    <li key={d.id} className="flex gap-3"><span className="shrink-0 font-mono text-xs text-muted-foreground">{d.start.slice(0, 8)}</span><span className="italic">{d.text}</span></li>
                  ))}
                </ul>
              </div>
            )}
            {homophones.length > 0 && (
              <div className="mb-5">
                <p className="text-sm font-semibold text-foreground mb-2">
                  Đã kiểm tra và sửa {homophones.length} lỗi đồng âm tiếng Trung (同音字 / 近音词)
                </p>
                <div className="overflow-x-auto rounded-lg border border-border">
                  <table className="w-full text-left text-xs">
                    <thead className="border-b border-border bg-muted/60 font-semibold text-muted-foreground">
                      <tr>
                        <th className="px-3 py-2">Dòng</th>
                        <th className="px-3 py-2">Chữ gốc ASR (lỗi đồng âm)</th>
                        <th className="px-3 py-2">Đã sửa theo ngữ cảnh</th>
                        <th className="px-3 py-2">Pinyin</th>
                        <th className="px-3 py-2">Ngữ cảnh / Giải thích</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {homophones.map((h, idx) => (
                        <tr key={idx} className="hover:bg-muted/30">
                          <td className="px-3 py-2 font-mono text-muted-foreground">#{h.id}</td>
                          <td className="px-3 py-2 font-medium text-destructive line-through">{h.original}</td>
                          <td className="px-3 py-2 font-semibold text-primary-strong">{h.corrected}</td>
                          <td className="px-3 py-2 font-mono text-muted-foreground">{h.pinyin}</td>
                          <td className="px-3 py-2 text-muted-foreground">{h.explanation}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
            {suggested.length > 0 && (
              <div>
                <p className="text-sm font-semibold">Thuật ngữ mới được đề xuất</p>
                <ul className="mt-2 flex flex-wrap gap-2">
                  {suggested.map((t) => (
                    <li key={t.term} className="rounded-full bg-muted px-3 py-1 text-sm" title={t.note}>{t.term}</li>
                  ))}
                </ul>
                {job.film_id && (
                  <Link to={`/films/${job.film_id}`} className="mt-3 inline-block text-sm font-semibold text-primary-strong hover:underline">
                    Duyệt và thêm bản dịch cho các thuật ngữ này
                  </Link>
                )}
              </div>
            )}
          </Card>
        )}

        {finished && (
          <div className="flex flex-wrap gap-2">
            {job.status === "done" && <Button icon={RotateCcw} onClick={retry} loading={busy}>Chạy lại (dùng thuật ngữ mới nhất)</Button>}
            <Button variant="danger" icon={Trash2} onClick={remove} disabled={busy}>Xoá công việc</Button>
          </div>
        )}
      </div>
    </>
  );
}
