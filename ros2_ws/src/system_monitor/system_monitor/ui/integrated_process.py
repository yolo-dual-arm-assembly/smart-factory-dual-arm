"""통합 공정에서 실행할 단계를 장치 상태로 결정하는 순수 로직.

실제 장치 제어와 Tk 위젯 갱신은 :mod:`system_monitor.ui.viewer`가 담당한다.
여기는 버튼을 누른 시점의 네 장치 상태와 설정 파일 준비 여부만 받아서 어떤
단계를 실행하고 건너뛸지 정한다. 하드웨어 없이도 공정 계획을 테스트하기 위해
GUI와 장치 모듈을 import하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass


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
