from pathlib import Path

from common.camera import (
    CameraDevice,
    fallback_camera_devices,
    linux_camera_devices,
    pair_device_names,
    selectable_devices,
    windows_camera_devices,
)


def make_video_node(
    root: Path, index: int, name: str, device: str | None = None
) -> None:
    """가짜 sysfs video 노드. ``device``를 주면 실제 sysfs처럼 그 노드를 만든
    USB 인터페이스를 가리키는 심링크를 만든다."""
    node = root / f"video{index}"
    node.mkdir()
    (node / "name").write_text(name + "\n", encoding="utf-8")
    if device is not None:
        target = root / "devices" / device
        target.mkdir(parents=True, exist_ok=True)
        (node / "device").symlink_to(target)


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


def test_two_identical_cameras_stay_separate(tmp_path: Path) -> None:
    """같은 모델 두 대는 이름이 똑같아도 각각 잡혀야 한다.

    회귀 방지: 이름으로 중복 제거하면 C270 두 대가 한 대로 합쳐진다
    (실제 현장에서 겪은 문제). 같은 카메라의 노드끼리만 device 심링크가 같다.
    """
    make_video_node(tmp_path, 0, "C270 HD WEBCAM", device="1-7.2:1.0")
    make_video_node(tmp_path, 1, "C270 HD WEBCAM", device="1-7.2:1.0")
    make_video_node(tmp_path, 2, "C270 HD WEBCAM", device="1-10:1.0")
    make_video_node(tmp_path, 3, "C270 HD WEBCAM", device="1-10:1.0")

    devices = linux_camera_devices(tmp_path)

    assert devices == (
        CameraDevice(0, "C270 HD WEBCAM"),
        CameraDevice(2, "C270 HD WEBCAM"),
    )


def test_multi_node_camera_still_collapses_with_symlinks(tmp_path: Path) -> None:
    """심링크가 있어도 한 카메라의 노드 두 개는 여전히 하나로 합쳐진다."""
    make_video_node(tmp_path, 0, "720p HD Camera", device="1-3:1.0")
    make_video_node(tmp_path, 1, "720p HD Camera", device="1-3:1.0")
    make_video_node(tmp_path, 2, "Logi C270 HD WebCam", device="1-7.2:1.0")
    make_video_node(tmp_path, 3, "Logi C270 HD WebCam", device="1-7.2:1.0")

    devices = linux_camera_devices(tmp_path)

    assert devices == (
        CameraDevice(2, "Logi C270 HD WebCam"),
        CameraDevice(0, "720p HD Camera"),
    )


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
