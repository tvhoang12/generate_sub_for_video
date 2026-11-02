import { useState, useRef, useEffect, useCallback, type PointerEvent } from "react";
import {
  Bold,
  Check,
  Eye,
  EyeOff,
  GripVertical,
  ImagePlus,
  Italic,
  Monitor,
  MoveVertical,
  Palette,
  RotateCcw,
  Sliders,
  Smartphone,
  X,
} from "lucide-react";
import type { SubtitleConfig } from "../api";
import { Button, Card, Field } from "./ui";

export const DEFAULT_SUBTITLE_CONFIG: Required<SubtitleConfig> = {
  font: "",
  font_size: 25,
  color: "#FFFFFF",
  color_border: "#000000",
  has_border: true,
  has_shadow: true,
  color_shadow: "#000000",
  bold: true,
  italic: false,
  margin_l: 10,
  margin_r: 10,
  margin_v: 12,
  outline: 1.6,
  shadow: 0.5,
  burn_video: true,
  mask_enabled: true,
  mask_color: "#000000",
  mask_blur: 12,
  mask_opacity: 40,
  mask_shape: "pill",
};

export function hexToRgba(hex: string, opacity: number): string {
  const c = (hex || "#000000").replace("#", "").trim();
  let r = 0,
    g = 0,
    b = 0;
  if (c.length === 3) {
    r = parseInt(c[0] + c[0], 16) || 0;
    g = parseInt(c[1] + c[1], 16) || 0;
    b = parseInt(c[2] + c[2], 16) || 0;
  } else if (c.length === 6) {
    r = parseInt(c.slice(0, 2), 16) || 0;
    g = parseInt(c.slice(2, 4), 16) || 0;
    b = parseInt(c.slice(4, 6), 16) || 0;
  }
  return `rgba(${r}, ${g}, ${b}, ${Math.max(0, Math.min(1, opacity))})`;
}

const MASK_SHAPE_OPTIONS = [
  {
    id: "pill" as const,
    name: "Bo tròn (Pill)",
    desc: "Bám sát dòng chữ",
    roundedClass: "rounded-full",
  },
  {
    id: "rounded" as const,
    name: "Bo góc nhẹ",
    desc: "Khung chữ nhật bo góc mềm",
    roundedClass: "rounded-xl",
  },
  {
    id: "rectangle" as const,
    name: "Chữ nhật vuông",
    desc: "Khối sắc nét che kín",
    roundedClass: "rounded-none",
  },
  {
    id: "bar" as const,
    name: "Dải ngang toàn khung",
    desc: "Kéo dài suốt chân video",
    roundedClass: "rounded-none",
  },
];

const COLOR_PRESETS = [
  { name: "Trắng tinh (Chuẩn)", hex: "#FFFFFF" },
  { name: "Đen tuyền (Viền chuẩn)", hex: "#000000" },
  { name: "Vàng kinh điển", hex: "#FACC15" },
  { name: "Vàng chanh", hex: "#FEF08A" },
  { name: "Cam sáng", hex: "#FB923C" },
  { name: "Xanh ngọc", hex: "#2DD4BF" },
  { name: "Xanh dương nhạt", hex: "#93C5FD" },
  { name: "Hồng phấn", hex: "#F472B6" },
  { name: "Xanh mint", hex: "#86EFAC" },
  { name: "Tím lilac", hex: "#C084FC" },
  { name: "Xám bạc", hex: "#E2E8F0" },
  { name: "Đen chì (Viền đậm)", hex: "#1E293B" },
  { name: "Xanh bóng đêm", hex: "#0F172A" },
  { name: "Đỏ rượu", hex: "#450A0A" },
  { name: "Nâu cánh gián", hex: "#451A03" },
];

const FONT_OPTIONS = [
  { label: "Tự động tối ưu theo ngôn ngữ (Khuyên dùng)", value: "" },
  { label: "Phetsarath OT (Chuẩn tiếng Lào)", value: "Phetsarath OT" },
  { label: "Kantumruy Pro (Chuẩn tiếng Khmer)", value: "Kantumruy Pro" },
  { label: "Noto Sans (Đa ngôn ngữ)", value: "Noto Sans" },
  { label: "Arial", value: "Arial" },
  { label: "Roboto", value: "Roboto" },
  { label: "Plus Jakarta Sans", value: "Plus Jakarta Sans" },
  { label: "Leelawadee UI (Khmer / Lao / Thai)", value: "Leelawadee UI" },
  { label: "Microsoft YaHei (Trung giản thể)", value: "Microsoft YaHei" },
  { label: "Tuỳ chỉnh phông chữ...", value: "__custom__" },
];

const SAMPLE_TEXTS: Record<string, string> = {
  km: "ឥឡូវព្រះអធិរាជចង់ឱ្យលោកតាសរសេរថ្កោលទោសអតីតអធិរាជ",
  lo: "ຕອນນີ້ ພະເຈົ້າຈັກກະພັດ ຕ້ອງການໃຫ້ທ່ານຂຽນປະນາມອະດີດຈັກກະພັດ",
  vi: "Tôi sẽ tìm ra chân tướng sự việc đằng sau chuyện này",
  en: "I will uncover the truth behind this incident",
  zh: "怎么做回甲乙丙丁",
};

