import main as main_entrypoint
from system_monitor.ui.viewer import main as viewer_main


def test_main_entrypoint_uses_viewer_main() -> None:
    assert main_entrypoint.main is viewer_main
