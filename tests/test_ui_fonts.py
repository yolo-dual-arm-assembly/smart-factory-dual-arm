from system_monitor.ui.ui_fonts import (
    KOREAN_FONT_CANDIDATES,
    KOREAN_MONO_FONT_CANDIDATES,
    choose_font_family,
)


def test_choose_font_family_uses_candidate_priority() -> None:
    available = ("NanumGothic", "Noto Sans CJK KR", "DejaVu Sans")

    chosen = choose_font_family(
        available,
        ("Noto Sans CJK KR", "NanumGothic"),
        fallback="DejaVu Sans",
    )

    assert chosen == "Noto Sans CJK KR"


def test_choose_font_family_is_case_insensitive() -> None:
    chosen = choose_font_family(
        ("NanumGothicCoding",),
        ("nanumgothiccoding",),
        fallback="monospace",
    )

    assert chosen == "NanumGothicCoding"


def test_choose_font_family_uses_fallback() -> None:
    chosen = choose_font_family(
        ("DejaVu Sans",),
        ("Noto Sans CJK KR",),
        fallback="DejaVu Sans",
    )

    assert chosen == "DejaVu Sans"


def test_windows_korean_fonts_are_candidates() -> None:
    """윈도우에 리눅스 한글 글꼴이 없어도 한글 글꼴을 고를 수 있어야 한다."""
    windows_families = ("맑은 고딕", "굴림", "굴림체", "Consolas", "D2Coding")

    ui_family = choose_font_family(
        windows_families, KOREAN_FONT_CANDIDATES, fallback="시스템 기본"
    )
    mono_family = choose_font_family(
        windows_families, KOREAN_MONO_FONT_CANDIDATES, fallback="시스템 기본"
    )

    assert ui_family == "맑은 고딕"
    assert mono_family == "D2Coding"


def test_linux_korean_fonts_keep_priority() -> None:
    """리눅스 환경의 기존 선택 결과는 그대로 유지되어야 한다."""
    linux_families = (
        "NanumGothic",
        "Noto Sans CJK KR",
        "Noto Sans Mono CJK KR",
        "DejaVu Sans",
    )

    ui_family = choose_font_family(
        linux_families, KOREAN_FONT_CANDIDATES, fallback="시스템 기본"
    )
    mono_family = choose_font_family(
        linux_families, KOREAN_MONO_FONT_CANDIDATES, fallback="시스템 기본"
    )

    assert ui_family == "Noto Sans CJK KR"
    assert mono_family == "Noto Sans Mono CJK KR"
