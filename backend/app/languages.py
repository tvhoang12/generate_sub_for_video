"""Target languages the tool can subtitle into, with the font and script rules each one needs."""

import re
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Language:
    code: str
    label: str  # shown to editors (Vietnamese UI)
    english_name: str  # used inside LLM prompts
    windows_font: str  # font family libass uses when burning, per OS (Linux = Noto, installed in the image)
    linux_font: str
    script: re.Pattern[str] | None  # characters a translated line is expected to contain
    max_line_chars: int

    @property
    def font(self) -> str:
        return self.windows_font if sys.platform == "win32" else self.linux_font


LANGUAGES: dict[str, Language] = {
    lang.code: lang
    for lang in [
        Language("lo", "Tiếng Lào", "Lao", "Leelawadee UI", "Noto Sans Lao", re.compile(r"[຀-໿]"), 38),
        Language("my", "Tiếng Myanmar", "Burmese (Myanmar, Unicode — never Zawgyi)", "Myanmar Text", "Noto Sans Myanmar", re.compile(r"[က-႟]"), 38),
        Language("km", "Tiếng Khmer (Campuchia)", "Khmer", "Leelawadee UI", "Noto Sans Khmer", re.compile(r"[ក-៿]"), 38),
        Language("th", "Tiếng Thái", "Thai", "Leelawadee UI", "Noto Sans Thai", re.compile(r"[฀-๿]"), 38),
        Language("vi", "Tiếng Việt", "Vietnamese", "Arial", "Noto Sans", None, 42),
        Language("id", "Tiếng Indonesia", "Indonesian", "Arial", "Noto Sans", None, 42),
        Language("en", "Tiếng Anh", "English", "Arial", "Noto Sans", None, 42),
        Language("zh", "Tiếng Trung (giản thể)", "Simplified Chinese", "Microsoft YaHei", "Noto Sans CJK SC", re.compile(r"[一-鿿]"), 18),
    ]
}

# Spoken languages FunASR is asked to recognise; "auto" lets it detect.
SOURCE_LANGUAGES: dict[str, str] = {
    "auto": "Tự nhận diện",
    "en": "Tiếng Anh",
    "zh": "Tiếng Trung",
    "ja": "Tiếng Nhật",
    "ko": "Tiếng Hàn",
    "vi": "Tiếng Việt",
    "th": "Tiếng Thái",
}


def get_language(code: str) -> Language:
    try:
        return LANGUAGES[code]
    except KeyError:
        raise ValueError(f"Unsupported target language: {code}") from None
