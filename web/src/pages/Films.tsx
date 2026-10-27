import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import { BookOpen, ChevronRight, Clapperboard, Plus, Sparkles } from "lucide-react";
import { api, type Film } from "../api";
import { Alert, Button, Card, EmptyState, Field, PageHeader } from "../components/ui";

export function FilmsPage() {
  const navigate = useNavigate();
  const [films, setFilms] = useState<Film[] | null>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.films().then(setFilms).catch((e) => setError(e.message));
  }, []);

  const create = async (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return setError("Nhập tên phim");
    setSaving(true);
    try {
      const film = await api.createFilm({ name: name.trim() });
      navigate(`/films/${film.id}`);
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };

  return (
    <>
      <PageHeader
        title="Phim & thuật ngữ"
        description="Mỗi phim giữ ngữ cảnh và bảng thuật ngữ dùng chung cho mọi tập, để tên nhân vật và cách xưng hô được dịch thống nhất."
      />
      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
        <div>
          {films === null ? (
            <p className="text-muted-foreground">Đang tải…</p>
          ) : films.length === 0 ? (
            <EmptyState icon={Clapperboard} title="Chưa có phim nào">Thêm phim đầu tiên ở khung bên cạnh.</EmptyState>
          ) : (
            <ul className="flex flex-col gap-3">
              {films.map((f) => (
                <li key={f.id}>
                  <Link to={`/films/${f.id}`}
                    className="group flex items-center gap-4 rounded-xl border border-border bg-card p-4 shadow-sm transition-colors duration-200 hover:border-primary">
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-semibold">{f.name}</p>
                      <p className="mt-1 flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
                        <span className="inline-flex items-center gap-1"><BookOpen className="size-4" aria-hidden />{f.term_count} thuật ngữ</span>
                        {!!f.suggested_count && (
                          <span className="inline-flex items-center gap-1 font-semibold text-warning">
                            <Sparkles className="size-4" aria-hidden />{f.suggested_count} đề xuất chờ duyệt
                          </span>
                        )}
                      </p>
                    </div>
                    <ChevronRight className="size-5 text-muted-foreground group-hover:text-primary" aria-hidden />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
        <Card title="Thêm phim">
          <form onSubmit={create} className="flex flex-col gap-4">
            <Field label="Tên phim" error={error ?? undefined}>
              {(p) => <input {...p} value={name} onChange={(e) => { setName(e.target.value); setError(null); }} placeholder="VD: The Mirror Between" />}
            </Field>
            <Button type="submit" variant="primary" icon={Plus} loading={saving}>Thêm phim</Button>
          </form>
          {films === null && error && <div className="mt-4"><Alert tone="error" title="Lỗi">{error}</Alert></div>}
        </Card>
      </div>
    </>
  );
}
