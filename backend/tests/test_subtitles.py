from app.pipeline.subtitles import Cue, is_non_speech, parse_srt, tighten_timing, to_srt


def test_srt_round_trip_keeps_multiline_text():
    cues = [Cue(1, 81_140, 83_140, "Kestrel, right on schedule."), Cue(2, 83_700, 87_070, "Line one\nLine two")]
    parsed = parse_srt(to_srt(cues))
    assert [(c.start_ms, c.end_ms, c.text) for c in parsed] == [(c.start_ms, c.end_ms, c.text) for c in cues]


def test_stretched_cue_is_trimmed_to_the_speech_inside_it():
    # Episode 3: "Sorry, what was that about?" came out as 2:05.45-2:22.11; the voice is at 2:20.98-2:22.41.
    cues = [Cue(1, 125_450, 142_110, "Sorry, what was that about?")]
    fitted = tighten_timing(cues, [(119_420, 120_740), (140_980, 142_410)], max_cue_ms=7000)
    assert (fitted[0].start_ms, fitted[0].end_ms) == (140_980, 142_110)


def test_small_margins_around_speech_are_kept():
    # "I'm sure it managed." 1:28.52-1:29.78, voice 1:29.05-1:30.08: trimming would leave 0.7 s on screen.
    fitted = tighten_timing([Cue(1, 88_520, 89_780, "I'm sure it managed.")], [(89_050, 90_080)], max_cue_ms=7000)
    assert (fitted[0].start_ms, fitted[0].end_ms) == (88_520, 89_780)


def test_cue_without_detected_speech_is_capped_keeping_its_tail():
    fitted = tighten_timing([Cue(1, 0, 20_000, "long")], [], max_cue_ms=7000)
    assert (fitted[0].start_ms, fitted[0].end_ms) == (13_000, 20_000)


def test_short_cue_is_extended_but_never_overlaps_the_next():
    cues = [Cue(1, 1000, 1200, "Mm."), Cue(2, 1500, 3000, "Next")]
    fitted = tighten_timing(cues, [], max_cue_ms=7000)
    assert fitted[0].end_ms == 1460
    assert fitted[1].start_ms == 1500


def test_sound_tags_are_not_speech():
    assert is_non_speech("[Music]")
    assert is_non_speech(" (laughs) ")
    assert is_non_speech("♪ ♪")
    assert not is_non_speech("No!")


def test_ass_events_keep_line_breaks_and_escape_override_braces():
    from app.pipeline.subtitles import to_ass

    ass = to_ass([Cue(1, 61_230, 3_723_450, "ព្រមទាំង {x}\nline two")], "Noto Sans Khmer")
    assert "Style: Default,Noto Sans Khmer,110," in ass
    assert r"Dialogue: 1,0:01:01.23,1:02:03.45,Default,,0,0,0,,ព្រមទាំង \{x\}\Nline two" in ass


def test_ass_border_and_shadow_configs():
    from app.pipeline.subtitles import to_ass

    cues = [Cue(1, 1000, 2000, "Sample")]

    # Default has border outline=3.0 and shadow=1.5 with black shadow &H80000000
    ass_default = to_ass(cues, "Arial")
    assert ",1,3.0,1.5,2," in ass_default
    assert ",&H80000000,1,0," in ass_default

    # Disabling border sets outline to 0.0
    ass_no_border = to_ass(cues, "Arial", {"has_border": False})
    assert ",1,0.0,1.5,2," in ass_no_border

    # Disabling shadow sets shadow to 0.0
    ass_no_shadow = to_ass(cues, "Arial", {"has_shadow": False})
    assert ",1,3.0,0.0,2," in ass_no_shadow

    # Custom shadow color #FF0000 translates to ASS BackColour &H800000FF
    ass_custom_shadow = to_ass(cues, "Arial", {"color_shadow": "#FF0000"})
    assert ",&H800000FF,1,0," in ass_custom_shadow


