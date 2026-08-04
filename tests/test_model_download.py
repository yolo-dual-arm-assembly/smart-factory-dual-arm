from pathlib import Path

import pytest

import vision_inspection.models
from vision_inspection.models import (
    DOWNLOADABLE_MODEL_FILENAMES,
    MODEL_FILENAMES,
    download_model,
    missing_model_paths,
)


def test_missing_model_paths_returns_only_missing_models(tmp_path: Path) -> None:
    existing_model = tmp_path / DOWNLOADABLE_MODEL_FILENAMES[0]
    existing_model.touch()

    assert missing_model_paths(tmp_path) == [
        tmp_path / filename for filename in DOWNLOADABLE_MODEL_FILENAMES[1:]
    ]


def test_missing_model_paths_excludes_local_custom_models(tmp_path: Path) -> None:
    assert "best.pt" in MODEL_FILENAMES
    assert "best.pt" not in DOWNLOADABLE_MODEL_FILENAMES
    assert tmp_path / "best.pt" not in missing_model_paths(tmp_path)


def test_download_model_returns_downloaded_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model_path = tmp_path / "yolov8n.pt"

    def fake_download(path: Path) -> str:
        path.write_bytes(b"model")
        return str(path)

    monkeypatch.setattr(vision_inspection.models, "attempt_download_asset", fake_download)

    assert download_model(model_path) == model_path


def test_download_model_raises_when_file_was_not_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model_path = tmp_path / "yolov8n.pt"
    monkeypatch.setattr(
        vision_inspection.models,
        "attempt_download_asset",
        lambda path: str(path),
    )

    with pytest.raises(FileNotFoundError, match="모델 다운로드에 실패했습니다"):
        download_model(model_path)
