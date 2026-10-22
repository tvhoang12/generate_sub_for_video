import { NavLink, Outlet } from "react-router";
import { Clapperboard, ListVideo, Upload, type LucideIcon } from "lucide-react";
import { useMeta } from "../meta";

const NAV: { to: string; label: string; icon: LucideIcon; end?: boolean }[] = [
  { to: "/", label: "Tạo phụ đề", icon: Upload, end: true },
  { to: "/jobs", label: "Công việc", icon: ListVideo },
  { to: "/films", label: "Phim & thuật ngữ", icon: Clapperboard },
];

export function Layout() {
  const meta = useMeta();
  return (
    <div className="min-h-dvh md:grid md:grid-cols-[240px_1fr]">
      <aside className="border-b border-border bg-card md:sticky md:top-0 md:h-dvh md:border-r md:border-b-0">
        <div className="flex items-center gap-2 px-4 py-4 md:px-5 md:py-6">
          <div className="grid size-9 place-items-center rounded-lg bg-primary text-sm font-bold text-on-primary" aria-hidden>
            SS
          </div>
          <div>
            <p className="font-bold leading-tight">SubStudio</p>
            <p className="text-xs text-muted-foreground">Phụ đề tự động</p>
          </div>
        </div>
        <nav aria-label="Điều hướng chính" className="flex gap-1 px-2 pb-2 md:flex-col md:px-3">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `flex min-h-11 flex-1 flex-col items-center justify-center gap-1 rounded-lg px-2 py-2 text-center text-xs font-semibold transition-colors duration-200 md:flex-none md:flex-row md:justify-start md:gap-3 md:px-3 md:text-left md:text-sm ${
                  isActive ? "bg-primary text-on-primary" : "text-muted-foreground hover:bg-muted hover:text-foreground"
                }`
              }
            >
              <Icon className="size-4" aria-hidden />
              {label}
            </NavLink>
          ))}
        </nav>
        {meta && (
          <p className="hidden px-5 pt-6 text-xs text-muted-foreground md:block">
            Dịch bằng <span className="font-semibold text-foreground">{meta.provider}</span>
            {meta.model && <> · {meta.model}</>}
          </p>
        )}
      </aside>
      <main className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 md:py-10">
        <Outlet />
      </main>
    </div>
  );
}