def test_ass_mask_configs():
    from app.pipeline.subtitles import to_ass

    cues = [Cue(1, 1000, 2000, "Sample")]

    # Default has backdrop with blur10 and Dialogue 0
    ass_default = to_ass(cues, "Arial")
    assert r"Dialogue: 0,0:00:01.00,0:00:02.00,Backdrop,,0,0,0,,{\blur10}Sample" in ass_default

    # Disabling mask removes Backdrop Dialogue
    ass_disabled = to_ass(cues, "Arial", {"mask_enabled": False})
    assert "Backdrop,,0,0,0" not in ass_disabled
    assert "Default,,0,0,0" in ass_disabled

    # Custom mask with rectangle shape, opacity 75%, blur 20
    ass_custom = to_ass(cues, "Arial", {
        "mask_color": "#0000FF",
        "mask_opacity": 75,
        "mask_blur": 20,
        "mask_shape": "rectangle",
    })
    assert r"Dialogue: 0,0:00:01.00,0:00:02.00,Backdrop,,0,0,0,,{\blur20}Sample" in ass_custom
    # BorderStyle 3 for rectangle
    assert ",3," in ass_custom

    # Mask by text aligns to text with Backdrop style
    ass_by_text = to_ass(cues, "Arial", {"mask_by_text": True})
    assert r"Dialogue: 0,0:00:01.00,0:00:02.00,Backdrop,,0,0,0,,{\blur10}Sample" in ass_by_text

    # Fixed box for all subs (mask_by_text = False) generates BackdropFixed vector drawing
    ass_fixed = to_ass(cues, "Arial", {"mask_by_text": False})
    assert "Style: BackdropFixed," in ass_fixed
    assert r"Dialogue: 0,0:00:01.00,0:00:02.00,BackdropFixed,,0,0,0,,{\pos(" in ass_fixed
    assert r"\p1}m 0 0 l " in ass_fixed


def test_to_ass_aspect_ratio_resolution():
    from app.pipeline.subtitles import Cue, to_ass

    cues = [Cue(1, 1000, 2000, "Test resolution")]

    # 16:9 landscape video (1920x1080) -> PlayResX: 1920, PlayResY: 1080
    ass_16_9 = to_ass(cues, "Arial", video_width=1920, video_height=1080)
    assert "PlayResX: 1920" in ass_16_9
    assert "PlayResY: 1080" in ass_16_9

    # 9:16 portrait video (1080x1920) -> PlayResX: 1080, PlayResY: 1920
    ass_9_16 = to_ass(cues, "Arial", video_width=1080, video_height=1920)
    assert "PlayResX: 1080" in ass_9_16
    assert "PlayResY: 1920" in ass_9_16

    # Default fallback when dimensions not given -> PlayResX: 1920, PlayResY: 1080
    ass_default = to_ass(cues, "Arial")
    assert "PlayResX: 1920" in ass_default
    assert "PlayResY: 1080" in ass_default


def test_split_segment_cues_by_pauses_and_cadence():
    from app.pipeline.media import split_segment_cues

    # A single sentence broken into 3 phrases by punctuation and pauses
    text = "Xin chào các bạn, hôm nay chúng ta, tiếp tục tập hai."
    # 6-second segment with 3 distinct speech intervals (and silence gaps between 2500-3200 and 4500-5100)
    speech = [(1000, 2500), (3200, 4500), (5100, 6800)]
    splits = split_segment_cues(1000, 7000, text, max_dur_ms=4000, speech_regions=speech)

    assert len(splits) == 3
    # First phrase aligned to first speech interval
    assert "Xin chào các bạn" in splits[0][2]
    assert splits[0][0] == 1000 and splits[0][1] == 2500
    # Second phrase aligned to second speech interval
    assert "hôm nay chúng ta" in splits[1][2]
    assert splits[1][0] == 3200 and splits[1][1] == 4500
    # Third phrase aligned to third speech interval
    assert "tiếp tục tập hai" in splits[2][2]
    assert splits[2][0] == 5100 and splits[2][1] == 6800


def test_split_segment_cues_short_segment_no_oversplit():
    from app.pipeline.media import split_segment_cues

    # A short 1.2s segment with a comma should not be over-split into tiny blips
    text = "Dạ, vâng."
    splits = split_segment_cues(1000, 2200, text, max_dur_ms=4000)
    assert len(splits) == 1
    assert splits[0][2] == "Dạ, vâng."


