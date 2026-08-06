"""Google Colab에서 학습을 돌릴 때 쓰는 Drive 마운트 도우미.

Colab 런타임은 예고 없이 끊기고, 끊기면 ``/content`` 아래는 전부 사라진다.
그래서 체크포인트만은 마운트한 Google Drive에 **직접** 쓰게 한다.
``TrainingConfig.output_dir``을 :func:`drive_runs_dir` 결과로 잡으면 ultralytics가
``last.pt``를 매 epoch Drive에 덮어쓰므로, 세션이 죽어도 진행분이 남는다.

반대로 **학습 데이터는 Drive에 두면 안 된다.** Drive FUSE는 파일 하나당 지연이
커서 3천 장을 매 epoch 읽으면 GPU가 데이터를 기다리며 논다. 압축 파일 하나를
Drive에 올려 두고 로컬 디스크(``/content``)로 풀어 쓰는 쪽이 훨씬 빠르다.
:func:`extract_dataset`이 그 과정을 담당한다.

이 모듈은 Colab 밖에서 import해도 안전하다. ``google.colab``을 실제로 건드리는
것은 :func:`mount_drive`를 불렀을 때뿐이라, 데스크톱에서 돌리는 GUI나 pytest가
이 파일을 읽어도 문제가 없다.
"""
from __future__ import annotations

import importlib.util
import shutil
import tarfile
import time
import zipfile
from pathlib import Path

# Colab이 Drive를 붙이는 표준 위치. drive.mount는 이 아래에 MyDrive를 만든다.
COLAB_MOUNT_POINT = Path("/content/drive")
DRIVE_ROOT_NAME = "MyDrive"
# Drive 안에서 이 프로젝트가 쓸 폴더. 노트북에서 바꿀 수 있다.
DEFAULT_DRIVE_SUBDIR = "smart-factory-dual-arm"

ARCHIVE_SUFFIXES = (".zip", ".tar", ".tar.gz", ".tgz")


def in_colab() -> bool:
    """지금 Colab 런타임에서 실행 중인지."""
    try:
        return importlib.util.find_spec("google.colab") is not None
    except (ImportError, ValueError):
        # find_spec은 점 이름을 받으면 부모 패키지를 먼저 import한다. 데스크톱에는
        # google 패키지 자체가 없어서 None이 아니라 ModuleNotFoundError가 난다.
        return False


def mount_drive(
    mount_point: Path = COLAB_MOUNT_POINT, *, force_remount: bool = False
) -> Path:
    """Google Drive를 마운트하고 ``MyDrive`` 경로를 돌려준다.

    이미 마운트돼 있으면 다시 붙지 않는다. Colab 셀은 여러 번 실행되기 마련이라
    호출이 반복돼도 안전해야 한다.
    """
    if not in_colab():
        raise RuntimeError(
            "Google Colab 런타임이 아닙니다. Drive 마운트는 Colab에서만 됩니다."
        )

    mount_point = Path(mount_point)
    root = mount_point / DRIVE_ROOT_NAME
    if root.is_dir() and not force_remount:
        return root

    from google.colab import drive  # Colab 런타임에만 있는 모듈

    drive.mount(str(mount_point), force_remount=force_remount)
    if not root.is_dir():
        raise RuntimeError(
            f"Drive를 마운트했지만 {root}가 없습니다. 인증을 마쳤는지 확인하세요."
        )
    return root


def drive_dir(
    *parts: str,
    subdir: str = DEFAULT_DRIVE_SUBDIR,
    mount_point: Path = COLAB_MOUNT_POINT,
    create: bool = True,
) -> Path:
    """``MyDrive/<subdir>/<parts...>`` 경로를 만들어 돌려준다."""
    path = mount_drive(mount_point).joinpath(subdir, *parts)
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def drive_runs_dir(
    *,
    subdir: str = DEFAULT_DRIVE_SUBDIR,
    mount_point: Path = COLAB_MOUNT_POINT,
) -> Path:
    """학습 결과를 쌓을 Drive 폴더. ``TrainingConfig.output_dir``에 그대로 넣는다."""
    return drive_dir("runs", subdir=subdir, mount_point=mount_point)


def archive_root(archive: Path) -> str | None:
    """압축 안의 최상위 폴더 이름. 판별할 수 없으면 None.

    첫 항목만 읽는다. 0.5GB짜리 tar.gz의 전체 목록을 훑으면 느리기 때문이다.
    """
    archive = Path(archive)
    if archive.name.lower().endswith(".zip"):
        with zipfile.ZipFile(archive) as bundle:
            names = bundle.namelist()
            first = names[0] if names else ""
    else:
        with tarfile.open(archive) as bundle:
            member = bundle.next()
            first = member.name if member is not None else ""
    root = first.strip("/").split("/")[0]
    return root or None


def extract_dataset(archive: Path, destination: Path, *, force: bool = False) -> Path:
    """Drive에 올려 둔 데이터셋 압축을 로컬 디스크로 푼다.

    ``destination``은 압축을 풀어 넣을 **상위** 폴더다. 압축 안에 ``train_set/``이
    들어 있고 ``destination``이 저장소 루트면 ``<저장소>/train_set/``이 된다.

    이미 풀려 있으면 건너뛴다. 같은 셀을 다시 실행해도 수 GB를 다시 풀지 않게
    하려는 것이다. 다시 풀려면 ``force=True``.

    건너뛸지는 ``destination``이 아니라 **압축의 최상위 폴더**가 이미 채워져
    있는지로 판단한다. ``destination``은 보통 git 클론처럼 원래 다른 파일이 들어
    있는 곳이라, 그것만 보고 판단하면 압축을 영영 풀지 않는다.
    """
    archive = Path(archive)
    destination = Path(destination)
    if not archive.is_file():
        raise FileNotFoundError(
            f"압축 파일이 없습니다: {archive}\n"
            "Google Drive의 해당 폴더에 파일을 올렸는지 확인하세요."
        )
    name = archive.name.lower()
    if not name.endswith(ARCHIVE_SUFFIXES):
        raise ValueError(
            f"지원하지 않는 압축 형식입니다: {archive.name} "
            f"({', '.join(ARCHIVE_SUFFIXES)} 중 하나여야 합니다)"
        )

    root = archive_root(archive)
    target = destination / root if root else destination

    if target.is_dir() and any(target.iterdir()):
        if not force:
            count = sum(1 for path in target.rglob("*") if path.is_file())
            print(f"[colab] {target}에 파일 {count}개가 이미 있어 건너뜁니다.")
            return target
        shutil.rmtree(target)

    destination.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    if name.endswith(".zip"):
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(destination)
    else:
        with tarfile.open(archive) as bundle:
            # 파이썬 3.12부터 filter 인자가 없으면 경고가 뜬다. 신뢰하는 내 파일이라
            # data 필터로 충분하다(절대경로·상위경로 탈출을 막아 준다).
            bundle.extractall(destination, filter="data")

    elapsed = time.perf_counter() - started
    count = sum(1 for path in target.rglob("*") if path.is_file())
    print(f"[colab] {target}에 파일 {count}개 해제 ({elapsed:.0f}초)")
    return target
