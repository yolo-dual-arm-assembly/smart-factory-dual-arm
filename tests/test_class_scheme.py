from pathlib import Path

from vision_inspection.class_scheme import (
    CLASS_SCHEME_PATH,
    DEFAULT_CLASS_SCHEME,
    ClassScheme,
    load_class_scheme,
    load_target_count,
    warn_on_mismatch,
)


def write_scheme(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "class_scheme.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_shipped_config_is_loadable() -> None:
    """레포에 들어 있는 설정이 실제로 읽히는지 확인한다.

    defect_names는 비어 있는 게 정상이다(공 자체의 불량은 라벨링하지 않기로
    했다). ball_names가 비면 아무것도 못 세므로 그것만 확인한다.
    """
    scheme = load_class_scheme(CLASS_SCHEME_PATH)

    assert scheme.ball_names


def test_loads_names_and_flag(tmp_path: Path) -> None:
    path = write_scheme(
        tmp_path,
        "ball_names: [ball_ok]\n"
        "defect_names: [ball_ng]\n"
        "count_defects_as_balls: false\n",
    )

    scheme = load_class_scheme(path)

    assert scheme.ball_names == ("ball_ok",)
    assert scheme.defect_names == ("ball_ng",)
    assert scheme.count_defects_as_balls is False


def test_single_name_string_is_not_split_into_letters(tmp_path: Path) -> None:
    """`ball_names: ball`처럼 목록을 빠뜨려도 글자 단위로 쪼개지면 안 된다."""
    path = write_scheme(tmp_path, "ball_names: ball\n")

    scheme = load_class_scheme(path)

    assert scheme.ball_names == ("ball",)


def test_missing_file_falls_back_to_default(tmp_path: Path) -> None:
    """설정이 없다고 검사가 멈추면 안 된다."""
    scheme = load_class_scheme(tmp_path / "없는파일.yaml")

    assert scheme == DEFAULT_CLASS_SCHEME


def test_broken_yaml_falls_back_to_default(tmp_path: Path) -> None:
    path = write_scheme(tmp_path, "ball_names: [ball\n  defect_names: :\n")

    assert load_class_scheme(path) == DEFAULT_CLASS_SCHEME


def test_non_mapping_falls_back_to_default(tmp_path: Path) -> None:
    path = write_scheme(tmp_path, "- ball\n- defect\n")

    assert load_class_scheme(path) == DEFAULT_CLASS_SCHEME


def test_explicit_empty_list_stays_empty(tmp_path: Path) -> None:
    """'결함 클래스는 아직 없다'는 정당한 설정이라 기본값으로 되살리면 안 된다."""
    path = write_scheme(tmp_path, "ball_names: [ball]\ndefect_names: []\n")

    scheme = load_class_scheme(path)

    assert scheme.defect_names == ()
    assert scheme.ball_names == ("ball",)


def test_absent_key_uses_default(tmp_path: Path) -> None:
    """빈 목록과 달리, 항목을 아예 안 적으면 기본값을 쓴다."""
    path = write_scheme(tmp_path, "ball_names: [ball]\n")

    assert load_class_scheme(path).defect_names == DEFAULT_CLASS_SCHEME.defect_names


def test_no_defect_classes_never_reports_defects(tmp_path: Path) -> None:
    path = write_scheme(tmp_path, "ball_names: [ball]\ndefect_names: []\n")
    scheme = load_class_scheme(path)

    assert scheme.is_defect("defect") is False
    assert scheme.is_ball("ball") is True


def test_defect_is_ball_only_when_flag_set() -> None:
    counted = ClassScheme(("ball",), ("defect",), count_defects_as_balls=True)
    separate = ClassScheme(("ball",), ("defect",), count_defects_as_balls=False)

    assert counted.is_ball("defect") is True
    assert separate.is_ball("defect") is False
    assert counted.is_defect("defect") is separate.is_defect("defect") is True


def test_known_names_has_no_duplicates() -> None:
    scheme = ClassScheme(("ball", "defect"), ("defect",))

    assert scheme.known_names == ("ball", "defect")


def test_unknown_names_detects_scheme_mismatch() -> None:
    """설정 이름이 모델에 없으면 개수가 늘 0이 되어 항상 REJECT가 난다."""
    scheme = ClassScheme(("ball",), ("defect",))

    assert scheme.unknown_names(["ball_ok", "ball_ng"]) == ("ball", "defect")
    assert scheme.unknown_names(["ball", "defect", "basket"]) == ()


def test_warn_on_mismatch_returns_unknown_names() -> None:
    scheme = ClassScheme(("ball",), ("defect",))

    assert warn_on_mismatch(scheme, ["ball"]) == ("defect",)
    assert warn_on_mismatch(scheme, ["ball", "defect"]) == ()


# ── 오투입(foreign) ─────────────────────────────────────────────────


def test_loads_foreign_names(tmp_path: Path) -> None:
    path = write_scheme(
        tmp_path, "ball_names: [ball]\nforeign_names: [others]\n"
    )

    assert load_class_scheme(path).foreign_names == ("others",)


def test_foreign_names_default_to_empty() -> None:
    """오투입 라벨을 안 정했으면 검사가 꺼진 채여야 한다."""
    assert DEFAULT_CLASS_SCHEME.foreign_names == ()


def test_foreign_is_neither_ball_nor_defect() -> None:
    scheme = ClassScheme(("ball",), ("defect",), ("others",))

    assert scheme.is_foreign("others") is True
    assert scheme.is_ball("others") is False
    assert scheme.is_defect("others") is False


def test_foreign_wins_when_a_name_is_listed_twice() -> None:
    """같은 이름을 공에도 오투입에도 적으면 오투입이 이긴다."""
    scheme = ClassScheme(("ball",), (), ("ball",))

    assert scheme.is_foreign("ball") is True
    assert scheme.is_ball("ball") is False


def test_foreign_names_are_checked_against_the_model() -> None:
    scheme = ClassScheme(("ball",), (), ("others",))

    assert scheme.unknown_names(["ball"]) == ("others",)
    assert scheme.unknown_names(["ball", "others"]) == ()


# ── 기준 수량 ───────────────────────────────────────────────────────


def test_loads_target_count(tmp_path: Path) -> None:
    path = write_scheme(tmp_path, "target_count: 3\nball_names: [ball]\n")

    assert load_target_count(path) == 3


def test_null_target_count_disables_the_check(tmp_path: Path) -> None:
    path = write_scheme(tmp_path, "target_count: null\nball_names: [ball]\n")

    assert load_target_count(path) is None


def test_absent_target_count_is_none(tmp_path: Path) -> None:
    path = write_scheme(tmp_path, "ball_names: [ball]\n")

    assert load_target_count(path) is None


def test_non_integer_target_count_disables_the_check(tmp_path: Path) -> None:
    """오타로 개수 검사가 터지느니 꺼지는 편이 낫다."""
    path = write_scheme(tmp_path, "target_count: 세개\n")

    assert load_target_count(path) is None


def test_missing_file_target_count_is_none(tmp_path: Path) -> None:
    assert load_target_count(tmp_path / "없는파일.yaml") is None


def test_shipped_config_has_a_target_count() -> None:
    """운영 설정에 기준 수량이 들어 있어야 GUI가 개수 판정을 한다."""
    assert load_target_count(CLASS_SCHEME_PATH) is not None
