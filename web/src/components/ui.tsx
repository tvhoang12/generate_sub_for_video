import { useId, type ButtonHTMLAttributes, type ReactNode } from "react";
import { CheckCircle2, CircleAlert, Clock, Loader2, type LucideIcon } from "lucide-react";
import type { JobStatus } from "../api";

type Variant = "primary" | "secondary" | "ghost" | "danger";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-accent text-on-accent hover:bg-accent-strong hover:text-white shadow-sm",
  secondary: "border-2 border-primary text-foreground hover:bg-primary/10",
  ghost: "text-muted-foreground hover:bg-muted hover:text-foreground",
  danger: "text-destructive hover:bg-destructive/10",
};

export function Button({
  variant = "secondary",
  icon: Icon,
  loading,
  children,
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; icon?: LucideIcon; loading?: boolean }) {
  return (
    <button
      {...props}
      disabled={props.disabled || loading}
      className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold transition-colors duration-200 disabled:cursor-not-allowed disabled:opacity-50 ${VARIANTS[variant]} ${className}`}
    >
      {loading ? <Loader2 className="size-4 animate-spin" aria-hidden /> : Icon && <Icon className="size-4" aria-hidden />}
      {children}
    </button>
  );
}

export function LinkButton({ href, icon: Icon, children, variant = "secondary", download }: {
  href: string; icon?: LucideIcon; children: ReactNode; variant?: Variant; download?: boolean;
}) {
  return (
    <a
      href={href}
      download={download}
      className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold transition-colors duration-200 ${VARIANTS[variant]}`}
    >
      {Icon && <Icon className="size-4" aria-hidden />}
      {children}
    </a>
  );
}

export function Card({ title, description, actions, children, className = "" }: {
  title?: string; description?: string; actions?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section className={`rounded-xl border border-border bg-card p-5 shadow-sm sm:p-6 ${className}`}>
      {(title || actions) && (
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            {title && <h2 className="text-lg font-semibold text-foreground">{title}</h2>}
            {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
          </div>
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

const inputClass =
  "w-full rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-base text-foreground transition-colors duration-200 placeholder:text-slate-400 focus:border-primary focus:outline-none focus:ring-3 focus:ring-primary/20";

export function Field({ label, helper, error, children }: {
  label: string; helper?: string; error?: string; children: (props: { id: string; className: string; "aria-describedby"?: string; "aria-invalid"?: boolean }) => ReactNode;
}) {
  const id = useId();
  const hintId = `${id}-hint`;
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-semibold text-foreground">{label}</label>
      {children({ id, className: inputClass, "aria-describedby": helper || error ? hintId : undefined, "aria-invalid": !!error || undefined })}
      {error ? (
        <p id={hintId} className="text-sm text-destructive">{error}</p>
      ) : (
        helper && <p id={hintId} className="text-sm text-muted-foreground">{helper}</p>
      )}
    </div>
  );
}

const STATUS: Record<JobStatus, { label: string; icon: LucideIcon; className: string; spin?: boolean }> = {
  queued: { label: "Đang chờ", icon: Clock, className: "bg-muted text-muted-foreground" },
  running: { label: "Đang xử lý", icon: Loader2, className: "bg-primary/10 text-primary-strong", spin: true },
  done: { label: "Hoàn thành", icon: CheckCircle2, className: "bg-green-100 text-success" },
  failed: { label: "Lỗi", icon: CircleAlert, className: "bg-red-100 text-destructive" },
};

export function StatusBadge({ status }: { status: JobStatus }) {
  const s = STATUS[status];
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold ${s.className}`}>
      <s.icon className={`size-3.5 ${s.spin ? "animate-spin" : ""}`} aria-hidden />
      {s.label}
    </span>
  );
}

export function ProgressBar({ value, label }: { value: number; label: string }) {
  return (
    <div role="progressbar" aria-label={label} aria-valuenow={value} aria-valuemin={0} aria-valuemax={100}
      className="h-2 w-full overflow-hidden rounded-full bg-muted">
      <div className="h-full rounded-full bg-primary transition-[width] duration-300" style={{ width: `${value}%` }} />
    </div>
  );
}

export function Alert({ tone, title, children }: { tone: "error" | "info" | "warning"; title: string; children?: ReactNode }) {
  const styles = {
    error: "border-red-200 bg-red-50 text-red-800",
    warning: "border-amber-200 bg-amber-50 text-amber-900",
    info: "border-teal-200 bg-teal-50 text-teal-900",
  }[tone];
  return (
    <div role={tone === "error" ? "alert" : "status"} className={`rounded-lg border px-4 py-3 text-sm ${styles}`}>
      <p className="font-semibold">{title}</p>
      {children && <div className="mt-1">{children}</div>}
    </div>
  );
}

export function EmptyState({ icon: Icon, title, children }: { icon: LucideIcon; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-border bg-card px-6 py-12 text-center">
      <Icon className="size-10 text-primary" aria-hidden />
      <p className="font-semibold">{title}</p>
      {children && <div className="text-sm text-muted-foreground">{children}</div>}
    </div>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-foreground sm:text-3xl">{title}</h1>
        {description && <p className="mt-1 max-w-prose text-muted-foreground">{description}</p>}
      </div>
      {actions}
    </header>
  );
}
