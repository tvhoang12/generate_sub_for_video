import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { ArrowLeft, Check, Pencil, Plus, Save, Sparkles, Trash2, X } from "lucide-react";
import { api, type FilmDetail, type Term } from "../api";
import { useLanguageLabel, useMeta } from "../meta";
import { Alert, Button, Card, Field, PageHeader } from "../components/ui";

type Draft = { term: string; note: string; translations: Record<string, string> };
const emptyDraft: Draft = { term: "", note: "", translations: {} };

function TermEditor({ initial, onSave, onCancel, saveLabel }: {
  initial: Draft; onSave: (d: Draft) => Promise<void>; onCancel?: () => void; saveLabel: string;
}) {
  const meta = useMeta();
  const [draft, setDraft] = useState<Draft>(initial);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!draft.term.trim()) return setError("Nhập thuật ngữ");
    setSaving(true);
    try {
      await onSave({ ...draft, term: draft.term.trim() });
      if (!onCancel) setDraft(emptyDraft);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} className="flex flex-col gap-4 rounded-xl bg-muted/60 p-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Thuật ngữ (theo bản gốc)" error={error ?? undefined}>
          {(p) => <input {...p} value={draft.term} onChange={(e) => { setDraft({ ...draft, term: e.target.value }); setError(null); }} placeholder="VD: Kestrel" />}
        </Field>
        <Field label="Ghi chú" helper="Là ai / là gì, giới tính, cách xưng hô.">
          {(p) => <input {...p} value={draft.note} onChange={(e) => setDraft({ ...draft, note: e.target.value })} placeholder="VD: nữ chính, người đưa thư" />}
        </Field>
      </div>
      <fieldset>
        <legend className="mb-2 text-sm font-semibold">Bản dịch cố định <span className="font-normal text-muted-foreground">(để trống nếu để AI tự phiên âm)</span></legend>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {meta?.languages.map((l) => (
            <Field key={l.code} label={l.label}>
              {(p) => (
                <input {...p} value={draft.translations[l.code] ?? ""}
                  onChange={(e) => setDraft({ ...draft, translations: { ...draft.translations, [l.code]: e.target.value } })} />
              )}
            </Field>
          ))}
        </div>
      </fieldset>
      <div className="flex flex-wrap gap-2">
        <Button type="submit" variant="primary" icon={onCancel ? Check : Plus} loading={saving}>{saveLabel}</Button>
        {onCancel && <Button type="button" variant="ghost" icon={X} onClick={onCancel}>Huỷ</Button>}
      </div>
    </form>
  );
}

