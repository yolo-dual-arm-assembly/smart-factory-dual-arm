from pathlib import Path

from vision_inspection.analysis import run_analysis


class FakeResult:
    def save(self, filename: str) -> None:
        Path(filename).write_bytes(b"result")

    def verbose(self) -> str:
        return "1 object"


def fake_model(path: str, **_kwargs) -> list[FakeResult]:
    if "bad" in path:
        raise RuntimeError("boom")
    return [FakeResult()]


def test_run_analysis_continues_after_single_failure(tmp_path: Path) -> None:
    targets = [tmp_path / "a.jpg", tmp_path / "bad.jpg", tmp_path / "c.jpg"]
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    progress: list[tuple[int, bool]] = []

    failures = run_analysis(
        fake_model,
        targets,
        lambda image_path: output_dir / f"det_{image_path.name}",
        on_progress=lambda index, total, image_path, ok: progress.append((index, ok)),
    )

    assert failures == ["bad.jpg"]
    assert (output_dir / "det_a.jpg").is_file()
    assert (output_dir / "det_c.jpg").is_file()
    assert not (output_dir / "det_bad.jpg").exists()
    assert progress == [(1, True), (2, False), (3, True)]


def test_run_analysis_reports_all_failures(tmp_path: Path) -> None:
    targets = [tmp_path / "bad1.jpg", tmp_path / "bad2.jpg"]

    failures = run_analysis(
        fake_model,
        targets,
        lambda image_path: tmp_path / f"det_{image_path.name}",
    )

    assert failures == ["bad1.jpg", "bad2.jpg"]
