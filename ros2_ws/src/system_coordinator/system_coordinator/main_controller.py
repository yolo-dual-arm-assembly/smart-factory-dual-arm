"""전체 공정 흐름 오케스트레이션.

담당: 1번(통합). 적재 → 검사 → 분류 순서를 여기서만 정하고, 각 단계는 다른
담당자의 함수를 주입받아 호출한다. 그래서 로봇이나 YOLO가 아직 없어도 가짜
함수로 전체 흐름을 돌려볼 수 있다.

```python
controller = MainController(
    load_basket=lambda: RobotStatus("OMX_1", RobotState.LOADING_COMPLETE),
    inspect=lambda: InspectionResult.from_counts(3, 0),
    sort_basket=lambda result: RobotStatus("OMX_2", RobotState.COMPLETE),
)
controller.run_cycle()
```
"""
from __future__ import annotations

from typing import Callable

from common.constants import RobotId, RobotState
from common.logger import get_logger
from common.messages import InspectionResult, RobotStatus
from system_coordinator.communication import (
    TOPIC_INSPECTION,
    TOPIC_ROBOT_STATUS,
    Channel,
    LocalChannel,
)
from system_coordinator.state_machine import StateMachine

logger = get_logger(__name__)

LoadCallback = Callable[[], RobotStatus]
InspectCallback = Callable[[], InspectionResult]
SortCallback = Callable[[InspectionResult], RobotStatus]


class MainController:
    """한 바구니가 적재부터 분류까지 지나가는 한 사이클을 관리한다."""

    def __init__(
        self,
        load_basket: LoadCallback,
        inspect: InspectCallback,
        sort_basket: SortCallback,
        channel: Channel | None = None,
    ) -> None:
        self.load_basket = load_basket
        self.inspect = inspect
        self.sort_basket = sort_basket
        self.channel: Channel = channel or LocalChannel()
        self.machine = StateMachine()

    def run_cycle(self) -> RobotState:
        """한 사이클을 실행하고 ``COMPLETE`` 또는 ``ERROR``를 반환한다.

        성공한 이전 사이클의 ``COMPLETE``는 다음 호출을 시작할 때 ``IDLE``로
        정리한다. 반면 실패한 ``ERROR``는 운영자가 원인을 확인한 뒤
        :meth:`reset`을 명시적으로 호출해야 다시 시작할 수 있다.
        """
        if not self._prepare_cycle():
            return self.machine.state

        try:
            self.machine.move_to(RobotState.LOADING)
            loading = self.load_basket()
            self._report(loading)
            if not loading.success:
                return self.machine.fail()
            self.machine.move_to(RobotState.LOADING_COMPLETE)

            self.machine.move_to(RobotState.INSPECTING)
            inspection = self.inspect()
            self.channel.publish(TOPIC_INSPECTION, inspection)
            logger.info("검사 결과 %s", inspection.to_dict())
            self.machine.move_to(inspection.result)

            self.machine.move_to(RobotState.MOVING)
            sorting = self.sort_basket(inspection)
            self._report(sorting)
            if not sorting.success:
                return self.machine.fail()
            return self.machine.move_to(RobotState.COMPLETE)
        except Exception as error:  # 통합 루프는 한 사이클 실패로 멈추지 않는다.
            logger.exception("사이클 실패: %s", error)
            if self.machine.state is not RobotState.ERROR:
                self.machine.fail()
            return self.machine.state

    def reset(self) -> RobotState:
        """완료 또는 오류 상태를 확인한 뒤 다음 사이클을 위해 대기로 돌린다."""
        return self.machine.reset()

    def _prepare_cycle(self) -> bool:
        """새 사이클을 시작할 수 있는 상태인지 확인하고 성공 완료를 정리한다."""
        if self.machine.state is RobotState.COMPLETE:
            self.machine.reset()
        if self.machine.state is RobotState.ERROR:
            logger.error("오류 상태에서는 reset() 후 새 사이클을 시작해야 합니다.")
            return False
        if self.machine.state is not RobotState.IDLE:
            logger.error(
                "사이클 실행 중 새 사이클을 시작할 수 없습니다: %s",
                self.machine.state,
            )
            self.machine.fail()
            return False
        return True

    def _report(self, status: RobotStatus) -> None:
        self.channel.publish(TOPIC_ROBOT_STATUS, status)
        logger.info("%s 상태 %s", status.robot_id, status.state)


def mock_cycle() -> RobotState:
    """장비 없이 흐름만 확인하는 실행 예시."""
    return MainController(
        load_basket=lambda: RobotStatus(RobotId.LOADING, RobotState.LOADING_COMPLETE),
        inspect=lambda: InspectionResult.from_counts(total_count=3, defect_count=0),
        sort_basket=lambda _result: RobotStatus(
            RobotId.SORTING, RobotState.COMPLETE
        ),
    ).run_cycle()


if __name__ == "__main__":
    print(mock_cycle())
