import common.serial_ports as serial_ports

from common.serial_ports import (
    LINUX_FALLBACK_PORT,
    WINDOWS_FALLBACK_PORT,
    choose_serial_port,
    fallback_port,
    serial_permission_guidance,
)


def test_fallback_port_is_platform_specific() -> None:
    assert fallback_port("win32") == WINDOWS_FALLBACK_PORT
    assert fallback_port("linux") == LINUX_FALLBACK_PORT
    assert fallback_port("darwin") == LINUX_FALLBACK_PORT


def test_choose_serial_port_prefers_usb_over_bluetooth() -> None:
    ports = [
        ("COM6", "표준 Bluetooth를 통한 직렬 링크(COM6)"),
        ("COM5", "표준 Bluetooth를 통한 직렬 링크(COM5)"),
        ("COM10", "USB 직렬 장치(COM10)"),
    ]

    assert choose_serial_port(ports, fallback="COM3") == "COM10"


def test_choose_serial_port_finds_linux_acm_node() -> None:
    ports = [
        ("/dev/ttyS0", "n/a"),
        ("/dev/ttyACM0", "OpenRB-150"),
    ]

    assert choose_serial_port(ports, fallback="/dev/ttyACM0") == "/dev/ttyACM0"


def test_choose_serial_port_sorts_numbers_numerically() -> None:
    ports = [("COM10", "USB Serial"), ("COM5", "USB Serial")]

    assert choose_serial_port(ports, fallback="COM3") == "COM5"


def test_choose_serial_port_uses_fallback_without_usable_ports() -> None:
    bluetooth_only = [("COM6", "Standard Serial over Bluetooth link")]

    assert choose_serial_port([], fallback="COM3") == "COM3"
    assert choose_serial_port(bluetooth_only, fallback="COM3") == "COM3"


def test_choose_serial_port_accepts_port_without_description() -> None:
    assert choose_serial_port([("COM4", "")], fallback="COM3") == "COM4"


def test_serial_permission_guidance_shows_persistent_linux_fix(
    tmp_path, monkeypatch
) -> None:
    port = tmp_path / "ttyACM0"
    port.touch()
    monkeypatch.setattr(serial_ports.os, "access", lambda *_args: False)

    guidance = serial_permission_guidance(
        str(port), platform="linux", username="itec"
    )

    assert guidance is not None
    assert "sudo usermod -aG dialout itec" in guidance
    assert "sudo reboot" in guidance


def test_serial_permission_guidance_ignores_accessible_or_missing_ports(
    tmp_path, monkeypatch
) -> None:
    port = tmp_path / "ttyACM0"
    port.touch()
    monkeypatch.setattr(serial_ports.os, "access", lambda *_args: True)

    assert serial_permission_guidance(str(port), platform="linux") is None
    assert (
        serial_permission_guidance(
            str(tmp_path / "missing"), platform="linux"
        )
        is None
    )
    assert serial_permission_guidance(str(port), platform="win32") is None
