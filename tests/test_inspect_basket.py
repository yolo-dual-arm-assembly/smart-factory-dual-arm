from common.constants import RobotState
from vision_inspection.inspection_logic import count_detections


def test_counts_balls_and_defects() -> None:
    result = count_detections(["ball", "ball", "defect"])

    assert result.total_count == 3
    assert result.defect_count == 1
    assert result.result is RobotState.REJECT


def test_unknown_classes_are_ignored() -> None:
    """바구니나 사람 같은 다른 클래스가 공 개수에 섞이면 안 된다."""
    result = count_detections(["ball", "basket", "person"])

    assert result.total_count == 1
    assert result.defect_count == 0
    assert result.result is RobotState.PASS


def test_empty_basket_passes_with_zero_count() -> None:
    result = count_detections([])

    assert result.to_dict() == {
        "total_count": 0,
        "defect_count": 0,
        "result": "PASS",
    }
