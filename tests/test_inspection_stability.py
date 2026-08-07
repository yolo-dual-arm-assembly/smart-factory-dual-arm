from common.constants import RobotState
from common.messages import InspectionResult

from vision_inspection.stability import (
    MIN_STABLE_SAMPLES,
    STABLE_HOLD_SEC,
    VerdictStabilizer,
)


def PASS(total: int = 3) -> InspectionResult:
    return InspectionResult(total, 0, RobotState.PASS)


def REJECT(total: int = 2) -> InspectionResult:
    return InspectionResult(total, 0, RobotState.REJECT)


def settle(
    gate: VerdictStabilizer, result: InspectionResult, *, start_id: int = 0
) -> None:
    """개수 하나를 임계까지 밀어 넣어 확정시킨다."""
    for step in range(MIN_STABLE_SAMPLES + 1):
        gate.update(
            result, sample_id=start_id + step, now=step * STABLE_HOLD_SEC
        )


def test_bouncing_counts_never_confirm() -> None:
    """바구니가 흔들려 개수가 계속 바뀌면 아무것도 확정하지 않는다."""
    gate = VerdictStabilizer()
    for step in range(20):
        result = PASS(3) if step % 2 == 0 else REJECT(2)
        verdict = gate.update(result, sample_id=step, now=step * 10.0)

    assert verdict.confirmed is None
    assert verdict.settling is True


def test_confirms_after_hold_time_and_samples() -> None:
    gate = VerdictStabilizer()
    verdict = gate.update(PASS(), sample_id=0, now=0.0)
    assert verdict.confirmed is None and verdict.settling is True

    verdict = gate.update(PASS(), sample_id=1, now=STABLE_HOLD_SEC / 2)
    assert verdict.confirmed is None, "시간이 차기 전에는 확정하면 안 된다"

    verdict = gate.update(PASS(), sample_id=2, now=STABLE_HOLD_SEC)
    assert verdict.confirmed == PASS()
    assert verdict.settling is False


def test_stalled_inference_does_not_confirm() -> None:
    """추론이 멈춰 같은 결과가 재사용되면 시간이 흘러도 확정하지 않는다."""
    gate = VerdictStabilizer()
    verdict = gate.update(PASS(), sample_id=7, now=0.0)
    for step in range(1, 10):
        # sample_id가 그대로 = 추론 스레드가 새 결과를 내지 못한 상태.
        verdict = gate.update(PASS(), sample_id=7, now=step * 10.0)

    assert verdict.confirmed is None
    assert verdict.settling is True


def test_confirmed_verdict_latches_through_shaking() -> None:
    """확정 후 흔들려도 이전 확정값이 유지되고 settling만 켜진다."""
    gate = VerdictStabilizer()
    settle(gate, PASS(3))
    assert gate.confirmed == PASS(3)

    verdict = gate.update(REJECT(2), sample_id=100, now=100.0)
    assert verdict.confirmed == PASS(3), "흔들리는 동안 확정값을 지우면 안 된다"
    assert verdict.settling is True
    assert verdict.live == REJECT(2)


def test_new_stable_count_replaces_confirmed() -> None:
    gate = VerdictStabilizer()
    settle(gate, PASS(3))

    for step in range(MIN_STABLE_SAMPLES + 1):
        verdict = gate.update(
            REJECT(2), sample_id=100 + step, now=1000.0 + step * STABLE_HOLD_SEC
        )

    assert verdict.confirmed == REJECT(2)
    assert verdict.settling is False


def test_same_count_new_verdict_applies_immediately() -> None:
    """기준 개수만 바꿔 판정이 달라지면 기다리지 않고 즉시 반영한다."""
    gate = VerdictStabilizer()
    settle(gate, InspectionResult(3, 0, RobotState.REJECT))  # 기준 1, 공 3개

    # 스핀박스를 3으로 → 같은 개수인데 판정만 PASS로 바뀐다.
    verdict = gate.update(
        InspectionResult(3, 0, RobotState.PASS), sample_id=200, now=2000.0
    )
    assert verdict.confirmed == InspectionResult(3, 0, RobotState.PASS)
    assert verdict.settling is False


def test_reset_clears_confirmed() -> None:
    gate = VerdictStabilizer()
    settle(gate, PASS(3))
    assert gate.confirmed is not None

    gate.reset()

    assert gate.confirmed is None
    verdict = gate.update(PASS(3), sample_id=500, now=5000.0)
    assert verdict.confirmed is None, "reset 후 첫 표본으로 바로 확정하면 안 된다"
