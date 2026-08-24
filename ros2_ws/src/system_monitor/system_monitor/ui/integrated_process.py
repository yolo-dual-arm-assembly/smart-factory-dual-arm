"""통합 공정에서 실행할 단계를 장치 상태로 결정하고, 그 계획을 순서대로 실행하는 순수 로직.

실제 장치 제어와 Tk 위젯 갱신은 :mod:`system_monitor.ui.viewer`가 담당한다.
여기는 버튼을 누른 시점의 네 장치 상태와 설정 파일 준비 여부만 받아서 어떤
단계를 실행하고 건너뛸지 정하고(``build_process_plan``), 실제 실행은 장치
제어를 콜백으로 주입받아 순서·취소·예외만 담당한다(``run_process_cycle``).
하드웨어 없이도 계획 수립과 실행 시퀀싱을 테스트하기 위해 GUI와 장치 모듈을
import하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from common.messages import InspectionResult, RobotStatus


@dataclass(frozen=True)
class DeviceAvailability:
    """통합 공정 시작 시점에 확인한 네 장치의 연결 상태."""

    omx1: bool
    omx2: bool
    imitation_camera: bool
    inspection_camera: bool

    def missing_labels(self) -> tuple[str, ...]:
        """연결되지 않은 장치 이름을 화면 표시 순서대로 반환한다."""
        devices = (
            ("OMX 1 · 적재", self.omx1),
            ("OMX 2 · 분류", self.omx2),
            ("모방학습 캠", self.imitation_camera),
            ("검수 캠", self.inspection_camera),
        )
        return tuple(label for label, available in devices if not available)


@dataclass(frozen=True)
class ProcessPlan:
    """장치와 설정 의존성을 반영한 한 번의 통합 공정 계획."""

    run_loading: bool
    run_inspection: bool
    run_sorting: bool
    skipped: tuple[tuple[str, str], ...]

    @property
    def has_runnable_stage(self) -> bool:
        return self.run_loading or self.run_inspection or self.run_sorting


def build_process_plan(
    devices: DeviceAvailability,
    *,
    loading_configured: bool,
    inspection_configured: bool,
) -> ProcessPlan:
    """누락 장치는 건너뛰되 의존성이 충족된 단계만 순서에 넣는다.

    적재는 OMX1·모방학습 캠·보정/모델 설정이 모두 필요하다. 검사는 검수 캠과
    검사 모델이 필요하고, 분류는 그 검사가 새 PASS/REJECT를 만든 경우에만
    방향을 정할 수 있으므로 검사 단계가 계획에 있을 때만 실행한다.
    """
    skipped: list[tuple[str, str]] = []

    loading_missing: list[str] = []
    if not devices.omx1:
        loading_missing.append("OMX 1")
    if not devices.imitation_camera:
        loading_missing.append("모방학습 캠")
    if not loading_configured:
        loading_missing.append("적재 보정/모델")
    run_loading = not loading_missing
    if loading_missing:
        skipped.append(("OMX 1 적재", ", ".join(loading_missing) + " 없음"))

    inspection_missing: list[str] = []
    if not devices.inspection_camera:
        inspection_missing.append("검수 캠")
    if not inspection_configured:
        inspection_missing.append("검사 모델")
    run_inspection = not inspection_missing
    if inspection_missing:
        skipped.append(("비전 검사", ", ".join(inspection_missing) + " 없음"))

    run_sorting = devices.omx2 and run_inspection
    if not run_sorting:
        reason = "OMX 2 없음" if not devices.omx2 else "검사 결과를 만들 수 없음"
        skipped.append(("OMX 2 분류", reason))

    return ProcessPlan(
        run_loading=run_loading,
        run_inspection=run_inspection,
        run_sorting=run_sorting,
        skipped=tuple(skipped),
    )


class ProcessCancelled(Exception):
    """사용자가 통합 공정 중단을 요청했다는 신호."""


@dataclass(frozen=True)
class CycleOutcome:
    """``run_process_cycle`` 한 번 실행의 최종 결과."""

    status: str  # "completed" | "partial" | "cancelled" | "failed"
    completed: tuple[str, ...]
    detail: str


def run_process_cycle(
    plan: ProcessPlan,
    *,
    run_loading: Callable[[], None],
    wait_for_inspection: Callable[[], InspectionResult | None],
    run_sorting: Callable[[InspectionResult], RobotStatus],
    set_status: Callable[[str], None],
    is_cancelled: Callable[[], bool],
    inspection_timeout_sec: float,
) -> CycleOutcome:
    """계획된 단계를 순서대로 실행하고 결과를 요약한다.

    장치 제어·카메라 대기·Tk 상태 표시는 전부 콜백으로 주입받는다 — 이 함수
    자체는 하드웨어나 GUI를 몰라서 순서·취소·예외 처리만 하드웨어 없이 테스트할
    수 있다. 실제 장치 호출·타이밍은 :mod:`system_monitor.ui.viewer`가 담당한다.
    """

    def check_cancelled() -> None:
        if is_cancelled():
            raise ProcessCancelled

    completed: list[str] = []
    inspection: InspectionResult | None = None
    status = "completed"
    detail = ""
    try:
        if plan.run_loading:
            set_status("1/3 · OMX1 적재 중 — 물체 탐지 대기")
            run_loading()
            check_cancelled()
            completed.append("OMX1 적재")
            print("[통합 공정] OMX1 적재 완료")

        if plan.run_inspection:
            check_cancelled()
            set_status("2/3 · 새 검사 판정 안정화 대기 중...")
            inspection = wait_for_inspection()
            if inspection is None:
                detail = (
                    f"{inspection_timeout_sec:.0f}초 안에 새 검사 결과가 "
                    "확정되지 않아 OMX2 분류를 건너뛰었습니다."
                )
                status = "partial"
                print(f"[통합 공정] {detail}")
            else:
                completed.append("비전 검사")
                print(
                    f"[통합 공정] 검사 완료: {inspection.result} · "
                    f"전체 {inspection.total_count}, 불량 {inspection.defect_count}"
                )

        if plan.run_sorting and inspection is not None:
            check_cancelled()
            motion = "PASS" if inspection.is_pass else "REJECT"
            set_status(f"3/3 · OMX2 {motion} 분류 중...")
            sort_status = run_sorting(inspection)
            if not sort_status.success:
                raise RuntimeError(sort_status.message or f"OMX2 {motion} 동작 실패")
            completed.append(f"OMX2 {motion} 분류")
            print(f"[통합 공정] {motion} 분류 완료: {sort_status.message}")

        check_cancelled()
    except ProcessCancelled:
        status = "cancelled"
        detail = "사용자 요청으로 중단했습니다."
        print("[통합 공정] 사용자 중단")
    except Exception as error:
        if is_cancelled():
            status = "cancelled"
            detail = "사용자 요청으로 중단했습니다."
            print(f"[통합 공정] 사용자 중단: {error}")
        else:
            status = "failed"
            detail = str(error)
            print(f"[통합 공정] 실패: {error}")

    return CycleOutcome(status=status, completed=tuple(completed), detail=detail)
