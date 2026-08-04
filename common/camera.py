"""운영체제별 카메라 탐색과 OpenCV 캡처 생성."""
from __future__ import annotations

import subprocess
import sys
import threading
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import cv2


WINDOWS_CAMERA_INDEXES = (1, 0)
PREFERRED_CAMERA_NAMES = ("C270", "Logi")
LINUX_V4L_SYS_DIR = Path("/sys/class/video4linux")
CAPTURE_WIDTH = 1280
CAPTURE_HEIGHT = 720
# 윈도우에는 리눅스의 video 노드 같은 장치 목록이 없어 인덱스를 직접 열어 본다.
# 없는 인덱스는 즉시 실패하므로 비용은 실제 연결된 카메라 수에만 비례한다.
WINDOWS_PROBE_LIMIT = 6
# 탐색이 아무것도 찾지 못했을 때도 사용자가 직접 번호를 고를 수 있게 남겨 둔다.
FALLBACK_DEVICE_COUNT = 4


@dataclass(frozen=True)
class CameraDevice:
    """선택 가능한 카메라 하나. ``name``은 알아낼 수 있을 때만 채운다."""

    index: int
    name: str = ""

    @property
    def label(self) -> str:
        """GUI 목록에 그대로 넣을 수 있는 표시 문자열."""
        if self.name:
            return f"{self.index}번 · {self.name}"
        return f"{self.index}번 카메라"


def _capture_backend() -> int:
    return cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY


def open_camera(
    index: int,
    width: int = CAPTURE_WIDTH,
    height: int = CAPTURE_HEIGHT,
) -> cv2.VideoCapture:
    """카메라를 열고 실시간 표시에 적합한 옵션을 설정한다."""
    backend = _capture_backend()
    capture = cv2.VideoCapture(index, backend)
    if not capture.isOpened() and backend != cv2.CAP_ANY:
        capture = cv2.VideoCapture(index, cv2.CAP_ANY)
    if not capture.isOpened():
        raise RuntimeError(
            f"카메라 {index}번을 열 수 없습니다. "
            "웹캠 연결과 다른 앱의 점유 여부를 확인하세요."
        )

    capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return capture


def linux_camera_devices(
    sys_dir: Path = LINUX_V4L_SYS_DIR,
) -> tuple[CameraDevice, ...]:
    """리눅스 video 노드에서 USB 외장 카메라를 앞세운 장치 목록을 만든다.

    한 카메라가 video0·video1처럼 노드를 여러 개 만드는 일이 흔하므로 이름이
    같으면 가장 낮은(캡처용) 노드 하나만 남긴다.
    """
    entries: list[tuple[int, str]] = []
    for node in sys_dir.glob("video*"):
        suffix = node.name.removeprefix("video")
        if not suffix.isdigit():
            continue
        try:
            name = (node / "name").read_text(encoding="utf-8").strip()
        except OSError:
            continue
        entries.append((int(suffix), name))

    capture_index_by_name: dict[str, int] = {}
    for index, name in sorted(entries):
        capture_index_by_name.setdefault(name, index)

    devices = [
        CameraDevice(index, name)
        for name, index in capture_index_by_name.items()
    ]
    devices.sort(
        key=lambda device: (
            not _is_preferred_name(device.name),
            device.index,
        )
    )
    return tuple(devices)


def _is_preferred_name(name: str) -> bool:
    return any(tag.casefold() in name.casefold() for tag in PREFERRED_CAMERA_NAMES)


def linux_camera_indexes(
    sys_dir: Path = LINUX_V4L_SYS_DIR,
) -> tuple[int, ...]:
    """리눅스 video 노드에서 USB 외장 카메라를 앞세운다."""
    indexes = tuple(device.index for device in linux_camera_devices(sys_dir))
    return indexes or (0,)


def probe_camera_index(index: int) -> bool:
    """해당 인덱스에서 실제로 프레임을 읽을 수 있는지 확인한다.

    ``open_camera``와 달리 백엔드를 하나만 시도한다. 비어 있는 인덱스까지
    대체 백엔드로 다시 열어 보면 탐색이 몇 배로 느려지고, 실제로 쓸 카메라를
    더 찾아 주지도 않는다.
    """
    capture = cv2.VideoCapture(index, _capture_backend())
    try:
        if not capture.isOpened():
            return False
        grabbed, _frame = capture.read()
    except cv2.error:
        return False
    finally:
        capture.release()
    return bool(grabbed)


