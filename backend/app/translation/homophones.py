"""Chinese homophone error detection and correction module (Kiểm tra và sửa lỗi đồng âm tiếng Trung).

ASR models (SenseVoice/FunASR, Whisper) transcribe audio phonetically. In tonal and homophone-dense
Chinese (同音字 / 近音词), speech recognition frequently chooses the wrong Hanzi when background music,
dramatic delivery, or regional accents are present. This module provides specialized context-aware
guidance and reference rules to detect and correct homophone errors in short dramas.
"""

# Common homophone and near-homophone pairs frequently confused in Chinese speech recognition and dramas
COMMON_CHINESE_HOMOPHONE_MAP: dict[str, dict] = {
    # Pronouns (tā)
    "他": {"pinyin": "tā", "confusions": ["她", "它"], "note": "Phân biệt giới tính nam/nữ/đồ vật theo ngữ cảnh nhân vật"},
    "她": {"pinyin": "tā", "confusions": ["他", "它"], "note": "Phân biệt giới tính nam/nữ/đồ vật theo ngữ cảnh nhân vật"},
    "它": {"pinyin": "tā", "confusions": ["他", "她"], "note": "Phân biệt giới tính nam/nữ/đồ vật theo ngữ cảnh nhân vật"},
    # Particles (zài, de, zuò, dài, xiàng)
    "在": {"pinyin": "zài", "confusions": ["再"], "note": "Ở/đang/tại vs Lại/nữa/tái (ví dụ: '再见' tạm biệt, không phải '在见')"},
    "再": {"pinyin": "zài", "confusions": ["在"], "note": "Lại/nữa vs Ở/đang (ví dụ: '在不在', '在这里')"},
    "的": {"pinyin": "de", "confusions": ["得", "地"], "note": "Định ngữ (người của tôi) vs Bổ ngữ (chạy được nhanh) vs Trạng từ (từ từ đi)"},
    "得": {"pinyin": "de", "confusions": ["的", "地"], "note": "Bổ ngữ chỉ mức độ/khả năng"},
    "地": {"pinyin": "de", "confusions": ["的", "得"], "note": "Trạng từ đứng trước động từ"},
    "做": {"pinyin": "zuò", "confusions": ["作", "坐", "座"], "note": "Làm/hành động vs Sáng tác/tác phẩm vs Ngồi vs Ghế/tòa nhà"},
    "作": {"pinyin": "zuò", "confusions": ["做", "坐", "座"], "note": "Tác phong, tác phẩm, làm việc"},
    "带": {"pinyin": "dài", "confusions": ["戴", "代"], "note": "Mang/dắt theo vs Đeo/đội trên người vs Đại diện/thời đại"},
    "戴": {"pinyin": "dài", "confusions": ["带", "代"], "note": "Đeo kính, đội nón, mang trang sức"},
    "像": {"pinyin": "xiàng", "confusions": ["相", "象"], "note": "Giống như/hình tượng vs Tướng mạo/tương trợ vs Con voi/hiện tượng"},
    # Common drama names and executive titles
    "顾总": {"pinyin": "gù zǒng", "confusions": ["雇总"], "note": "Tổng tài họ Cố (顾), thường bị ASR nhầm thành 雇 (thuê)"},
    "陆总": {"pinyin": "lù zǒng", "confusions": ["路总"], "note": "Tổng tài họ Lục (陆), thường bị ASR nhầm thành 路 (con đường)"},
    "陆少": {"pinyin": "lù shào", "confusions": ["路少"], "note": "Thiếu gia họ Lục (陆)"},
    "傅少": {"pinyin": "fù shào", "confusions": ["付少"], "note": "Thiếu gia họ Phó (傅), ASR hay nhầm thành 付 (trả tiền)"},
    "傅总": {"pinyin": "fù zǒng", "confusions": ["付总"], "note": "Tổng tài họ Phó (傅)"},
    "霍总": {"pinyin": "huò zǒng", "confusions": ["获总", "惑总"], "note": "Tổng tài họ Hoắc (霍)"},
    "萧总": {"pinyin": "xiāo zǒng", "confusions": ["肖总", "销总"], "note": "Tổng tài họ Tiêu (萧), ASR hay nhầm 肖/销"},
    "萧氏": {"pinyin": "xiāo shì", "confusions": ["肖氏", "销烟"], "note": "Tập đoàn họ Tiêu (萧氏)"},
    "叶总": {"pinyin": "yè zǒng", "confusions": ["夜总"], "note": "Tổng tài họ Diệp (叶)"},
    "厉总": {"pinyin": "lì zǒng", "confusions": ["丽总", "立总"], "note": "Tổng tài họ Lệ (厉)"},
    # Drama terms & homophone confusion
    "权力": {"pinyin": "quán lì", "confusions": ["权利"], "note": "Quyền lực thống trị/cai quản vs Quyền lợi công dân"},
    "权利": {"pinyin": "quán lì", "confusions": ["权力"], "note": "Quyền lợi pháp lý vs Quyền lực chính trị"},
    "报复": {"pinyin": "bào fù", "confusions": ["抱负"], "note": "Báo thù/trả đũa vs Hoài bão/ước mơ"},
    "抱负": {"pinyin": "bào fù", "confusions": ["报复"], "note": "Hoài bão/chí hướng vs Báo thù"},
    "交代": {"pinyin": "jiāo dài", "confusions": ["胶带"], "note": "Giải thích/giao phó/thú nhận vs Băng dính"},
    "胶带": {"pinyin": "jiāo dài", "confusions": ["交代"], "note": "Băng dính vs Lời giải thích/bàn giao"},
    "启程": {"pinyin": "qǐ chéng", "confusions": ["起程"], "note": "Lên đường/khởi hành"},
    "治病": {"pinyin": "zhì bìng", "confusions": ["致病"], "note": "Chữa bệnh vs Gây ra bệnh"},
    "绝境": {"pinyin": "jué jìng", "confusions": ["决境"], "note": "Đường cùng/tuyệt cảnh"},
    "吩咐": {"pinyin": "fēn fù", "confusions": ["分付"], "note": "Dặn dò/ra lệnh"},
    "身分": {"pinyin": "shēn fèn", "confusions": ["身份"], "note": "Thân phận/địa vị"},
    "份": {"pinyin": "fèn", "confusions": ["分"], "note": "Phần ăn/bản hợp đồng vs Phút/chia"},
}


