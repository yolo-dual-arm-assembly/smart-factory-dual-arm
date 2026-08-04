from pathlib import Path

from common.camera import linux_camera_indexes


def make_video_node(root: Path, index: int, name: str) -> None:
    node = root / f"video{index}"
    node.mkdir()
    (node / "name").write_text(name + "\n", encoding="utf-8")


def test_prefers_named_usb_camera_capture_node(tmp_path: Path) -> None:
    """내장캠(0·1)과 C270(2·3)이 있으면 C270 캡처 노드(2)를 앞세운다."""
    make_video_node(tmp_path, 0, "720p HD Camera")
    make_video_node(tmp_path, 1, "720p HD Camera")
    make_video_node(tmp_path, 2, "Logi C270 HD WebCam")
    make_video_node(tmp_path, 3, "Logi C270 HD WebCam")

    assert linux_camera_indexes(tmp_path) == (2, 0)


def test_no_preferred_name_keeps_index_order(tmp_path: Path) -> None:
    make_video_node(tmp_path, 0, "Integrated Camera")
    make_video_node(tmp_path, 1, "Integrated Camera")
    make_video_node(tmp_path, 2, "Generic UVC Camera")

    assert linux_camera_indexes(tmp_path) == (0, 2)


def test_only_usb_camera_connected(tmp_path: Path) -> None:
    """로봇 배포처럼 C270만 있으면 그 캡처 노드 하나만 나온다."""
    make_video_node(tmp_path, 0, "Logi C270 HD WebCam")
    make_video_node(tmp_path, 1, "Logi C270 HD WebCam")

    assert linux_camera_indexes(tmp_path) == (0,)


def test_double_digit_indexes_sort_numerically(tmp_path: Path) -> None:
    make_video_node(tmp_path, 10, "Logi C270 HD WebCam")
    make_video_node(tmp_path, 2, "Logi C270 HD WebCam")

    assert linux_camera_indexes(tmp_path) == (2,)


def test_empty_sys_dir_defaults_to_zero(tmp_path: Path) -> None:
    assert linux_camera_indexes(tmp_path) == (0,)
