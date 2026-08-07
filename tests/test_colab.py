import tarfile
import zipfile
from pathlib import Path

import pytest

from vision_inspection.colab import (
    archive_probe,
    drive_runs_dir,
    extract_dataset,
    in_colab,
    mount_drive,
)


def make_tree(root: Path) -> Path:
    """압축할 데이터셋 흉내. train_set/<폴더>/images|labels/<split>/ 구조."""
    images = root / "train_set" / "1_ball1" / "images" / "train"
    labels = root / "train_set" / "1_ball1" / "labels" / "train"
    images.mkdir(parents=True)
    labels.mkdir(parents=True)
    (images / "frame_000000.jpg").write_bytes(b"jpeg")
    (labels / "frame_000000.txt").write_text("0 0.5 0.5 0.1 0.1\n", encoding="utf-8")
    return root / "train_set"


def make_tarball(tmp_path: Path) -> Path:
    source = make_tree(tmp_path / "source")
    archive = tmp_path / "train_set.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(source, arcname="train_set")
    return archive


def make_zip(tmp_path: Path) -> Path:
    source = make_tree(tmp_path / "source_zip")
    archive = tmp_path / "train_set.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                bundle.write(path, Path("train_set") / path.relative_to(source))
    return archive


def test_archive_probe_reads_root_and_first_file(tmp_path: Path) -> None:
    for archive in (make_tarball(tmp_path), make_zip(tmp_path)):
        root, probe = archive_probe(archive)
        assert root == "train_set"
        # 폴더가 아니라 실제 파일이어야 한다. 폴더로는 이미 풀렸는지 알 수 없다.
        assert probe is not None and not probe.endswith("/")
        assert probe.startswith("train_set/")


def test_extract_when_target_folder_exists_with_tracked_file(tmp_path: Path) -> None:
    """``train_set/``이 README.md 하나만 담은 채 이미 있어도 풀어야 한다.

    회귀 방지: ``train_set/README.md``는 git에 추적되는 파일이라 클론만 해도
    폴더가 생긴다. 폴더 존재나 '비어 있지 않음'으로 판단하면 압축을 영영
    풀지 않는다 (Colab에서 실제로 겪은 문제).
    """
    archive = make_tarball(tmp_path)
    repo = tmp_path / "repo"
    (repo / "train_set").mkdir(parents=True)
    readme = repo / "train_set" / "README.md"
    readme.write_text("데이터셋 폴더 규칙", encoding="utf-8")

    extract_dataset(archive, repo)

    assert (repo / "train_set/1_ball1/images/train/frame_000000.jpg").is_file()
    assert (repo / "train_set/1_ball1/labels/train/frame_000000.txt").is_file()
    # 추적 중인 README는 건드리지 않는다.
    assert readme.is_file()


def test_extract_into_non_empty_destination(tmp_path: Path) -> None:
    """저장소 루트처럼 이미 파일이 있는 폴더에도 풀려야 한다.

    회귀 방지: 목적지가 비어 있는지로 건너뛸지 판단하면, git 클론 위에 풀 때
    영영 압축을 풀지 않는다.
    """
    archive = make_tarball(tmp_path)
    repo = tmp_path / "repo"
    (repo / "ros2_ws").mkdir(parents=True)
    (repo / "main.py").write_text("x", encoding="utf-8")

    extracted = extract_dataset(archive, repo)

    assert extracted == repo / "train_set"
    assert (repo / "train_set/1_ball1/images/train/frame_000000.jpg").is_file()
    assert (repo / "train_set/1_ball1/labels/train/frame_000000.txt").is_file()
    # 원래 있던 파일은 그대로 둔다.
    assert (repo / "main.py").is_file()


def test_extract_skips_when_already_extracted(tmp_path: Path) -> None:
    archive = make_tarball(tmp_path)
    repo = tmp_path / "repo"
    extract_dataset(archive, repo)

    marker = repo / "train_set" / "이미풀림.txt"
    marker.write_text("keep", encoding="utf-8")
    extract_dataset(archive, repo)

    assert marker.is_file(), "건너뛰지 않고 다시 풀어 기존 내용을 지웠다"


def test_extract_force_replaces_existing(tmp_path: Path) -> None:
    archive = make_tarball(tmp_path)
    repo = tmp_path / "repo"
    extract_dataset(archive, repo)
    stale = repo / "train_set" / "낡은파일.txt"
    stale.write_text("old", encoding="utf-8")

    extract_dataset(archive, repo, force=True)

    assert not stale.exists()
    assert (repo / "train_set/1_ball1/images/train/frame_000000.jpg").is_file()


def test_extract_reports_missing_archive(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="압축 파일이 없습니다"):
        extract_dataset(tmp_path / "없음.tar.gz", tmp_path / "repo")


def test_extract_rejects_unsupported_format(tmp_path: Path) -> None:
    archive = tmp_path / "train_set.rar"
    archive.write_bytes(b"nope")

    with pytest.raises(ValueError, match="지원하지 않는 압축 형식"):
        extract_dataset(archive, tmp_path / "repo")


def test_drive_helpers_refuse_outside_colab() -> None:
    """데스크톱에서도 import와 판별이 안전해야 한다.

    find_spec은 점 이름을 받으면 부모 패키지를 import하므로, google 패키지가
    없는 환경에서 예외가 새어 나오지 않는지 확인한다.
    """
    assert in_colab() is False
    with pytest.raises(RuntimeError, match="Colab"):
        mount_drive()
    with pytest.raises(RuntimeError, match="Colab"):
        drive_runs_dir()
