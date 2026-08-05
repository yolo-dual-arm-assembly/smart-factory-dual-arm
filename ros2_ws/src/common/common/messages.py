"""모듈 사이에 오가는 데이터 규격.

비전·좌표 변환·로봇 담당이 서로의 코드를 읽지 않고도 연결할 수 있게, 주고받는
값의 모양을 여기서만 정한다. 규격 설명은 ``docs/communication_protocol.md``에
있고 이 파일이 그 문서의 실행 가능한 정의다.

dict 대신 dataclass를 쓰는 이유는 ``result["reslut"]`` 같은 오타와 빠진 키가
통합 시점이 아니라 만든 사람 자리에서 바로 드러나기 때문이다. 다른 프로세스나
ROS2 노드로 보낼 때는 :meth:`to_dict`로 변환한다.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from common.constants import RobotState


@dataclass(frozen=True)
class InspectionResult:
    """비전 검사 결과. ``vision/inspect_basket.py``가 만든다."""

    total_count: int
    defect_count: int
    result: RobotState  # PASS 또는 REJECT

    @property
    def is_pass(self) -> bool:
        return self.result is RobotState.PASS

    @property
    def normal_count(self) -> int:
        """정상 개수. ``InspectBasket.srv``의 같은 이름 필드에 그대로 넣는다.

        빼기 한 번이지만 담당자마다 직접 계산하면 total과 defect의 의미가
        갈라진다. 파생값도 여기서만 만든다.
        """
        return self.total_count - self.defect_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_count": self.total_count,
            "defect_count": self.defect_count,
            "result": str(self.result),
        }

    @classmethod
    def from_counts(cls, total_count: int, defect_count: int) -> "InspectionResult":
        """개수만으로 합격 여부까지 정한다. 판정 기준을 한 곳에 둔다."""
        verdict = RobotState.PASS if defect_count == 0 else RobotState.REJECT
        return cls(total_count, defect_count, verdict)


@dataclass(frozen=True)
class RobotPosition:
    """로봇 기준 좌표(미터). ``calibration/coordinate_transform.py``가 만든다."""

    x: float
    y: float
    z: float

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass(frozen=True)
class RobotStatus:
    """로봇이 통합 제어기에 보고하는 현재 상태."""

    robot_id: str
    state: RobotState
    success: bool = True
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "robot_id": self.robot_id,
            "state": str(self.state),
            "success": self.success,
            "message": self.message,
        }
