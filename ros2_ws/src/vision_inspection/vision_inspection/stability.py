"""검사 판정이 흔들릴 때 확정을 미루는 안정화 게이트.

로봇팔이 바구니를 내려놓으면 잠시 흔들린다. 그 사이 공 하나가 가려졌다 보였다
하면 개수가 3→2→3으로 튀고, 판정도 PASS→REJECT→PASS로 함께 튄다. 프레임마다
나오는 판정을 그대로 쓰면 분류 팔이 그 튐을 그대로 따라 움직인다.

그래서 **개수가 일정 시간 안정될 때까지 확정하지 않는다.** 판정이 아니라 개수를
기준으로 보는 이유는 두 가지다.

1. 물리적 의미가 그대로 산다 — "바구니가 가만히 있을 때까지 기다린다".
2. 기준 개수(``target_count``)를 바꾸면 장면은 그대로인데 판정만 달라진다.
   개수로 판단하면 이때는 기다리지 않고 즉시 새 판정을 반영할 수 있다.

이 모듈은 PASS/REJECT 조건을 새로 쓰지 않는다. :mod:`inspection_logic`이 만든
결과를 **언제 채택할지**만 정한다. 판정 기준은 계속 그쪽에만 있다.

시간과 표본 번호를 인자로 받으므로 카메라도 시계도 없이 테스트할 수 있다.
"""
from __future__ import annotations

from dataclasses import dataclass

from common.messages import InspectionResult

# 개수가 이 시간(초) 동안 그대로여야 확정한다. 공정 속도에 맞춰 조정할 값이다.
STABLE_HOLD_SEC = 1.0
# 서로 다른 추론을 최소 이만큼 봐야 확정한다.
#
# 캡처 루프는 같은 추론 결과를 여러 프레임에 걸쳐 재사용한다. 시간만 보면 추론이
# 멈춰 버린 경우에도 낡은 개수가 "안정"으로 보인다. 표본 번호가 실제로 바뀐
# 횟수를 함께 세어 그것을 막는다.
MIN_STABLE_SAMPLES = 3


def _counts(result: InspectionResult) -> tuple[int, int]:
    """안정 여부를 판단할 키. 판정(PASS/REJECT)은 일부러 제외한다."""
    return (result.total_count, result.defect_count)


@dataclass(frozen=True)
class StableVerdict:
    """안정화 게이트가 돌려주는 상태."""

    # 래치된 확정 판정. 한 번 확정되면 다음 확정까지 유지된다.
    confirmed: InspectionResult | None = None
    # 지금 개수가 흔들리는 중인가. 확정값과 별개로 화면에 표시한다.
    settling: bool = False
    # 방금 본 순간값. 참고 표시용이며 확정과는 무관하다.
    live: InspectionResult | None = None


class VerdictStabilizer:
    """개수가 안정될 때까지 판정 확정을 미룬다.

    확정값은 **래치**한다. 흔들리는 동안 판정을 지워 버리면 운영자가 마지막 유효
    결과를 잃는다. 대신 ``settling``으로 재평가 중임을 알린다.
    """

    def __init__(
        self,
        hold_sec: float = STABLE_HOLD_SEC,
        min_samples: int = MIN_STABLE_SAMPLES,
    ) -> None:
        self.hold_sec = hold_sec
        self.min_samples = min_samples
        self._confirmed: InspectionResult | None = None
        self._pending: InspectionResult | None = None
        self._pending_since = 0.0
        self._pending_samples = 0
        self._last_sample_id: int | None = None

    def reset(self) -> None:
        """확정값과 대기 상태를 모두 버린다. 카메라를 바꾸거나 놓을 때 부른다."""
        self._confirmed = None
        self._pending = None
        self._pending_since = 0.0
        self._pending_samples = 0
        self._last_sample_id = None

    @property
    def confirmed(self) -> InspectionResult | None:
        return self._confirmed

    def update(
        self, result: InspectionResult, *, sample_id: int, now: float
    ) -> StableVerdict:
        """판정 하나를 넣고 지금의 확정 상태를 돌려받는다.

        ``sample_id``는 추론 결과가 실제로 바뀌었는지 구분하는 값이다. 같은
        추론을 여러 번 넣어도 표본 수는 늘지 않는다.
        """
        fresh = sample_id != self._last_sample_id
        self._last_sample_id = sample_id

        # 이미 확정된 개수와 같으면 기다릴 이유가 없다. 판정만 갈아 끼운다.
        # 기준 개수를 바꿨을 때 즉시 반영되는 것이 이 가지다.
        if self._confirmed is not None and _counts(result) == _counts(self._confirmed):
            self._confirmed = result
            self._pending = None
            self._pending_samples = 0
            return StableVerdict(confirmed=result, settling=False, live=result)

        if self._pending is None or _counts(result) != _counts(self._pending):
            # 새로운 개수가 나타났다. 대기 창을 다시 연다.
            self._pending = result
            self._pending_since = now
            self._pending_samples = 1 if fresh else 0
            return StableVerdict(
                confirmed=self._confirmed, settling=True, live=result
            )

        # 대기 중인 개수와 같다. 시간과 표본을 쌓는다.
        self._pending = result
        if fresh:
            self._pending_samples += 1
        held = now - self._pending_since
        if held >= self.hold_sec and self._pending_samples >= self.min_samples:
            self._confirmed = result
            self._pending = None
            self._pending_samples = 0
            return StableVerdict(confirmed=result, settling=False, live=result)

        return StableVerdict(confirmed=self._confirmed, settling=True, live=result)
