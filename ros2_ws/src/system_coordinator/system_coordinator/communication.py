"""모듈 사이 메시지 전달 통로.

담당: 1번(통합). 지금은 한 프로세스 안에서 주고받는 :class:`LocalChannel`만
있고, 실제 장비 연결 단계에서 ROS2(``ros2_ws/src/project_interfaces``)나 소켓 구현을
같은 인터페이스로 추가한다. 보내는 값은 항상 ``common.messages``의 dataclass다.
"""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Callable, Protocol

Handler = Callable[[Any], None]


class Channel(Protocol):
    """송수신 통로가 지켜야 할 최소 규격."""

    def publish(self, topic: str, message: Any) -> None: ...

    def subscribe(self, topic: str, handler: Handler) -> None: ...


class LocalChannel:
    """같은 프로세스 안에서 동작하는 통로.

    실제 로봇이 없어도 통합 흐름을 시험할 수 있게 먼저 쓴다. 구독자가 없으면
    메시지를 큐에 쌓아 두므로 테스트에서 꺼내 확인할 수 있다.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self._pending: dict[str, deque[Any]] = defaultdict(deque)

    def publish(self, topic: str, message: Any) -> None:
        handlers = self._handlers.get(topic)
        if not handlers:
            self._pending[topic].append(message)
            return
        for handler in handlers:
            handler(message)

    def subscribe(self, topic: str, handler: Handler) -> None:
        self._handlers[topic].append(handler)
        # 구독 전에 도착한 메시지를 흘리지 않는다.
        queued = self._pending.pop(topic, deque())
        while queued:
            handler(queued.popleft())

    def pending(self, topic: str) -> list[Any]:
        """아직 아무도 받아가지 않은 메시지 목록."""
        return list(self._pending.get(topic, ()))


# 통합 제어기가 쓰는 토픽 이름. 문자열을 각자 적지 않도록 여기서만 정한다.
TOPIC_INSPECTION = "inspection/result"
TOPIC_ROBOT_STATUS = "robot/status"
TOPIC_TARGET_POSITION = "robot/target_position"
