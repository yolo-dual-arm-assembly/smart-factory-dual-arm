"""ROBOTIS OMX 로봇팔 제어 모듈 (DYNAMIXEL SDK 직접 제어).

연결: USB-C → 리눅스 /dev/ttyACM0 · 윈도우 COMx, Protocol 2.0,
Baudrate 1,000,000

사용 예::

    ctrl = OmxController()
    ctrl.connect()
    ctrl.home()
    ctrl.move_xyz(0.20, 0.0, 0.10)   # 로봇 베이스 기준 XYZ (미터)
    ctrl.gripper_open()
    ctrl.disconnect()
"""
from __future__ import annotations

import math
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from numbers import Real
from pathlib import Path
from typing import Callable, Optional

from common.serial_ports import default_omx_port, serial_permission_guidance

try:
    from dynamixel_sdk import (
        COMM_SUCCESS,
        PacketHandler,
        PortHandler,
    )
    _DXL_AVAILABLE = True
except ImportError:
    _DXL_AVAILABLE = False


class OmxCancelled(RuntimeError):
    """사용자가 중단을 요청해 동작이 끊겼다."""


class OmxCommunicationError(RuntimeError):
    """모터가 응답하지 않아 동작을 이어 갈 수 없다."""


# 응답 없는 포트에 붙으면 쓰기 한 번마다 SDK 패킷 타임아웃(약 34ms)을 꽉 채운다.
# 몇 번 연속 실패하면 남은 웨이포인트를 끝까지 두드려 봐야 결과가 같으므로,
# 수백 줄을 찍으며 수십 초를 버리는 대신 그 자리에서 예외로 끊는다.
MAX_CONSECUTIVE_WRITE_FAILURES = 5


# ---------------------------------------------------------------------------
# DYNAMIXEL Protocol 2.0 제어 테이블 주소 (X-Series 공통)
# ---------------------------------------------------------------------------
ADDR_OPERATING_MODE   = 11    # 1 byte
ADDR_TORQUE_ENABLE    = 64    # 1 byte
ADDR_GOAL_POSITION    = 116   # 4 bytes
ADDR_PRESENT_POSITION = 132   # 4 bytes
ADDR_PROFILE_VELOCITY = 112   # 4 bytes  (속도 프로파일)

# 운용 모드
MODE_POSITION         = 3     # 위치 제어
MODE_CURRENT_POSITION = 5     # 전류 기반 위치 제어 (그리퍼용)

# DYNAMIXEL XL430 기준 위치값 범위
DXL_MINIMUM_POSITION  = 0
DXL_MAXIMUM_POSITION  = 4095
DXL_CENTER_POSITION   = 2048

# ---------------------------------------------------------------------------
# OMX-F 공식 URDF 링크 파라미터 (미터)
# ---------------------------------------------------------------------------
# joint1 원점은 로봇 베이스 중심에서 X=-11.25mm이고, joint2(어깨)는
# 바닥에서 97.5mm 높이에 있다. 어깨→팔꿈치 링크는 수평이 아니라
# (X=41.5mm, Z=113.15mm)로 기울어진 구조다.
OMX_BASE_X = -0.01125
OMX_L0 = 0.034 + 0.0635
OMX_LINK1_X = 0.0415
OMX_LINK1_Z = 0.11315
OMX_L1 = math.hypot(OMX_LINK1_X, OMX_LINK1_Z)
OMX_LINK1_ANGLE = math.atan2(OMX_LINK1_Z, OMX_LINK1_X)
OMX_L2 = 0.162
OMX_L3 = 0.0287 + 0.09193
OMX_TOOL_PITCH = math.pi / 2  # 그리퍼 끝이 테이블 아래 방향을 향함

# OMX 관절 한계값 (라디안)
JOINT_LIMITS: tuple[tuple[float, float], ...] = (
    (-math.pi, math.pi),                 # Joint 1 (베이스)
    (-math.pi * 2 / 3, math.pi / 2),     # Joint 2 (어깨, -120°~90°)
    (-math.pi / 2, math.pi * 2 / 3),     # Joint 3 (팔꿈치, -90°~120°)
    (-math.pi * 3 / 4, math.pi * 3 / 4), # Joint 4 (손목, -135°~135°)
    (-math.pi, math.pi),                 # Joint 5 (손목 롤)
)