export function SubtitleConfigCard({
  value,
  onChange,
}: {
  value: SubtitleConfig;
  onChange: (cfg: SubtitleConfig) => void;
}) {
  const cfg: Required<SubtitleConfig> = { ...DEFAULT_SUBTITLE_CONFIG, ...value };
  const [showColorModal, setShowColorModal] = useState(false);
  const [colorTarget, setColorTarget] = useState<"color" | "color_border" | "color_shadow" | "color_mask">("color");
  const [tempColor, setTempColor] = useState(cfg.color);
  const [customFont, setCustomFont] = useState(
    FONT_OPTIONS.some((o) => o.value === cfg.font && o.value !== "__custom__") ? "" : cfg.font
  );
  const [sampleLang, setSampleLang] = useState<string>("km");
  const [customSampleText, setCustomSampleText] = useState("");
  const [previewAspect, setPreviewAspect] = useState<"16:9" | "9:16">("9:16");
  const [isDragging, setIsDragging] = useState(false);
  const [sampleImageUrl, setSampleImageUrl] = useState<string | null>(null);

  const colorModalRef = useRef<HTMLDivElement>(null);
  const previewContainerRef = useRef<HTMLDivElement>(null);
  const sampleImageInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    return () => {
      if (sampleImageUrl) URL.revokeObjectURL(sampleImageUrl);
    };
  }, [sampleImageUrl]);

  // Close color modal on Escape
  useEffect(() => {
    if (!showColorModal) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setShowColorModal(false);
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [showColorModal]);

  const update = <K extends keyof SubtitleConfig>(key: K, val: SubtitleConfig[K]) => {
    onChange({ ...cfg, [key]: val });
  };

  const resetDefaults = () => {
    onChange({ ...DEFAULT_SUBTITLE_CONFIG });
    setCustomFont("");
  };

  const openColorPicker = (target: "color" | "color_border" | "color_shadow" | "color_mask") => {
    setColorTarget(target);
    if (target === "color") {
      setTempColor(cfg.color);
    } else if (target === "color_border") {
      setTempColor(cfg.color_border);
    } else if (target === "color_shadow") {
      setTempColor(cfg.color_shadow);
    } else {
      setTempColor(cfg.mask_color);
    }
    setShowColorModal(true);
  };

  const applyColor = (colorHex: string) => {
    if (colorTarget === "color") {
      update("color", colorHex);
    } else if (colorTarget === "color_border") {
      update("color_border", colorHex);
    } else if (colorTarget === "color_shadow") {
      update("color_shadow", colorHex);
    } else {
      update("mask_color", colorHex);
    }
    setShowColorModal(false);
  };

  // Direct Drag-and-Drop vertical positioning calculation
  const handlePointerDown = (e: PointerEvent) => {
    e.preventDefault();
    setIsDragging(true);
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
  };

  const handlePointerMove = useCallback(
    (e: PointerEvent) => {
      if (!isDragging || !previewContainerRef.current) return;
      const rect = previewContainerRef.current.getBoundingClientRect();
      const bottomDistancePx = rect.bottom - e.clientY;
      // Convert pixel distance to ASS PlayResY (288) coordinate
      const ratio = bottomDistancePx / rect.height;
      const newMarginV = Math.max(5, Math.min(400, Math.round(ratio * 400)));
      update("margin_v", newMarginV);
    },
    [isDragging, cfg]
  );

  const handlePointerUp = (e: PointerEvent) => {
    if (isDragging) {
      setIsDragging(false);
      try {
        (e.target as HTMLElement).releasePointerCapture?.(e.pointerId);
      } catch {
        // ignore
      }
    }
  };

  const currentSample = customSampleText.trim() || SAMPLE_TEXTS[sampleLang] || SAMPLE_TEXTS.km;

  const handleSampleImage = (file: File | undefined) => {
    if (!file || !file.type.startsWith("image/")) return;
    setSampleImageUrl((previousUrl) => {
      if (previousUrl) URL.revokeObjectURL(previousUrl);
      return URL.createObjectURL(file);
    });
  };

  const previewFontFamily = cfg.font
    ? `"${cfg.font}", var(--font-sans)`
    : "var(--font-sans)";

  // Render exact font size selected by user (1:1, without artificial scaling)
  const renderedFontSize = cfg.font_size;
  const scaledMarginV = Math.max(4, cfg.margin_v);
  const scaledMarginL = Math.max(0, cfg.margin_l);
  const scaledMarginR = Math.max(0, cfg.margin_r);
  const outlinePx = Math.max(1, cfg.outline || 1.6);

  const previewTextShadow = (() => {
    const parts: string[] = [];
    if (cfg.has_border) {
      parts.push(
        `-${outlinePx}px -${outlinePx}px 0 ${cfg.color_border}`,
        `${outlinePx}px -${outlinePx}px 0 ${cfg.color_border}`,
        `-${outlinePx}px  ${outlinePx}px 0 ${cfg.color_border}`,
        `${outlinePx}px  ${outlinePx}px 0 ${cfg.color_border}`
      );
    }
    if (cfg.has_shadow) {
      parts.push(`0 1.5px 4px ${cfg.color_shadow || "#000000"}`);
    }
    return parts.length > 0 ? parts.join(", ") : "none";
  })();

  const modalBorderColor = colorTarget === "color_border" ? tempColor : cfg.color_border;
  const modalShadowColor = colorTarget === "color_shadow" ? tempColor : (cfg.color_shadow || "#000000");

  const modalTextShadow = (() => {
    const parts: string[] = [];
    if (cfg.has_border || colorTarget === "color_border") {
      parts.push(
        `-1.5px -1.5px 0 ${modalBorderColor}`,
        ` 1.5px -1.5px 0 ${modalBorderColor}`,
        `-1.5px  1.5px 0 ${modalBorderColor}`,
        ` 1.5px  1.5px 0 ${modalBorderColor}`
      );
    }
    if (cfg.has_shadow || colorTarget === "color_shadow") {
      parts.push(`0 1.5px 4px ${modalShadowColor}`);
    }
    return parts.length > 0 ? parts.join(", ") : "none";
  })();

  const modalSubTextShadow = (() => {
    const parts: string[] = [];
    if (cfg.has_border || colorTarget === "color_border") {
      parts.push(
        `-1px -1px 0 ${modalBorderColor}`,
        ` 1px -1px 0 ${modalBorderColor}`,
        `-1px  1px 0 ${modalBorderColor}`,
        ` 1px  1px 0 ${modalBorderColor}`
      );
    }
    if (cfg.has_shadow || colorTarget === "color_shadow") {
      parts.push(`0 1px 3px ${modalShadowColor}`);
    }
    return parts.length > 0 ? parts.join(", ") : "none";
  })();

  const getMaskShapeClasses = (shape: "pill" | "rounded" | "rectangle" | "bar") => {
    switch (shape) {
      case "pill":
        return "inset-0 -inset-x-3.5 -inset-y-1.5 rounded-full";
      case "rounded":
        return "inset-0 -inset-x-3 -inset-y-1.5 rounded-xl";
      case "rectangle":
        return "inset-0 -inset-x-3 -inset-y-1 rounded-none";
      case "bar":
        return "-inset-y-1 -left-[1000px] -right-[1000px] rounded-none";
      default:
        return "inset-0 -inset-x-3.5 -inset-y-1.5 rounded-full";
    }
  };

  const maskBlurPx = cfg.mask_blur ?? 12;
  const maskBgColor = hexToRgba(cfg.mask_color || "#000000", (cfg.mask_opacity ?? 40) / 100);
  const maskBoxShadow =
    maskBlurPx > 0
      ? `0 2px ${Math.max(4, maskBlurPx)}px ${hexToRgba(
          cfg.mask_color || "#000000",
          ((cfg.mask_opacity ?? 40) / 100) * 0.75
        )}`
      : "none";

  const activeModalMaskColor = colorTarget === "color_mask" ? tempColor : (cfg.mask_color || "#000000");
  const modalMaskBgColor = hexToRgba(activeModalMaskColor, (cfg.mask_opacity ?? 40) / 100);
  const showModalMask = cfg.mask_enabled || colorTarget === "color_mask";

  return (
    <Card
      title="4. Cấu hình phụ đề"
      description="Tuỳ chỉnh giao diện phụ đề: phông chữ, màu chữ, viền, đổ bóng, làm mờ phụ đề cũ, kích thước, căn lề và xem trước trực tiếp trên khung hình video bên dưới."
      actions={
        <Button
          type="button"
          variant="ghost"
          icon={RotateCcw}
          onClick={resetDefaults}
          className="text-xs"
          title="Khôi phục thông số mặc định khuyến nghị"
        >
          Khôi phục mặc định
        </Button>
      }
    >
      <div className="flex flex-col gap-6">
        {/* --- Top Section: Controls Grid --- */}
        <div className="flex flex-col gap-5">
          {/* Row 1: Font Picker & Main Text Color */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
            {/* Font Picker (7 cols) */}
            <div className="lg:col-span-7">
              <Field
                label="Phông chữ phụ đề"
                helper="Hỗ trợ chuẩn Phetsarath OT (tiếng Lào), Kantumruy Pro (Khmer), Noto Sans và các phông tuỳ chọn."
              >
                {(p) => (
                  <div className="flex flex-col gap-2">
                    <select
                      {...p}
                      value={
                        FONT_OPTIONS.some((o) => o.value === cfg.font && o.value !== "__custom__")
                          ? cfg.font
                          : "__custom__"
                      }
                      onChange={(e) => {
                        const v = e.target.value;
                        if (v === "__custom__") {
                          update("font", customFont || "Noto Sans");
                        } else {
                          update("font", v);
                        }
                      }}
                    >
                      {FONT_OPTIONS.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                    {(!FONT_OPTIONS.some((o) => o.value === cfg.font && o.value !== "__custom__") ||
                      cfg.font === "__custom__") && (
                        <input
                          type="text"
                          className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-foreground focus:border-primary focus:outline-none"
                          placeholder="Nhập tên font (VD: Phetsarath OT, Kantumruy Pro, Arial...)"
                          value={customFont}
                          onChange={(e) => {
                            setCustomFont(e.target.value);
                            update("font", e.target.value);
                          }}
                        />
                      )}
                  </div>
                )}
              </Field>
            </div>

            {/* Màu chữ (5 cols) */}
            <div className="flex flex-col gap-1.5 lg:col-span-5">
              <label className="text-sm font-semibold text-foreground">Màu chữ phụ đề</label>
              <button
                type="button"
                onClick={() => openColorPicker("color")}
                className="group flex min-h-11 items-center justify-between gap-2.5 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium transition-all hover:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
              >
                <div className="flex items-center gap-2">
                  <span
                    className="size-5 shrink-0 rounded-md border border-slate-400/60 shadow-inner"
                    style={{ backgroundColor: cfg.color }}
                  />
                  <span className="font-mono text-xs font-bold text-foreground">{cfg.color}</span>
                </div>
                <Palette className="size-4 text-primary group-hover:scale-110 transition-transform" aria-hidden />
              </button>
              <p className="text-xs text-muted-foreground">Màu thân chữ chính</p>
            </div>
          </div>

          {/* Row 2: Font Size & Bold/Italic Formats */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {/* Font Size with Instant Slider & Presets */}
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between">
                <label htmlFor="font-size-slider" className="text-sm font-semibold text-foreground">
                  Kích thước chữ
                </label>
                <span className="rounded bg-primary/10 px-2.5 py-0.5 font-mono text-sm font-bold text-primary-strong">
                  {cfg.font_size} px
                </span>
              </div>
              <div className="flex items-center gap-3">
                <input
                  id="font-size-slider"
                  type="range"
                  min="16"
                  max="42"
                  step="1"
                  value={cfg.font_size}
                  onChange={(e) => update("font_size", Number(e.target.value))}
                  className="h-2 w-full cursor-pointer accent-primary"
                />
                <input
                  type="number"
                  min="14"
                  max="48"
                  value={cfg.font_size}
                  onChange={(e) => {
                    const v = parseInt(e.target.value, 10);
                    if (!isNaN(v)) update("font_size", v);
                  }}
                  onBlur={(e) => {
                    const v = Math.max(14, Math.min(48, Number(e.target.value) || 25));
                    update("font_size", v);
                  }}
                  className="w-16 rounded-lg border border-slate-300 px-2 py-1.5 text-center font-mono text-sm font-bold text-foreground"
                />
              </div>
              <div className="flex justify-between text-xs text-muted-foreground pt-0.5">
                <button
                  type="button"
                  onClick={() => update("font_size", 20)}
                  className={`hover:text-primary ${cfg.font_size === 20 ? "font-bold text-primary" : ""}`}
                >
                  Nhỏ (20)
                </button>
                <button
                  type="button"
                  onClick={() => update("font_size", 25)}
                  className={`hover:text-primary ${cfg.font_size === 25 ? "font-bold text-primary underline" : ""}`}
                >
                  Chuẩn (25)
                </button>
                <button
                  type="button"
                  onClick={() => update("font_size", 28)}
                  className={`hover:text-primary ${cfg.font_size === 28 ? "font-bold text-primary" : ""}`}
                >
                  Lớn (28)
                </button>
                <button
                  type="button"
                  onClick={() => update("font_size", 34)}
                  className={`hover:text-primary ${cfg.font_size === 34 ? "font-bold text-primary" : ""}`}
                >
                  Cực lớn (34)
                </button>
              </div>
            </div>

            {/* In đậm / In nghiêng Checkbox Options */}
            <div className="flex flex-col gap-1.5">
              <label className="text-sm font-semibold text-foreground">Định dạng kiểu chữ</label>
              <div className="grid grid-cols-2 gap-3">
                <label
                  className={`flex min-h-11 cursor-pointer select-none items-center justify-center gap-2 rounded-lg border-2 px-3 text-sm font-semibold transition-all ${cfg.bold
                    ? "border-primary bg-primary/10 text-primary-strong"
                    : "border-slate-300 bg-white text-muted-foreground hover:border-slate-400"
                    }`}
                >
                  <input
                    type="checkbox"
                    checked={cfg.bold}
                    onChange={(e) => update("bold", e.target.checked)}
                    className="sr-only"
                  />
                  <Bold className="size-4 shrink-0" aria-hidden />
                  <span>In đậm (Bold)</span>
                  {cfg.bold && <Check className="ml-auto size-4 text-primary" aria-hidden />}
                </label>

                <label
                  className={`flex min-h-11 cursor-pointer select-none items-center justify-center gap-2 rounded-lg border-2 px-3 text-sm font-semibold transition-all ${cfg.italic
                    ? "border-primary bg-primary/10 text-primary-strong"
                    : "border-slate-300 bg-white text-muted-foreground hover:border-slate-400"
                    }`}
                >
                  <input
                    type="checkbox"
                    checked={cfg.italic}
                    onChange={(e) => update("italic", e.target.checked)}
                    className="sr-only"
                  />
                  <Italic className="size-4 shrink-0" aria-hidden />
                  <span>In nghiêng (Italic)</span>
                  {cfg.italic && <Check className="ml-auto size-4 text-primary" aria-hidden />}
                </label>
              </div>
              <p className="text-xs text-muted-foreground">Khuyên dùng in đậm để chữ sắc nét và nổi bật trên video.</p>
            </div>
          </div>

          {/* Row 3: Hiệu ứng viền chữ & đổ bóng */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {/* Box 1: Cấu hình Viền chữ */}
            <div
              className={`flex flex-col justify-between gap-3 rounded-xl border p-4 transition-all ${
                cfg.has_border ? "border-primary/30 bg-primary/5" : "border-slate-200 bg-slate-50/60"
              }`}
            >
              <div className="flex items-center justify-between">
                <label className="flex items-center gap-2.5 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={cfg.has_border}
                    onChange={(e) => update("has_border", e.target.checked)}
                    className="size-4.5 rounded border-slate-300 text-primary accent-primary focus:ring-2 focus:ring-primary/20 cursor-pointer"
                  />
                  <span className="text-sm font-semibold text-foreground">Viền chữ</span>
                </label>
                <span
                  className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                    cfg.has_border
                      ? "bg-primary/10 text-primary-strong"
                      : "bg-slate-200/70 text-slate-500"
                  }`}
                >
                  {cfg.has_border ? "Đang bật" : "Đang tắt"}
                </span>
              </div>

              <div className="flex flex-col gap-1.5">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-semibold text-foreground">Màu viền chữ</label>
                  {cfg.has_border && (
                    <span className="font-mono text-[11px] font-bold text-muted-foreground">{cfg.color_border}</span>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => {
                    if (!cfg.has_border) update("has_border", true);
                    openColorPicker("color_border");
                  }}
                  className={`group flex min-h-11 items-center justify-between gap-2.5 rounded-lg border px-3 py-2 text-sm font-medium transition-all ${
                    cfg.has_border
                      ? "border-slate-300 bg-white hover:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
                      : "border-slate-200 bg-slate-100/70 text-slate-400 hover:border-slate-300"
                  }`}
                  title={cfg.has_border ? "Nhấp để đổi màu viền chữ" : "Nhấp để bật và chọn màu viền chữ"}
                >
                  <div className="flex items-center gap-2">
                    <span
                      className={`size-5 shrink-0 rounded-md border shadow-inner ${
                        cfg.has_border ? "border-slate-400/60" : "border-slate-300 opacity-40"
                      }`}
                      style={{ backgroundColor: cfg.color_border }}
                    />
                    <span className={`font-mono text-xs font-bold ${cfg.has_border ? "text-foreground" : "text-slate-400"}`}>
                      {cfg.has_border ? cfg.color_border : "Không có viền (Bấm để bật)"}
                    </span>
                  </div>
                  <Palette className={`size-4 ${cfg.has_border ? "text-primary group-hover:scale-110" : "text-slate-400"} transition-transform`} aria-hidden />
                </button>
                <p className="text-xs text-muted-foreground">Viền bo chống lẫn nền video</p>
              </div>
            </div>

            {/* Box 2: Cấu hình Đổ bóng chữ */}
            <div
              className={`flex flex-col justify-between gap-3 rounded-xl border p-4 transition-all ${
                cfg.has_shadow ? "border-primary/30 bg-primary/5" : "border-slate-200 bg-slate-50/60"
              }`}
            >
              <div className="flex items-center justify-between">
                <label className="flex items-center gap-2.5 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={cfg.has_shadow}
                    onChange={(e) => update("has_shadow", e.target.checked)}
                    className="size-4.5 rounded border-slate-300 text-primary accent-primary focus:ring-2 focus:ring-primary/20 cursor-pointer"
                  />
                  <span className="text-sm font-semibold text-foreground">Đổ bóng chữ</span>
                </label>
                <span
                  className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                    cfg.has_shadow
                      ? "bg-primary/10 text-primary-strong"
                      : "bg-slate-200/70 text-slate-500"
                  }`}
                >
                  {cfg.has_shadow ? "Đang bật" : "Đang tắt"}
                </span>
              </div>

              <div className="flex flex-col gap-1.5">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-semibold text-foreground">Màu đổ bóng</label>
                  {cfg.has_shadow && (
                    <span className="font-mono text-[11px] font-bold text-muted-foreground">{cfg.color_shadow}</span>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => {
                    if (!cfg.has_shadow) update("has_shadow", true);
                    openColorPicker("color_shadow");
                  }}
                  className={`group flex min-h-11 items-center justify-between gap-2.5 rounded-lg border px-3 py-2 text-sm font-medium transition-all ${
                    cfg.has_shadow
                      ? "border-slate-300 bg-white hover:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
                      : "border-slate-200 bg-slate-100/70 text-slate-400 hover:border-slate-300"
                  }`}
                  title={cfg.has_shadow ? "Nhấp để đổi màu đổ bóng chữ" : "Nhấp để bật và chọn màu đổ bóng"}
                >
                  <div className="flex items-center gap-2">
                    <span
                      className={`size-5 shrink-0 rounded-md border shadow-inner ${
                        cfg.has_shadow ? "border-slate-400/60" : "border-slate-300 opacity-40"
                      }`}
                      style={{ backgroundColor: cfg.color_shadow }}
                    />
                    <span className={`font-mono text-xs font-bold ${cfg.has_shadow ? "text-foreground" : "text-slate-400"}`}>
                      {cfg.has_shadow ? cfg.color_shadow : "Không đổ bóng (Bấm để bật)"}
                    </span>
                  </div>
                  <Palette className={`size-4 ${cfg.has_shadow ? "text-primary group-hover:scale-110" : "text-slate-400"} transition-transform`} aria-hidden />
                </button>
                <p className="text-xs text-muted-foreground">Bóng mờ tạo chiều sâu cho chữ</p>
              </div>
            </div>
          </div>

          {/* Row 4: Làm mờ phụ đề cũ (Che phụ đề gốc trên video) */}
          <div className="rounded-xl border border-border/90 bg-muted/30 p-4 transition-all sm:p-5">
            {/* Header: Title, Description, and Toggle Checkbox */}
            <div className="flex flex-col gap-3 pb-4 border-b border-border/70 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-start gap-3">
                <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary mt-0.5">
                  <EyeOff className="size-5" aria-hidden />
                </div>
                <div className="flex flex-col">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-foreground">
                      Làm mờ phụ đề cũ (Che phụ đề gốc)
                    </span>
                    <span
                      className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                        cfg.mask_enabled
                          ? "bg-primary/10 text-primary-strong"
                          : "bg-slate-200/70 text-slate-500"
                      }`}
                    >
                      {cfg.mask_enabled ? "Đang bật" : "Đang tắt"}
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Tạo ô mờ phía sau phụ đề để che đi phụ đề gốc (tiếng Trung, tiếng Anh...) có sẵn trên video mà không cần chèn thanh đen thô cứng.
                  </p>
                </div>
              </div>

              <label className="flex items-center gap-2 cursor-pointer select-none shrink-0 self-start sm:self-center">
                <input
                  type="checkbox"
                  checked={cfg.mask_enabled}
                  onChange={(e) => update("mask_enabled", e.target.checked)}
                  className="size-4.5 rounded border-slate-300 text-primary accent-primary focus:ring-2 focus:ring-primary/20 cursor-pointer"
                />
                <span className="text-sm font-semibold text-foreground">Bật làm mờ</span>
              </label>
            </div>

            {/* Options grid (Color, Blur intensity & Opacity, Shape) */}
            <div className={`mt-4 flex flex-col gap-5 transition-opacity ${cfg.mask_enabled ? "opacity-100" : "opacity-40 pointer-events-none"}`}>
              {/* Top row: Chọn màu làm mờ & Mức độ mờ */}
              <div className="grid grid-cols-1 gap-5 lg:grid-cols-12">
                {/* 1. Chọn màu làm mờ (4 cols) */}
                <div className="flex flex-col gap-1.5 lg:col-span-4">
                  <div className="flex items-center justify-between">
                    <label className="text-xs font-semibold text-foreground">Màu làm mờ</label>
                    <span className="font-mono text-[11px] font-bold text-muted-foreground">{cfg.mask_color}</span>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      if (!cfg.mask_enabled) update("mask_enabled", true);
                      openColorPicker("color_mask");
                    }}
                    className="group flex min-h-11 items-center justify-between gap-2.5 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium transition-all hover:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
                    title="Nhấp để chọn màu nền làm mờ"
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className="size-5 shrink-0 rounded-md border border-slate-400/60 shadow-inner"
                        style={{ backgroundColor: cfg.mask_color }}
                      />
                      <span className="font-mono text-xs font-bold text-foreground">{cfg.mask_color}</span>
                    </div>
                    <Palette className="size-4 text-primary group-hover:scale-110 transition-transform" aria-hidden />
                  </button>
                  <p className="text-xs text-muted-foreground">Màu lớp nền che phụ đề cũ (mặc định đen tuyền)</p>
                </div>

                {/* 2. Mức độ mờ: Blur radius & Opacity (8 cols) */}
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:col-span-8">
                  {/* Độ nhòe mờ (Blur Radius) */}
                  <div className="flex flex-col gap-1.5">
                    <div className="flex items-center justify-between">
                      <label htmlFor="mask-blur-slider" className="text-xs font-semibold text-foreground">
                        Độ nhòe mờ (Blur)
                      </label>
                      <span className="rounded bg-primary/10 px-2 py-0.5 font-mono text-xs font-bold text-primary-strong">
                        {cfg.mask_blur} px
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      <input
                        id="mask-blur-slider"
                        type="range"
                        min="0"
                        max="30"
                        step="1"
                        value={cfg.mask_blur}
                        onChange={(e) => update("mask_blur", Number(e.target.value))}
                        className="h-2 w-full cursor-pointer accent-primary"
                      />
                      <input
                        type="number"
                        min="0"
                        max="30"
                        value={cfg.mask_blur}
                        onChange={(e) => {
                          const v = parseInt(e.target.value, 10);
                          if (!isNaN(v)) update("mask_blur", Math.max(0, Math.min(30, v)));
                        }}
                        className="w-14 rounded-lg border border-slate-300 px-1.5 py-1 text-center font-mono text-xs font-bold text-foreground"
                      />
                    </div>
                    <div className="flex justify-between text-[11px] text-muted-foreground pt-0.5">
                      <button
                        type="button"
                        onClick={() => update("mask_blur", 0)}
                        className={`hover:text-primary ${cfg.mask_blur === 0 ? "font-bold text-primary underline" : ""}`}
                      >
                        Tắt (0)
                      </button>
                      <button
                        type="button"
                        onClick={() => update("mask_blur", 6)}
                        className={`hover:text-primary ${cfg.mask_blur === 6 ? "font-bold text-primary underline" : ""}`}
                      >
                        Nhẹ (6)
                      </button>
                      <button
                        type="button"
                        onClick={() => update("mask_blur", 12)}
                        className={`hover:text-primary ${cfg.mask_blur === 12 ? "font-bold text-primary underline" : ""}`}
                      >
                        Chuẩn (12)
                      </button>
                      <button
                        type="button"
                        onClick={() => update("mask_blur", 20)}
                        className={`hover:text-primary ${cfg.mask_blur === 20 ? "font-bold text-primary underline" : ""}`}
                      >
                        Mạnh (20)
                      </button>
                    </div>
                  </div>

                  {/* Độ đậm nền (Opacity) */}
                  <div className="flex flex-col gap-1.5">
                    <div className="flex items-center justify-between">
                      <label htmlFor="mask-opacity-slider" className="text-xs font-semibold text-foreground">
                        Độ đậm nền (Opacity)
                      </label>
                      <span className="rounded bg-primary/10 px-2 py-0.5 font-mono text-xs font-bold text-primary-strong">
                        {cfg.mask_opacity} %
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      <input
                        id="mask-opacity-slider"
                        type="range"
                        min="10"
                        max="100"
                        step="5"
                        value={cfg.mask_opacity}
                        onChange={(e) => update("mask_opacity", Number(e.target.value))}
                        className="h-2 w-full cursor-pointer accent-primary"
                      />
                      <input
                        type="number"
                        min="10"
                        max="100"
                        step="5"
                        value={cfg.mask_opacity}
                        onChange={(e) => {
                          const v = parseInt(e.target.value, 10);
                          if (!isNaN(v)) update("mask_opacity", Math.max(10, Math.min(100, v)));
                        }}
                        className="w-14 rounded-lg border border-slate-300 px-1.5 py-1 text-center font-mono text-xs font-bold text-foreground"
                      />
                    </div>
                    <div className="flex justify-between text-[11px] text-muted-foreground pt-0.5">
                      <button
                        type="button"
                        onClick={() => update("mask_opacity", 25)}
                        className={`hover:text-primary ${cfg.mask_opacity === 25 ? "font-bold text-primary underline" : ""}`}
                      >
                        Mờ (25%)
                      </button>
                      <button
                        type="button"
                        onClick={() => update("mask_opacity", 40)}
                        className={`hover:text-primary ${cfg.mask_opacity === 40 ? "font-bold text-primary underline" : ""}`}
                      >
                        Chuẩn (40%)
                      </button>
                      <button
                        type="button"
                        onClick={() => update("mask_opacity", 70)}
                        className={`hover:text-primary ${cfg.mask_opacity === 70 ? "font-bold text-primary underline" : ""}`}
                      >
                        Đậm (70%)
                      </button>
                      <button
                        type="button"
                        onClick={() => update("mask_opacity", 100)}
                        className={`hover:text-primary ${cfg.mask_opacity === 100 ? "font-bold text-primary underline" : ""}`}
                      >
                        Kín (100%)
                      </button>
                    </div>
                  </div>
                </div>
              </div>

              {/* 3. Hình dạng làm mờ (ô chữ) */}
              <div className="flex flex-col gap-2 pt-2 border-t border-border/60">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-semibold text-foreground">
                    Hình dạng làm mờ (ô chữ)
                  </label>
                  <span className="text-[11px] text-muted-foreground">
                    Chọn kiểu dáng khung che chữ phía sau
                  </span>
                </div>

                <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
                  {MASK_SHAPE_OPTIONS.map((shape) => {
                    const isSelected = (cfg.mask_shape || "pill") === shape.id;
                    return (
                      <button
                        key={shape.id}
                        type="button"
                        onClick={() => update("mask_shape", shape.id)}
                        className={`group flex flex-col items-center justify-center gap-2 rounded-xl border-2 p-3 text-center transition-all ${
                          isSelected
                            ? "border-primary bg-primary/10 text-primary-strong ring-2 ring-primary/20 shadow-xs"
                            : "border-slate-300 bg-white text-muted-foreground hover:border-slate-400 hover:text-foreground"
                        }`}
                      >
                        <div className="flex h-7 items-center justify-center w-full">
                          <span
                            className={`h-4 border border-slate-400/80 bg-slate-700/60 transition-all ${shape.roundedClass} ${
                              shape.id === "bar" ? "w-16" : shape.id === "pill" ? "w-12" : "w-11"
                            } ${isSelected ? "border-primary bg-primary/40" : ""}`}
                          />
                        </div>
                        <div className="flex flex-col">
                          <span className={`text-xs font-bold ${isSelected ? "text-primary-strong" : "text-foreground"}`}>
                            {shape.name}
                          </span>
                          <span className="text-[10px] text-muted-foreground line-clamp-1">
                            {shape.desc}
                          </span>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>

          {/* Row 5: Margins (Căn lề dọc nâng cao với mốc nhanh + Căn lề ngang) */}
          <div className="rounded-xl border border-border/80 bg-muted/40 p-4">
            <div className="mb-3 flex items-center justify-between">
              <div className="flex items-center gap-2 text-xs font-semibold text-foreground">
                <Sliders className="size-4 text-primary" aria-hidden />
                <span>Căn chỉnh lề hiển thị phụ đề (Khoảng cách & Vị trí)</span>
              </div>
              <span className="text-[11px] text-muted-foreground font-medium">Kéo thả phụ đề trên ảnh để chỉnh nhanh</span>
            </div>

            <div className="grid grid-cols-1 gap-5 lg:grid-cols-12">
              {/* Căn lề dọc (Margin V) - Mở rộng phạm vi 5 - 220px kèm mốc định sẵn */}
              <div className="flex flex-col gap-2 lg:col-span-6 border-b pb-4 lg:border-b-0 lg:border-r lg:pr-5 border-border">
                <div className="flex items-center justify-between text-xs font-semibold">
                  <span className="flex items-center gap-1.5 text-foreground">
                    <MoveVertical className="size-3.5 text-primary" aria-hidden />
                    <span>Vị trí theo chiều dọc (Căn lề dưới)</span>
                  </span>
                  <span className="rounded bg-primary/10 px-2 py-0.5 font-mono font-bold text-primary-strong">
                    {cfg.margin_v} px
                  </span>
                </div>

                <div className="flex items-center gap-2">
                  <input
                    type="range"
                    min="5"
                    max="400"
                    step="1"
                    value={cfg.margin_v}
                    onChange={(e) => update("margin_v", Number(e.target.value))}
                    className="h-2 w-full cursor-pointer accent-primary"
                  />
                  <input
                    type="number"
                    min="5"
                    max="400"
                    value={cfg.margin_v}
                    onChange={(e) => {
                      const v = parseInt(e.target.value, 10);
                      if (!isNaN(v)) update("margin_v", Math.max(5, Math.min(400, v)));
                    }}
                    className="w-16 rounded-lg border border-slate-300 px-2 py-1 text-center font-mono text-xs font-bold text-foreground"
                  />
                </div>
              </div>

              {/* Margin Left (L) & Right (R) (3 cols each) */}
              <div className="grid grid-cols-2 gap-4 lg:col-span-6">
                <div className="flex flex-col gap-1.5">
                  <div className="flex items-center justify-between text-xs font-semibold">
                    <span>Lề trái (L)</span>
                    <span className="font-mono font-bold text-primary">{cfg.margin_l} px</span>
                  </div>
                  <input
                    type="range"
                    min="0"
                    max="50"
                    value={cfg.margin_l}
                    onChange={(e) => update("margin_l", Number(e.target.value))}
                    className="h-2 w-full cursor-pointer accent-primary"
                  />
                  <span className="text-[11px] text-muted-foreground">Cách mép trái</span>
                </div>

                <div className="flex flex-col gap-1.5">
                  <div className="flex items-center justify-between text-xs font-semibold">
                    <span>Lề phải (R)</span>
                    <span className="font-mono font-bold text-primary">{cfg.margin_r} px</span>
                  </div>
                  <input
                    type="range"
                    min="0"
                    max="50"
                    value={cfg.margin_r}
                    onChange={(e) => update("margin_r", Number(e.target.value))}
                    className="h-2 w-full cursor-pointer accent-primary"
                  />
                  <span className="text-[11px] text-muted-foreground">Cách mép phải</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* --- Bottom Section: Full-Width Visual Live Preview (Placed below all configuration categories) --- */}
        <div className="flex flex-col gap-3 border-t border-border pt-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Eye className="size-5 text-primary" aria-hidden />
              <span className="text-base font-semibold text-foreground">
                Bản xem trước trực tiếp trên khung hình video
              </span>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              {/* Aspect Ratio Toggle: 16:9 vs 9:16 */}
              <div className="inline-flex rounded-lg border border-slate-300 bg-white p-0.5 shadow-xs text-xs font-semibold">
                <button
                  type="button"
                  onClick={() => setPreviewAspect("16:9")}
                  className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 transition-colors ${previewAspect === "16:9"
                    ? "bg-primary text-on-primary shadow-xs"
                    : "text-muted-foreground hover:text-foreground"
                    }`}
                >
                  <Monitor className="size-3.5" aria-hidden />
                  <span>Ngang (16:9)</span>
                </button>
                <button
                  type="button"
                  onClick={() => setPreviewAspect("9:16")}
                  className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 transition-colors ${previewAspect === "9:16"
                    ? "bg-primary text-on-primary shadow-xs"
                    : "text-muted-foreground hover:text-foreground"
                    }`}
                >
                  <Smartphone className="size-3.5" aria-hidden />
                  <span>Dọc (9:16)</span>
                </button>
              </div>

              <input
                ref={sampleImageInputRef}
                type="file"
                accept="image/*"
                className="sr-only"
                tabIndex={-1}
                aria-hidden
                onChange={(e) => {
                  handleSampleImage(e.target.files?.[0]);
                  e.target.value = "";
                }}
              />
              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  variant="secondary"
                  icon={ImagePlus}
                  onClick={() => sampleImageInputRef.current?.click()}
                  className="min-h-9 px-3 py-1 text-xs"
                  title="Ảnh chỉ dùng để xem trước và không được tải lên máy chủ"
                >
                  {sampleImageUrl ? "Đổi ảnh mẫu" : "Tải ảnh mẫu"}
                </Button>
                {sampleImageUrl && (
                  <button
                    type="button"
                    onClick={() => setSampleImageUrl(null)}
                    className="text-xs font-semibold text-muted-foreground hover:text-foreground"
                  >
                    Bỏ ảnh
                  </button>
                )}
              </div>

              {/* Sample Language Switcher */}
              <div className="flex items-center gap-1 text-xs">
                <span className="text-muted-foreground font-medium mr-1">Mẫu:</span>
                {(["km", "lo", "vi", "zh", "en"] as const).map((code) => {
                  const labels: Record<string, string> = {
                    km: "Khmer",
                    lo: "Lào",
                    vi: "Việt",
                    zh: "Trung",
                    en: "Anh",
                  };
                  const active = sampleLang === code;
                  return (
                    <button
                      key={code}
                      type="button"
                      onClick={() => setSampleLang(code)}
                      className={`rounded-md px-2 py-1 font-semibold transition-colors ${active
                        ? "bg-primary text-on-primary shadow-xs"
                        : "bg-muted text-muted-foreground hover:text-foreground"
                        }`}
                    >
                      {labels[code]}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>

          {/* Frame Container */}
          <div className="w-full flex justify-center bg-slate-950/20 rounded-2xl p-2 sm:p-4 border border-border">
            <div
              ref={previewContainerRef}
              onPointerMove={handlePointerMove}
              onPointerUp={handlePointerUp}
              className={`relative select-none overflow-hidden rounded-xl border border-slate-800 bg-black shadow-xl transition-all ${previewAspect === "16:9"
                ? "aspect-video w-full"
                : "aspect-[9/16] w-full max-w-[340px]"
                }`}
            >
              {/* Background image: 16:9 horizontal frame or 9:16 vertical video frame */}
              <img
                key={previewAspect}
                src={sampleImageUrl || (previewAspect === "16:9" ? "/subtitle-preview-bg.png" : "/subtitle-preview-vertical.png")}
                alt={sampleImageUrl ? "Ảnh mẫu người dùng tải lên" : "Mẫu khung hình video đầu ra"}
                className="size-full object-cover pointer-events-none"
                onError={(e) => {
                  e.currentTarget.style.display = "none";
                }}
              />

              {/* Subtitle Positioning Container */}
              <div
                className="absolute inset-0 flex flex-col justify-end"
                style={{
                  paddingBottom: `${scaledMarginV}px`,
                  paddingLeft: `${scaledMarginL}px`,
                  paddingRight: `${scaledMarginR}px`,
                }}
              >
                <div className="flex w-full justify-center text-center">
                  <div
                    onPointerDown={handlePointerDown}
                    className={`group relative inline-block max-w-[95%] cursor-grab active:cursor-grabbing touch-none transition-transform ${isDragging ? "scale-105" : "hover:scale-[1.02]"
                      }`}
                    title="Bấm và giữ chuột để kéo phụ đề lên/xuống căn chỉnh vị trí trực tiếp"
                  >
                    {/* Layer 0: Backdrop Blur (Làm mờ phụ đề cũ) */}
                    {cfg.mask_enabled && (
                      <span
                        aria-hidden
                        className={`absolute pointer-events-none transition-all ${getMaskShapeClasses(cfg.mask_shape || "pill")}`}
                        style={{
                          backgroundColor: maskBgColor,
                          backdropFilter: maskBlurPx > 0 ? `blur(${maskBlurPx}px)` : "none",
                          WebkitBackdropFilter: maskBlurPx > 0 ? `blur(${maskBlurPx}px)` : "none",
                          boxShadow: maskBoxShadow,
                        }}
                      />
                    )}

                    {/* Drag indicator hint on hover/drag */}
                    <span
                      aria-hidden
                      className="absolute -top-6 left-1/2 -translate-x-1/2 flex items-center gap-1 rounded bg-black/80 px-1.5 py-0.5 text-[10px] font-mono text-white opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none"
                    >
                      <GripVertical className="size-3 text-primary" />
                      <span>Kéo để chỉnh vị trí ({cfg.margin_v}px)</span>
                    </span>

                    {/* Layer 1: Foreground Text (Exact font size as selected, 1:1 without scaling) */}
                    <span
                      className="relative z-10 block px-2 leading-tight"
                      style={{
                        fontFamily: previewFontFamily,
                        fontSize: `${renderedFontSize}px`,
                        color: cfg.color,
                        fontWeight: cfg.bold ? 700 : 400,
                        fontStyle: cfg.italic ? "italic" : "normal",
                        textShadow: previewTextShadow,
                      }}
                    >
                      {currentSample}
                    </span>
                  </div>
                </div>
              </div>

              {/* Live Indicator Badges */}
              <div className="absolute right-2.5 top-2.5 flex items-center gap-1.5 rounded-lg bg-black/75 px-2 py-1 text-[11px] font-mono text-white/90 backdrop-blur-md border border-white/10 pointer-events-none">
                <span>Cỡ chữ: <strong className="text-primary">{cfg.font_size}px</strong></span>
                <span>•</span>
                <span>Lề dọc: <strong className="text-primary">{cfg.margin_v}px</strong></span>
              </div>
            </div>
          </div>

          {/* Quick custom text input for testing arbitrary sentences */}
          <div className="flex items-center gap-2 mt-1">
            <span className="text-xs font-medium text-muted-foreground shrink-0">Thử nội dung khác:</span>
            <input
              type="text"
              value={customSampleText}
              onChange={(e) => setCustomSampleText(e.target.value)}
              placeholder="Nhập thử một câu bất kỳ để xem phụ đề ngắt dòng và độ rõ nét..."
              className="w-full rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs text-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary/20"
            />
            {customSampleText && (
              <button
                type="button"
                onClick={() => setCustomSampleText("")}
                className="text-xs font-semibold text-muted-foreground hover:text-foreground shrink-0"
              >
                Khôi phục câu mẫu
              </button>
            )}
          </div>
        </div>
      </div>

      {/* --- Color Picker Modal Popup (Cho cả Màu chữ và Màu viền chữ) --- */}
      {showColorModal && (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-xs"
          onClick={() => setShowColorModal(false)}
        >
          <div
            ref={colorModalRef}
            className="w-full max-w-lg rounded-2xl border border-border bg-card p-6 shadow-2xl animate-in fade-in-0 zoom-in-95"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div className="flex items-center justify-between border-b border-border pb-4">
              <div className="flex items-center gap-2.5">
                <div className="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <Palette className="size-5" aria-hidden />
                </div>
                <div>
                  <h3 className="text-base font-semibold text-foreground">
                    {colorTarget === "color"
                      ? "Chọn màu chữ phụ đề"
                      : colorTarget === "color_border"
                      ? "Chọn màu viền chữ phụ đề"
                      : colorTarget === "color_shadow"
                      ? "Chọn màu đổ bóng phụ đề"
                      : "Chọn màu làm mờ phụ đề cũ"}
                  </h3>
                  <p className="text-xs text-muted-foreground">
                    {colorTarget === "color"
                      ? "Chọn màu thân chữ từ bảng hoặc nhập mã HEX."
                      : colorTarget === "color_border"
                      ? "Chọn màu viền bao quanh chữ để tăng tương phản trên nền video."
                      : colorTarget === "color_shadow"
                      ? "Chọn màu bóng mờ phía sau chữ để tạo chiều sâu và nổi bật trên nền video."
                      : "Chọn màu nền làm mờ để che phụ đề gốc có sẵn trên video."}
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setShowColorModal(false)}
                className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                aria-label="Đóng popup"
              >
                <X className="size-5" />
              </button>
            </div>

            {/* Modal Body: Left: Palette & Input | Right: Color Test Box */}
            <div className="grid grid-cols-1 gap-5 py-5 sm:grid-cols-[1.2fr_1fr]">
              {/* Left Side: Palette & Hex input */}
              <div className="flex flex-col gap-4">
                <div>
                  <label className="text-xs font-semibold text-foreground">Bảng màu thông dụng</label>
                  <div className="mt-2 grid grid-cols-5 gap-2">
                    {COLOR_PRESETS.map((p) => {
                      const isSelected = tempColor.toUpperCase() === p.hex.toUpperCase();
                      return (
                        <button
                          key={p.hex}
                          type="button"
                          onClick={() => setTempColor(p.hex)}
                          className={`group relative flex size-9 items-center justify-center rounded-lg border-2 shadow-sm transition-all hover:scale-105 ${isSelected
                            ? "border-primary ring-2 ring-primary/30"
                            : "border-slate-300 hover:border-slate-400"
                            }`}
                          style={{ backgroundColor: p.hex }}
                          title={p.name}
                        >
                          {isSelected && (
                            <Check
                              className={`size-4 ${["#FFFFFF", "#FACC15", "#FEF08A", "#E2E8F0", "#86EFAC"].includes(p.hex)
                                ? "text-black"
                                : "text-white"
                                }`}
                            />
                          )}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Custom Color Input */}
                <div className="flex flex-col gap-2">
                  <label htmlFor="hex-color-input" className="text-xs font-semibold text-foreground">
                    Tuỳ chỉnh mã màu (HEX)
                  </label>
                  <div className="flex items-center gap-2">
                    <input
                      type="color"
                      value={tempColor.length === 7 ? tempColor : colorTarget === "color" ? "#FFFFFF" : "#000000"}
                      onChange={(e) => setTempColor(e.target.value.toUpperCase())}
                      className="size-10 cursor-pointer rounded-lg border border-slate-300 bg-transparent p-1"
                      title="Chọn trên phổ màu"
                    />
                    <div className="relative flex-1">
                      <span className="absolute left-3 top-2.5 font-mono text-sm font-semibold text-slate-400">#</span>
                      <input
                        id="hex-color-input"
                        type="text"
                        maxLength={6}
                        value={tempColor.replace(/^#/, "")}
                        onChange={(e) => {
                          const val = e.target.value.replace(/[^0-9A-Fa-f]/g, "").toUpperCase();
                          setTempColor(`#${val}`);
                        }}
                        placeholder="FFFFFF"
                        className="w-full rounded-lg border border-slate-300 bg-white py-2 pl-7 pr-3 font-mono text-sm font-bold text-foreground focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
                      />
                    </div>
                  </div>
                </div>
              </div>

              {/* Right Side: Ô chữ nhật thử màu chữ + màu viền ở 1 bên làm mẫu */}
              <div className="flex flex-col gap-2">
                <label className="text-xs font-semibold text-foreground">
                  Ô chữ nhật thử màu mẫu
                </label>
                <div className="relative flex flex-1 flex-col items-center justify-center rounded-xl border border-slate-700 bg-slate-950 p-4 text-center shadow-inner overflow-hidden min-h-[160px]">
                  {/* Movie frame background simulation */}
                  <div className="absolute inset-0 bg-gradient-to-b from-slate-900/60 via-slate-950/80 to-black pointer-events-none" />

                  {/* Backdrop Blur Pill & Sample Text */}
                  <div className="relative z-10 inline-block px-3 py-1.5 my-auto">
                    {showModalMask && (
                      <span
                        aria-hidden
                        className={`absolute pointer-events-none transition-all ${getMaskShapeClasses(cfg.mask_shape || "pill")}`}
                        style={{
                          backgroundColor: modalMaskBgColor,
                          backdropFilter: maskBlurPx > 0 ? `blur(${maskBlurPx}px)` : "none",
                          WebkitBackdropFilter: maskBlurPx > 0 ? `blur(${maskBlurPx}px)` : "none",
                          boxShadow: maskBoxShadow,
                        }}
                      />
                    )}
                    <span
                      className="relative z-10 block text-lg font-bold leading-tight"
                      style={{
                        color: colorTarget === "color" ? tempColor : cfg.color,
                        textShadow: modalTextShadow,
                      }}
                    >
                      Phụ đề mẫu
                    </span>
                    <span
                      className="relative z-10 block text-xs font-bold mt-1"
                      style={{
                        color: colorTarget === "color" ? tempColor : cfg.color,
                        textShadow: modalSubTextShadow,
                      }}
                    >
                      ឥឡូវព្រះអធិរាជ
                    </span>
                  </div>

                  <div className="relative z-10 mt-auto rounded-full bg-white/10 px-2.5 py-0.5 text-[11px] text-slate-300">
                    Đang chọn: <span className="font-mono font-bold text-white">{tempColor}</span>
                  </div>
                </div>
              </div>
            </div>

            {/* Modal Footer */}
            <div className="flex items-center justify-end gap-3 border-t border-border pt-4">
              <Button type="button" variant="ghost" onClick={() => setShowColorModal(false)}>
                Huỷ bỏ
              </Button>
              <Button
                type="button"
                variant="primary"
                onClick={() => applyColor(tempColor)}
              >
                Áp dụng màu này
              </Button>
            </div>
          </div>
        </div>
      )}
    </Card>
  );
}
