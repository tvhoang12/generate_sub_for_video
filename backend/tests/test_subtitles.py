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
    assert "Style: Default,Noto Sans Khmer,25," in ass
    assert r"Dialogue: 1,0:01:01.23,1:02:03.45,Default,,0,0,0,,ព្រមទាំង \{x\}\Nline two" in ass


def test_ass_border_and_shadow_configs():
    from app.pipeline.subtitles import to_ass

    cues = [Cue(1, 1000, 2000, "Sample")]

    # Default has border outline=1.6 and shadow=0.5 with black shadow &H80000000
    ass_default = to_ass(cues, "Arial")
    assert ",1,1.6,0.5,2," in ass_default
    assert ",&H80000000,1,0," in ass_default

    # Disabling border sets outline to 0.0
    ass_no_border = to_ass(cues, "Arial", {"has_border": False})
    assert ",1,0.0,0.5,2," in ass_no_border

    # Disabling shadow sets shadow to 0.0
    ass_no_shadow = to_ass(cues, "Arial", {"has_shadow": False})
    assert ",1,1.6,0.0,2," in ass_no_shadow

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
    assert ",3,3,0,2," in ass_custom