# 홈 포즈 관절각 (라디안) — 팔을 위로 세운 초기 자세
# 홈 포즈: 사용자 지정 초기 자세 (J1:0°, J2:-120°, J3:100°, J4:90°, J5:0°)
HOME_ANGLES = [
    0.0,
    math.radians(-120.0),
    math.radians(100.0),
    math.radians(90.0),
    0.0,
]

# 그리퍼 위치값 (DYNAMIXEL 단위)
GRIPPER_OPEN_POS  = 2700   # 완전 열린 상태 (실기 보정값)
GRIPPER_CLOSE_POS = 1900   # 완전 닫힌 상태 (실기 보정값)

# 이동 속도 프로파일 (X-Series: 1 unit = 약 0.229 rpm, 0 = 속도 제한 없음)
# 홈 포즈를 포함한 GUI 조작이 갑자기 움직이지 않도록 약 6.9 rpm으로 제한한다.
PROFILE_VELOCITY  = 30
HOME_MOVE_DURATION = 6.0
HOME_UPDATE_INTERVAL = 0.05


# ---------------------------------------------------------------------------
# 안전 검증
# ---------------------------------------------------------------------------
def validate_joint_angles(
    angles: Sequence[float],
    *,
    label: str = "목표 관절각",
) -> list[float]:
    """5개 관절각이 유한한 수이고 소프트 리밋 안인지 검증한다.

    검증된 값을 ``float`` 리스트로 반환하므로 JSON에서 읽은 숫자도 이후
    동작에서 같은 표현을 사용한다. 이 함수는 하드웨어 접근 없이 호출할 수 있어,
    전체 동작 계획을 모터 연결 전에 사전 검증하는 데도 사용한다.
    """
    if isinstance(angles, (str, bytes)) or not isinstance(angles, Sequence):
        raise ValueError(
            f"{label}: 관절각은 순서가 있는 숫자 목록이어야 합니다."
        )
    if len(angles) != len(JOINT_LIMITS):
        raise ValueError(
            f"{label}: 각도 개수 불일치: "
            f"{len(angles)} != {len(JOINT_LIMITS)}"
        )

    validated: list[float] = []
    for index, (angle, (lower, upper)) in enumerate(
        zip(angles, JOINT_LIMITS),
        start=1,
    ):
        if isinstance(angle, bool) or not isinstance(angle, Real):
            raise ValueError(
                f"{label} Joint {index}: 유한한 숫자가 필요합니다 "
                f"(입력: {angle!r})."
            )

        value = float(angle)
        if not math.isfinite(value):
            raise ValueError(
                f"{label} Joint {index}: 유한한 숫자가 필요합니다 "
                f"(입력: {value!r})."
            )
        if not lower <= value <= upper:
            raise ValueError(
                f"{label} Joint {index} 한계 초과: "
                f"{math.degrees(value):.1f}° "
                f"(허용: {math.degrees(lower):.1f}°~"
                f"{math.degrees(upper):.1f}°)"
            )
        validated.append(value)

    return validated


# ---------------------------------------------------------------------------
# 데이터 클래스
# ---------------------------------------------------------------------------
@dataclass
class JointState:
    """현재 관절 상태."""
    angles: list[float]   # 라디안
    positions: list[int]  # DYNAMIXEL 단위 (0-4095)


@dataclass
class OmxConfig:
    """OmxController 설정값."""
    # 포트 이름 규칙이 OS마다 달라 고정값 대신 연결 상태를 보고 정한다.
    port: str = field(default_factory=default_omx_port)
    baudrate: int = 1_000_000
    protocol: float = 2.0
    joint_ids: list[int] = field(default_factory=lambda: [11, 12, 13, 14, 15])
    gripper_id: int = 16
    profile_velocity: int = PROFILE_VELOCITY


