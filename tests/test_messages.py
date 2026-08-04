from common.constants import RobotId, RobotState
from common.messages import InspectionResult, RobotPosition, RobotStatus


def test_inspection_result_decides_pass_in_one_place() -> None:
    assert InspectionResult.from_counts(3, 0).result is RobotState.PASS
    assert InspectionResult.from_counts(3, 1).result is RobotState.REJECT


def test_inspection_result_dict_matches_agreed_protocol() -> None:
    """docs/communication_protocol.md에 적힌 모양 그대로 나가야 한다."""
    result = InspectionResult.from_counts(total_count=3, defect_count=0)

    assert result.to_dict() == {
        "total_count": 3,
        "defect_count": 0,
        "result": "PASS",
    }


def test_robot_position_dict_uses_meters_keys() -> None:
    assert RobotPosition(0.215, -0.083, 0.045).to_dict() == {
        "x": 0.215,
        "y": -0.083,
        "z": 0.045,
    }


def test_robot_status_dict_keeps_state_as_plain_string() -> None:
    status = RobotStatus(RobotId.LOADING, RobotState.LOADING_COMPLETE)

    assert status.to_dict() == {
        "robot_id": "OMX_1",
        "state": "LOADING_COMPLETE",
        "success": True,
        "message": "",
    }
