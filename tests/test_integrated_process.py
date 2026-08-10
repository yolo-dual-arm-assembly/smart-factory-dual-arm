from system_monitor.ui.integrated_process import (
    DeviceAvailability,
    build_process_plan,
)


def test_all_devices_run_all_process_stages() -> None:
    devices = DeviceAvailability(True, True, True, True)

    plan = build_process_plan(
        devices, loading_configured=True, inspection_configured=True
    )

    assert plan.run_loading
    assert plan.run_inspection
    assert plan.run_sorting
    assert plan.skipped == ()


def test_missing_loading_devices_only_skip_loading() -> None:
    devices = DeviceAvailability(False, True, False, True)

    plan = build_process_plan(
        devices, loading_configured=True, inspection_configured=True
    )

    assert not plan.run_loading
    assert plan.run_inspection
    assert plan.run_sorting
    assert plan.skipped == (("OMX 1 적재", "OMX 1, 모방학습 캠 없음"),)
    assert devices.missing_labels() == ("OMX 1 · 적재", "모방학습 캠")


def test_missing_inspection_camera_also_skips_dependent_sorting() -> None:
    devices = DeviceAvailability(True, True, True, False)

    plan = build_process_plan(
        devices, loading_configured=True, inspection_configured=True
    )

    assert plan.run_loading
    assert not plan.run_inspection
    assert not plan.run_sorting
    assert plan.skipped == (
        ("비전 검사", "검수 캠 없음"),
        ("OMX 2 분류", "검사 결과를 만들 수 없음"),
    )


def test_missing_calibration_skips_loading_but_keeps_inspection_and_sorting() -> None:
    devices = DeviceAvailability(True, True, True, True)

    plan = build_process_plan(
        devices, loading_configured=False, inspection_configured=True
    )

    assert not plan.run_loading
    assert plan.run_inspection
    assert plan.run_sorting
    assert plan.skipped == (("OMX 1 적재", "적재 보정/모델 없음"),)


def test_no_devices_produces_no_runnable_stage() -> None:
    devices = DeviceAvailability(False, False, False, False)

    plan = build_process_plan(
        devices, loading_configured=False, inspection_configured=False
    )

    assert not plan.has_runnable_stage
    assert [stage for stage, _reason in plan.skipped] == [
        "OMX 1 적재",
        "비전 검사",
        "OMX 2 분류",
    ]
