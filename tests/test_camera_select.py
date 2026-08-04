from common.camera import CameraDevice
from system_monitor.ui.camera_select import scan_status


def test_status_asks_for_a_choice_with_two_or_more_cameras() -> None:
    devices = (CameraDevice(0, "720p HD Camera"), CameraDevice(1, "Logi C270"))

    assert scan_status(devices, detected=True) == (
        "카메라 2대 감지 · 사용할 카메라를 선택하세요"
    )


def test_status_says_single_camera_is_automatic() -> None:
    devices = (CameraDevice(0, "720p HD Camera"),)

    assert scan_status(devices, detected=True) == "카메라 1대 · 자동 선택됨"


def test_status_explains_manual_choice_when_nothing_detected() -> None:
    assert scan_status((CameraDevice(0),), detected=False) == (
        "카메라를 찾지 못했습니다 · 번호를 직접 선택하세요"
    )