def test_split_segment_cues_sentence_terminators():
    from app.pipeline.media import split_segment_cues

    text = "Anh đến rồi à? Em đợi anh lâu lắm rồi đấy."
    splits = split_segment_cues(1000, 6000, text, max_dur_ms=4000)
    assert len(splits) == 2
    assert "Anh đến rồi à?" in splits[0][2]
    assert "Em đợi anh lâu lắm rồi đấy." in splits[1][2]


def test_ass_margins_standard():
    from app.pipeline.subtitles import Cue, to_ass

    cues = [Cue(1, 1000, 2000, "Sample")]

    # Default margins are margin_l=50, margin_r=50, ass_margin_v=38 (bottom-aligned with Alignment=2)
    ass_default = to_ass(cues, "Arial")
    assert ",1,3.0,1.5,2,50,50,38,1" in ass_default

    # User margin_r = 0 -> exact margin_r is 0
    ass_zero = to_ass(cues, "Arial", {"margin_r": 0})
    assert ",1,3.0,1.5,2,50,0,38,1" in ass_zero

    # User margin_r = 20 -> exact margin_r is 20
    ass_custom = to_ass(cues, "Arial", {"margin_r": 20})
    assert ",1,3.0,1.5,2,50,20,38,1" in ass_custom


def test_auto_line_wrap_based_on_frame_size_and_margins():
    from app.pipeline.subtitles import Cue, to_ass

    long_vi = "Tôi sẽ tìm ra chân tướng sự việc đằng sau chuyện này dù cho có bất kỳ khó khăn nào xảy ra"
    cues = [Cue(1, 1000, 2000, long_vi)]

    # In 9:16 portrait video (width 1080, height 1920), available width is 1080 - 50 - 50 = 980
    ass_portrait = to_ass(cues, "Arial", video_width=1080, video_height=1920)
    for line in ass_portrait.splitlines():
        if line.startswith("Dialogue: 1,"):
            # Must auto-wrap into multiple lines with \N
            assert r"\N" in line
            parts = line.split(",,", 1)[1].split(r"\N")
            assert len(parts) >= 3

    # In 16:9 landscape video (width 1920, height 1080), lines wrap with wider threshold
    ass_landscape = to_ass(cues, "Arial", video_width=1920, video_height=1080)
    for line in ass_landscape.splitlines():
        if line.startswith("Dialogue: 1,"):
            assert r"\N" in line
            parts = line.split(",,", 1)[1].split(r"\N")
            assert len(parts) < len(ass_portrait.split(r"\N"))

    # Test auto-wrap on scripts without spaces (Khmer)
    km_text = "ឥឡូវព្រះអធិរាជចង់ឱ្យលោកតាសរសេរថ្កោលទោសអតីតអធិរាជ"
    ass_km_portrait = to_ass([Cue(1, 1000, 2000, km_text)], "Noto Sans Khmer", video_width=1080, video_height=1920)
    for line in ass_km_portrait.splitlines():
        if line.startswith("Dialogue: 1,"):
            assert r"\N" in line


def test_ass_line_spacing_and_mask_padding():
    from app.pipeline.subtitles import Cue, to_ass

    cues = [Cue(1, 1000, 3000, "First line\nSecond line")]

    # Default (no line spacing specified) uses simple \N
    ass_std = to_ass(cues, "Arial")
    assert r"Dialogue: 1,0:00:01.00,0:00:03.00,Default,,0,0,0,,First line\NSecond line" in ass_std
    # Default mask padding x is 24, so Backdrop outline is 24 with Alignment=2
    assert ",3,24,0,2," in ass_std

    # Custom line_spacing=18 and mask_padding_x=32
    ass_custom = to_ass(cues, "Arial", {"line_spacing": 18, "mask_padding_x": 32})
    # Spacer tag expands line spacing by 18px without visible artifacts
    assert r"Dialogue: 1,0:00:01.00,0:00:03.00,Default,,0,0,0,,First line\N{\fs18\alpha&HFF&}\h\N{\fs61\alpha&H00&}Second line" in ass_custom
    assert r"Dialogue: 0,0:00:01.00,0:00:03.00,Backdrop,,0,0,0,,{\blur10}First line\N{\fs18\alpha&HFF&}\h\N{\fs61\1a&HFF&\3a&H99&\4a&H99&}Second line" in ass_custom
    # Backdrop outline equals mask_padding_x = 32 with Alignment=2
    assert ",3,32,0,2," in ass_custom

    # Custom line_spacing and mask_padding_x in fixed box mode (mask_by_text = False)
    ass_fixed = to_ass(cues, "Arial", {"line_spacing": 20, "mask_padding_x": 30, "mask_by_text": False})
    # x1 = margin_l - mask_padding_x = 50 - 30 = 20
    # x2 = 1920 - 50 + 30 = 1900 -> w = 1880
    assert r"\pos(20," in ass_fixed
    assert "m 0 0 l 1880 0" in ass_fixed


