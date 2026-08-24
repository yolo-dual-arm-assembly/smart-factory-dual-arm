"""로봇팔 한 대의 상태를 읽기 전용으로 감시한다.

대시보드는 팔을 조작하지 않고 보기만 한다. 그래서 이 감시자는 포트를 열어
관절 위치만 주기적으로 읽고, **토크는 한 번도 켜지 않는다.** 토크를 켠 적이
없으므로 :meth:`release`가 연결을 끊어도 팔이 자세를 잃고 떨어지지 않는다.

시리얼 포트는 배타 자원이라 감시자가 포트를 쥔 채로는 교시 창이나 비전
실행기가 같은 팔을 열지 못한다. 그래서 도구를 띄우기 전에 :meth:`release`로
포트를 내주고, 도구가 끝나면 :meth:`acquire`로 되찾는다.

Tk는 스레드 안전하지 않으므로 이 클래스는 위젯을 만지지 않는다. 최신 상태를
:meth:`snapshot`으로 꺼내 가고, 화면 갱신은 메인 스레드의 ``after`` 폴링이
담당한다.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

from common.constants import RobotState
from common.omx_controller import OmxConfig, OmxController, fk_5dof
from common.serial_ports import serial_permission_guidance

# 관절각은 사람이 보는 값이라 빠를 필요가 없다. 시리얼 통신이 교시·비전 작업과
# 겹칠 때 서로 방해하지 않도록 넉넉히 둔다.
POLL_INTERVAL_SEC = 0.5
# 연결이 실패해도 계속 재시도하되, 포트가 없는 상태에서 매초 두드리지 않는다.
RECONNECT_INTERVAL_SEC = 3.0
# 포트는 열리지만 모터가 없는 경우(잘못 잡은 포트, 전원 꺼짐)에는 아무리 다시
# 붙어도 결과가 같다. 실패가 이어지면 간격을 늘려 로그와 시리얼 트래픽을 줄인다.
MAX_RECONNECT_INTERVAL_SEC = 30.0
RECONNECT_BACKOFF = 2.0


@dataclass(frozen=True)
class ArmSnapshot:
    """어느 시점의 팔 상태. 화면에 그대로 뿌릴 수 있는 형태다."""

    connected: bool = False
    port: str | None = None
    angles: tuple[float, ...] = ()
    position: tuple[float, float, float] | None = None
    state: RobotState = RobotState.IDLE
    # 연결 실패 이유나 권한 안내처럼 사람이 읽을 설명.
    message: str = ""
    released: bool = False

    @property
    def status_text(self) -> str:
        if self.released:
            return "다른 도구가 사용 중"
        if self.port is None:
            return "포트 없음"
        if not self.connected:
            return self.message or "연결 안 됨"
        return str(self.state)


class ArmMonitor:
    """팔 한 대의 연결과 상태 폴링을 담당한다."""

    def __init__(self, role_key: str, port: str | None) -> None:
        self.role_key = role_key
        self._port = port
        self._controller: OmxController | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._snapshot = ArmSnapshot(port=port)
        # release() 중에는 워커가 포트를 다시 열지 않아야 한다.
        self._released = False

    # ------------------------------------------------------------------ 수명주기

    def start(self) -> None:
        """감시 스레드를 띄운다. 포트가 없으면 상태만 남기고 아무 일도 하지 않는다."""
        if self._port is None:
            self._store(ArmSnapshot(port=None, message="배정된 포트가 없습니다"))
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._worker, name=f"arm-{self.role_key}", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        """감시를 끝내고 포트를 닫는다. 종료 경로에서 부른다."""
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None
        self._disconnect()

    # ------------------------------------------------------------------ 소유권 인계

    def release(self) -> None:
        """포트를 도구에 넘긴다. 감시는 멈추지만 객체는 살아 있다."""
        with self._lock:
            if self._released:
                return
            self._released = True
        self.stop()
        self._store(
            ArmSnapshot(port=self._port, released=True, message="다른 도구가 사용 중")
        )

    def acquire(self) -> None:
        """도구가 끝난 뒤 포트를 되찾고 감시를 재개한다."""
        with self._lock:
            if not self._released:
                return
            self._released = False
        self._stop_event.clear()
        self._store(ArmSnapshot(port=self._port, message="다시 연결하는 중..."))
        self.start()

    @property
    def is_released(self) -> bool:
        with self._lock:
            return self._released

    @property
    def port(self) -> str | None:
        return self._port

    def set_port(self, port: str | None) -> None:
        """사용자가 포트를 바꿨을 때. 감시를 다시 시작한다."""
        if port == self._port:
            return
        self.stop()
        self._port = port
        self._store(ArmSnapshot(port=port))
        if not self.is_released:
            self.start()

    # ------------------------------------------------------------------ 상태 조회

    def snapshot(self) -> ArmSnapshot:
        with self._lock:
            return self._snapshot

    def _store(self, snapshot: ArmSnapshot) -> None:
        with self._lock:
            self._snapshot = snapshot

    # ------------------------------------------------------------------ 워커

    def _worker(self) -> None:
        retry_delay = RECONNECT_INTERVAL_SEC
        while not self._stop_event.is_set():
            if self._controller is None and not self._connect():
                # 연결 실패 사유는 _connect가 이미 상태에 남겼다.
                if self._stop_event.wait(retry_delay):
                    break
                retry_delay = self._next_delay(retry_delay)
                continue
            if not self._read_once():
                # 포트는 열렸지만 모터가 응답하지 않는 상태다. 다시 붙어도
                # 같은 결과이므로 간격을 늘려 가며 재시도한다.
                self._disconnect()
                if self._stop_event.wait(retry_delay):
                    break
                retry_delay = self._next_delay(retry_delay)
                continue
            # 한 번이라도 제대로 읽었으면 간격을 원래대로 되돌린다.
            retry_delay = RECONNECT_INTERVAL_SEC
            if self._stop_event.wait(POLL_INTERVAL_SEC):
                break
        self._disconnect()

    @staticmethod
    def _next_delay(delay: float) -> float:
        return min(delay * RECONNECT_BACKOFF, MAX_RECONNECT_INTERVAL_SEC)

    def _connect(self) -> bool:
        assert self._port is not None
        guidance = serial_permission_guidance(self._port)
        if guidance is not None:
            self._store(
                ArmSnapshot(port=self._port, message="시리얼 포트 권한 없음")
            )
            print(f"[arm {self.role_key}] {guidance}")
            return False
        controller = OmxController(OmxConfig(port=self._port))
        try:
            # connect()는 포트를 열고 통신만 준비한다. 토크는 켜지 않는다.
            controller.connect()
        except Exception as error:
            self._store(ArmSnapshot(port=self._port, message=str(error)))
            return False
        self._controller = controller
        print(f"[arm {self.role_key}] 감시 시작: {self._port}")
        return True

    def _read_once(self) -> bool:
        controller = self._controller
        if controller is None:
            return False
        try:
            # strict=True로 읽어야 통신이 끊긴 것을 중앙값으로 덮지 않는다.
            state = controller.read_joint_state(strict=True)
        except Exception as error:
            self._store(ArmSnapshot(port=self._port, message=str(error)))
            return False

        angles = tuple(state.angles)
        try:
            position = fk_5dof(list(angles))
        except ValueError:
            # 관절 개수가 맞지 않는 등 FK가 안 되는 자세도 상태 표시는 이어 간다.
            position = None
        self._store(
            ArmSnapshot(
                connected=True,
                port=self._port,
                angles=angles,
                position=position,
                state=RobotState.IDLE,
            )
        )
        return True

    def _disconnect(self) -> None:
        controller, self._controller = self._controller, None
        if controller is None:
            return
        try:
            controller.disconnect()
        except Exception:
            # 이미 뽑힌 포트를 닫는 실패로 종료 흐름을 막지 않는다.
            pass
