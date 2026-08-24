# YOLO 학습 데이터셋 (train_set/)

이 폴더는 이 README를 빼고 전부 git이 무시한다. 데이터셋 정의 파일(`data.yaml`)은
여기가 아니라 `ros2_ws/src/vision_inspection/config/data.yaml`에 있다 — 코드가
관리하는 설정은 패키지가 들고, 무거운 데이터만 여기에 둔다.

## 구조

```text
train_set/
├─ 1_ball1/  1_ball2/  2_ball1/  3_ball1/   # 공 촬영 세션 (클래스 0: ball)
├─ other1/ … other5/                        # 오투입 물체 촬영 세션 (클래스 1: others)
├─ no_ball/                                 # 빈 바구니 — 라벨 없음(배경 negative)
├─ coco_others/                             # COCO에서 생성한 혼합 세션 (아래 참고)
├─ coco_src/                                # COCO val2017 원본 (coco_others의 재료)
└─ val/                                     # 중앙 검증 폴더 (아래 참고)
```

촬영 세션 하나의 내부는 이미지와 라벨이 파일명(stem)으로 짝을 이룬다:

```text
1_ball1/
├─ images/train/frame_000000.png …
└─ labels/train/frame_000000.txt …          # no_ball은 labels/가 아예 없다
```

라벨은 객체 하나당 한 줄, `class_id x_center y_center width height` 형식이며
좌표·크기는 이미지 크기 기준 0~1로 정규화한다. 클래스 번호는 `data.yaml`의
`names`(0=ball, 1=others)와 일치해야 한다.

## val/ — 중앙 검증 폴더

모든 세션에서 **연속 프레임 블록 단위**로 떼어 `val/images/<세션>/`,
`val/labels/<세션>/`에 모은다(파일명이 세션마다 겹쳐 평평하게 못 합침).
`other_val` 세션은 **val 전용**이다 — 학습에 안 보인 물체를 others로 잡는지
재는 일반화 측정용이므로 절대 train에 넣지 않는다.

## coco_others/ — 손대지 말 것 (자동 생성)

COCO val2017에서 샘플링해 sports ball→ball(0), 나머지 물체→others(1)로
재매핑한 세션이다. others 일반화용이며 다음 명령으로 만들어진다:

```bash
python -m vision_inspection.coco_import          # 기본 800장, --count로 조절
```

시드가 고정이라 같은 개수면 항상 같은 이미지가 나온다. 손으로 라벨을 고쳐도
재생성하면 사라지므로 편집하지 말 것. `coco_src/`가 없으면 위 명령이 다운로드
안내를 출력한다. 이 세션은 val 추출을 하지 않는다(도메인이 달라 val 지표를
왜곡함 — 일반화 측정은 other_val 담당).

## 새 촬영 세션 추가 절차

1. `train_set/<세션>/images/train/` + `labels/train/`으로 넣는다.
2. `ros2_ws/src/vision_inspection/config/data.yaml`의 `train:`에 한 줄 추가.
3. val 추출을 다시 돌려 `val/images/<세션>/`을 채운다.

## Colab 업로드

Colab 학습용 압축을 만들 때 COCO 폴더는 뺀다(원본 1GB, 세션은 Colab이 재생성):

```bash
tar --exclude=train_set/coco_src --exclude=train_set/coco_others \
    -czf train_set.tar.gz train_set
```

자세한 흐름은 `ros2_ws/src/vision_inspection/notebooks/train_colab.ipynb` 참고.