def windows_camera_names() -> list[str]:
    """윈도우 장치 관리자에 등록된 카메라 이름을 열거 순서대로 읽는다.

    실패하면 빈 목록을 돌려준다. 이름은 목록을 알아보기 쉽게 해 줄 뿐이라
    조회가 안 되더라도 번호만으로 선택할 수 있어야 한다.
    """
    command = [
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
        "Get-CimInstance Win32_PnPEntity | "
        "Where-Object { $_.PNPClass -eq 'Camera' } | "
        "ForEach-Object { $_.Name }",
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            timeout=15,
            # 콘솔 창이 잠깐 떴다 사라지지 않도록 숨긴다.
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return []
    text = result.stdout.decode("utf-8", errors="replace")
    return [line.strip() for line in text.splitlines() if line.strip()]


def pair_device_names(
    indexes: Sequence[int], names: Sequence[str]
) -> tuple[CameraDevice, ...]:
    """열린 인덱스와 장치 이름을 순서대로 짝지어 준다.

    DirectShow 인덱스와 장치 목록은 같은 열거 순서를 따르지만, 개수가 어긋나면
    어떤 이름이 어떤 인덱스인지 보장할 수 없다. 틀린 이름은 없는 이름보다
    나쁘므로 그때는 번호만 남긴다.
    """
    if len(names) != len(indexes):
        return tuple(CameraDevice(index) for index in indexes)
    return tuple(
        CameraDevice(index, name) for index, name in zip(indexes, names)
    )


@contextmanager
def quiet_opencv():
    """비어 있는 인덱스를 열어 볼 때마다 나오는 OpenCV 경고를 감춘다."""
    logging_api = getattr(getattr(cv2, "utils", None), "logging", None)
    if logging_api is None:
        yield
        return
    try:
        previous = logging_api.getLogLevel()
        logging_api.setLogLevel(logging_api.LOG_LEVEL_SILENT)
    except Exception:
        yield
        return
    try:
        yield
    finally:
        logging_api.setLogLevel(previous)


def windows_camera_devices(
    limit: int = WINDOWS_PROBE_LIMIT,
    probe: Callable[[int], bool] = probe_camera_index,
    names: Callable[[], list[str]] = windows_camera_names,
) -> tuple[CameraDevice, ...]:
    """윈도우에서 인덱스를 직접 열어 사용 가능한 카메라를 찾는다."""
    with quiet_opencv():
        indexes = [index for index in range(limit) if probe(index)]
    if not indexes:
        return ()
    return pair_device_names(indexes, names())


def fallback_camera_devices(
    count: int = FALLBACK_DEVICE_COUNT,
) -> tuple[CameraDevice, ...]:
    """탐색이 실패했을 때 직접 고를 수 있는 기본 번호 목록."""
    return tuple(CameraDevice(index) for index in range(count))


def selectable_devices(
    devices: Sequence[CameraDevice],
) -> tuple[CameraDevice, ...]:
    """GUI 목록에 넣을 장치를 정한다. 하나도 없으면 기본 번호를 쓴다."""
    return tuple(devices) or fallback_camera_devices()


def scan_cameras() -> tuple[CameraDevice, ...]:
    """현재 OS 방식으로 연결된 카메라를 실제로 조회한다(느릴 수 있다)."""
    if sys.platform.startswith("linux"):
        return linux_camera_devices()
    return windows_camera_devices()


_scan_lock = threading.Lock()
_cached_devices: tuple[CameraDevice, ...] | None = None


def list_cameras(refresh: bool = False) -> tuple[CameraDevice, ...]:
    """연결된 카메라 목록을 반환한다.

    윈도우 탐색은 장치를 직접 열어 보므로 느리고, 같은 장치를 동시에 열면
    실패한다. 결과를 캐시하고 잠금으로 직렬화해 창 여러 개가 각자 조회해도
    카메라를 한 번에 하나씩만 건드리게 한다.
    """
    global _cached_devices
    with _scan_lock:
        if refresh or _cached_devices is None:
            _cached_devices = scan_cameras()
        return _cached_devices


def preferred_camera_indexes() -> tuple[int, ...]:
    """운영체제별 카메라 인덱스를 우선순위대로 반환한다."""
    if sys.platform.startswith("linux"):
        return linux_camera_indexes()
    return WINDOWS_CAMERA_INDEXES


def open_preferred_camera(
    width: int = CAPTURE_WIDTH,
    height: int = CAPTURE_HEIGHT,
) -> tuple[cv2.VideoCapture, int]:
    """선호 카메라를 열어 ``(capture, index)``로 반환한다."""
    last_error: RuntimeError | None = None
    for index in preferred_camera_indexes():
        try:
            capture = open_camera(index, width, height)
        except RuntimeError as error:
            last_error = error
            continue
        grabbed, _frame = capture.read()
        if grabbed:
            return capture, index
        capture.release()
        last_error = RuntimeError(
            f"카메라 {index}번이 프레임을 반환하지 않습니다."
        )

    if last_error is None:
        last_error = RuntimeError(
            "사용 가능한 카메라를 찾지 못했습니다."
        )
    raise last_error


# 이전 코드가 가져가던 private 이름도 당분간 유지한다.
_linux_camera_indexes = linux_camera_indexes
