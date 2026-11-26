import { useEffect, useRef, useState, type DragEvent } from "react";
import {
  AlertCircle,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock,
  Copy,
  Download,
  FileVideo,
  Layers,
  Loader2,
  Play,
  RotateCw,
  Search,
  Terminal,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import {
  formatBytes,
  formatTime,
  HLS_RENDITIONS,
  hlsApi,
  type HlsJob,
  type HlsJobStatus,
} from "../api";
import { Alert, Button, Card, PageHeader } from "../components/ui";

const ACCEPT = ".mp4,.mov,.mkv,.webm,.m4v";
const DEFAULT_RENDITIONS = ["480p", "720p"];

interface SelectedFileItem {
  file: File;
  key: string;
  jobId: string | null;
  uploading: boolean;
  uploadProgress: number;
  uploaded: boolean;
  error: string | null;
  abortFn?: () => void;
}

export function HlsConverterPage() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [selectedFiles, setSelectedFiles] = useState<SelectedFileItem[]>([]);
  const [selectedRenditions, setSelectedRenditions] = useState<string[]>(DEFAULT_RENDITIONS);
  const [isDragging, setIsDragging] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Jobs state
  const [jobs, setJobs] = useState<HlsJob[]>([]);
  const [loadingJobs, setLoadingJobs] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | "processing" | "done" | "error">("all");
  const [selectedJobIds, setSelectedJobIds] = useState<Set<string>>(new Set());
  const [expandedLogs, setExpandedLogs] = useState<Set<string>>(new Set());
  const [copiedJobId, setCopiedJobId] = useState<string | null>(null);
  const [confirmDeleteAll, setConfirmDeleteAll] = useState(false);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [previewJob, setPreviewJob] = useState<HlsJob | null>(null);
  const [queueStatus, setQueueStatus] = useState<{
    running: number;
    queued: number;
    max_concurrent: number;
  } | null>(null);

  // Fetch jobs on demand (e.g. after starting conversion or deleting)
  const fetchJobs = async () => {
    try {
      const [data, qStatus] = await Promise.all([
        hlsApi.listJobs(),
        hlsApi.getQueueStatus().catch(() => null),
      ]);
      setJobs(data.jobs || []);
      if (qStatus) setQueueStatus(qStatus);
    } catch {
      // Ignore poll error
    } finally {
      setLoadingJobs(false);
    }
  };

  useEffect(() => {
    let timer: number;
    let isMounted = true;

    const poll = async () => {
      try {
        const [data, qStatus] = await Promise.all([
          hlsApi.listJobs(),
          hlsApi.getQueueStatus().catch(() => null),
        ]);
        if (!isMounted) return;
        const jobList = data.jobs || [];
        setJobs(jobList);
        if (qStatus) setQueueStatus(qStatus);

        const hasActive = jobList.some(
          (j) => j.status === "queued" || j.status === "processing" || j.status === "uploading"
        );
        timer = window.setTimeout(poll, hasActive ? 3000 : 12000);
      } catch {
        if (!isMounted) return;
        timer = window.setTimeout(poll, 12000);
      } finally {
        if (isMounted) setLoadingJobs(false);
      }
    };

    poll();

    return () => {
      isMounted = false;
      window.clearTimeout(timer);
    };
  }, []);

  // Handle file additions
  const addFiles = (files: File[]) => {
    const validFiles = files.filter((f) => {
      const ext = f.name.slice(f.name.lastIndexOf(".")).toLowerCase();
      return [".mp4", ".mov", ".mkv", ".webm", ".m4v"].includes(ext);
    });

    if (validFiles.length === 0) return;

    setSelectedFiles((prev) => {
      const next = [...prev];
      for (const f of validFiles) {
        const key = `${f.name}:${f.size}:${f.lastModified}`;
        if (!next.some((item) => item.key === key)) {
          next.push({
            file: f,
            key,
            jobId: null,
            uploading: false,
            uploadProgress: 0,
            uploaded: false,
            error: null,
          });
        }
      }
      return next;
    });

    setSubmitError(null);
  };

  const removeFile = (index: number) => {
    setSelectedFiles((prev) => {
      const target = prev[index];
      if (target?.abortFn) target.abortFn();
      if (target?.jobId) {
        hlsApi.deleteJob(target.jobId).catch(() => {});
      }
      return prev.filter((_, i) => i !== index);
    });
  };

  const clearAllFiles = () => {
    selectedFiles.forEach((item) => {
      if (item.abortFn) item.abortFn();
      if (item.jobId) hlsApi.deleteJob(item.jobId).catch(() => {});
    });
    setSelectedFiles([]);
  };

  // Upload a single file item
  const uploadItem = async (item: SelectedFileItem): Promise<string> => {
    if (item.jobId && item.uploaded) return item.jobId;

    setSelectedFiles((prev) =>
      prev.map((i) => (i.key === item.key ? { ...i, uploading: true, error: null } : i))
    );

    try {
      const initRes = await hlsApi.initUpload(
        item.file.name,
        item.file.size,
        selectedRenditions
      );
      const jobId = initRes.id;

      await hlsApi.uploadFile(
        jobId,
        item.file,
        (pct) => {
          setSelectedFiles((prev) =>
            prev.map((i) => (i.key === item.key ? { ...i, uploadProgress: pct } : i))
          );
        },
        (abort) => {
          setSelectedFiles((prev) =>
            prev.map((i) => (i.key === item.key ? { ...i, jobId, abortFn: abort } : i))
          );
        }
      );

      setSelectedFiles((prev) =>
        prev.map((i) =>
          i.key === item.key
            ? { ...i, jobId, uploading: false, uploaded: true, uploadProgress: 100 }
            : i
        )
      );

      return jobId;
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Upload thất bại";
      setSelectedFiles((prev) =>
        prev.map((i) => (i.key === item.key ? { ...i, uploading: false, error: msg } : i))
      );
      throw err;
    }
  };

  // Start conversion for a single uploaded file
  const startSingleConvert = async (item: SelectedFileItem) => {
    try {
      let jobId = item.jobId;
      if (!jobId || !item.uploaded) {
        jobId = await uploadItem(item);
      }
      await hlsApi.startJobs([jobId]);
      // Remove from selected list as it is now in active jobs
      setSelectedFiles((prev) => prev.filter((i) => i.key !== item.key));
      fetchJobs();
    } catch (err: unknown) {
      setSubmitError(err instanceof Error ? err.message : "Không thể bắt đầu convert");
    }
  };

  // Start conversion for all files
  const startAllConversions = async () => {
    if (selectedFiles.length === 0) return;
    setIsSubmitting(true);
    setSubmitError(null);

    const uploadedIds: string[] = [];
    const errors: string[] = [];

    for (const item of selectedFiles) {
      try {
        let jobId = item.jobId;
        if (!jobId || !item.uploaded) {
          jobId = await uploadItem(item);
        }
        uploadedIds.push(jobId);
      } catch (err: unknown) {
        errors.push(`${item.file.name}: ${err instanceof Error ? err.message : "Lỗi upload"}`);
      }
    }

    if (uploadedIds.length > 0) {
      try {
        await hlsApi.startJobs(uploadedIds);
        // Clear successfully submitted items
        setSelectedFiles((prev) => prev.filter((i) => !uploadedIds.includes(i.jobId || "")));
        fetchJobs();
      } catch (err: unknown) {
        errors.push(err instanceof Error ? err.message : "Lỗi khi bắt đầu convert");
      }
    }

    if (errors.length > 0) {
      setSubmitError(errors.join(" | "));
    }
    setIsSubmitting(false);
  };

  // Rendition toggle
  const toggleRendition = (label: string) => {
    setSelectedRenditions((prev) =>
      prev.includes(label) ? prev.filter((r) => r !== label) : [...prev, label]
    );
  };

  // Copy HLS stream URL
  const copyStreamUrl = async (jobId: string) => {
    const url = `${window.location.origin}${hlsApi.streamUrl(jobId)}`;
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(url);
      } else {
        const textArea = document.createElement("textarea");
        textArea.value = url;
        textArea.style.position = "fixed";
        textArea.style.opacity = "0";
        textArea.style.left = "-9999px";
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        document.execCommand("copy");
        document.body.removeChild(textArea);
      }
      setCopiedJobId(jobId);
      setTimeout(() => setCopiedJobId(null), 2000);
    } catch {
      window.prompt("Sao chép URL stream HLS:", url);
    }
  };

  // Delete handlers
  const handleDeleteJob = async (jobId: string) => {
    if (confirmDeleteId !== jobId) {
      setConfirmDeleteId(jobId);
      setTimeout(() => setConfirmDeleteId((cur) => (cur === jobId ? null : cur)), 3000);
      return;
    }
    try {
      await hlsApi.deleteJob(jobId);
      setJobs((prev) => prev.filter((j) => j.id !== jobId));
      setConfirmDeleteId(null);
    } catch {
      // Ignore
    }
  };

  const handleDeleteSelected = async () => {
    if (selectedJobIds.size === 0) return;
    try {
      await hlsApi.deleteJobs(Array.from(selectedJobIds));
      setJobs((prev) => prev.filter((j) => !selectedJobIds.has(j.id)));
      setSelectedJobIds(new Set());
    } catch {
      // Ignore
    }
  };

  const handleDeleteAll = async () => {
    if (!confirmDeleteAll) {
      setConfirmDeleteAll(true);
      setTimeout(() => setConfirmDeleteAll(false), 3000);
      return;
    }
    try {
      await hlsApi.deleteJobs(undefined, true);
      setJobs([]);
      setSelectedJobIds(new Set());
      setConfirmDeleteAll(false);
    } catch {
      // Ignore
    }
  };

  // Filter and search
  const filteredJobs = jobs.filter((job) => {
    if (job.status === "uploading" || job.status === "uploaded") return false;

    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      if (!job.original_name.toLowerCase().includes(q)) return false;
    }

    if (statusFilter === "processing") {
      return job.status === "queued" || job.status === "processing";
    }
    if (statusFilter === "done") return job.status === "done";
    if (statusFilter === "error") return job.status === "error";

    return true;
  });

  const countProcessing = jobs.filter(
    (j) => j.status === "queued" || j.status === "processing"
  ).length;
  const countDone = jobs.filter((j) => j.status === "done").length;
  const countError = jobs.filter((j) => j.status === "error").length;

  const selectedDoneIds = jobs
    .filter((j) => selectedJobIds.has(j.id) && j.status === "done")
    .map((j) => j.id);
  const selectedDoneCount = selectedDoneIds.length;

  const allFilteredSelected =
    filteredJobs.length > 0 && filteredJobs.every((j) => selectedJobIds.has(j.id));
  const handleToggleSelectAllFiltered = () => {
    setSelectedJobIds((prev) => {
      const next = new Set(prev);
      if (allFilteredSelected) {
        filteredJobs.forEach((j) => next.delete(j.id));
      } else {
        filteredJobs.forEach((j) => next.add(j.id));
      }
      return next;
    });
  };

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Chuyển MP4 sang HLS"
        description="Chuyển đổi video MP4, MOV, MKV thành định dạng phát trực tuyến HLS đa độ phân giải (360p, 480p, 720p, 1080p)."
        actions={
          queueStatus ? (
            <div className="flex items-center gap-2 rounded-xl border border-border bg-card px-3.5 py-2 text-xs shadow-xs">
              <span className="flex size-2 rounded-full bg-emerald-500 animate-pulse" />
              <span className="font-semibold text-foreground">Hàng đợi HLS độc lập:</span>
              <span className="text-muted-foreground">
                {queueStatus.running} đang chạy · {queueStatus.queued} đang chờ (tối đa {queueStatus.max_concurrent} song song)
              </span>
            </div>
          ) : undefined
        }
      />

      {/* Upload & Rendition Setup Card */}
      <Card title="Tải video lên & Chọn độ phân giải">
        <div className="flex flex-col gap-5">
          {/* Drag & Drop Zone */}
          <div
            className={`relative flex min-h-[160px] cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed p-6 text-center transition-all duration-200 ${
              isDragging
                ? "border-primary bg-primary/10"
                : "border-border hover:border-primary/60 hover:bg-muted/30"
            }`}
            onDragEnter={(e: DragEvent) => {
              e.preventDefault();
              setIsDragging(true);
            }}
            onDragLeave={(e: DragEvent) => {
              e.preventDefault();
              setIsDragging(false);
            }}
            onDragOver={(e: DragEvent) => e.preventDefault()}
            onDrop={(e: DragEvent) => {
              e.preventDefault();
              setIsDragging(false);
              if (e.dataTransfer.files) {
                addFiles(Array.from(e.dataTransfer.files));
              }
            }}
            onClick={() => fileInputRef.current?.click()}
          >
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept={ACCEPT}
              className="hidden"
              onChange={(e) => {
                if (e.target.files) {
                  addFiles(Array.from(e.target.files));
                  e.target.value = "";
                }
              }}
            />
            <div className="mb-2 grid size-12 place-items-center rounded-full bg-primary/10 text-primary">
              <Upload className="size-6" />
            </div>
            <p className="font-semibold text-foreground">
              Kéo thả các file video vào đây hoặc <span className="text-primary underline">chọn từ máy tính</span>
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              Hỗ trợ định dạng MP4, MOV, MKV, WebM, M4V (tự động streaming upload trực tiếp xuống đĩa)
            </p>
          </div>

          {/* Selected files preview */}
          {selectedFiles.length > 0 && (
            <div className="rounded-xl border border-border bg-muted/20 p-4">
              <div className="mb-3 flex items-center justify-between">
                <span className="text-sm font-semibold text-foreground">
                  Đã chọn {selectedFiles.length} file
                </span>
                <button
                  type="button"
                  onClick={clearAllFiles}
                  className="text-xs font-semibold text-destructive hover:underline"
                >
                  Xóa tất cả file
                </button>
              </div>

              <div className="flex flex-col gap-2">
                {selectedFiles.map((item, idx) => (
                  <div
                    key={item.key}
                    className="flex flex-col gap-2 rounded-lg border border-border bg-card p-3 shadow-xs"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="flex min-w-0 items-center gap-2.5">
                        <FileVideo className="size-5 shrink-0 text-primary" />
                        <span className="truncate text-sm font-medium text-foreground" title={item.file.name}>
                          {item.file.name}
                        </span>
                        <span className="shrink-0 text-xs text-muted-foreground">
                          ({formatBytes(item.file.size)})
                        </span>
                      </div>

                      <div className="flex shrink-0 items-center gap-2">
                        {item.uploaded ? (
                          <span className="inline-flex items-center gap-1 rounded-md bg-green-100 px-2 py-0.5 text-xs font-semibold text-success">
                            <Check className="size-3" /> Đã tải lên
                          </span>
                        ) : item.uploading ? (
                          <span className="text-xs font-semibold text-primary">
                            {item.uploadProgress}%
                          </span>
                        ) : null}

                        <Button
                          variant="secondary"
                          className="h-8 px-2.5 text-xs"
                          disabled={item.uploading || isSubmitting}
                          onClick={() => startSingleConvert(item)}
                        >
                          <Play className="size-3" /> Convert
                        </Button>

                        <button
                          type="button"
                          onClick={() => removeFile(idx)}
                          className="text-muted-foreground hover:text-destructive"
                          title="Xóa khỏi danh sách"
                        >
                          <X className="size-4" />
                        </button>
                      </div>
                    </div>

                    {/* Per-file upload progress bar */}
                    {item.uploading && (
                      <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                        <div
                          className="h-full bg-primary transition-all duration-200"
                          style={{ width: `${item.uploadProgress}%` }}
                        />
                      </div>
                    )}

                    {item.error && (
                      <p className="text-xs text-destructive">{item.error}</p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Rendition Selector */}
          <div>
            <label className="mb-2 block text-xs font-bold uppercase tracking-wider text-muted-foreground">
              Độ phân giải đầu ra
            </label>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {HLS_RENDITIONS.map((r) => {
                const isChecked = selectedRenditions.includes(r.label);
                return (
                  <button
                    type="button"
                    key={r.label}
                    onClick={() => toggleRendition(r.label)}
                    className={`flex items-center justify-between rounded-xl border p-3.5 text-left transition-all duration-200 ${
                      isChecked
                        ? "border-primary bg-primary/10 shadow-xs"
                        : "border-border bg-card hover:border-primary/50"
                    }`}
                  >
                    <div>
                      <p className="font-bold text-foreground">{r.label}</p>
                      <p className="text-xs text-muted-foreground">
                        {r.resolution} · {r.bitrateLabel}
                      </p>
                    </div>
                    <div
                      className={`grid size-5 place-items-center rounded-md border text-xs ${
                        isChecked
                          ? "border-primary bg-primary text-on-primary"
                          : "border-slate-300 bg-white"
                      }`}
                    >
                      {isChecked && <Check className="size-3.5" />}
                    </div>
                  </button>
                );
              })}
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              ⚠ Video nguồn có độ phân giải thấp hơn sẽ tự động bỏ qua rendition cao hơn (không upscale).
            </p>
          </div>

          {/* Action Row */}
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
            <Button
              variant="primary"
              disabled={isSubmitting || selectedFiles.length === 0 || selectedRenditions.length === 0}
              loading={isSubmitting}
              onClick={startAllConversions}
              className="px-6 py-2.5"
            >
              <RotateCw className="size-4" /> Bắt đầu chuyển đổi{" "}
              {selectedFiles.length > 0 && `(${selectedFiles.length} video)`}
            </Button>

            <span className="text-xs text-muted-foreground">
              Đã chọn: {selectedRenditions.join(", ") || "Chưa chọn chất lượng"}
            </span>
          </div>

          {submitError && (
            <Alert tone="error" title="Không thể chuyển đổi">
              {submitError}
            </Alert>
          )}
        </div>
      </Card>

      {/* Jobs Management Section */}
      <section className="flex flex-col gap-4">
        {/* Toolbar */}
        <div className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4 shadow-sm sm:flex-row sm:items-center sm:justify-between">
          {/* Search box */}
          <div className="relative flex-1 max-w-md">
            <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <input
              type="text"
              placeholder="Tìm theo tên video..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full rounded-lg border border-slate-300 bg-white pl-9 pr-8 py-2 text-sm text-foreground focus:border-primary focus:outline-none"
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery("")}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              >
                <X className="size-3.5" />
              </button>
            )}
          </div>

          {/* Filter Tabs */}
          <div className="flex flex-wrap items-center gap-1.5">
            <button
              type="button"
              onClick={() => setStatusFilter("all")}
              className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
                statusFilter === "all"
                  ? "bg-primary text-on-primary"
                  : "bg-muted text-muted-foreground hover:bg-muted/80"
              }`}
            >
              Tất cả ({jobs.length})
            </button>
            <button
              type="button"
              onClick={() => setStatusFilter("processing")}
              className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
                statusFilter === "processing"
                  ? "bg-primary text-on-primary"
                  : "bg-muted text-muted-foreground hover:bg-muted/80"
              }`}
            >
              Đang xử lý ({countProcessing})
            </button>
            <button
              type="button"
              onClick={() => setStatusFilter("done")}
              className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
                statusFilter === "done"
                  ? "bg-primary text-on-primary"
                  : "bg-muted text-muted-foreground hover:bg-muted/80"
              }`}
            >
              Hoàn thành ({countDone})
            </button>
            <button
              type="button"
              onClick={() => setStatusFilter("error")}
              className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
                statusFilter === "error"
                  ? "bg-primary text-on-primary"
                  : "bg-muted text-muted-foreground hover:bg-muted/80"
              }`}
            >
              Lỗi ({countError})
            </button>
          </div>
        </div>

        {/* Batch Actions Bar (when selected) */}
        {selectedJobIds.size > 0 && (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-primary/30 bg-primary/5 p-3">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-foreground">
                Đã chọn {selectedJobIds.size} tác vụ
              </span>
              <button
                type="button"
                onClick={() => setSelectedJobIds(new Set())}
                className="text-xs text-muted-foreground hover:text-foreground underline"
              >
                Bỏ chọn
              </button>
            </div>
            <div className="flex items-center gap-2">
              {selectedDoneCount > 0 ? (
                <a
                  href={hlsApi.batchDownloadUrl(selectedDoneIds)}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-xs font-semibold text-foreground hover:bg-muted shadow-xs transition-colors"
                  download
                >
                  <Download className="size-3.5" /> Tải ZIP đã chọn ({selectedDoneCount})
                </a>
              ) : (
                <button
                  type="button"
                  disabled
                  className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card/50 px-3 py-1.5 text-xs font-semibold text-muted-foreground/60 cursor-not-allowed"
                  title="Chưa có tác vụ hoàn tất nào trong số tác vụ đã chọn"
                >
                  <Download className="size-3.5" /> Tải ZIP đã chọn (0)
                </button>
              )}
              <Button
                variant="danger"
                className="h-8 px-3 text-xs"
                onClick={handleDeleteSelected}
              >
                <Trash2 className="size-3.5" /> Xóa đã chọn
              </Button>
            </div>
          </div>
        )}

        {/* Global actions: Download All & Clear All */}
        {jobs.length > 0 && (
          <div className="flex flex-wrap items-center justify-between gap-3 text-xs">
            {filteredJobs.length > 0 ? (
              <label className="flex items-center gap-2 cursor-pointer font-medium text-muted-foreground hover:text-foreground">
                <input
                  type="checkbox"
                  checked={allFilteredSelected}
                  onChange={handleToggleSelectAllFiltered}
                  className="size-4 rounded border-slate-300 text-primary focus:ring-primary"
                />
                <span>Chọn tất cả ({filteredJobs.length})</span>
              </label>
            ) : <div />}
            <div className="flex items-center gap-3">
              {countDone > 0 && (
                <a
                  href={hlsApi.batchDownloadUrl(undefined, true)}
                  className="inline-flex items-center gap-1 font-semibold text-primary hover:underline"
                  download
                >
                  <Download className="size-3.5" /> Tải toàn bộ video xong ({countDone})
                </a>
              )}
              <button
                type="button"
                onClick={handleDeleteAll}
                className={`font-semibold transition-colors ${
                  confirmDeleteAll ? "text-destructive font-bold" : "text-muted-foreground hover:text-destructive"
                }`}
              >
                {confirmDeleteAll ? "Chắc chắn xóa toàn bộ?" : "Xóa tất cả tác vụ"}
              </button>
            </div>
          </div>
        )}

        {/* Jobs List */}
        {loadingJobs ? (
          <div className="flex items-center justify-center p-12 text-sm text-muted-foreground">
            <Loader2 className="mr-2 size-5 animate-spin" /> Đang tải danh sách tác vụ...
          </div>
        ) : filteredJobs.length === 0 ? (
          <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border bg-card p-12 text-center">
            <Layers className="size-10 text-muted-foreground/50" />
            <p className="mt-3 text-base font-semibold text-foreground">
              {searchQuery ? "Không tìm thấy tác vụ phù hợp" : "Chưa có tác vụ chuyển đổi nào"}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              Tải lên video phía trên để bắt đầu chuyển đổi sang HLS.
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {filteredJobs.map((job) => {
              const isSelected = selectedJobIds.has(job.id);
              const isExpanded = expandedLogs.has(job.id);
              const isCopied = copiedJobId === job.id;
              const isConfirmDelete = confirmDeleteId === job.id;

              return (
                <div
                  key={job.id}
                  className={`flex flex-col gap-3 rounded-xl border p-4 shadow-xs transition-colors ${
                    isSelected ? "border-primary bg-primary/5" : "border-border bg-card"
                  }`}
                >
                  {/* Job Header */}
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex min-w-0 items-center gap-3">
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={(e) => {
                          setSelectedJobIds((prev) => {
                            const next = new Set(prev);
                            if (e.target.checked) next.add(job.id);
                            else next.delete(job.id);
                            return next;
                          });
                        }}
                        className="size-4 rounded border-slate-300 text-primary focus:ring-primary"
                      />
                      <FileVideo className="size-5 shrink-0 text-primary" />
                      <div className="min-w-0">
                        <p className="truncate font-semibold text-foreground" title={job.original_name}>
                          {job.original_name}
                        </p>
                        <div className="flex items-center gap-2 text-xs text-muted-foreground">
                          {job.source_size && <span>{formatBytes(job.source_size)}</span>}
                          {job.src_height && (
                            <>
                              <span>·</span>
                              <span className="rounded bg-muted px-1.5 py-0.5 text-xs font-medium">
                                Nguồn: {job.src_height}px
                              </span>
                            </>
                          )}
                          <span>·</span>
                          <span>{formatTime(job.created_at)}</span>
                        </div>
                      </div>
                    </div>

                    {/* Status Badge & Actions */}
                    <div className="flex flex-wrap items-center gap-2">
                      <StatusBadge status={job.status} />

                      {job.status === "done" && (
                        <>
                          <Button
                            variant="secondary"
                            className="h-8 px-2.5 text-xs text-primary font-semibold hover:bg-primary/10"
                            onClick={() => setPreviewJob(job)}
                            title="Xem video stream HLS trực tiếp"
                          >
                            <Play className="size-3" /> Xem
                          </Button>

                          <Button
                            variant="secondary"
                            className="h-8 px-2.5 text-xs"
                            onClick={() => copyStreamUrl(job.id)}
                            title="Sao chép URL stream HLS"
                          >
                            {isCopied ? (
                              <>
                                <Check className="size-3 text-success" /> Đã sao chép!
                              </>
                            ) : (
                              <>
                                <Copy className="size-3" /> Link HLS
                              </>
                            )}
                          </Button>

                          <a
                            href={hlsApi.downloadUrl(job.id)}
                            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border bg-card px-2.5 text-xs font-semibold text-foreground hover:bg-muted"
                            title="Tải trọn gói playlist ZIP"
                            download
                          >
                            <Download className="size-3" /> ZIP
                          </a>
                        </>
                      )}

                      <button
                        type="button"
                        onClick={() => handleDeleteJob(job.id)}
                        className={`rounded-lg px-2.5 py-1.5 text-xs font-semibold transition-colors ${
                          isConfirmDelete
                            ? "bg-destructive text-white"
                            : "text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                        }`}
                        title="Xóa tác vụ"
                      >
                        {isConfirmDelete ? "Chắc chắn xóa?" : <Trash2 className="size-3.5" />}
                      </button>
                    </div>
                  </div>

                  {/* Progress Bar (if processing) */}
                  {(job.status === "processing" || job.status === "queued") && (
                    <div className="flex flex-col gap-1.5 pt-1">
                      <div className="flex items-center justify-between text-xs text-muted-foreground">
                        <span>
                          {job.status === "queued"
                            ? "Đang chờ trong hàng đợi..."
                            : job.current_rendition
                            ? `Đang encode ${job.current_rendition}...`
                            : "Đang xử lý..."}
                        </span>
                        <span className="font-semibold text-foreground">{job.progress}%</span>
                      </div>
                      <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                        <div
                          className="h-full bg-primary transition-all duration-300"
                          style={{ width: `${job.progress}%` }}
                        />
                      </div>
                    </div>
                  )}

                  {/* Rendition Chips */}
                  <div className="flex flex-wrap items-center gap-1.5 pt-1 text-xs">
                    {job.selected_renditions.map((r) => {
                      const isCompleted = job.completed_renditions?.includes(r);
                      const isCurrent = job.current_rendition === r;
                      const isSkipped = job.skipped_renditions?.includes(r);

                      if (isCompleted) {
                        return (
                          <a
                            key={r}
                            href={hlsApi.downloadUrl(job.id, r)}
                            className="inline-flex items-center gap-1 rounded-md bg-green-100 px-2 py-0.5 font-medium text-success hover:bg-green-200"
                            title={`Tải file ZIP cho độ phân giải ${r}`}
                            download
                          >
                            <Check className="size-3" /> {r} (Tải)
                          </a>
                        );
                      }
                      if (isCurrent) {
                        return (
                          <span
                            key={r}
                            className="inline-flex items-center gap-1 rounded-md bg-primary/20 px-2 py-0.5 font-semibold text-primary-strong animate-pulse"
                          >
                            <Loader2 className="size-3 animate-spin" /> {r}
                          </span>
                        );
                      }
                      if (isSkipped) {
                        return (
                          <span
                            key={r}
                            className="inline-flex items-center gap-1 rounded-md bg-muted px-2 py-0.5 text-muted-foreground line-through opacity-70"
                            title="Video nguồn không đủ độ phân giải, bỏ qua để không upscale"
                          >
                            {r}
                          </span>
                        );
                      }
                      return (
                        <span
                          key={r}
                          className="inline-flex items-center gap-1 rounded-md border border-border bg-card px-2 py-0.5 text-muted-foreground"
                        >
                          {r}
                        </span>
                      );
                    })}
                  </div>

                  {/* Error display if failed */}
                  {job.status === "error" && job.error_message && (
                    <div className="rounded-lg bg-red-50 p-2.5 text-xs text-destructive">
                      <strong>Lỗi:</strong> {job.error_message}
                    </div>
                  )}

                  {/* Logs Toggle & Terminal */}
                  {job.logs && job.logs.length > 0 && (
                    <div className="border-t border-border pt-2 text-xs">
                      <button
                        type="button"
                        onClick={() => {
                          setExpandedLogs((prev) => {
                            const next = new Set(prev);
                            if (next.has(job.id)) next.delete(job.id);
                            else next.add(job.id);
                            return next;
                          });
                        }}
                        className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground"
                      >
                        <Terminal className="size-3" />
                        <span>{isExpanded ? "Ẩn log xử lý" : `Xem log (${job.logs.length} dòng)`}</span>
                        {isExpanded ? <ChevronUp className="size-3" /> : <ChevronDown className="size-3" />}
                      </button>

                      {isExpanded && (
                        <div className="mt-2 max-h-48 overflow-y-auto rounded-lg bg-slate-900 p-3 font-mono text-xs text-emerald-400">
                          {job.logs.map((line, lIdx) => (
                            <div key={lIdx} className="leading-relaxed">
                              {line}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </section>

      {previewJob && (
        <HlsPreviewModal job={previewJob} onClose={() => setPreviewJob(null)} />
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: HlsJobStatus }) {
  switch (status) {
    case "queued":
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-muted px-2.5 py-0.5 text-xs font-semibold text-muted-foreground">
          <Clock className="size-3" /> Đang chờ
        </span>
      );
    case "processing":
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2.5 py-0.5 text-xs font-semibold text-primary-strong">
          <Loader2 className="size-3 animate-spin" /> Đang chuyển đổi
        </span>
      );
    case "done":
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-semibold text-success">
          <CheckCircle2 className="size-3" /> Hoàn thành
        </span>
      );
    case "error":
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2.5 py-0.5 text-xs font-semibold text-destructive">
          <AlertCircle className="size-3" /> Lỗi
        </span>
      );
    default:
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-muted px-2.5 py-0.5 text-xs font-semibold text-muted-foreground">
          {status}
        </span>
      );
  }
}

function HlsPreviewModal({ job, onClose }: { job: HlsJob; onClose: () => void }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [copied, setCopied] = useState(false);
  const streamUrl = hlsApi.streamUrl(job.id);
  const fullUrl = `${window.location.origin}${streamUrl}`;

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    if (video.canPlayType("application/vnd.apple.mpegurl")) {
      video.src = streamUrl;
    } else {
      type HlsInstance = {
        loadSource: (src: string) => void;
        attachMedia: (v: HTMLVideoElement) => void;
        destroy: () => void;
      };
      type WinWithHls = typeof window & {
        Hls?: {
          isSupported: () => boolean;
          new (): HlsInstance;
        };
      };
      const win = window as WinWithHls;

      let hlsInstance: HlsInstance | null = null;
      const initHls = () => {
        if (win.Hls && win.Hls.isSupported() && videoRef.current) {
          hlsInstance = new win.Hls();
          hlsInstance.loadSource(streamUrl);
          hlsInstance.attachMedia(videoRef.current);
        }
      };

      if (win.Hls) {
        initHls();
      } else {
        const script = document.createElement("script");
        script.src = "https://cdn.jsdelivr.net/npm/hls.js@1.5.8/dist/hls.min.js";
        script.onload = () => initHls();
        document.head.appendChild(script);
      }

      return () => {
        if (hlsInstance) {
          hlsInstance.destroy();
        }
      };
    }
  }, [streamUrl]);

  const copyUrl = async () => {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(fullUrl);
      } else {
        const textArea = document.createElement("textarea");
        textArea.value = fullUrl;
        textArea.style.position = "fixed";
        textArea.style.opacity = "0";
        textArea.style.left = "-9999px";
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        document.execCommand("copy");
        document.body.removeChild(textArea);
      }
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      window.prompt("Sao chép URL stream HLS:", fullUrl);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-xs">
      <div className="relative flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-3.5">
          <div className="min-w-0 pr-4">
            <h3 className="truncate text-base font-semibold text-foreground">
              {job.original_name}
            </h3>
            <p className="text-xs text-muted-foreground">
              Độ phân giải: {job.completed_renditions?.join(", ") || "HLS"}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
            title="Đóng"
          >
            <X className="size-5" />
          </button>
        </div>

        {/* Video Player */}
        <div className="relative aspect-video w-full bg-black">
          <video
            ref={videoRef}
            controls
            autoPlay
            playsInline
            className="h-full w-full object-contain"
          />
        </div>

        {/* Footer / URL copy bar */}
        <div className="flex flex-col gap-2.5 border-t border-border bg-muted/30 p-4 text-xs">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-foreground shrink-0">URL Stream:</span>
            <div className="flex min-w-0 flex-1 items-center rounded-lg border border-border bg-card px-2.5 py-1.5 font-mono text-muted-foreground">
              <span className="truncate">{fullUrl}</span>
            </div>
            <Button
              variant="secondary"
              className="h-8 shrink-0 px-3 text-xs"
              onClick={copyUrl}
            >
              {copied ? (
                <>
                  <Check className="size-3 text-success" /> Đã sao chép!
                </>
              ) : (
                <>
                  <Copy className="size-3" /> Sao chép link
                </>
              )}
            </Button>
          </div>
          <div className="flex items-center justify-between text-muted-foreground">
            <span>Dùng URL này trong các trình phát HLS (VLC, ExoPlayer, AVPlayer, v.v.)</span>
            <a
              href={streamUrl}
              target="_blank"
              rel="noreferrer"
              className="text-primary hover:underline font-medium"
            >
              Mở stream trực tiếp ↗
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}
