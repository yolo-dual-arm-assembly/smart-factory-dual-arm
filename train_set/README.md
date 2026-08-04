# 간단한 YOLO 학습 데이터 구성

이미지와 라벨 파일의 이름을 똑같이 맞춥니다.

```text
train_set/
├─ data.yaml
├─ images/
│  ├─ train/
│  │  └─ sample01.jpg
│  └─ val/
│     └─ sample02.jpg
└─ labels/
   ├─ train/
   │  └─ sample01.txt
   └─ val/
      └─ sample02.txt
```

각 라벨 파일은 객체 하나당 한 줄이며 다음 형식을 사용합니다.

```text
class_id x_center y_center width height
```

좌표와 크기는 이미지 전체 크기를 기준으로 `0`부터 `1` 사이로 정규화합니다.
클래스 번호는 `0`부터 시작하며 `data.yaml`의 `names`와 일치해야 합니다.

예를 들어 클래스 `0`인 객체가 이미지 정중앙에 있고 너비와 높이가 이미지의
절반이라면 라벨은 다음과 같습니다.

```text
0 0.5 0.5 0.5 0.5
```

전체 이미지 중 약 80%는 `train`, 20%는 `val`에 넣는 것으로 시작하면 됩니다.
라벨링 도구에서 내보낼 때 `YOLO Detection` 형식을 선택하면 라벨 파일을 직접
계산할 필요가 없습니다.
