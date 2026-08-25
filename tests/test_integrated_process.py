from common.constants import RobotState
from common.messages import InspectionResult, RobotStatus
from system_monitor.ui.integrated_process import (
    DeviceAvailability,
    ProcessCancelled,
    ProcessPlan,
    build_process_plan,
    run_process_cycle,
)

_FULL_PLAN = ProcessPlan(
    run_loading=True, run_inspection=True, run_sorting=True, skipped=()
)
_PASS_RESULT = InspectionResult(total_count=5, defect_count=0, result=RobotState.PASS)
_REJECT_RESULT = InspectionResult(
    total_count=5, defect_count=2, result=RobotState.REJECT
)


def _cycle(plan=_FULL_PLAN, **overrides):
    kwargs = dict(
        run_loading=lambda: None,
        wait_for_inspection=lambda: _PASS_RESULT,
        run_sorting=lambda inspection: RobotStatus(
            robot_id="omx2", state=RobotState.PASS, success=True
        ),
        set_status=lambda text: None,
        is_cancelled=lambda: False,
        inspection_timeout_sec=15.0,
    )
    kwargs.update(overrides)
    return run_process_cycle(plan, **kwargs)


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


def test_run_process_cycle_runs_all_stages_in_order() -> None:
    calls: list[str] = []
    result = _cycle(
        run_loading=lambda: calls.append("loading"),
        wait_for_inspection=lambda: calls.append("inspection") or _PASS_RESULT,
        run_sorting=lambda inspection: calls.append("sorting")
        or RobotStatus(robot_id="omx2", state=RobotState.PASS, success=True),
    )

    assert calls == ["loading", "inspection", "sorting"]
    assert result.status == "completed"
    assert result.completed == ("OMX1 적재", "비전 검사", "OMX2 PASS 분류")
    assert result.detail == ""


def test_run_process_cycle_skips_stages_the_plan_does_not_include() -> None:
    plan = ProcessPlan(
        run_loading=False, run_inspection=True, run_sorting=False, skipped=()
    )
    calls: list[str] = []

    result = _cycle(
        plan,
        run_loading=lambda: calls.append("loading"),
        wait_for_inspection=lambda: calls.append("inspection") or _REJECT_RESULT,
        run_sorting=lambda inspection: calls.append("sorting")
        or RobotStatus(robot_id="omx2", state=RobotState.REJECT, success=True),
    )

    assert calls == ["inspection"]
    assert result.status == "completed"
    assert result.completed == ("비전 검사",)


def test_run_process_cycle_reports_partial_when_inspection_times_out() -> None:
    result = _cycle(wait_for_inspection=lambda: None)

    assert result.status == "partial"
    assert result.completed == ("OMX1 적재",)
    assert "15초" in result.detail


def test_run_process_cycle_fails_when_sorting_reports_failure() -> None:
    result = _cycle(
        run_sorting=lambda inspection: RobotStatus(
            robot_id="omx2", state=RobotState.PASS, success=False, message="토크 오류"
        )
    )

    assert result.status == "failed"
    assert result.detail == "토크 오류"
    assert result.completed == ("OMX1 적재", "비전 검사")


def test_run_process_cycle_stops_at_next_checkpoint_when_cancelled() -> None:
    calls: list[str] = []

    def run_loading() -> None:
        calls.append("loading")

    def wait_for_inspection() -> InspectionResult:
        calls.append("inspection")
        return _PASS_RESULT

    result = _cycle(
        run_loading=run_loading,
        wait_for_inspection=wait_for_inspection,
        is_cancelled=lambda: len(calls) >= 1,
    )

    assert calls == ["loading"]
    assert result.status == "cancelled"
    assert result.completed == ()


def test_run_process_cycle_treats_mid_call_exception_as_cancelled_if_flagged() -> None:
    """취소 도중 하드웨어 호출이 별개 예외를 던져도 취소로 분류한다."""

    def run_loading() -> None:
        raise RuntimeError("모션 중단으로 인한 하드웨어 오류")

    result = _cycle(run_loading=run_loading, is_cancelled=lambda: True)

    assert result.status == "cancelled"
    assert result.detail == "사용자 요청으로 중단했습니다."


def test_run_process_cycle_reports_failure_when_not_cancelled() -> None:
    def run_loading() -> None:
        raise RuntimeError("보정 파일을 읽을 수 없습니다.")

    result = _cycle(run_loading=run_loading, is_cancelled=lambda: False)

    assert result.status == "failed"
    assert result.detail == "보정 파일을 읽을 수 없습니다."


def test_run_process_cycle_raises_process_cancelled_is_caught_internally() -> None:
    def run_loading() -> None:
        raise ProcessCancelled

    result = _cycle(run_loading=run_loading)

    assert result.status == "cancelled"
