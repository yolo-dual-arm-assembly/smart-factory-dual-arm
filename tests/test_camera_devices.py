from pathlib import Path

from common.camera import (
    CameraDevice,
    fallback_camera_devices,
    linux_camera_devices,
    pair_device_names,
    selectable_devices,
    windows_camera_devices,
)


def make_video_node(root: Path, index: int, name: str) -> None:
    node = root / f"video{index}"
    node.mkdir()
    (node / "name").write_text(name + "\n", encoding="utf-8")


def test_device_label_uses_name_when_known() -> None:
    assert CameraDevice(1, "Logi C270 HD WebCam").label == "1번 · Logi C270 HD WebCam"
    assert CameraDevice(1).label == "1번 카메라"


def test_linux_devices_keep_one_entry_per_camera(tmp_path: Path) -> None:
    """카메라 한 대가 노드를 둘 만들어도 선택 목록에는 한 번만 나와야 한다."""
    make_video_node(tmp_path, 0, "720p HD Camera")
    make_video_node(tmp_path, 1, "720p HD Camera")
    make_video_node(tmp_path, 2, "Logi C270 HD WebCam")
    make_video_node(tmp_path, 3, "Logi C270 HD WebCam")

    devices = linux_camera_devices(tmp_path)

    assert devices == (
        CameraDevice(2, "Logi C270 HD WebCam"),
        CameraDevice(0, "720p HD Camera"),
    )


def test_linux_devices_are_empty_without_video_nodes(tmp_path: Path) -> None:
    assert linux_camera_devices(tmp_path) == ()


def test_windows_devices_probe_each_index() -> None:
    opened = {0, 2}
    devices = windows_camera_devices(
        limit=4,
        probe=lambda index: index in opened,
        names=lambda: [],
    )

    assert devices == (CameraDevice(0), CameraDevice(2))


def test_windows_devices_take_names_in_enumeration_order() -> None:
    devices = windows_camera_devices(
        limit=3,
        probe=lambda index: index < 2,
        names=lambda: ["720p HD Camera", "Logi C270 HD WebCam"],
    )

    assert devices == (
        CameraDevice(0, "720p HD Camera"),
        CameraDevice(1, "Logi C270 HD WebCam"),
    )


def test_names_are_dropped_when_count_does_not_match() -> None:
    """개수가 어긋나면 이름을 잘못 붙이느니 번호만 보여 준다."""
    assert pair_device_names([0, 1], ["720p HD Camera"]) == (
        CameraDevice(0),
        CameraDevice(1),
    )


def test_selectable_devices_fall_back_to_plain_indexes() -> None:
    assert selectable_devices(()) == fallback_camera_devices()
    assert selectable_devices((CameraDevice(3),)) == (CameraDevice(3),)
