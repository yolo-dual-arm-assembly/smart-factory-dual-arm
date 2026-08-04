"""Tkinter에서 한글을 안정적으로 표시하기 위한 글꼴 설정."""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from collections.abc import Iterable


# 운영체제마다 설치된 한글 글꼴이 다르므로 리눅스·윈도우·macOS 후보를 함께
# 나열하고, 실제로 설치된 것 중 우선순위가 가장 높은 글꼴을 고른다.
# 윈도우는 한국어 로캘에서 한글 이름("맑은 고딕"), 영문 로캘에서 영문 이름
# ("Malgun Gothic")으로 같은 글꼴을 노출하므로 두 이름을 모두 넣는다.
KOREAN_FONT_CANDIDATES = (
    "Noto Sans CJK KR",
    "NanumGothic",
    "NanumBarunGothic",
    "맑은 고딕",
    "Malgun Gothic",
    "Apple SD Gothic Neo",
    "AppleGothic",
    "돋움",
    "Dotum",
    "굴림",
    "Gulim",
)
KOREAN_MONO_FONT_CANDIDATES = (
    "Noto Sans Mono CJK KR",
    "NanumGothicCoding",
    "D2Coding",
    "Consolas",
    "Menlo",
    "굴림체",
    "GulimChe",
)
TK_UI_NAMED_FONTS = (
    "TkDefaultFont",
    "TkTextFont",
    "TkMenuFont",
    "TkHeadingFont",
    "TkCaptionFont",
    "TkSmallCaptionFont",
    "TkIconFont",
    "TkTooltipFont",
)


def choose_font_family(
    available_families: Iterable[str],
    candidates: Iterable[str],
    fallback: str,
) -> str:
    """설치된 글꼴 중 우선순위가 가장 높은 family 이름을 반환한다."""
    installed = {family.casefold(): family for family in available_families}
    for candidate in candidates:
        if candidate.casefold() in installed:
            return installed[candidate.casefold()]
    return fallback


def installed_family(root: tk.Misc, font_name: str, fallback: str) -> str:
    """named font가 현재 실제로 쓰는 family를 반환한다.

    후보 글꼴이 하나도 설치되지 않았을 때 쓸 폴백을 구하기 위한 함수다.
    설치되지 않은 이름을 폴백으로 쓰면 Tk가 조용히 임의의 글꼴로 대체해
    한글이 깨지므로, 시스템이 이미 쓰고 있는 글꼴을 폴백으로 삼는다.
    """
    try:
        return tkfont.nametofont(font_name, root=root).actual("family")
    except tk.TclError:
        return fallback


def configure_korean_fonts(root: tk.Misc) -> tuple[str, str]:
    """현재 Tk interpreter의 기본 UI/고정폭 글꼴을 한글 글꼴로 설정한다."""
    available = tkfont.families(root)
    ui_family = choose_font_family(
        available,
        KOREAN_FONT_CANDIDATES,
        fallback=installed_family(root, "TkDefaultFont", "DejaVu Sans"),
    )
    mono_family = choose_font_family(
        available,
        KOREAN_MONO_FONT_CANDIDATES,
        fallback=installed_family(root, "TkFixedFont", ui_family),
    )

    for name in TK_UI_NAMED_FONTS:
        try:
            tkfont.nametofont(name, root=root).configure(family=ui_family)
        except tk.TclError:
            # Tk 버전에 따라 일부 named font가 없을 수 있다.
            continue

    try:
        tkfont.nametofont("TkFixedFont", root=root).configure(family=mono_family)
    except tk.TclError:
        pass

    # tk.Listbox처럼 ttk가 아닌 위젯도 별도 지정 없이 named font를 사용한다.
    root.option_add("*Font", "TkDefaultFont")
    return ui_family, mono_family