def get_homophone_cleaning_prompt(source_language: str = "zh") -> str:
    """Builds specific instructions for detecting and correcting Chinese homophone errors during line cleanup."""
    if source_language and source_language.lower() not in ("zh", "auto", "chinese"):
        return ""

    return """=== KIỂM TRA VÀ SỬA LỖI ĐỒNG ÂM TIẾNG TRUNG (CHINESE HOMOPHONE ERROR CHECKING) ===
Do bản ghi âm lời thoại được xử lý tự động bằng nhận diện giọng nói (ASR: FunASR/SenseVoice/Whisper), trong tiếng Trung thường xuyên xảy ra lỗi nhận diện nhầm từ đồng âm (同音字 / 近音词 / 谐音错别字) do phát âm giống hoặc gần giống nhau nhưng viết sai chữ Hán.
Bạn PHẢI kiểm tra kỹ lưỡng từng dòng dựa trên ngữ cảnh bộ phim (tóm tắt phim, danh sách nhân vật, giới tính, quan hệ nhân vật, thể loại phim, bảng thuật ngữ) và ngữ cảnh câu thoại xung quanh:

1. Đại từ nhân xưng & Giới tính nhân vật (同音人称代词):
   - Phân biệt rõ ràng: 他 (nam), 她 (nữ), 它 (đồ vật/động vật) [pinyin: tā]. Phải khớp chính xác với giới tính của nhân vật đang nói hoặc được nhắc đến trong bối cảnh phim.

2. Trợ từ, Phó từ & Chữ Hán cơ bản dễ nhầm (常用同音字):
   - "在" (ở, tại, đang) vs "再" (lại, nữa, tái) [zài]: ví dụ "再见" (tạm biệt, hẹn gặp lại) KHÔNG ĐƯỢC để thành "在见"; "在这里" (ở đây) không được thành "再这里".
   - "的 / 得 / 地" [de]: dùng chuẩn xác theo ngữ pháp kết cấu tiếng Trung (định ngữ 的, bổ ngữ 得, trạng ngữ 地).
   - "做 / 作 / 坐 / 座" [zuò]: "作为" vs "做为", "请坐" vs "请做".
   - "带 / 戴 / 代" [dài]: "戴眼镜" vs "带眼镜", "代表" vs "带领".
   - "像 / 相 / 象" [xiàng]: "好像" vs "好相", "形象" vs "形像".

3. Họ tên nhân vật, Chức vị, Danh xưng trong phim (人名与头衔同音替代):
   - ASR thường tự động thay thế họ tên nhân vật ít gặp bằng từ ngữ thông dụng có cùng phát âm Pinyin:
     * "顾总" (Tổng tài họ Cố) bị nhận diện nhầm thành "雇总" [gù zǒng]
     * "陆总 / 陆少" (họ Lục) bị nhận diện nhầm thành "路总 / 路少" [lù]
     * "傅少 / 傅先生" (họ Phó) bị nhận diện nhầm thành "付少 / 付先生" [fù]
     * "霍总 / 霍少" (họ Hoắc) bị nhận diện nhầm thành "获总 / 惑总" [huò]
     * "萧总 / 萧氏" (họ Tiêu) bị nhận diện nhầm thành "肖总 / 销烟" [xiāo]
     * "叶总 / 叶天" (họ Diệp) bị nhận diện nhầm thành "夜总 / 夜天" [yè]
     * "厉总" (họ Lệ) bị nhận diện nhầm thành "丽总 / 立总" [lì]
   - Phải đối chiếu với danh sách nhân vật <film> và <glossary> để khôi phục đúng họ tên chữ Hán.

4. Từ vựng kịch tính / Ngữ cảnh phim truyền hình (影视剧高频同音混淆词):
   - "权力" (quyền lực chính trị, cai trị) vs "权利" (quyền lợi pháp lý cá nhân) [quánlì]
   - "报复" (trả thù, trả đũa) vs "抱负" (hoài bão, ước mơ lớn) [bàofù]
   - "交代" (giao phó, dặn dò, giải thích, thú nhận) vs "胶带" (băng dính dán) [jiāodài]
   - "绝境" (bước đường cùng, hoàn cảnh tuyệt vọng) vs "决境" [juéjìng]
   - "启程" (lên đường, khởi hành) vs "起程" [qǐchéng]
   - "治病" (chữa bệnh) vs "致病" (gây bệnh) [zhìbìng]

5. Lỗi do khẩu âm địa phương / Âm gần giống (近音字 / 方言口音):
   - Âm uốn lưỡi zh/ch/sh vs âm thẳng lưỡi z/c/s (ví dụ: 知道 / 子道)
   - Lỗi n/l (ví dụ: 蓝 / 男)
   - Lỗi in/ing, en/eng (ví dụ: 经 / 金, 分 / 风)

QUY TẮC XỬ LÝ:
- Nếu phát hiện lỗi đồng âm, sửa lại chữ Hán chính xác trong trường 'text' của dòng đó.
- Đồng thời ghi nhận chi tiết vào mảng 'homophone_corrections' cho từng lỗi:
  * 'id': mã số id của dòng phụ đề
  * 'original': chữ/từ Hán bị nhận diện nhầm từ ASR
  * 'corrected': chữ/từ Hán đúng theo ngữ cảnh
  * 'pinyin': phiên âm Pinyin của cặp âm (ví dụ: 'gù zǒng', 'quán lì')
  * 'explanation': giải thích ngắn lý do sửa dựa vào ngữ cảnh bộ phim
- Nếu không phát hiện lỗi đồng âm nào, trả về homophone_corrections là danh sách rỗng []."""


def get_homophone_translation_prompt(source_language: str = "zh") -> str:
    """Builds translation instructions emphasizing Chinese homophone disambiguation according to context."""
    if source_language and source_language.lower() not in ("zh", "auto", "chinese"):
        return ""

    return """- Ngữ cảnh và Phân giải lỗi đồng âm tiếng Trung (Chinese Homophone Context Awareness):
  Khi dịch từ lời thoại tiếng Trung, chú ý các trường hợp từ đồng âm (同音字), gần âm (近音词), chữ nhiều âm nhiều nghĩa (多音多义字), và cách chơi chữ/hài kịch (谐音双关).
  Luôn dịch theo đúng ý nghĩa ngữ cảnh cảnh quay, thân phận và mối quan hệ nhân vật, tâm trạng kịch bản thay vì dịch theo nghĩa đen của chữ bị nhận diện nhầm."""
