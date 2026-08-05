"""장치를 역할에 자동 배정하는 순수 로직.

셀에는 로봇팔 두 대와 카메라 두 대가 있고, 각각 하는 일이 다르다.

- OMX 1 (적재) / OMX 2 (분류)
- 모방학습 캠 (교시·자동 이동) / 검수 캠 (결함 판정)

포트 이름과 카메라 번호는 연결 순서와 부팅마다 달라지므로 사용자가 매번 고르게
하지 않고 여기서 정해진 규칙으로 배정한다. 배정 결과는 GUI에서 바꿀 수 있다.

``common.serial_ports``의 :func:`choose_serial_port`는 한 개만 고르므로 두 대를
나눌 수 없다. 그 모듈은 공용이라 여기서 고치지 않고, 같은 판별 기준
(``USB_HINTS`` · ``BLUETOOTH_HINTS``)만 가져와 두 개 배정을 새로 만든다.

Tk도 장치도 건드리지 않으므로 하드웨어 없이 그대로 시험할 수 있다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence

from common.camera import CameraDevice
from common.serial_ports import BLUETOOTH_HINTS, USB_HINTS, fallback_port


@dataclass(frozen=True)
class ArmRole:
    """로봇팔 한 대의 역할 정의."""

    key: str
    title: str
    description: str


@dataclass(frozen=True)
class CameraRole:
    """카메라 한 대의 역할 정의."""

    key: str
    title: str
    description: str


# RobotId(OMX_1/OMX_2)와 짝이 맞도록 순서를 고정한다.
ARM_ROLES: tuple[ArmRole, ...] = (
    ArmRole("loading", "OMX 1 · 적재", "공을 바구니에 투입한다"),
    ArmRole("sorting", "OMX 2 · 분류", "바구니를 정상/불량 구역으로 옮긴다"),
)
CAMERA_ROLES: tuple[CameraRole, ...] = (
    CameraRole("imitation", "모방학습 캠", "Mouse 교시와 자동 이동에 쓴다"),
    CameraRole("inspection", "검수 캠", "공 개수와 결함을 판정한다"),
)


# 거의 모든 PC 메인보드에 있는 레거시 16550 UART다. 포트 파일은 열리지만
# DYNAMIXEL이 물려 있을 일이 없어서, 자동 배정에 넣으면 응답 없는 팔이 하나
# 생긴 것처럼 보이고 재연결만 반복한다. OMX는 USB(ttyACM/ttyUSB)로 붙는다.
NON_ROBOT_PORT_PATTERNS = (
    re.compile(r"^/dev/ttyS\d+$"),
    re.compile(r"^/dev/ttyprintk$"),
)


def is_non_robot_port(device: str) -> bool:
    """로봇이 붙을 리 없는 포트인지 판별한다."""
    return any(pattern.match(device) for pattern in NON_ROBOT_PORT_PATTERNS)


def _text_has_hint(text: str, hints: Iterable[str]) -> bool:
    lowered = text.casefold()
    return any(hint.casefold() in lowered for hint in hints)


def _port_sort_key(device: str) -> tuple[str, int, str]:
    """ttyACM10이 ttyACM2보다 앞서지 않도록 끝의 숫자를 정수로 비교한다."""
    match = re.search(r"(\d+)$", device)
    if match is None:
        return (device, 0, device)
    return (device[: match.start()], int(match.group(1)), device)


def usable_omx_ports(ports: Sequence[tuple[str, str]]) -> list[str]:
    """OMX에 쓸 만한 포트를 우선순위대로 나열한다.

    블루투스 가상 포트와 메인보드 내장 UART는 항상 목록에 잡히지만 로봇 포트가
    아니므로 뺀다. USB 시리얼로 보이는 포트를 앞에 두고, 나머지는 뒤에 남겨
    둔다. 판별에 실패해도 포트를 아예 감추지는 않는다 — 이름만으로는 알 수 없는
    USB 장치가 있다.
    """
    entries = sorted(
        ((device, description or "") for device, description in ports if device),
        key=lambda entry: _port_sort_key(entry[0]),
    )
    candidates = [
        entry
        for entry in entries
        if not _text_has_hint(entry[1], BLUETOOTH_HINTS)
        and not is_non_robot_port(entry[0])
    ]
    usb_like = [
        device
        for device, description in candidates
        if _text_has_hint(f"{device} {description}", USB_HINTS)
    ]
    others = [device for device, _ in candidates if device not in set(usb_like)]
    return usb_like + others


def assign_omx_ports(
    ports: Sequence[tuple[str, str]],
) -> tuple[str | None, str | None]:
    """``(장치명, 설명)`` 목록을 OMX 1·2 포트로 나눈다.

    한 대만 잡히면 적재(OMX 1)에 먼저 준다. 적재 쪽이 교시·비전 작업까지 쓰기
    때문에 하나뿐일 때 그쪽이 살아 있는 편이 낫다. 하나도 없으면 둘 다 None이고,
    호출한 쪽이 :func:`fallback_omx_port`로 안내용 기본 이름을 보여 준다.
    """
    usable = usable_omx_ports(ports)
    first = usable[0] if len(usable) >= 1 else None
    second = usable[1] if len(usable) >= 2 else None
    return first, second


def fallback_omx_port() -> str:
    """포트를 하나도 찾지 못했을 때 화면에 보여 줄 OS별 기본 이름."""
    return fallback_port()


def assign_camera_roles(
    devices: Sequence[CameraDevice],
) -> tuple[CameraDevice | None, CameraDevice | None]:
    """카메라 목록을 모방학습 캠·검수 캠으로 나눈다.

    ``common.camera.linux_camera_devices()``가 이미 USB 외장 카메라를 앞에
    세워 주므로 그 순서를 그대로 존중한다. 한 대뿐이면 모방학습 캠에 준다 —
    교시 없이는 로봇을 못 움직이지만 검수는 이미지 파일로도 시험할 수 있다.
    """
    first = devices[0] if len(devices) >= 1 else None
    second = devices[1] if len(devices) >= 2 else None
    return first, second


def camera_assignment_status(
    devices: Sequence[CameraDevice], detected: bool
) -> str:
    """카메라 배정 결과를 사용자용 한 줄로 만든다."""
    if not detected:
        return "카메라를 찾지 못했습니다 · 번호를 직접 선택하세요"
    if len(devices) == 1:
        return "카메라 1대 · 모방학습 캠에 배정됨 · 검수 캠은 직접 선택하세요"
    if len(devices) == 2:
        return "카메라 2대 · 모방학습/검수 캠에 자동 배정됨"
    return f"카메라 {len(devices)}대 감지 · 앞의 2대를 자동 배정했습니다"


def omx_assignment_status(loading_port: str | None, sorting_port: str | None) -> str:
    """포트 배정 결과를 사용자용 한 줄로 만든다."""
    if loading_port is None and sorting_port is None:
        return f"시리얼 포트를 찾지 못했습니다 · 기본값 {fallback_omx_port()} 표시"
    if sorting_port is None:
        return f"포트 1개 · OMX 1에 {loading_port} 배정 · OMX 2 포트 없음"
    return f"포트 2개 · OMX 1 {loading_port} · OMX 2 {sorting_port}"


__all__ = [
    "ARM_ROLES",
    "CAMERA_ROLES",
    "ArmRole",
    "CameraRole",
    "assign_camera_roles",
    "assign_omx_ports",
    "camera_assignment_status",
    "fallback_omx_port",
    "omx_assignment_status",
    "usable_omx_ports",
]
