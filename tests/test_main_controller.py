from common.constants import RobotId, RobotState
from common.messages import InspectionResult, RobotStatus
from system_coordinator.communication import (
    TOPIC_INSPECTION,
    TOPIC_ROBOT_STATUS,
    LocalChannel,
)
from system_coordinator.main_controller import MainController, mock_cycle


def loading_ok() -> RobotStatus:
    return RobotStatus(RobotId.LOADING, RobotState.LOADING_COMPLETE)


def sorting_ok(_result: InspectionResult) -> RobotStatus:
    return RobotStatus(RobotId.SORTING, RobotState.COMPLETE)


def test_mock_cycle_completes_without_hardware() -> None:
    """장비가 없어도 통합 담당자가 흐름을 먼저 돌려볼 수 있어야 한다."""
    assert mock_cycle() is RobotState.COMPLETE


def test_cycle_publishes_inspection_and_status() -> None:
    channel = LocalChannel()
    controller = MainController(
        load_basket=loading_ok,
        inspect=lambda: InspectionResult.from_counts(3, 0),
        sort_basket=sorting_ok,
        channel=channel,
    )

    controller.run_cycle()

    assert channel.pending(TOPIC_INSPECTION) == [
        InspectionResult.from_counts(3, 0)
    ]
    assert [status.state for status in channel.pending(TOPIC_ROBOT_STATUS)] == [
        RobotState.LOADING_COMPLETE,
        RobotState.COMPLETE,
    ]


def test_reject_result_still_reaches_sorting() -> None:
    controller = MainController(
        load_basket=loading_ok,
        inspect=lambda: InspectionResult.from_counts(3, 1),
        sort_basket=sorting_ok,
    )

    assert controller.run_cycle() is RobotState.COMPLETE
    assert RobotState.REJECT in controller.machine.history


def test_failed_loading_stops_the_cycle_in_error() -> None:
    controller = MainController(
        load_basket=lambda: RobotStatus(
            RobotId.LOADING, RobotState.ERROR, success=False, message="그리퍼 실패"
        ),
        inspect=lambda: InspectionResult.from_counts(3, 0),
        sort_basket=sorting_ok,
    )

    assert controller.run_cycle() is RobotState.ERROR
    assert RobotState.INSPECTING not in controller.machine.history


def test_subscriber_receives_messages_published_before_subscribing() -> None:
    channel = LocalChannel()
    channel.publish(TOPIC_INSPECTION, "early")
    received: list[str] = []

    channel.subscribe(TOPIC_INSPECTION, received.append)

    assert received == ["early"]
    assert channel.pending(TOPIC_INSPECTION) == []
