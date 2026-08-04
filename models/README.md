# models

YOLO 가중치(`*.pt`)를 두는 곳입니다. 용량이 커서 Git에는 올리지 않습니다.

| 파일 | 받는 방법 |
|---|---|
| `yolov8n.pt`, `yolov8m.pt`, `yolo11m-seg.pt` | 통합 GUI를 처음 실행하면 Ultralytics 공식 배포본을 자동으로 내려받습니다 |
| `best.pt` | 직접 학습한 모델입니다. `python -m vision_inspection.train` 실행 후 `runs/custom_detect/weights/best.pt`를 이 폴더로 복사하세요 |

학습한 `best.pt`를 팀원과 공유할 때는 레포에 커밋하지 말고 GitHub Release나
공유 드라이브를 사용합니다. 경로는 코드에서 `common.constants.MODELS_DIR`로
참조하므로 파일만 이 폴더에 두면 됩니다.