# ---------------------------------------------------------------------------
# 역기구학 (Inverse Kinematics)
# ---------------------------------------------------------------------------
def ik_5dof(x: float, y: float, z: float) -> list[float]:
    """목표 위치(XYZ, 미터)를 5-DOF OMX 관절각(라디안)으로 변환.

    좌표계:
    - X: 로봇 정면 방향
    - Y: 로봇 왼쪽 방향
    - Z: 위 방향
    베이스 원점은 로봇 바닥 중심.

    Args:
        x: 목표 X 위치 (미터)
        y: 목표 Y 위치 (미터)
        z: 목표 Z 위치 (미터)

    Returns:
        [θ1, θ2, θ3, θ4, θ5] 관절각 리스트 (라디안).

    Raises:
        ValueError: 도달 불가능한 위치일 때.
    """
    # joint1/어깨 축은 베이스 중심에서 X=-11.25mm에 위치한다.
    relative_x = x - OMX_BASE_X
    theta1 = math.atan2(y, relative_x)
    r = math.hypot(relative_x, y)

    # 그리퍼가 아래를 향하도록 끝단 링크를 목표점에서 제거해 wrist 목표를 구한다.
    wrist_r = r - OMX_L3 * math.cos(OMX_TOOL_PITCH)
    wrist_z = z + OMX_L3 * math.sin(OMX_TOOL_PITCH) - OMX_L0
    dist = math.hypot(wrist_r, wrist_z)
    max_reach = OMX_L1 + OMX_L2
    min_reach = abs(OMX_L1 - OMX_L2)
    if not (min_reach <= dist <= max_reach):
        raise ValueError(
            f"도달 불가능한 위치: wrist 거리={dist:.3f}m, "
            f"허용={min_reach:.3f}~{max_reach:.3f}m "
            f"(x={x:.3f}, y={y:.3f}, z={z:.3f})"
        )

    # 표준 2링크 IK의 elbow-up 해를 OMX URDF joint 축(+Y)으로 변환한다.
    cos_elbow = (
        dist ** 2 - OMX_L1 ** 2 - OMX_L2 ** 2
    ) / (2 * OMX_L1 * OMX_L2)
    cos_elbow = max(-1.0, min(1.0, cos_elbow))
    elbow = -math.acos(cos_elbow)
    link1_world_angle = math.atan2(wrist_z, wrist_r) - math.atan2(
        OMX_L2 * math.sin(elbow),
        OMX_L1 + OMX_L2 * math.cos(elbow),
    )
    link2_world_angle = link1_world_angle + elbow

    theta2 = OMX_LINK1_ANGLE - link1_world_angle
    theta3 = -link2_world_angle - theta2
    theta4 = OMX_TOOL_PITCH - theta2 - theta3

    # θ5: 손목 롤 고정 (0)
    theta5 = 0.0


    return validate_joint_angles(
        [theta1, theta2, theta3, theta4, theta5],
        label="IK 결과",
    )


def fk_5dof(angles: list[float]) -> tuple[float, float, float]:
    """OMX-F 공식 URDF 치수로 엔드이펙터 XYZ 위치를 계산한다."""
    if len(angles) != 5:
        raise ValueError("FK 계산에는 5개 관절각이 필요합니다.")
    theta1, theta2, theta3, theta4, _ = angles
    total_pitch = theta2 + theta3 + theta4
    radial = (
        OMX_L1 * math.cos(OMX_LINK1_ANGLE - theta2)
        + OMX_L2 * math.cos(-(theta2 + theta3))
        + OMX_L3 * math.cos(total_pitch)
    )
    z = (
        OMX_L0
        + OMX_L1 * math.sin(OMX_LINK1_ANGLE - theta2)
        + OMX_L2 * math.sin(-(theta2 + theta3))
        - OMX_L3 * math.sin(total_pitch)
    )
    x = OMX_BASE_X + radial * math.cos(theta1)
    y = radial * math.sin(theta1)
    return x, y, z


