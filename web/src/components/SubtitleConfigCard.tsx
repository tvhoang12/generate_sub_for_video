import { useState, useRef, useEffect, useCallback, useMemo, type PointerEvent, type DragEvent } from "react";
import {
  Bold,
  Check,
  Eye,
  EyeOff,
  FileVideo,
  GripVertical,
  Italic,
  MoveVertical,
  Palette,
  Pause,
  Play,
  RotateCcw,
  Sliders,
  Volume2,
  VolumeX,
  X,
} from "lucide-react";
import { formatBytes, type SubtitleConfig } from "../api";
import { Button, Card, Field } from "./ui";

function formatVideoTime(seconds: number): string {
  if (isNaN(seconds) || seconds < 0) return "00:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

function getAspectRatioLabel(width: number, height: number): string {
  const ratio = width / height;
  if (Math.abs(ratio - 16 / 9) < 0.05) return "16:9 Ngang";
  if (Math.abs(ratio - 9 / 16) < 0.05) return "9:16 Dọc";
  if (Math.abs(ratio - 4 / 3) < 0.05) return "4:3 Ngang";
  if (Math.abs(ratio - 3 / 4) < 0.05) return "3:4 Dọc";
  if (Math.abs(ratio - 1) < 0.05) return "1:1 Vuông";
  if (Math.abs(ratio - 21 / 9) < 0.08) return "21:9 Siêu rộng";
  return `${width}:${height}`;
}

export const DEFAULT_SUBTITLE_CONFIG: Required<SubtitleConfig> = {
  font: "",
  font_size: 50,
  color: "#FFFFFF",
  color_border: "#000000",
  has_border: true,
  has_shadow: true,
  color_shadow: "#000000",
  bold: true,
  italic: false,
  margin_l: 50,
  margin_r: 50,
  margin_v: 50,
  outline: 3.0,
  shadow: 1.5,
  line_spacing: 12,
  mask_padding_x: 24,
  burn_video: true,
  mask_enabled: true,
  mask_color: "#000000",
  mask_blur: 10,
  mask_opacity: 40,
  mask_shape: "pill",
  mask_by_text: true,
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

const LAO_ZERO_WIDTH_CODES = new Set([
  0x0eb1, 0x0eb4, 0x0eb5, 0x0eb6, 0x0eb7, 0x0eb8, 0x0eb9, 0x0eba, 0x0ebb, 0x0ebc, 0x0ecd,
  0x0ec8, 0x0ec9, 0x0eca, 0x0ecb, 0x0ecc,
]);

const THAI_ZERO_WIDTH_CODES = new Set([
  0x0e31, 0x0e34, 0x0e35, 0x0e36, 0x0e37, 0x0e38, 0x0e39, 0x0e3a,
  0x0e47, 0x0e48, 0x0e49, 0x0e4a, 0x0e4b, 0x0e4c, 0x0e4d, 0x0e4e,
]);

const MYANMAR_ZERO_WIDTH_CODES = new Set([
  0x102d, 0x102e, 0x102f, 0x1030, 0x1032, 0x1033, 0x1034, 0x1035,
  0x1036, 0x1037, 0x1039, 0x103a, 0x103d, 0x103e,
]);

const KHMER_ZERO_WIDTH_CODES = new Set([
  0x17b7, 0x17b8, 0x17b9, 0x17ba, 0x17bb, 0x17bc, 0x17bd,
  0x17c6, 0x17c9, 0x17ca, 0x17cb, 0x17cc, 0x17cd, 0x17ce, 0x17cf, 0x17d0, 0x17d1, 0x17d2, 0x17d3,
  0x17dd,
]);

const OVERFLOW_TOLERANCE = 1.05;
const PUNCTUATION_CHARS = new Set("，,、。！？!?…;；:：ฯๆ។");

function isZeroWidthMark(ch: string, prevCh = ""): boolean {
  const code = ch.charCodeAt(0);
  if (LAO_ZERO_WIDTH_CODES.has(code) || THAI_ZERO_WIDTH_CODES.has(code)) return true;
  if (MYANMAR_ZERO_WIDTH_CODES.has(code) || KHMER_ZERO_WIDTH_CODES.has(code)) return true;
  if (prevCh === "\u17d2" || prevCh === "\u1039") return true;
  return /\p{M}/u.test(ch);
}

function isPreVowel(ch: string): boolean {
  const code = ch.charCodeAt(0);
  return (code >= 0x0ec0 && code <= 0x0ec4) || (code >= 0x0e40 && code <= 0x0e44);
}

function isDependentMark(ch: string): boolean {
  if (isZeroWidthMark(ch)) return true;
  const code = ch.charCodeAt(0);
  if (code === 0x0eb0 || code === 0x0eb2 || code === 0x0eb3) return true;
  if (code === 0x0e30 || code === 0x0e32 || code === 0x0e33 || code === 0x0e45) return true;
  if (code === 0x102b || code === 0x102c || code === 0x1038) return true;
  if (code >= 0x17b4 && code <= 0x17d3) return true;
  return false;
}

function getCharWidth(ch: string, fontSize: number, prevCh = ""): number {
  if (isZeroWidthMark(ch, prevCh)) return 0;
  const code = ch.charCodeAt(0);
  // CJK fullwidth
  if ((code >= 0x4e00 && code <= 0x9fff) || (code >= 0x3000 && code <= 0x303f) || (code >= 0xff00 && code <= 0xffef)) {
    return fontSize * 0.95;
  }
  // Khmer
  if (code >= 0x1780 && code <= 0x17ff) return fontSize * 0.58;
  // Lao
  if (code >= 0x0e80 && code <= 0x0eff) return fontSize * 0.52;
  // Thai
  if (code >= 0x0e00 && code <= 0x0e7f) return fontSize * 0.52;
  // Myanmar
  if (code >= 0x1000 && code <= 0x109f) return fontSize * 0.55;
  if ("ijlI1.,:;!'\"| ".includes(ch)) return fontSize * 0.28;
  if ("mwMW@%#&".includes(ch)) return fontSize * 0.78;
  return fontSize * 0.50;
}

/** Width of a string in video pixels, measured with the real (shaped) font when available. */
type TextMeasurer = (text: string) => number;

function measureTextWidth(text: string, fontSize: number, measure?: TextMeasurer): number {
  if (measure) return measure(text);
  let w = 0;
  let prevC = "";
  for (const c of Array.from(text)) {
    w += getCharWidth(c, fontSize, prevC);
    prevC = c;
  }
  return w;
}

function splitTextClusters(text: string): string[] {
  const clusters: string[] = [];
  const chars = Array.from(text);
  let i = 0;
  while (i < chars.length) {
    const c = [chars[i]];
    i++;
    if (isPreVowel(c[0]) && i < chars.length) {
      c.push(chars[i]);
      i++;
    }
    while (i < chars.length) {
      if (isDependentMark(chars[i])) {
        c.push(chars[i]);
        i++;
      } else if (c[c.length - 1] === "\u17d2" || c[c.length - 1] === "\u1039") {
        c.push(chars[i]);
        i++;
      } else {
        break;
      }
    }
    clusters.push(c.join(""));
  }
  return clusters;
}

function splitBalancedClusters(text: string, maxWidth: number, fontSize: number, measure?: TextMeasurer): string[] {
  const clusters = splitTextClusters(text);
  if (clusters.length === 0) return [];
  const cWidths: number[] = [];
  let lastC = "";
  for (const cl of clusters) {
    let cw = 0;
    if (measure) {
      cw = measure(cl);
    } else {
      let prevC = lastC;
      for (const c of Array.from(cl)) {
        cw += getCharWidth(c, fontSize, prevC);
        prevC = c;
      }
    }
    cWidths.push(cw);
    lastC = cl[cl.length - 1] || "";
  }

  const totalW = cWidths.reduce((sum, w) => sum + w, 0);
  if (totalW <= maxWidth * OVERFLOW_TOLERANCE) {
    return [text];
  }

  const k = Math.max(2, Math.ceil(totalW / maxWidth));
  const targetW = totalW / k;

  const subLines: string[] = [];
  let curChunk: string[] = [];
  let curChunkW = 0;

  for (let i = 0; i < clusters.length; i++) {
    const cl = clusters[i];
    const cw = cWidths[i];
    curChunk.push(cl);
    curChunkW += cw;
    const remainingW = totalW - cWidths.slice(0, i + 1).reduce((sum, w) => sum + w, 0);
    const isPunct = Array.from(cl).some((ch) => PUNCTUATION_CHARS.has(ch));

    let shouldBreak = false;
    if (subLines.length < k - 1 && remainingW > 0) {
      if (isPunct && curChunkW >= targetW * 0.8) {
        shouldBreak = true;
      } else if (curChunkW >= targetW) {
        shouldBreak = true;
      }
    }

    if (shouldBreak) {
      subLines.push(curChunk.join(""));
      curChunk = [];
      curChunkW = 0;
    }
  }

  if (curChunk.length > 0) {
    subLines.push(curChunk.join(""));
  }
  return subLines;
}

export function wrapSampleText(text: string, maxWidth: number, fontSize: number, measure?: TextMeasurer): string[] {
  const rawLines = text.replace(/\r\n/g, "\n").replace(/\\N/g, "\n").split("\n");
  const result: string[] = [];

  for (const rawLine of rawLines) {
    const line = rawLine.trim();
    if (!line) {
      result.push("");
      continue;
    }
    const totalW = measureTextWidth(line, fontSize, measure);
    if (totalW <= maxWidth * OVERFLOW_TOLERANCE) {
      result.push(line);
      continue;
    }

    if (!line.includes(" ")) {
      result.push(...splitBalancedClusters(line, maxWidth, fontSize, measure));
      continue;
    }

    const words = line.split(" ").filter(Boolean);
    const expandedWords: string[] = [];
    for (const w of words) {
      const wW = measureTextWidth(w, fontSize, measure);
      if (wW > maxWidth * OVERFLOW_TOLERANCE) {
        expandedWords.push(...splitBalancedClusters(w, maxWidth, fontSize, measure));
      } else {
        expandedWords.push(w);
      }
    }

    const spaceW = measure ? measure(" ") : getCharWidth(" ", fontSize);
    const lines: string[] = [];
    let curLine: string[] = [];
    let curW = 0;

    for (const word of expandedWords) {
      const wordW = measureTextWidth(word, fontSize, measure);
      const addedW = curLine.length === 0 ? wordW : spaceW + wordW;
      if (curLine.length > 0 && curW + addedW > maxWidth * OVERFLOW_TOLERANCE) {
        lines.push(curLine.join(" "));
        curLine = [word];
        curW = wordW;
      } else {
        curLine.push(word);
        curW += addedW;
      }
    }
    if (curLine.length > 0) {
      lines.push(curLine.join(" "));
    }

    // Orphan prevention
    if (lines.length >= 2) {
      const lastLineWords = lines[lines.length - 1].split(" ");
      const prevLineWords = lines[lines.length - 2].split(" ");
      if (lastLineWords.length === 1 && prevLineWords.length >= 2) {
        const candidateLast = prevLineWords[prevLineWords.length - 1] + " " + lines[lines.length - 1];
        if (measureTextWidth(candidateLast, fontSize, measure) <= maxWidth * OVERFLOW_TOLERANCE) {
          lines[lines.length - 2] = prevLineWords.slice(0, -1).join(" ");
          lines[lines.length - 1] = candidateLast;
        }
      }
    }

    result.push(...lines);
  }
  return result;
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
  { label: "Phetsarath OT (Chuẩn tiếng Lào)", value: "Phetsarath" },
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
  zh: "怎么做回甲乙丙丁，找回最初的自己",
};

export function SubtitleConfigCard({
  value,
  onChange,
  videoFile,
  onVideoFileChange,
  onPickVideo,
}: {
  value: SubtitleConfig;
  onChange: (cfg: SubtitleConfig) => void;
  videoFile?: File | null;
  onVideoFileChange?: (file: File | null) => void;
  onPickVideo?: () => void;
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
  const [isDragging, setIsDragging] = useState(false);
  const [previewAspectRatio, setPreviewAspectRatio] = useState<"16:9" | "9:16">("16:9");

  // Video preview & measured frame dimensions
  const [videoObjectUrl, setVideoObjectUrl] = useState<string | null>(null);
  const [videoError, setVideoError] = useState<string | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [isMuted, setIsMuted] = useState(true);
  const [videoDimensions, setVideoDimensions] = useState<{ width: number; height: number } | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);

  const colorModalRef = useRef<HTMLDivElement>(null);
  const previewContainerRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    if (!videoFile) {
      setVideoObjectUrl(null);
      setVideoDimensions(null);
      setIsPlaying(false);
      setCurrentTime(0);
      setDuration(0);
      setVideoError(null);
      return;
    }
    const url = URL.createObjectURL(videoFile);
    setVideoObjectUrl(url);
    setVideoError(null);
    setIsPlaying(false);
    setCurrentTime(0);
    setDuration(0);

    const tempVideo = document.createElement("video");
    tempVideo.preload = "metadata";
    tempVideo.src = url;
    const onMeta = () => {
      if (tempVideo.videoWidth && tempVideo.videoHeight) {
        setVideoDimensions({ width: tempVideo.videoWidth, height: tempVideo.videoHeight });
        setDuration(tempVideo.duration || 0);
      }
    };
    tempVideo.onloadedmetadata = onMeta;
    tempVideo.onloadeddata = onMeta;
    tempVideo.oncanplay = onMeta;

    return () => {
      URL.revokeObjectURL(url);
      tempVideo.src = "";
    };
  }, [videoFile]);

  const togglePlayPause = () => {
    if (!videoRef.current) return;
    if (videoRef.current.paused) {
      videoRef.current.play().then(() => setIsPlaying(true)).catch(() => {});
    } else {
      videoRef.current.pause();
      setIsPlaying(false);
    }
  };

  const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
    const t = Number(e.target.value);
    setCurrentTime(t);
    if (videoRef.current) {
      videoRef.current.currentTime = t;
    }
  };

  const handleLoadedMetadata = (e: React.SyntheticEvent<HTMLVideoElement>) => {
    const v = e.currentTarget;
    setDuration(v.duration || 0);
    if (v.videoWidth && v.videoHeight) {
      setVideoDimensions({ width: v.videoWidth, height: v.videoHeight });
    }
  };

  const handleTimeUpdate = () => {
    if (videoRef.current) {
      setCurrentTime(videoRef.current.currentTime);
    }
  };

  const handleDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragOver(true);
  };

  const handleDragLeave = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragOver(false);
  };

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragOver(false);
    const dropped = e.dataTransfer.files?.[0];
    if (!dropped) return;
    if (dropped.type.startsWith("video/") || /\.(mp4|mov|mkv|webm|m4v)$/i.test(dropped.name)) {
      onVideoFileChange?.(dropped);
    }
  };

  // Close color modal on Escape
  useEffect(() => {
    if (!showColorModal) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setShowColorModal(false);
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [showColorModal]);

  const update = useCallback(
    <K extends keyof SubtitleConfig>(key: K, val: SubtitleConfig[K]) => {
      onChange({ ...cfg, [key]: val });
    },
    [cfg, onChange]
  );

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

  const isVertical = Boolean(
    videoDimensions
      ? videoDimensions.width < videoDimensions.height
      : previewAspectRatio === "9:16"
  );

  const refVideoWidth = videoDimensions
    ? videoDimensions.width
    : previewAspectRatio === "9:16"
    ? 1080
    : 1920;
  const refVideoHeight = videoDimensions
    ? videoDimensions.height
    : previewAspectRatio === "9:16"
    ? 1920
    : 1080;

  // Direct Drag-and-Drop vertical positioning calculation in exact video pixel coordinates
  const handlePointerDown = (e: PointerEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
  };

  const handlePointerMove = useCallback(
    (e: PointerEvent) => {
      if (!isDragging || !previewContainerRef.current) return;
      const rect = previewContainerRef.current.getBoundingClientRect();
      const bottomDistancePx = rect.bottom - e.clientY;
      const ratio = Math.max(0.01, Math.min(0.85, bottomDistancePx / rect.height));
      const newMarginV = Math.max(
        10,
        Math.min(Math.round(refVideoHeight * 0.85), Math.round(ratio * refVideoHeight))
      );
      update("margin_v", newMarginV);
    },
    [isDragging, update, refVideoHeight]
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

  const previewFontFamily = (() => {
    if (cfg.font && cfg.font !== "__custom__") {
      // Same aliases as the backend (subtitles.FONT_ALIASES); the web font is "Phetsarath"
      const alias: Record<string, string> = {
        "phetsarath ot": "Phetsarath",
        kantumruy: "Kantumruy Pro",
      };
      const family = alias[cfg.font.trim().toLowerCase()] ?? cfg.font;
      return `"${family}", var(--font-sans)`;
    }
    switch (sampleLang) {
      case "km":
        return '"Kantumruy Pro", "Noto Sans Khmer", var(--font-sans)';
      case "lo":
        return '"Phetsarath", "Noto Sans Lao", var(--font-sans)';
      case "th":
        return '"Noto Sans Thai", "Leelawadee UI", var(--font-sans)';
      case "zh":
        return '"Noto Sans CJK SC", "Microsoft YaHei", var(--font-sans)';
      case "vi":
      case "en":
      default:
        return '"Noto Sans", Arial, var(--font-sans)';
    }
  })();

  const [containerSize, setContainerSize] = useState<{ width: number; height: number }>({
    width: 640,
    height: 360,
  });

  useEffect(() => {
    if (!previewContainerRef.current) return;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        if (width > 0 && height > 0) {
          setContainerSize({ width, height });
        }
      }
    });
    observer.observe(previewContainerRef.current);
    return () => observer.disconnect();
  }, [videoDimensions, previewAspectRatio]);

  // Width is capped so the 520px height limit is never hit: a clipped height would break the
  // aspect ratio, letterbox the video and misplace the %-positioned subtitle.
  const containerAspectRatioStyle = {
    aspectRatio: `${refVideoWidth} / ${refVideoHeight}`,
    maxWidth: `${Math.floor(Math.min(isVertical ? 380 : 640, 520 * (refVideoWidth / refVideoHeight)))}px`,
  };

  const containerMaxWidthClass = "w-full";

  const previewScale =
    containerSize.width > 0 &&
    containerSize.height > 0 &&
    refVideoWidth > 0 &&
    refVideoHeight > 0
      ? Math.min(
          containerSize.width / refVideoWidth,
          containerSize.height / refVideoHeight
        )
      : containerSize.height > 0 && refVideoHeight > 0
      ? containerSize.height / refVideoHeight
      : containerSize.width > 0 && refVideoWidth > 0
      ? containerSize.width / refVideoWidth
      : 0.333;

  const renderedFontSize = Math.max(9, Math.round(cfg.font_size * previewScale));
  // Scaled line spacing and mask padding matching libass render
  const renderedLineSpacing = Math.round((cfg.line_spacing ?? 12) * previewScale);
  const renderedMaskPaddingX = Math.round((cfg.mask_padding_x ?? 24) * previewScale);
  const renderedMaskPaddingY = Math.max(2, Math.round((cfg.mask_padding_x ?? 24) * 0.45 * previewScale));

  const effectiveMarginL = Math.max(0, Number(cfg.margin_l ?? 50));
  const effectiveMarginR = Math.max(0, Number(cfg.margin_r ?? 50));
  const effectiveMarginV = Math.max(5, Number(cfg.margin_v ?? 50));

  const scaledMarginLPct = (effectiveMarginL / refVideoWidth) * 100;
  const scaledMarginRPct = (effectiveMarginR / refVideoWidth) * 100;
  const scaledMarginVPct = (effectiveMarginV / refVideoHeight) * 100;

  // Available canvas width for subtitle text wrapping matching ASS render
  const availableCanvasWidth = Math.max(50, refVideoWidth - effectiveMarginL - effectiveMarginR);
  // Re-measure once web fonts finish loading, otherwise the fallback font's widths are used.
  const [fontsVersion, setFontsVersion] = useState(0);
  const canvasFont = `${cfg.italic ? "italic " : ""}${cfg.bold ? 700 : 400} ${cfg.font_size}px ${previewFontFamily.replace(
    /var\([^)]*\)/g,
    "sans-serif"
  )}`;
  useEffect(() => {
    const fonts = document.fonts;
    if (!fonts) return;
    let alive = true;
    const bump = () => alive && setFontsVersion((v) => v + 1);
    fonts.load(canvasFont, currentSample).then(bump, () => {});
    fonts.addEventListener?.("loadingdone", bump);
    return () => {
      alive = false;
      fonts.removeEventListener?.("loadingdone", bump);
    };
  }, [canvasFont, currentSample]);

  const measureText = useMemo<TextMeasurer | undefined>(() => {
    const ctx = document.createElement("canvas").getContext("2d");
    if (!ctx) return undefined;
    ctx.font = canvasFont;
    const cache = new Map<string, number>();
    return (text: string) => {
      let w = cache.get(text);
      if (w === undefined) {
        w = ctx.measureText(text).width;
        cache.set(text, w);
      }
      return w;
    };
  }, [canvasFont, fontsVersion]);

  const wrappedLines = useMemo(() => {
    return wrapSampleText(currentSample, availableCanvasWidth, cfg.font_size, measureText).filter((l) => l.trim());
  }, [currentSample, availableCanvasWidth, cfg.font_size, measureText]);

  // Scaled outline, shadow, and blur matching libass ScaledBorderAndShadow.
  // -webkit-text-stroke is centred on the glyph edge and paint-order hides the inner half,
  // so the stroke must be twice the libass Outline to show the same width outside the glyph.
  const scaledOutlinePx = cfg.has_border
    ? Math.max(1.5, 2 * (cfg.outline ?? 3.0) * previewScale)
    : 0;
  const scaledShadowPx = cfg.has_shadow
    ? Math.max(0.5, (cfg.shadow ?? 1.5) * previewScale)
    : 0;
  const scaledMaskBlurPx = Math.round((cfg.mask_blur ?? 10) * previewScale);

  const previewTextShadow = (() => {
    const parts: string[] = [];
    if (cfg.has_shadow && scaledShadowPx > 0) {
      // libass: hard-edged copy offset by Shadow px, BackColour alpha &H80 (50%)
      parts.push(
        `${scaledShadowPx.toFixed(1)}px ${scaledShadowPx.toFixed(1)}px 0 ${hexToRgba(cfg.color_shadow || "#000000", 0.5)}`
      );
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

  const getMaskShapeClasses = (shape: "pill" | "rounded" | "rectangle" | "bar", byText: boolean = true) => {
    if (!byText) {
      switch (shape) {
        case "pill":
          return "inset-x-0 -inset-y-1.5 rounded-full";
        case "rounded":
          return "inset-x-0 -inset-y-1.5 rounded-xl";
        case "rectangle":
          return "inset-x-0 -inset-y-1 rounded-none";
        case "bar":
          return "-inset-y-1 -left-[1000px] -right-[1000px] rounded-none";
        default:
          return "inset-x-0 -inset-y-1.5 rounded-xl";
      }
    }
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

          {/* Row 2: Font Size, Line Spacing & Bold/Italic Formats */}
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            {/* Font Size with Instant Slider & Presets (Chuẩn ASS) */}
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between">
                <label htmlFor="font-size-slider" className="text-sm font-semibold text-foreground">
                  Kích thước chữ (chuẩn ASS)
                </label>
                <span className="rounded bg-primary/10 px-2.5 py-0.5 font-mono text-sm font-bold text-primary-strong">
                  {cfg.font_size} px
                </span>
              </div>
              <div className="flex items-center gap-3">
                <input
                  id="font-size-slider"
                  type="range"
                  min="20"
                  max="120"
                  step="1"
                  value={cfg.font_size}
                  onChange={(e) => update("font_size", Number(e.target.value))}
                  className="h-2 w-full cursor-pointer accent-primary"
                />
                <input
                  type="number"
                  min="16"
                  max="160"
                  value={cfg.font_size}
                  onChange={(e) => {
                    const v = parseInt(e.target.value, 10);
                    if (!isNaN(v)) update("font_size", v);
                  }}
                  onBlur={(e) => {
                    const v = Math.max(16, Math.min(160, Number(e.target.value) || 50));
                    update("font_size", v);
                  }}
                  className="w-16 rounded-lg border border-slate-300 px-2 py-1.5 text-center font-mono text-sm font-bold text-foreground"
                />
              </div>
              <div className="flex justify-between text-xs text-muted-foreground pt-0.5">
                <button
                  type="button"
                  onClick={() => update("font_size", 38)}
                  className={`hover:text-primary ${cfg.font_size === 38 ? "font-bold text-primary underline" : ""}`}
                >
                  Nhỏ (38)
                </button>
                <button
                  type="button"
                  onClick={() => update("font_size", 50)}
                  className={`hover:text-primary ${cfg.font_size === 50 ? "font-bold text-primary underline" : ""}`}
                >
                  Chuẩn (50)
                </button>
                <button
                  type="button"
                  onClick={() => update("font_size", 62)}
                  className={`hover:text-primary ${cfg.font_size === 62 ? "font-bold text-primary underline" : ""}`}
                >
                  Lớn (62)
                </button>
                <button
                  type="button"
                  onClick={() => update("font_size", 76)}
                  className={`hover:text-primary ${cfg.font_size === 76 ? "font-bold text-primary underline" : ""}`}
                >
                  Cực lớn (76)
                </button>
              </div>
              <p className="text-xs text-muted-foreground">Chuẩn ASS 50px trên video Full HD 1080p, đồng bộ 1:1 không lệch cỡ.</p>
            </div>

            {/* Khoảng cách giữa các dòng phụ đề */}
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between">
                <label htmlFor="sub-line-spacing" className="text-sm font-semibold text-foreground">
                  Khoảng cách dòng
                </label>
                <span className="rounded bg-primary/10 px-2.5 py-0.5 font-mono text-sm font-bold text-primary-strong">
                  {cfg.line_spacing ?? 12} px
                </span>
              </div>
              <div className="flex items-center gap-3">
                <input
                  id="sub-line-spacing"
                  type="range"
                  min="0"
                  max="60"
                  step="2"
                  value={cfg.line_spacing ?? 12}
                  onChange={(e) => update("line_spacing", Number(e.target.value))}
                  className="h-2 w-full cursor-pointer accent-primary"
                />
                <input
                  type="number"
                  min="0"
                  max="60"
                  value={cfg.line_spacing ?? 12}
                  onChange={(e) => {
                    const v = parseInt(e.target.value, 10);
                    if (!isNaN(v)) update("line_spacing", Math.max(0, Math.min(60, v)));
                  }}
                  className="w-16 rounded-lg border border-slate-300 px-2 py-1.5 text-center font-mono text-sm font-bold text-foreground"
                />
              </div>
              <div className="flex justify-between text-xs text-muted-foreground pt-0.5">
                <button
                  type="button"
                  onClick={() => update("line_spacing", 4)}
                  className={`hover:text-primary ${(cfg.line_spacing ?? 12) === 4 ? "font-bold text-primary underline" : ""}`}
                >
                  Sát (4)
                </button>
                <button
                  type="button"
                  onClick={() => update("line_spacing", 12)}
                  className={`hover:text-primary ${(cfg.line_spacing ?? 12) === 12 ? "font-bold text-primary underline" : ""}`}
                >
                  Chuẩn (12)
                </button>
                <button
                  type="button"
                  onClick={() => update("line_spacing", 20)}
                  className={`hover:text-primary ${(cfg.line_spacing ?? 12) === 20 ? "font-bold text-primary underline" : ""}`}
                >
                  Thoáng (20)
                </button>
                <button
                  type="button"
                  onClick={() => update("line_spacing", 30)}
                  className={`hover:text-primary ${(cfg.line_spacing ?? 12) === 30 ? "font-bold text-primary underline" : ""}`}
                >
                  Rộng (30)
                </button>
              </div>
              <p className="text-xs text-muted-foreground">Khoảng cách giữa các dòng của câu phụ đề dài hoặc nhiều dòng.</p>
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

          {/* Row 3: Hiệu ứng viền chữ & đổ bóng (Chuẩn libass Outline & Shadow) */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {/* Box 1: Cấu hình Viền chữ (libass Outline) */}
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
                  <span className="text-sm font-semibold text-foreground">Viền chữ (Outline)</span>
                </label>
                <span
                  className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                    cfg.has_border
                      ? "bg-primary/10 text-primary-strong"
                      : "bg-slate-200/70 text-slate-500"
                  }`}
                >
                  {cfg.has_border ? `${cfg.outline ?? 3.0}px` : "Đang tắt"}
                </span>
              </div>

              <div className="flex flex-col gap-2">
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

                {/* Độ dày viền chữ chuẩn ASS Outline */}
                {cfg.has_border && (
                  <div className="flex flex-col gap-1.5 pt-2 border-t border-primary/20">
                    <div className="flex items-center justify-between">
                      <label className="text-xs font-semibold text-foreground">Độ dày nét viền</label>
                      <span className="font-mono text-xs font-bold text-primary">{cfg.outline ?? 3.0} px</span>
                    </div>
                    <input
                      type="range"
                      min="0.5"
                      max="8.0"
                      step="0.5"
                      value={cfg.outline ?? 3.0}
                      onChange={(e) => update("outline", Number(e.target.value))}
                      className="h-1.5 w-full cursor-pointer accent-primary"
                    />
                    <div className="flex justify-between text-[11px] text-muted-foreground">
                      <button type="button" onClick={() => update("outline", 1.5)} className={`hover:text-primary ${(cfg.outline ?? 3.0) === 1.5 ? "font-bold text-primary underline" : ""}`}>Mảnh (1.5)</button>
                      <button type="button" onClick={() => update("outline", 3.0)} className={`hover:text-primary ${(cfg.outline ?? 3.0) === 3.0 ? "font-bold text-primary underline" : ""}`}>Chuẩn (3.0)</button>
                      <button type="button" onClick={() => update("outline", 5.0)} className={`hover:text-primary ${(cfg.outline ?? 3.0) === 5.0 ? "font-bold text-primary underline" : ""}`}>Đậm (5.0)</button>
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Box 2: Cấu hình Đổ bóng chữ (libass Shadow) */}
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
                  <span className="text-sm font-semibold text-foreground">Đổ bóng chữ (Shadow)</span>
                </label>
                <span
                  className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                    cfg.has_shadow
                      ? "bg-primary/10 text-primary-strong"
                      : "bg-slate-200/70 text-slate-500"
                  }`}
                >
                  {cfg.has_shadow ? `${cfg.shadow ?? 1.5}px` : "Đang tắt"}
                </span>
              </div>

              <div className="flex flex-col gap-2">
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

                {/* Độ sâu bóng đổ chuẩn ASS Shadow */}
                {cfg.has_shadow && (
                  <div className="flex flex-col gap-1.5 pt-2 border-t border-primary/20">
                    <div className="flex items-center justify-between">
                      <label className="text-xs font-semibold text-foreground">Khoảng cách bóng đổ</label>
                      <span className="font-mono text-xs font-bold text-primary">{cfg.shadow ?? 1.5} px</span>
                    </div>
                    <input
                      type="range"
                      min="0.5"
                      max="6.0"
                      step="0.5"
                      value={cfg.shadow ?? 1.5}
                      onChange={(e) => update("shadow", Number(e.target.value))}
                      className="h-1.5 w-full cursor-pointer accent-primary"
                    />
                    <div className="flex justify-between text-[11px] text-muted-foreground">
                      <button type="button" onClick={() => update("shadow", 1.0)} className={`hover:text-primary ${(cfg.shadow ?? 1.5) === 1.0 ? "font-bold text-primary underline" : ""}`}>Nhẹ (1.0)</button>
                      <button type="button" onClick={() => update("shadow", 1.5)} className={`hover:text-primary ${(cfg.shadow ?? 1.5) === 1.5 ? "font-bold text-primary underline" : ""}`}>Chuẩn (1.5)</button>
                      <button type="button" onClick={() => update("shadow", 3.0)} className={`hover:text-primary ${(cfg.shadow ?? 1.5) === 3.0 ? "font-bold text-primary underline" : ""}`}>Rõ (3.0)</button>
                    </div>
                  </div>
                )}
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

              {/* 4. Độ rộng viền làm mờ (Mask padding X) */}
              <div className="flex flex-col gap-1.5 pt-3 border-t border-border/60">
                <div className="flex items-center justify-between">
                  <label htmlFor="mask-padding-x-slider" className="text-xs font-semibold text-foreground">
                    Độ rộng viền làm mờ (Padding xung quanh chữ)
                  </label>
                  <span className="rounded bg-primary/10 px-2 py-0.5 font-mono text-xs font-bold text-primary-strong">
                    {cfg.mask_padding_x ?? 24} px
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <input
                    id="mask-padding-x-slider"
                    type="range"
                    min="4"
                    max="80"
                    step="2"
                    value={cfg.mask_padding_x ?? 24}
                    onChange={(e) => update("mask_padding_x", Number(e.target.value))}
                    className="h-2 w-full cursor-pointer accent-primary"
                  />
                  <input
                    type="number"
                    min="4"
                    max="80"
                    value={cfg.mask_padding_x ?? 24}
                    onChange={(e) => {
                      const v = parseInt(e.target.value, 10);
                      if (!isNaN(v)) update("mask_padding_x", Math.max(4, Math.min(80, v)));
                    }}
                    className="w-14 rounded-lg border border-slate-300 px-1.5 py-1 text-center font-mono text-xs font-bold text-foreground"
                  />
                </div>
                <div className="flex justify-between text-[11px] text-muted-foreground pt-0.5">
                  <button
                    type="button"
                    onClick={() => update("mask_padding_x", 12)}
                    className={`hover:text-primary ${(cfg.mask_padding_x ?? 24) === 12 ? "font-bold text-primary underline" : ""}`}
                  >
                    Gọn (12)
                  </button>
                  <button
                    type="button"
                    onClick={() => update("mask_padding_x", 24)}
                    className={`hover:text-primary ${(cfg.mask_padding_x ?? 24) === 24 ? "font-bold text-primary underline" : ""}`}
                  >
                    Chuẩn (24)
                  </button>
                  <button
                    type="button"
                    onClick={() => update("mask_padding_x", 36)}
                    className={`hover:text-primary ${(cfg.mask_padding_x ?? 24) === 36 ? "font-bold text-primary underline" : ""}`}
                  >
                    Rộng (36)
                  </button>
                  <button
                    type="button"
                    onClick={() => update("mask_padding_x", 50)}
                    className={`hover:text-primary ${(cfg.mask_padding_x ?? 24) === 50 ? "font-bold text-primary underline" : ""}`}
                  >
                    Rất rộng (50)
                  </button>
                </div>
                <p className="text-xs text-muted-foreground">
                  Độ rộng viền đệm của khối làm mờ che phủ xung quanh câu phụ đề (chuẩn ASS Backdrop Outline).
                </p>
              </div>

              {/* 5. Tùy chọn làm mờ theo text (Căn theo lề ngoài của sub) */}
              <div className="flex flex-col gap-2 pt-3 border-t border-border/60">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                  <label className="flex items-start sm:items-center gap-2.5 cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={cfg.mask_by_text}
                      onChange={(e) => update("mask_by_text", e.target.checked)}
                      className="size-4.5 rounded border-slate-300 text-primary accent-primary focus:ring-2 focus:ring-primary/20 cursor-pointer mt-0.5 sm:mt-0"
                    />
                    <div className="flex flex-col">
                      <span className="text-sm font-semibold text-foreground">
                        Làm mờ theo text (Căn theo lề ngoài của sub)
                      </span>
                      <span className="text-xs text-muted-foreground">
                        Khi bật, lề ngoài của khung làm mờ sẽ tự động căn theo lề ngoài của từng câu phụ đề (text). Khi tắt, hệ thống sẽ tạo một ô chữ chung cố định chứa toàn bộ phụ đề.
                      </span>
                    </div>
                  </label>
                  <span
                    className={`shrink-0 rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                      cfg.mask_by_text
                        ? "bg-primary/10 text-primary-strong"
                        : "bg-slate-200/70 text-slate-500"
                    }`}
                  >
                    {cfg.mask_by_text ? "Căn theo text" : "Ô chữ cố định"}
                  </span>
                </div>
              </div>
            </div>
          </div>

          {/* Row 5: Margins (Căn lề dọc nâng cao với mốc nhanh + Căn lề ngang chuẩn ASS) */}
          <div className="rounded-xl border border-border/80 bg-muted/40 p-4">
            <div className="mb-3 flex items-center justify-between">
              <div className="flex items-center gap-2 text-xs font-semibold text-foreground">
                <Sliders className="size-4 text-primary" aria-hidden />
                <span>Căn chỉnh lề hiển thị phụ đề (Khoảng cách & Vị trí chuẩn ASS)</span>
              </div>
              <span className="text-[11px] text-muted-foreground font-medium">Kéo thả phụ đề trên video để chỉnh nhanh vị trí</span>
            </div>

            <div className="grid grid-cols-1 gap-5 lg:grid-cols-12">
              {/* Căn lề dọc (Margin V) */}
              <div className="flex flex-col gap-2 lg:col-span-6 border-b pb-4 lg:border-b-0 lg:border-r lg:pr-5 border-border">
                <div className="flex items-center justify-between text-xs font-semibold">
                  <span className="flex items-center gap-1.5 text-foreground">
                    <MoveVertical className="size-3.5 text-primary" aria-hidden />
                    <span>Vị trí theo chiều dọc (Căn lề dưới MarginV)</span>
                  </span>
                  <span className="font-mono font-bold text-primary">{effectiveMarginV} px</span>
                </div>

                <div className="flex items-center gap-2">
                  <input
                    type="range"
                    min="10"
                    max={Math.max(300, Math.round(refVideoHeight * 0.6))}
                    step="1"
                    value={effectiveMarginV}
                    onChange={(e) => update("margin_v", Number(e.target.value))}
                    className="h-2 w-full cursor-pointer accent-primary"
                  />
                  <input
                    type="number"
                    min="10"
                    max={Math.round(refVideoHeight * 0.85)}
                    value={effectiveMarginV}
                    onChange={(e) => {
                      const v = parseInt(e.target.value, 10);
                      if (!isNaN(v)) update("margin_v", Math.max(10, Math.min(Math.round(refVideoHeight * 0.85), v)));
                    }}
                    className="w-16 rounded-lg border border-slate-300 px-2 py-1 text-center font-mono text-xs font-bold text-foreground"
                  />
                </div>
                <div className="flex justify-between text-[11px] text-muted-foreground pt-0.5">
                  <button type="button" onClick={() => update("margin_v", 30)} className={`hover:text-primary ${effectiveMarginV === 30 ? "font-bold text-primary underline" : ""}`}>Sát đáy (30)</button>
                  <button type="button" onClick={() => update("margin_v", 50)} className={`hover:text-primary ${effectiveMarginV === 50 ? "font-bold text-primary underline" : ""}`}>Chuẩn (50)</button>
                  <button type="button" onClick={() => update("margin_v", 90)} className={`hover:text-primary ${effectiveMarginV === 90 ? "font-bold text-primary underline" : ""}`}>Cao (90)</button>
                  <button type="button" onClick={() => update("margin_v", 140)} className={`hover:text-primary ${effectiveMarginV === 140 ? "font-bold text-primary underline" : ""}`}>Rất cao (140)</button>
                </div>
                <span className="text-[11px] text-muted-foreground">Khoảng cách từ mép dưới lên dòng phụ đề (chuẩn ASS MarginV)</span>
              </div>

              {/* Margin Left (L) & Right (R) (3 cols each) */}
              <div className="grid grid-cols-2 gap-4 lg:col-span-6">
                <div className="flex flex-col gap-1.5">
                  <div className="flex items-center justify-between text-xs font-semibold">
                    <span>Lề trái (L)</span>
                    <span className="font-mono font-bold text-primary">{effectiveMarginL} px</span>
                  </div>
                  <input
                    type="range"
                    min="0"
                    max="250"
                    step="5"
                    value={effectiveMarginL}
                    onChange={(e) => update("margin_l", Number(e.target.value))}
                    className="h-2 w-full cursor-pointer accent-primary"
                  />
                  <span className="text-[11px] text-muted-foreground">Khoảng cách an toàn mép trái (MarginL)</span>
                </div>

                <div className="flex flex-col gap-1.5">
                  <div className="flex items-center justify-between text-xs font-semibold">
                    <span>Lề phải (R)</span>
                    <span className="font-mono font-bold text-primary">{effectiveMarginR} px</span>
                  </div>
                  <input
                    type="range"
                    min="0"
                    max="250"
                    step="5"
                    value={effectiveMarginR}
                    onChange={(e) => update("margin_r", Number(e.target.value))}
                    className="h-2 w-full cursor-pointer accent-primary"
                  />
                  <span className="text-[11px] text-muted-foreground">Khoảng cách an toàn mép phải (MarginR)</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* --- Bottom Section: Full-Width Visual Live Preview --- */}
        <div className="flex flex-col gap-3 border-t border-border pt-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2.5">
              <div className="flex items-center gap-2">
                <Eye className="size-5 text-primary" aria-hidden />
                <span className="text-base font-semibold text-foreground">
                  Bản xem trước trực tiếp trên khung hình video
                </span>
              </div>
              {videoDimensions ? (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/10 border border-emerald-500/20 px-2.5 py-0.5 text-xs font-semibold text-emerald-700 dark:text-emerald-400">
                  <span className="size-1.5 rounded-full bg-emerald-500 animate-pulse" />
                  Khung hình đo được: {videoDimensions.width} × {videoDimensions.height} ({getAspectRatioLabel(videoDimensions.width, videoDimensions.height)})
                </span>
              ) : (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-500/10 border border-slate-500/20 px-2.5 py-0.5 text-xs font-semibold text-muted-foreground">
                  Khung hình mô phỏng: {previewAspectRatio === "9:16" ? "1080 × 1920 (9:16 Dọc)" : "1920 × 1080 (16:9 Ngang)"}
                </span>
              )}
            </div>

            <div className="flex flex-wrap items-center gap-2.5">
              {/* Aspect Ratio switcher when no video is uploaded */}
              {!videoDimensions && (
                <div className="flex items-center gap-1 text-xs mr-1">
                  <span className="text-muted-foreground font-medium mr-1">Tỉ lệ thử:</span>
                  <button
                    type="button"
                    onClick={() => setPreviewAspectRatio("16:9")}
                    className={`rounded-md px-2 py-1 font-semibold transition-colors ${
                      previewAspectRatio === "16:9"
                        ? "bg-primary text-on-primary shadow-xs"
                        : "bg-muted text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    16:9 Ngang
                  </button>
                  <button
                    type="button"
                    onClick={() => setPreviewAspectRatio("9:16")}
                    className={`rounded-md px-2 py-1 font-semibold transition-colors ${
                      previewAspectRatio === "9:16"
                        ? "bg-primary text-on-primary shadow-xs"
                        : "bg-muted text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    9:16 Dọc
                  </button>
                </div>
              )}

              {/* Sample Language Switcher */}
              <div className="flex items-center gap-1 text-xs">
                <span className="text-muted-foreground font-medium mr-1">Chữ mẫu:</span>
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
                      className={`rounded-md px-2 py-1 font-semibold transition-colors ${
                        active
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

          {/* Banner thông báo đồng bộ video dịch */}
          {videoFile && videoDimensions && (
            <div className="flex items-center gap-2 rounded-lg bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800 px-3 py-2 text-xs text-emerald-800 dark:text-emerald-300">
              <Check className="size-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
              <span>
                Đang dùng video <strong>{videoFile.name}</strong> để xem mẫu. Vị trí phụ đề được căn chỉnh chính xác theo tỉ lệ thực tế của khung hình (<strong>{videoDimensions.width} × {videoDimensions.height} px</strong>).
              </span>
            </div>
          )}

          {/* Frame Container */}
          <div className="w-full flex justify-center bg-slate-950/20 rounded-2xl p-2 sm:p-4 border border-border">
            <div
              ref={previewContainerRef}
              onPointerMove={handlePointerMove}
              onPointerUp={handlePointerUp}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              style={containerAspectRatioStyle}
              className={`relative select-none overflow-hidden rounded-xl border border-slate-800 bg-black shadow-xl transition-all ${containerMaxWidthClass}`}
            >
              {/* Drag file drop overlay */}
              {isDragOver && (
                <div className="absolute inset-0 z-30 flex flex-col items-center justify-center gap-2 bg-primary/20 backdrop-blur-xs border-2 border-dashed border-primary text-primary font-semibold text-sm">
                  <FileVideo className="size-8 animate-bounce" />
                  <span>Thả video vào đây để đặt làm video dịch & xem mẫu</span>
                </div>
              )}

              {/* Background: Video thực tế hoặc Khung hình mô phỏng */}
              {videoObjectUrl ? (
                <>
                  <video
                    ref={videoRef}
                    src={videoObjectUrl}
                    className="size-full object-contain pointer-events-none"
                    playsInline
                    muted={isMuted}
                    loop
                    onLoadedMetadata={handleLoadedMetadata}
                    onLoadedData={handleLoadedMetadata}
                    onCanPlay={handleLoadedMetadata}
                    onTimeUpdate={handleTimeUpdate}
                    onPlay={() => setIsPlaying(true)}
                    onPause={() => setIsPlaying(false)}
                    onEnded={() => setIsPlaying(false)}
                    onError={() => {
                      setVideoError("Trình duyệt không hỗ trợ phát trực tiếp định dạng video này để xem mẫu (video vẫn sẽ được dịch và render bình thường khi bấm Tạo phụ đề).");
                    }}
                  />

                  {/* Nút Play to ở giữa khung hình khi video đang tạm dừng */}
                  {!isPlaying && !videoError && (
                    <button
                      type="button"
                      onClick={togglePlayPause}
                      className="absolute inset-0 z-0 flex items-center justify-center bg-black/25 transition-opacity hover:bg-black/35"
                      title="Bấm để phát video (hoặc dùng thanh điều khiển bên dưới)"
                    >
                      <div className="flex size-14 items-center justify-center rounded-full bg-primary/90 text-on-primary shadow-lg backdrop-blur-xs transition-transform hover:scale-110">
                        <Play className="size-6 fill-current ml-0.5" />
                      </div>
                    </button>
                  )}

                  {videoError && (
                    <div className="absolute inset-0 z-0 flex flex-col items-center justify-center gap-2 bg-black/80 p-4 text-center text-xs text-amber-200">
                      <p className="font-semibold">{videoError}</p>
                    </div>
                  )}
                </>
              ) : (
                /* Simulated video background when no video file is uploaded yet */
                <div className="absolute inset-0 flex flex-col items-center justify-center p-4 text-center select-none bg-gradient-to-b from-slate-900 via-slate-950 to-black pointer-events-none">
                  <div className="flex size-12 items-center justify-center rounded-2xl bg-white/5 text-slate-400 mb-2">
                    <FileVideo className="size-6 opacity-60" />
                  </div>
                  <p className="text-xs font-semibold text-slate-300">
                    Khung xem trước mẫu ({previewAspectRatio === "9:16" ? "9:16 Dọc" : "16:9 Ngang"})
                  </p>
                  <p className="mt-0.5 text-[11px] text-slate-500 max-w-[320px]">
                    Tự động xuống dòng theo lề trái ({effectiveMarginL}px) & lề phải ({effectiveMarginR}px) chuẩn ASS
                  </p>
                  {onPickVideo && (
                    <Button
                      type="button"
                      variant="secondary"
                      icon={FileVideo}
                      onClick={onPickVideo}
                      className="mt-3 text-xs pointer-events-auto shadow-sm"
                    >
                      Chọn video ở mục 1
                    </Button>
                  )}
                </div>
              )}

                  {/* Subtitle Positioning Container */}
                  <div
                    className="absolute inset-x-0 flex flex-col justify-end pointer-events-none"
                    style={{
                      bottom: `${scaledMarginVPct}%`,
                      paddingLeft: `${scaledMarginLPct}%`,
                      paddingRight: `${scaledMarginRPct}%`,
                    }}
                  >
                    <div className="flex w-full justify-center text-center">
                      <div
                        onPointerDown={handlePointerDown}
                        className="group relative cursor-grab active:cursor-grabbing pointer-events-auto touch-none relative w-full text-center"
                        title="Bấm và giữ chuột để kéo phụ đề lên/xuống căn chỉnh vị trí trực tiếp trên video"
                      >
                        {/* Drag indicator hint on hover/drag */}
                        <span
                          aria-hidden
                          className="absolute -top-6 left-1/2 -translate-x-1/2 flex items-center gap-1 rounded bg-black/80 px-1.5 py-0.5 text-[10px] font-mono text-white opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none whitespace-nowrap z-20"
                        >
                          <GripVertical className="size-3 text-primary" />
                          <span>Kéo để chỉnh vị trí</span>
                        </span>

                        {cfg.mask_by_text ? (
                          <div
                            className="flex flex-col items-center w-full text-center"
                            style={{ gap: `${renderedLineSpacing}px` }}
                          >
                            {wrappedLines.map((line, idx) => (
                              <span
                                key={idx}
                                className="inline-block text-center select-none"
                                style={{
                                  backgroundColor: cfg.mask_enabled ? maskBgColor : "transparent",
                                  backdropFilter:
                                    cfg.mask_enabled && scaledMaskBlurPx > 0 ? `blur(${scaledMaskBlurPx}px)` : "none",
                                  WebkitBackdropFilter:
                                    cfg.mask_enabled && scaledMaskBlurPx > 0 ? `blur(${scaledMaskBlurPx}px)` : "none",
                                  boxShadow: cfg.mask_enabled ? maskBoxShadow : "none",
                                  borderRadius:
                                    cfg.mask_shape === "pill"
                                      ? "9999px"
                                      : cfg.mask_shape === "rounded"
                                      ? `${Math.max(4, Math.round(renderedFontSize * 0.28))}px`
                                      : "0px",
                                  padding: cfg.mask_enabled
                                    ? `${renderedMaskPaddingY}px ${renderedMaskPaddingX}px`
                                    : "0px",
                                  fontFamily: previewFontFamily,
                                  fontSize: `${renderedFontSize}px`,
                                  lineHeight: 1.3,
                                  whiteSpace: "nowrap",
                                  color: cfg.color,
                                  fontWeight: cfg.bold ? 700 : 400,
                                  fontStyle: cfg.italic ? "italic" : "normal",
                                  textShadow: previewTextShadow,
                                  WebkitTextStroke: cfg.has_border
                                    ? `${scaledOutlinePx.toFixed(1)}px ${cfg.color_border}`
                                    : undefined,
                                  paintOrder: "stroke fill",
                                }}
                              >
                                {line}
                              </span>
                            ))}
                          </div>
                        ) : (
                          <div className="relative w-full flex flex-col items-center">
                            {/* Layer 0: Backdrop Blur covering full width for all lines */}
                            {cfg.mask_enabled && (
                              <span
                                aria-hidden
                                className="absolute inset-0 pointer-events-none transition-all"
                                style={{
                                  borderRadius:
                                    cfg.mask_shape === "pill"
                                      ? "9999px"
                                      : cfg.mask_shape === "rounded"
                                      ? `${Math.max(4, Math.round(renderedFontSize * 0.28))}px`
                                      : "0px",
                                  backgroundColor: maskBgColor,
                                  backdropFilter: scaledMaskBlurPx > 0 ? `blur(${scaledMaskBlurPx}px)` : "none",
                                  WebkitBackdropFilter: scaledMaskBlurPx > 0 ? `blur(${scaledMaskBlurPx}px)` : "none",
                                  boxShadow: maskBoxShadow,
                                  top: `-${renderedMaskPaddingY}px`,
                                  bottom: `-${renderedMaskPaddingY}px`,
                                  left: cfg.mask_shape === "bar" ? "-1000px" : `-${renderedMaskPaddingX}px`,
                                  right: cfg.mask_shape === "bar" ? "-1000px" : `-${renderedMaskPaddingX}px`,
                                }}
                              />
                            )}

                            {/* Layer 1: Foreground Text */}
                            <div
                              className="relative z-10 flex flex-col items-center w-full text-center"
                              style={{ gap: `${renderedLineSpacing}px` }}
                            >
                              {wrappedLines.map((line, idx) => (
                                <span
                                  key={idx}
                                  className="block text-center select-none"
                                  style={{
                                    fontFamily: previewFontFamily,
                                    fontSize: `${renderedFontSize}px`,
                                    lineHeight: 1.3,
                                    whiteSpace: "nowrap",
                                    color: cfg.color,
                                    fontWeight: cfg.bold ? 700 : 400,
                                    fontStyle: cfg.italic ? "italic" : "normal",
                                    textShadow: previewTextShadow,
                                    WebkitTextStroke: cfg.has_border
                                      ? `${scaledOutlinePx.toFixed(1)}px ${cfg.color_border}`
                                      : undefined,
                                    paintOrder: "stroke fill",
                                  }}
                                >
                                  {line}
                                </span>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>

              {/* Live Indicator Badges */}
              <div className="absolute right-2.5 top-2.5 flex items-center gap-2 rounded-lg bg-black/80 px-2.5 py-1 text-[11px] font-mono text-white/95 backdrop-blur-md border border-white/10 pointer-events-none">
                <span>Khung: <strong className="text-emerald-400">{refVideoWidth}×{refVideoHeight}</strong></span>
                <span>•</span>
                <span>Cỡ chữ: <strong className="text-primary">{cfg.font_size}px</strong></span>
                <span>•</span>
                <span>Cách dòng: <strong className="text-primary">{cfg.line_spacing ?? 12}px</strong></span>
                <span>•</span>
                <span>Độ rộng mờ: <strong className="text-primary">{cfg.mask_padding_x ?? 24}px</strong></span>
                <span>•</span>
                <span>Lề dưới: <strong className="text-primary">{effectiveMarginV}px</strong></span>
                <span>•</span>
                <span>Lề L/R: <strong className="text-primary">{effectiveMarginL}/{effectiveMarginR}px</strong></span>
              </div>
            </div>
          </div>

          {/* Thanh điều khiển video (Playback Controls) khi có video */}
          {videoObjectUrl && (
            <div className="flex flex-col gap-2 rounded-xl border border-slate-700/60 bg-slate-900/95 p-3 text-white shadow-lg">
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={togglePlayPause}
                  className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary text-on-primary transition-transform hover:scale-105 active:scale-95 shadow-xs"
                  title={isPlaying ? "Tạm dừng (Space)" : "Phát video (Space)"}
                >
                  {isPlaying ? <Pause className="size-4 fill-current" /> : <Play className="size-4 fill-current ml-0.5" />}
                </button>

                <div className="flex flex-1 items-center gap-2">
                  <input
                    type="range"
                    min={0}
                    max={duration || 100}
                    step={0.1}
                    value={currentTime}
                    onChange={handleSeek}
                    className="h-2 w-full cursor-pointer accent-primary"
                    title="Kéo thanh này để tua video đến khung hình cần căn chỉnh phụ đề"
                  />
                </div>

                <span className="shrink-0 font-mono text-xs text-slate-300">
                  {formatVideoTime(currentTime)} / {formatVideoTime(duration)}
                </span>

                <button
                  type="button"
                  onClick={() => setIsMuted((m) => !m)}
                  className="flex size-7 shrink-0 items-center justify-center rounded-md text-slate-300 hover:bg-slate-800 hover:text-white transition-colors"
                  title={isMuted ? "Bật tiếng" : "Tắt tiếng"}
                >
                  {isMuted ? <VolumeX className="size-4 text-amber-400" /> : <Volume2 className="size-4" />}
                </button>
              </div>

              <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-800 pt-2 text-xs">
                <div className="flex items-center gap-2 text-slate-300 min-w-0">
                  <FileVideo className="size-4 shrink-0 text-primary" />
                  <span className="font-semibold text-white truncate max-w-[200px] sm:max-w-[340px]" title={videoFile?.name}>
                    {videoFile?.name}
                  </span>
                  {videoFile?.size && (
                    <span className="text-slate-400 shrink-0">({formatBytes(videoFile.size)})</span>
                  )}
                  {videoDimensions && (
                    <span className="text-emerald-400 font-mono shrink-0">
                      • {videoDimensions.width}×{videoDimensions.height} px ({getAspectRatioLabel(videoDimensions.width, videoDimensions.height)})
                    </span>
                  )}
                </div>

                <div className="flex items-center gap-3 shrink-0">
                  {onPickVideo && (
                    <button
                      type="button"
                      onClick={onPickVideo}
                      className="font-semibold text-primary hover:underline"
                    >
                      Đổi video khác
                    </button>
                  )}
                  <span className="text-slate-600">•</span>
                  <button
                    type="button"
                    onClick={() => onVideoFileChange?.(null)}
                    className="font-semibold text-slate-400 hover:text-rose-400 transition-colors"
                  >
                    Bỏ chọn
                  </button>
                </div>
              </div>
            </div>
          )}

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
                  <div className="relative z-10 px-3 py-1.5 my-auto w-full text-center">
                    {cfg.mask_by_text ? (
                      <div className="flex flex-col items-center gap-1">
                        <span
                          className="inline text-lg font-bold leading-tight [box-decoration-break:clone] [-webkit-box-decoration-break:clone]"
                          style={{
                            backgroundColor: showModalMask ? modalMaskBgColor : "transparent",
                            backdropFilter:
                              showModalMask && maskBlurPx > 0 ? `blur(${maskBlurPx}px)` : "none",
                            WebkitBackdropFilter:
                              showModalMask && maskBlurPx > 0 ? `blur(${maskBlurPx}px)` : "none",
                            boxShadow: showModalMask ? maskBoxShadow : "none",
                            borderRadius:
                              cfg.mask_shape === "pill"
                                ? "9999px"
                                : cfg.mask_shape === "rounded"
                                ? "6px"
                                : "0px",
                            padding: showModalMask
                              ? cfg.mask_shape === "pill"
                                ? "2.5px 12px"
                                : cfg.mask_shape === "rounded"
                                ? "2.5px 8px"
                                : "1.5px 6px"
                              : "0px",
                            color: colorTarget === "color" ? tempColor : cfg.color,
                            textShadow: modalTextShadow,
                          }}
                        >
                          Phụ đề mẫu
                        </span>
                        <span
                          className="inline text-xs font-bold leading-tight [box-decoration-break:clone] [-webkit-box-decoration-break:clone]"
                          style={{
                            backgroundColor: showModalMask ? modalMaskBgColor : "transparent",
                            backdropFilter:
                              showModalMask && maskBlurPx > 0 ? `blur(${maskBlurPx}px)` : "none",
                            WebkitBackdropFilter:
                              showModalMask && maskBlurPx > 0 ? `blur(${maskBlurPx}px)` : "none",
                            boxShadow: showModalMask ? maskBoxShadow : "none",
                            borderRadius:
                              cfg.mask_shape === "pill"
                                ? "9999px"
                                : cfg.mask_shape === "rounded"
                                ? "6px"
                                : "0px",
                            padding: showModalMask
                              ? cfg.mask_shape === "pill"
                                ? "2px 8px"
                                : cfg.mask_shape === "rounded"
                                ? "2px 6px"
                                : "1px 4px"
                              : "0px",
                            color: colorTarget === "color" ? tempColor : cfg.color,
                            textShadow: modalSubTextShadow,
                          }}
                        >
                          ឥឡូវព្រះអធិរាជ
                        </span>
                      </div>
                    ) : (
                      <div className="relative w-full">
                        {showModalMask && (
                          <span
                            aria-hidden
                            className={`absolute pointer-events-none transition-all ${getMaskShapeClasses(cfg.mask_shape || "pill", false)}`}
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
                    )}
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
