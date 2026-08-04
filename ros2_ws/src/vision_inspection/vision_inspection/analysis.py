from __future__ import annotations

import traceback
from pathlib import Path
from typing import Callable

from common.constants import CONFIDENCE_THRESHOLD

ProgressCallback = Callable[[int, int, Path, bool], None]


def run_analysis(
    model: Callable,
    targets: list[Path],
    result_path_for: Callable[[Path], Path],
    on_progress: ProgressCallback | None = None,
    confidence: float = CONFIDENCE_THRESHOLD,
) -> list[str]:
    """Run the model over targets one at a time; return filenames that failed.

    이미지를 한 장씩 추론해 메모리 사용을 일정하게 유지하고,
    한 장의 실패가 배치 전체를 중단시키지 않게 한다.
    """
    failures: list[str] = []
    total = len(targets)
    for index, image_path in enumerate(targets, start=1):
        succeeded = True
        try:
            result = model(str(image_path), verbose=False, conf=confidence)[0]
            result.save(filename=str(result_path_for(image_path)))
            print(
                f"[{index}/{total}] {image_path.name}: "
                f"{result.verbose().strip()}"
            )
        except Exception:
            traceback.print_exc()
            failures.append(image_path.name)
            succeeded = False
        if on_progress is not None:
            on_progress(index, total, image_path, succeeded)
    return failures