def angle_to_dxl(angle_rad: float) -> int:
    """라디안 관절각을 DYNAMIXEL 위치값(0-4095)으로 변환."""
    # 중심 2048 기준: ±π = ±2048 단위
    # int() 내림은 J2 -120°를 한계 바깥쪽 raw 값으로 만들 수 있으므로 가장
    # 가까운 정수 위치를 사용한다.
    pos = round(
        DXL_CENTER_POSITION
        + (angle_rad / math.pi) * DXL_CENTER_POSITION
    )
    return max(DXL_MINIMUM_POSITION, min(DXL_MAXIMUM_POSITION, pos))


def dxl_to_angle(pos: int) -> float:
    """DYNAMIXEL 위치값을 라디안 관절각으로 변환."""
    return (pos - DXL_CENTER_POSITION) * math.pi / DXL_CENTER_POSITION


def gripper_percent_to_dxl(percent: float) -> int:
    """그리퍼 닫힘 비율(0~100%)을 실기 보정된 DYNAMIXEL 값으로 변환한다."""
    percent_clamped = max(0.0, min(100.0, float(percent)))
    position = GRIPPER_OPEN_POS + (
        GRIPPER_CLOSE_POS - GRIPPER_OPEN_POS
    ) * percent_clamped / 100.0
    return round(position)


def interpolate_joint_angles(
    start: list[float],
    target: list[float],
    steps: int,
) -> list[list[float]]:
    """현재 각도부터 목표 각도까지 작은 관절 이동 단계들을 만든다."""
    if len(start) != len(target):
        raise ValueError("시작 각도와 목표 각도의 개수가 다릅니다.")
    if steps < 1:
        raise ValueError("보간 단계 수는 1 이상이어야 합니다.")

    return [
        [
            start_angle + (target_angle - start_angle) * step / steps
            for start_angle, target_angle in zip(start, target)
        ]
        for step in range(1, steps + 1)
    ]


