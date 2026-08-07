import os
from pathlib import Path

import pytest

from vision_inspection.hf_upload import (
    check_repo_id,
    model_upload_files,
    resolve_token,
    upload_dataset,
    upload_model,
)


class FakeApi:
    """huggingface_hub.HfApi 흉내. 호출 내용만 기록한다."""

    def __init__(self, *, existing: set[str] | None = None) -> None:
        self.created: list[dict] = []
        self.uploaded: list[dict] = []
        self._existing = existing or set()

    def create_repo(self, **kwargs) -> None:
        self.created.append(kwargs)

    def upload_file(self, **kwargs) -> None:
        self.uploaded.append(kwargs)

    def file_exists(self, *, repo_id: str, filename: str, repo_type: str) -> bool:
        return filename in self._existing


def make_run_dir(tmp_path: Path) -> Path:
    run_dir = tmp_path / "runs" / "custom_detect"
    (run_dir / "weights").mkdir(parents=True)
    (run_dir / "weights" / "best.pt").write_bytes(b"weights")
    (run_dir / "results.png").write_bytes(b"png")
    return run_dir


def test_check_repo_id_rejects_placeholder() -> None:
    with pytest.raises(ValueError, match="아이디/저장소이름"):
        check_repo_id("<아이디>/<모델-레포>")
    with pytest.raises(ValueError):
        check_repo_id("no-slash")
    assert check_repo_id(" gildong/ball ") == "gildong/ball"


def test_upload_model_sends_existing_files_only(tmp_path: Path) -> None:
    run_dir = make_run_dir(tmp_path)  # args.yaml은 일부러 없다
    fake = FakeApi()

    url = upload_model(
        "gildong/ball",
        model_upload_files(run_dir),
        token="tok",
        api_factory=lambda token: fake,
    )

    assert url == "https://huggingface.co/gildong/ball"
    assert fake.created[0]["repo_type"] == "model"
    assert fake.created[0]["exist_ok"] is True
    names = [call["path_in_repo"] for call in fake.uploaded]
    assert names == ["best.pt", "results.png"], "없는 args.yaml은 건너뛰어야 한다"


def test_upload_model_requires_best_pt(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="필수 파일"):
        upload_model(
            "gildong/ball",
            model_upload_files(tmp_path / "빈폴더"),
            token="tok",
            api_factory=lambda token: FakeApi(),
        )


def test_upload_dataset_skips_when_already_uploaded(tmp_path: Path) -> None:
    archive = tmp_path / "train_set.tar.gz"
    archive.write_bytes(b"data")
    fake = FakeApi(existing={"train_set.tar.gz"})

    upload_dataset(
        "gildong/ball-data", archive, token="tok", api_factory=lambda token: fake
    )
    assert fake.uploaded == [], "이미 올라간 압축을 다시 올리면 안 된다"

    upload_dataset(
        "gildong/ball-data",
        archive,
        token="tok",
        force=True,
        api_factory=lambda token: fake,
    )
    assert [call["path_in_repo"] for call in fake.uploaded] == ["train_set.tar.gz"]
    assert fake.created[0]["repo_type"] == "dataset"


def test_missing_token_raises_with_guidance(tmp_path: Path) -> None:
    archive = tmp_path / "train_set.tar.gz"
    archive.write_bytes(b"data")
    old = os.environ.pop("HF_TOKEN", None)
    try:
        with pytest.raises(RuntimeError, match="HF_TOKEN"):
            upload_dataset(
                "gildong/ball-data", archive, api_factory=lambda token: FakeApi()
            )
    finally:
        if old is not None:
            os.environ["HF_TOKEN"] = old


def test_resolve_token_prefers_argument_then_env() -> None:
    old = os.environ.pop("HF_TOKEN", None)
    try:
        assert resolve_token("직접") == "직접"
        assert resolve_token(None) is None
        os.environ["HF_TOKEN"] = "환경변수"
        assert resolve_token(None) == "환경변수"
    finally:
        os.environ.pop("HF_TOKEN", None)
        if old is not None:
            os.environ["HF_TOKEN"] = old