export function FilmDetailPage() {
  const { id } = useParams();
  const filmId = Number(id);
  const meta = useMeta();
  const navigate = useNavigate();
  const langLabel = useLanguageLabel();
  const [film, setFilm] = useState<FilmDetail | null>(null);
  const [form, setForm] = useState({ name: "", source_language: "auto", synopsis: "", characters: "", style_notes: "" });
  const [editing, setEditing] = useState<number | null>(null);
  const [status, setStatus] = useState<{ tone: "error" | "info"; text: string } | null>(null);
  const [saving, setSaving] = useState(false);

  const reload = () =>
    api.film(filmId).then((f) => {
      setFilm(f);
      return f;
    });

  useEffect(() => {
    reload()
      .then((f) => setForm({ name: f.name, source_language: f.source_language, synopsis: f.synopsis, characters: f.characters, style_notes: f.style_notes }))
      .catch((e) => setStatus({ tone: "error", text: e.message }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filmId]);

  if (!film) return status ? <Alert tone="error" title="Không tải được phim">{status.text}</Alert> : <p className="text-muted-foreground">Đang tải…</p>;

  const saveFilm = async (e: FormEvent) => {
    e.preventDefault();
    if (!form.name.trim()) return setStatus({ tone: "error", text: "Tên phim không được để trống" });
    setSaving(true);
    try {
      await api.updateFilm(filmId, form);
      await reload();
      setStatus({ tone: "info", text: "Đã lưu ngữ cảnh phim" });
    } catch (err) {
      setStatus({ tone: "error", text: (err as Error).message });
    } finally {
      setSaving(false);
    }
  };

  const removeFilm = async () => {
    if (!window.confirm(`Xoá phim "${film.name}" cùng toàn bộ thuật ngữ? Các video đã xử lý vẫn được giữ.`)) return;
    await api.deleteFilm(filmId);
    navigate("/films");
  };

  const removeTerm = async (t: Term) => {
    if (!window.confirm(`Xoá thuật ngữ "${t.term}"?`)) return;
    await api.deleteTerm(t.id);
    await reload();
  };

  const confirmed = film.terms.filter((t) => !t.suggested);
  const suggested = film.terms.filter((t) => t.suggested);

  return (
    <>
      <Link to="/films" className="mb-4 inline-flex min-h-11 items-center gap-2 text-sm font-semibold text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" aria-hidden /> Tất cả phim
      </Link>
      <PageHeader title={film.name} actions={<Button variant="danger" icon={Trash2} onClick={removeFilm}>Xoá phim</Button>} />

      <div className="flex flex-col gap-6">
        <Card title="Ngữ cảnh phim" description="AI đọc phần này trước mỗi lần soát lỗi và dịch, cho mọi tập của phim.">
          <form onSubmit={saveFilm} className="flex flex-col gap-5">
            <div className="grid gap-5 sm:grid-cols-2">
              <Field label="Tên phim">
                {(p) => <input {...p} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />}
              </Field>
              <Field label="Ngôn ngữ nói trong phim" helper="Chọn đúng ngôn ngữ giúp nhận dạng giọng nói chính xác hơn.">
                {(p) => (
                  <select {...p} value={form.source_language} onChange={(e) => setForm({ ...form, source_language: e.target.value })}>
                    {meta?.source_languages.map((l) => <option key={l.code} value={l.code}>{l.label}</option>)}
                  </select>
                )}
              </Field>
            </div>
            <Field label="Tóm tắt nội dung" helper="Bối cảnh, mạch truyện chính.">
              {(p) => <textarea {...p} rows={3} value={form.synopsis} onChange={(e) => setForm({ ...form, synopsis: e.target.value })} />}
            </Field>
            <Field label="Nhân vật" helper="Tên, giới tính, tuổi, quan hệ — để AI xưng hô đúng. Mỗi nhân vật một dòng.">
              {(p) => <textarea {...p} rows={4} value={form.characters} onChange={(e) => setForm({ ...form, characters: e.target.value })}
                placeholder={"Kestrel — nữ, người đưa thư của Đế chế\nValor — nam, cậu chủ trẻ"} />}
            </Field>
            <Field label="Giọng văn mong muốn" helper="VD: cổ trang trang trọng, thân mật, hài hước…">
              {(p) => <textarea {...p} rows={2} value={form.style_notes} onChange={(e) => setForm({ ...form, style_notes: e.target.value })} />}
            </Field>
            {status && <Alert tone={status.tone} title={status.text} />}
            <div><Button type="submit" variant="primary" icon={Save} loading={saving}>Lưu ngữ cảnh</Button></div>
          </form>
        </Card>

        {suggested.length > 0 && (
          <Card title="AI đề xuất thuật ngữ" description="Tìm thấy khi xử lý các tập. Chỉ thuật ngữ đã duyệt mới được dùng khi dịch.">
            <ul className="flex flex-col gap-3">
              {suggested.map((t) =>
                editing === t.id ? (
                  <li key={t.id}>
                    <TermEditor initial={t} saveLabel="Duyệt và lưu" onCancel={() => setEditing(null)}
                      onSave={async (d) => { await api.updateTerm(t.id, { ...d, suggested: false }); setEditing(null); await reload(); }} />
                  </li>
                ) : (
                  <li key={t.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
                    <div className="min-w-0">
                      <p className="inline-flex items-center gap-2 font-semibold"><Sparkles className="size-4 text-warning" aria-hidden />{t.term}</p>
                      {t.note && <p className="text-sm text-muted-foreground">{t.note}</p>}
                    </div>
                    <div className="flex gap-2">
                      <Button icon={Check} onClick={() => setEditing(t.id)}>Duyệt</Button>
                      <Button variant="ghost" icon={X} onClick={() => removeTerm(t)}>Bỏ qua</Button>
                    </div>
                  </li>
                ),
              )}
            </ul>
          </Card>
        )}

        <Card title={`Bảng thuật ngữ (${confirmed.length})`} description="Tên riêng, địa danh, cách gọi cố định. AI luôn dùng đúng bản dịch ở đây.">
          {confirmed.length > 0 && (
            <ul className="mb-5 divide-y divide-border">
              {confirmed.map((t) =>
                editing === t.id ? (
                  <li key={t.id} className="py-3">
                    <TermEditor initial={t} saveLabel="Lưu" onCancel={() => setEditing(null)}
                      onSave={async (d) => { await api.updateTerm(t.id, { ...d, suggested: false }); setEditing(null); await reload(); }} />
                  </li>
                ) : (
                  <li key={t.id} className="flex flex-wrap items-start justify-between gap-3 py-3">
                    <div className="min-w-0">
                      <p className="font-semibold">{t.term}</p>
                      {t.note && <p className="text-sm text-muted-foreground">{t.note}</p>}
                      {Object.keys(t.translations).length > 0 && (
                        <ul className="mt-2 flex flex-wrap gap-2">
                          {Object.entries(t.translations).map(([code, text]) => (
                            <li key={code} className="rounded-full bg-muted px-3 py-1 text-sm">
                              <span className="text-muted-foreground">{langLabel(code)}:</span> {text}
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                    <div className="flex gap-1">
                      <Button variant="ghost" icon={Pencil} onClick={() => setEditing(t.id)} aria-label={`Sửa ${t.term}`}>Sửa</Button>
                      <Button variant="danger" icon={Trash2} onClick={() => removeTerm(t)} aria-label={`Xoá ${t.term}`}>Xoá</Button>
                    </div>
                  </li>
                ),
              )}
            </ul>
          )}
          <TermEditor initial={emptyDraft} saveLabel="Thêm thuật ngữ" onSave={async (d) => { await api.addTerm(filmId, d); await reload(); }} />
        </Card>
      </div>
    </>
  );
}
