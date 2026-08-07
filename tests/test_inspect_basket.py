from common.constants import RobotState
from vision_inspection.class_scheme import ClassScheme
from vision_inspection.inspection_logic import (
    count_detections,
    judge,
    verdict_reason,
)

# 설정 파일 내용에 흔들리지 않도록 판정 테스트는 규칙과 기준 수량을 명시한다.
# 체계 B: 공 한 클래스 + 결함을 공 위에 겹쳐 표시.
SCHEME_B = ClassScheme(
    ball_names=("ball",),
    defect_names=("defect",),
    count_defects_as_balls=False,
)
# 팀이 정한 운영 체계: 공은 ball, 오투입은 others 하나로 묶음.
SCHEME_OTHERS = ClassScheme(
    ball_names=("ball",),
    defect_names=(),
    foreign_names=("others",),
)


def test_counts_balls_and_defects() -> None:
    scheme = ClassScheme(ball_names=("ball",), defect_names=("defect",))

    result = count_detections(["ball", "ball", "defect"], scheme, None)

    assert result.total_count == 3
    assert result.defect_count == 1
    assert result.result is RobotState.REJECT


def test_unknown_classes_are_ignored() -> None:
    """바구니나 사람처럼 규칙에 없는 클래스는 개수에 섞이면 안 된다."""
    result = count_detections(["ball", "basket", "person"], SCHEME_OTHERS, None)

    assert result.total_count == 1
    assert result.defect_count == 0
    assert result.result is RobotState.PASS


def test_empty_basket_passes_when_count_not_checked() -> None:
    result = count_detections([], SCHEME_OTHERS, None)

    assert result.to_dict() == {
        "total_count": 0,
        "defect_count": 0,
        "result": "PASS",
    }


# ── 오투입(others) ──────────────────────────────────────────────────


def test_foreign_object_rejects() -> None:
    """공 개수가 맞아도 공 아닌 물건이 있으면 REJECT."""
    result = count_detections(["ball", "others"], SCHEME_OTHERS, 1)

    assert result.total_count == 1
    assert result.defect_count == 1
    assert result.result is RobotState.REJECT


def test_foreign_object_is_not_counted_as_ball() -> None:
    """오투입은 공이 아니므로 공 개수를 부풀리면 안 된다."""
    result = count_detections(["ball", "others", "others"], SCHEME_OTHERS, None)

    assert result.total_count == 1
    assert result.defect_count == 2


def test_empty_foreign_names_disables_the_check() -> None:
    """오투입 라벨을 안 정한 팀은 이 검사가 꺼진 채로 돌아야 한다."""
    scheme = ClassScheme(ball_names=("ball",), defect_names=(), foreign_names=())

    result = count_detections(["ball", "others"], scheme, 1)

    assert result.defect_count == 0
    assert result.result is RobotState.PASS


def test_foreign_reason_mentions_contamination() -> None:
    result = count_detections(["ball", "others"], SCHEME_OTHERS, 1)

    assert "이물질" in verdict_reason(result, 1)


def test_defect_not_counted_as_ball_in_scheme_b() -> None:
    """결함 박스가 공 위에 겹쳐 잡히는 체계에서는 개수를 이중으로 세면 안 된다."""
    result = count_detections(["ball", "ball", "defect"], SCHEME_B)

    assert result.total_count == 2
    assert result.defect_count == 1


def test_ok_ng_scheme_counts_defective_ball_as_ball() -> None:
    """정상/불량을 라벨로 나눈 체계에서는 불량도 공 한 개로 세야 개수가 맞는다."""
    scheme = ClassScheme(
        ball_names=("ball_ok",),
        defect_names=("ball_ng",),
        count_defects_as_balls=True,
    )

    result = count_detections(["ball_ok", "ball_ok", "ball_ng"], scheme, 3)

    assert result.total_count == 3
    assert result.defect_count == 1
    assert result.result is RobotState.REJECT


def test_count_shortfall_rejects_even_without_defects() -> None:
    """목표 3번의 핵심: 결함이 없어도 개수가 모자라면 REJECT다."""
    result = judge(total_count=2, defect_count=0, target_count=3)

    assert result.result is RobotState.REJECT


def test_count_overflow_rejects() -> None:
    result = judge(total_count=4, defect_count=0, target_count=3)

    assert result.result is RobotState.REJECT


def test_exact_count_without_defect_passes() -> None:
    result = judge(total_count=3, defect_count=0, target_count=3)

    assert result.result is RobotState.PASS
    assert result.is_pass


def test_target_count_none_checks_defects_only() -> None:
    """기준 수량을 주지 않으면 개수는 보지 않는다."""
    assert judge(2, 0, None).result is RobotState.PASS
    assert judge(2, 1, None).result is RobotState.REJECT


def test_defect_rejects_even_when_count_matches() -> None:
    result = judge(total_count=3, defect_count=1, target_count=3)

    assert result.result is RobotState.REJECT


def test_count_detections_applies_target_count() -> None:
    """집계 경로에서도 기준 수량이 판정에 반영되어야 한다."""
    result = count_detections(["ball", "ball"], SCHEME_B, target_count=3)

    assert result.defect_count == 0
    assert result.result is RobotState.REJECT


def test_verdict_reason_reports_count_gap() -> None:
    """기대 개수는 InspectionResult에 실리지 않으므로 이유 문자열로 알린다."""
    result = judge(2, 0, 3)

    reason = verdict_reason(result, target_count=3)

    assert "기준 3" in reason
    assert "검출 2" in reason


def test_verdict_reason_reports_both_causes() -> None:
    reason = verdict_reason(judge(2, 1, 3), target_count=3)

    assert "개수 불일치" in reason
    assert "불량/이물질 1개" in reason


def test_verdict_reason_for_pass() -> None:
    reason = verdict_reason(judge(3, 0, 3), target_count=3)

    assert "결함 없음" in reason
