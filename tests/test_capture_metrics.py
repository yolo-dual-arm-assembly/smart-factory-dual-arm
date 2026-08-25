"""system_monitor.ui.capture_metrics의 순수 계산 테스트."""
from __future__ import annotations

from system_monitor.ui.capture_metrics import annotate_and_count, update_fps


def test_update_fps_seeds_from_first_sample() -> None:
    assert update_fps(0.0, 0.5) == 2.0


def test_update_fps_blends_with_ema() -> None:
    """순간 FPS는 1/0.1=10, 이전 값 20과 9:1로 섞이면 0.9*20 + 0.1*10 = 19."""
    assert update_fps(20.0, 0.1) == 19.0


class _FakeFrame:
    def __init__(self, marker: str = "raw") -> None:
        self.marker = marker

    def copy(self) -> "_FakeFrame":
        return _FakeFrame(f"{self.marker}-copy")


class _FakeResult:
    def __init__(self, boxes: list[object] | None) -> None:
        self.boxes = boxes
        self.plotted_with: _FakeFrame | None = None

    def plot(self, img: _FakeFrame) -> str:
        self.plotted_with = img
        return "annotated-frame"


def test_annotate_and_count_plots_on_a_copy_and_counts_boxes() -> None:
    """result.plot()은 넘긴 이미지를 직접 수정하므로 원본이 아니라 복사본을 넘겨야 한다."""
    frame = _FakeFrame()
    result = _FakeResult(boxes=[object(), object(), object()])

    annotated, count = annotate_and_count(result, frame)

    assert annotated == "annotated-frame"
    assert count == 3
    assert result.plotted_with is not None
    assert result.plotted_with is not frame
    assert result.plotted_with.marker == "raw-copy"


def test_annotate_and_count_treats_missing_boxes_as_zero() -> None:
    _, count = annotate_and_count(_FakeResult(boxes=None), _FakeFrame())
    assert count == 0