# ---------------------------------------------------------------------------
# OmxController
# ---------------------------------------------------------------------------
class OmxController:
    """DYNAMIXEL SDK를 사용한 OMX 로봇팔 제어 클래스.

    Example::

        with OmxController() as ctrl:
            ctrl.home()
            ctrl.move_xyz(0.2, 0.0, 0.1)
            ctrl.gripper_open()
    """

    def __init__(self, config: Optional[OmxConfig] = None) -> None:
        self.config = config or OmxConfig()
        self._port_handler: Optional[object] = None
        self._packet_handler: Optional[object] = None
        self._connected = False
        # 동작은 워커 스레드에서 돌고 중단 요청은 GUI 스레드에서 온다.
        self._cancel_event = threading.Event()
        self._write_failures = 0

    # --- 연결 관리 ---

    def connect(self) -> None:
        """포트를 열고 DYNAMIXEL 통신을 초기화한다.

        포트가 열렸다고 로봇이 붙어 있다는 뜻은 아니다. 모터 응답까지
        확인하려면 연결 후 :meth:`find_missing_motors`를 부른다. 여기서
        자동으로 확인하지 않는 이유는, 연결 자체는 성공시켜 놓고 스스로
        진단을 이어 가는 호출부(``run_vision_pick``의 연결 테스트 등)가
        있기 때문이다.
        """
        if not _DXL_AVAILABLE:
            raise RuntimeError(
                "dynamixel-sdk 미설치: pip install dynamixel-sdk 후 재시도하세요."
            )
        permission_guidance = serial_permission_guidance(self.config.port)
        if permission_guidance is not None:
            raise PermissionError(permission_guidance)
        ph = PortHandler(self.config.port)
        if not ph.openPort():
            raise RuntimeError(f"포트 열기 실패: {self.config.port}")
        if not ph.setBaudRate(self.config.baudrate):
            ph.closePort()
            raise RuntimeError(f"Baudrate 설정 실패: {self.config.baudrate}")

        self._port_handler = ph
        self._packet_handler = PacketHandler(self.config.protocol)
        self._connected = True
        # 중단 플래그는 여기서 지우지 않는다. connect()는 워커 스레드에서
        # 돌고 중단 요청은 그 전에 GUI 스레드에서 올 수 있는데, 여기서 지우면
        # 연결 도중 들어온 요청이 조용히 사라진다. 해제는 clear_stop()으로만.
        self._write_failures = 0
        print(f"[OMX] 연결됨: {self.config.port} @ {self.config.baudrate} bps")

    def expected_motor_ids(self) -> list[int]:
        """이 팔이 가지고 있어야 할 관절 + 그리퍼 ID."""
        return [*self.config.joint_ids, self.config.gripper_id]

    def find_missing_motors(self) -> list[int]:
        """응답하지 않는 모터 ID를 반환한다. 빈 리스트면 전부 정상이다.

        웨이포인트를 실행하기 전에 부르면, 응답 없는 포트에 수백 번 쓰기를
        시도하며 수십 초를 버리는 대신 곧바로 판단할 수 있다.
        """
        self._check_connected()
        return [
            dxl_id for dxl_id in self.expected_motor_ids() if not self._ping(dxl_id)
        ]

    def _ping(self, dxl_id: int) -> bool:
        _, result, _ = self._packet_handler.ping(  # type: ignore[union-attr]
            self._port_handler, dxl_id
        )
        return result == COMM_SUCCESS

    def disconnect(self) -> None:
        """토크를 비활성화하고 포트를 닫는다."""
        if not self._connected:
            return
        for dxl_id in self.config.joint_ids + [self.config.gripper_id]:
            self._set_torque(dxl_id, enable=False)
        self._port_handler.closePort()  # type: ignore[union-attr]
        self._connected = False
        print("[OMX] 연결 해제됨")

    def __enter__(self) -> "OmxController":
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.disconnect()

    def is_connected(self) -> bool:
        """연결 여부를 반환한다."""
        return self._connected

    # --- 중단 요청 ---

    def request_stop(self) -> None:
        """진행 중인 동작을 다음 확인 지점에서 멈춘다. 다른 스레드에서 불러도 된다.

        멈춘 동작은 :class:`OmxCancelled`를 던지므로, 웨이포인트 시퀀스는
        남은 스텝을 실행하지 않고 호출자에게 되돌아간다.
        """
        self._cancel_event.set()

    def clear_stop(self) -> None:
        """중단 요청을 지운다. 다음 동작을 시작하기 전에 부른다."""
        self._cancel_event.clear()

    def stop_requested(self) -> bool:
        """중단이 요청된 상태인지 반환한다."""
        return self._cancel_event.is_set()

    def _raise_if_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise OmxCancelled("동작이 중단 요청으로 멈췄습니다.")

    def _sleep(self, seconds: float) -> None:
        """중단 요청이 오면 즉시 깨어나는 대기.

        ``time.sleep``을 쓰면 2초짜리 스텝 하나를 끝까지 기다려야 중단이
        먹히므로, 대기도 중단 신호를 함께 본다.
        """
        if self._cancel_event.wait(seconds):
            raise OmxCancelled("동작이 중단 요청으로 멈췄습니다.")

    # --- 모터 스캔 ---

    def scan_motors(self, id_range: range = range(1, 21)) -> list[int]:
        """응답하는 모터 ID 목록을 반환한다."""
        self._check_connected()
        found: list[int] = []
        for dxl_id in id_range:
            _, result, _ = self._packet_handler.ping(  # type: ignore[union-attr]
                self._port_handler, dxl_id
            )
            if result == COMM_SUCCESS:
                found.append(dxl_id)
                print(f"[OMX] 모터 발견: ID {dxl_id}")
        if not found:
            print("[OMX] 응답하는 모터 없음 (ID, 포트, Baudrate 확인 필요)")
        return found

    # --- 토크 & 속도 설정 ---

    def enable_torque(self) -> None:
        """모든 관절 + 그리퍼 토크를 활성화한다."""
        self._check_connected()
        for dxl_id in self.config.joint_ids + [self.config.gripper_id]:
            self._set_torque(dxl_id, enable=True)
            self._set_profile_velocity(dxl_id, self.config.profile_velocity)

    def disable_torque(self) -> None:
        """모든 관절 + 그리퍼 토크를 비활성화한다."""
        self._check_connected()
        for dxl_id in self.config.joint_ids + [self.config.gripper_id]:
            self._set_torque(dxl_id, enable=False)

    # --- 고수준 동작 ---

    def home(self, duration: float = HOME_MOVE_DURATION) -> None:
        """현재 위치에서 홈 포즈까지 작은 단계로 천천히 이동한다."""
        print("[OMX] 홈 포즈로 이동 중...")
        self.move_joints_smooth(HOME_ANGLES, duration=duration)

    def move_joints_smooth(
        self,
        angles: Sequence[float],
        duration: float = HOME_MOVE_DURATION,
        update_interval: float = HOME_UPDATE_INTERVAL,
        progress_callback: Optional[Callable[[list[float]], None]] = None,
    ) -> None:
        """현재 위치와 목표 위치 사이를 보간하여 관절을 부드럽게 이동한다."""
        target_angles = validate_joint_angles(angles)
        if len(target_angles) != len(self.config.joint_ids):
            raise ValueError(
                "컨트롤러 관절 ID와 소프트 리밋 개수가 일치하지 않습니다: "
                f"{len(self.config.joint_ids)} != {len(JOINT_LIMITS)}"
            )
        if (
            not math.isfinite(duration)
            or not math.isfinite(update_interval)
            or duration <= 0
            or update_interval <= 0
        ):
            raise ValueError("이동 시간과 갱신 간격은 0보다 커야 합니다.")

        self._check_connected()
        start_angles = self.read_joint_state().angles
        validate_joint_angles(start_angles, label="현재 관절각")
        steps = max(1, math.ceil(duration / update_interval))
        self.enable_torque()

        for step_angles in interpolate_joint_angles(
            start_angles,
            target_angles,
            steps,
        ):
            self._raise_if_cancelled()
            for dxl_id, angle in zip(self.config.joint_ids, step_angles):
                self._write_goal_position(dxl_id, angle_to_dxl(angle))
            if progress_callback is not None:
                progress_callback(step_angles.copy())
            self._sleep(update_interval)

    def move_joints(
        self,
        angles: Sequence[float],
        duration: float = 2.0,
    ) -> None:
        """5개 관절을 지정 각도(라디안)로 이동한다.

        Args:
            angles: [θ1, θ2, θ3, θ4, θ5] 목표 관절각 (라디안)
            duration: 목표 위치 전송 후 대기 시간(초). 이동 속도는
                ``OmxConfig.profile_velocity``로 설정한다.
        """
        target_angles = validate_joint_angles(angles)
        if len(target_angles) != len(self.config.joint_ids):
            raise ValueError(
                "컨트롤러 관절 ID와 소프트 리밋 개수가 일치하지 않습니다: "
                f"{len(self.config.joint_ids)} != {len(JOINT_LIMITS)}"
            )
        if not math.isfinite(duration) or duration < 0:
            raise ValueError("이동 시간은 0 이상의 유한한 값이어야 합니다.")

        self._check_connected()
        self._raise_if_cancelled()
        self.enable_torque()
        for dxl_id, angle in zip(self.config.joint_ids, target_angles):
            pos = angle_to_dxl(angle)
            self._write_goal_position(dxl_id, pos)

        self._sleep(duration)

    def move_xyz(
        self,
        x: float,
        y: float,
        z: float,
        duration: float = 2.0,
    ) -> None:
        """목표 XYZ 위치(미터)로 이동한다 (역기구학 내부 적용).

        Args:
            x: 목표 X (미터, 로봇 정면)
            y: 목표 Y (미터, 로봇 좌측)
            z: 목표 Z (미터, 위쪽)
            duration: 이동 완료 후 대기 시간(초)

        Raises:
            ValueError: 목표가 도달 불가능하거나 관절 한계를 벗어날 때.

        실패를 로그만 남기고 정상 반환하면 호출부가 그리퍼 개방 같은 다음 동작을
        계속할 수 있다. IK 실패는 반드시 호출자에게 전파해 시퀀스를 중단한다.
        """
        angles = ik_5dof(x, y, z)
        print(
            f"[OMX] XYZ({x:.3f}, {y:.3f}, {z:.3f}) → "
            f"angles={[f'{math.degrees(a):.1f}°' for a in angles]}"
        )
        self.move_joints(angles, duration=duration)

    # --- 그리퍼 ---

    def set_gripper_position(self, pos: int) -> None:
        """그리퍼의 DYNAMIXEL 위치값(0~4095)을 직접 설정한다."""
        self._check_connected()
        self._set_torque(self.config.gripper_id, enable=True)
        pos_clamped = max(DXL_MINIMUM_POSITION, min(DXL_MAXIMUM_POSITION, int(pos)))
        self._write_goal_position(self.config.gripper_id, pos_clamped)

    def gripper_open(self, duration: float = 1.0) -> None:
        """그리퍼를 연다."""
        self.set_gripper_position(GRIPPER_OPEN_POS)
        self._sleep(duration)
        print("[OMX] 그리퍼 열림")

    def gripper_close(self, duration: float = 1.0) -> None:
        """그리퍼를 닫는다."""
        self.set_gripper_position(GRIPPER_CLOSE_POS)
        self._sleep(duration)
        print("[OMX] 그리퍼 닫힘")

    # --- 현재 상태 읽기 ---

    def read_joint_state(self, strict: bool = False) -> JointState:
        """현재 관절 위치를 읽어 JointState로 반환한다.

        Args:
            strict: 통신 실패 시 중앙값으로 대체하지 않고 예외를 발생시킨다.
        """
        self._check_connected()
        positions: list[int] = []
        for dxl_id in self.config.joint_ids:
            pos, result, _ = self._packet_handler.read4ByteTxRx(  # type: ignore[union-attr]
                self._port_handler, dxl_id, ADDR_PRESENT_POSITION
            )
            if result != COMM_SUCCESS:
                if strict:
                    raise RuntimeError(
                        f"관절 위치 읽기 실패 ID={dxl_id}: "
                        f"{self._packet_handler.getTxRxResult(result)}"  # type: ignore[union-attr]
                    )
                pos = DXL_CENTER_POSITION
            positions.append(pos)
        angles = [dxl_to_angle(p) for p in positions]
        return JointState(angles=angles, positions=positions)

    # --- 내부 헬퍼 ---

    def _check_connected(self) -> None:
        if not self._connected:
            raise RuntimeError("OmxController가 연결되지 않았습니다. connect()를 먼저 호출하세요.")

    def _set_torque(self, dxl_id: int, enable: bool) -> None:
        value = 1 if enable else 0
        self._packet_handler.write1ByteTxRx(  # type: ignore[union-attr]
            self._port_handler, dxl_id, ADDR_TORQUE_ENABLE, value
        )

    def _set_profile_velocity(self, dxl_id: int, velocity: int) -> None:
        result, error = self._packet_handler.write4ByteTxRx(  # type: ignore[union-attr]
            self._port_handler, dxl_id, ADDR_PROFILE_VELOCITY, velocity
        )
        if result != COMM_SUCCESS:
            print(
                f"[OMX] 속도 설정 오류 ID={dxl_id}: "
                f"{self._packet_handler.getTxRxResult(result)}"  # type: ignore[union-attr]
            )

    def _write_goal_position(self, dxl_id: int, position: int) -> None:
        result, _error = self._packet_handler.write4ByteTxRx(  # type: ignore[union-attr]
            self._port_handler, dxl_id, ADDR_GOAL_POSITION, position
        )
        if result == COMM_SUCCESS:
            self._write_failures = 0
            return

        self._write_failures += 1
        print(
            f"[OMX] 쓰기 오류 ID={dxl_id}: "
            f"{self._packet_handler.getTxRxResult(result)}"  # type: ignore[union-attr]
        )
        if self._write_failures >= MAX_CONSECUTIVE_WRITE_FAILURES:
            raise OmxCommunicationError(
                f"모터 쓰기가 연속 {self._write_failures}회 실패했습니다 "
                f"(마지막 ID={dxl_id}). 로봇 전원과 케이블을 확인하세요."
            )