def test_lao_and_thai_zero_width_marks_prevent_premature_wrapping():
    from app.pipeline.subtitles import Cue, to_ass, wrap_single_line

    # Cue from real job with Lao text containing multiple upper/lower vowels and tones
    # Real advance width is ~588px at font_size=50, which fits inside 720px portrait canvas (margin_l=0, margin_r=0)
    lao_line = "ຂ້ອຍໄດ້ໃຊ້ເວລາເຄິ່ງຊີວິດທີ່ເຫຼືອ"
    wrapped = wrap_single_line(lao_line, 720.0, 50.0)
    assert len(wrapped) == 1
    assert wrapped[0] == lao_line

    ass = to_ass([Cue(1, 1000, 2000, lao_line)], "Phetsarath", {"margin_l": 0, "margin_r": 0}, video_width=720, video_height=1280)
    for line in ass.splitlines():
        if line.startswith("Dialogue: 1,"):
            # Must NOT wrap onto 2 lines
            assert r"\N" not in line


def test_prevowels_stay_with_base_consonants():
    from app.pipeline.subtitles import split_clusters, wrap_single_line

    # In Lao, ເ (pre-vowel E) in ເຫຼືອ must stay attached to เหลือ, not get glued to ທີ່
    text = "ທີ່ເຫຼືອ"
    clusters = split_clusters(text)
    assert "ທີ່" in clusters
    assert "ເຫຼື" in clusters or any(cl.startswith("ເ") for cl in clusters)
    assert not any(cl.endswith("ເ") for cl in clusters)

    # When wrapping long Lao text, syllables must not split pre-vowels away from consonants
    long_lao = "ຂ້ອຍໄດ້ໃຊ້ເວລາເຄິ່ງຊີວິດທີ່ເຫຼືອເພື່ອຊົດເຊີຍມັນແລ້ວ."
    wrapped = wrap_single_line(long_lao, 720.0, 50.0)
    assert len(wrapped) == 2
    # Second line starts with the intact word ເຫຼືອ...
    assert wrapped[1].startswith("ເຫຼືອ")


def test_orphan_word_prevention_on_wrap():
    from app.pipeline.subtitles import wrap_single_line

    # Without orphan prevention, "này" would be stranded alone on the 2nd line.
    sentence = "Tôi sẽ nói rõ toàn bộ sự thật này"
    # Available width configured so that "Tôi sẽ nói rõ toàn bộ sự thật" slightly exceeds or wraps
    wrapped = wrap_single_line(sentence, 600.0, 50.0)
    if len(wrapped) >= 2:
        # Last line should have at least 2 words (not an orphan single word)
        assert len(wrapped[-1].split(" ")) >= 2


def test_multiline_subtitles_expand_upward_anchored_at_bottom():
    from app.pipeline.subtitles import Cue, to_ass

    cues = [
        Cue(1, 0, 1000, "Single line"),
        Cue(2, 1000, 2000, "First line\nSecond line"),
    ]
    ass = to_ass(cues, "Arial", {"margin_v": 60}, video_width=720, video_height=1280)

    # Styles must use bottom-center alignment (Alignment=2) with MarginV anchored to bottom margin
    assert ",1,3.0,1.5,2,50,50,58,1" in ass
    assert "Style: Backdrop,Arial,61,&HFF000000,&H000000FF,&H99000000,&H99000000,1,0,0,0,100,100,0,0,3,24,0,2,50,50,58,1" in ass










