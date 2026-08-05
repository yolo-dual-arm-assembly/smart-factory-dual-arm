"""운영체제별 OMX 시리얼 포트 탐색.

리눅스는 ``/dev/ttyACM0`` 계열, 윈도우는 ``COM3`` 계열로 포트 이름 규칙이
완전히 다르다. 한쪽 이름을 기본값으로 박아 두면 다른 OS에서는 항상 연결에
실패하므로, 연결된 포트를 실제로 조회해 가장 그럴듯한 것을 고른다.
"""
from __future__ import annotations

import getpass
import os
import re
import shlex
import sys
from collections.abc import Iterable
from pathlib import Path

# 블루투스 가상 COM 포트는 항상 목록에 잡히지만 로봇 포트가 아니다.
BLUETOOTH_HINTS = ("bluetooth", "블루투스")
# USB 시리얼 변환기·제어보드에서 흔히 보이는 표시 문자열과 장치 이름.
USB_HINTS = (
    "usb",
    "직렬",
    "serial",
    "ttyacm",
    "ttyusb",
    "u2d2",
    "ftdi",
    "cp210",
    "ch340",
    "openmanipulator",
    "opencr",
    "dynamixel",
)
LINUX_FALLBACK_PORT = "/dev/ttyACM0"
WINDOWS_FALLBACK_PORT = "COM3"


def fallback_port(platform: str = sys.platform) -> str:
    """포트를 하나도 찾지 못했을 때 보여줄 OS별 기본 이름."""
    if platform.startswith("win"):
        return WINDOWS_FALLBACK_PORT
    return LINUX_FALLBACK_PORT


def _contains_hint(text: str, hints: Iterable[str]) -> bool:
    lowered = text.casefold()
    return any(hint.casefold() in lowered for hint in hints)


def _sort_key(device: str) -> tuple[str, int, str]:
    """COM10이 COM5보다 앞서지 않도록 숫자 부분을 정수로 비교한다."""
    match = re.search(r"(\d+)$", device)
    if match is None:
        return (device, 0, device)
    return (device[: match.start()], int(match.group(1)), device)


def choose_serial_port(
    ports: Iterable[tuple[str, str]], fallback: str
) -> str:
    """``(장치명, 설명)`` 목록에서 로봇 연결에 가장 알맞은 포트를 고른다."""
    entries = sorted(
        (
            (device, description or "")
            for device, description in ports
            if device
        ),
        key=lambda entry: _sort_key(entry[0]),
    )
    usable = [
        entry
        for entry in entries
        if not _contains_hint(entry[1], BLUETOOTH_HINTS)
    ]
    if not usable:
        return fallback

    for device, description in usable:
        if _contains_hint(f"{device} {description}", USB_HINTS):
            return device
    return usable[0][0]


def list_serial_ports() -> list[tuple[str, str]]:
    """연결된 시리얼 포트를 ``(장치명, 설명)`` 목록으로 반환한다."""
    try:
        from serial.tools import list_ports
    except ImportError:
        # pyserial은 dynamixel-sdk의 의존성이라 보통 함께 설치되지만,
        # 없더라도 포트 기본값 때문에 앱이 멈추지는 않아야 한다.
        return []
    try:
        return [(port.device, port.description) for port in list_ports.comports()]
    except Exception:
        return []


def default_omx_port() -> str:
    """현재 OS와 연결 상태에 맞는 OMX 기본 포트 이름을 반환한다."""
    return choose_serial_port(list_serial_ports(), fallback_port())


def serial_permission_guidance(
    port: str,
    *,
    platform: str = sys.platform,
    username: str | None = None,
) -> str | None:
    """Linux 시리얼 장치의 읽기·쓰기 권한이 없으면 해결 안내를 반환한다.

    장치가 없거나 다른 운영체제이면 케이블·포트 선택 문제일 수 있으므로 권한
    문제로 단정하지 않는다. 권한 변경은 앱이 대신 실행하지 않고 사용자가 한 번
    명시적으로 수행하도록 명령만 안내한다.
    """
    if not platform.startswith("linux"):
        return None

    device = Path(port)
    try:
        lacks_permission = device.exists() and not os.access(
            device, os.R_OK | os.W_OK
        )
    except OSError:
        return None
    if not lacks_permission:
        return None

    account = username or getpass.getuser()
    quoted_account = shlex.quote(account)
    return (
        f"Linux 시리얼 포트 권한이 없습니다: {port}\n\n"
        "터미널에서 다음 명령을 한 번 실행하세요.\n\n"
        f"sudo usermod -aG dialout {quoted_account}\n"
        "sudo reboot\n\n"
        "재부팅 후 앱을 다시 실행하세요."
    )
