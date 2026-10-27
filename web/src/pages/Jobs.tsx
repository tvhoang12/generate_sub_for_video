import { useEffect, useState } from "react";
import { Link } from "react-router";
import { ChevronRight, ListVideo } from "lucide-react";
import { api, formatTime, STEP_LABELS, type Job } from "../api";
import { useLanguageLabel } from "../meta";
import { Alert, EmptyState, LinkButton, PageHeader, ProgressBar, StatusBadge } from "../components/ui";

export function useJobsPolling() {
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let timer: number;
    let alive = true;
    const load = async () => {
      try {
        const data = await api.jobs();
        if (!alive) return;
        setJobs(data);
        setError(null);
        const active = data.some((j) => j.status === "queued" || j.status === "running");
        timer = window.setTimeout(load, active ? 2000 : 10000);
      } catch (e) {
        if (!alive) return;
        setError((e as Error).message);
        timer = window.setTimeout(load, 5000);
      }
    };
    load();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, []);
  return { jobs, error };
}

export function JobsPage() {
  const { jobs, error } = useJobsPolling();
  const langLabel = useLanguageLabel();

  return (
    <>
      <PageHeader title="Công việc" description="Video đang xử lý và đã hoàn thành. Trang tự cập nhật." actions={<LinkButton href="/" variant="primary">Tạo phụ đề mới</LinkButton>} />
      {error && <div className="mb-4"><Alert tone="error" title="Không tải được danh sách">{error}</Alert></div>}
      {jobs === null ? (
        <p className="text-muted-foreground">Đang tải…</p>
      ) : jobs.length === 0 ? (
        <EmptyState icon={ListVideo} title="Chưa có công việc nào">
          <Link to="/" className="font-semibold text-primary-strong hover:underline">Tải video đầu tiên lên</Link>
        </EmptyState>
      ) : (
        <ul className="flex flex-col gap-3">
          {jobs.map((job) => (
            <li key={job.id}>
              <Link
                to={`/jobs/${job.id}`}
                className="group flex items-center gap-4 rounded-xl border border-border bg-card p-4 shadow-sm transition-colors duration-200 hover:border-primary"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="truncate font-semibold">{job.title}</p>
                    <StatusBadge status={job.status} />
                  </div>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {job.languages.map(langLabel).join(", ")} · {formatTime(job.created_at)}
                  </p>
                  {job.status === "running" && (
                    <div className="mt-3 flex items-center gap-3">
                      <ProgressBar value={job.progress} label={`Tiến độ ${job.title}`} />
                      <span className="shrink-0 text-xs font-semibold text-muted-foreground">
                        {job.step ? STEP_LABELS[job.step] : ""} {job.progress}%
                      </span>
                    </div>
                  )}
                  {job.status === "failed" && job.error && <p className="mt-2 line-clamp-1 text-sm text-destructive">{job.error}</p>}
                </div>
                <ChevronRight className="size-5 shrink-0 text-muted-foreground transition-colors group-hover:text-primary" aria-hidden />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
