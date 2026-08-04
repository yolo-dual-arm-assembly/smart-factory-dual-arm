# YOLO 이미지 분석 도구

`object` 폴더의 이미지를 YOLO 모델로 분석하고, 원본 이미지와 분석 결과를
나란히 보여 주는 Tkinter GUI 프로그램입니다. Windows와 Linux에서 같은 코드로
동작합니다. 분석 결과는 모델별로 `result` 폴더에 저장됩니다.

## 1. 준비 사항

- Windows 10/11 또는 Linux
- **64비트 Python 3.11 이상** (3.11 · 3.12 · 3.13 사용 가능)
- 인터넷 연결(최초 패키지 및 모델 설치 시 필요)

### Python 인터프리터

| 항목 | 값 |
| --- | --- |
| 최소 버전 | **3.11** (`pyproject.toml`의 `requires-python = ">=3.11"`) |
| 동작 확인 버전 | **3.11.9** (64비트, Windows 11) |
| 권장 배포판 | [python.org](https://www.python.org/downloads/) 공식 64비트 빌드 |
| 확인 명령 | `python -c "import sys; print(sys.version, sys.executable)"` |

버전 표시에 `64 bit (AMD64)`와 `3.11` 이상이 함께 나와야 합니다.

**MSYS2/MinGW Python(`C:\msys64\ucrt64\bin\python.exe`)은 사용할 수 없습니다.**
`pip install`로도 해결되지 않습니다. PyPI가 배포하는 `torch`·`opencv-python`
휠은 표준 CPython(`win_amd64`) ABI용이라 MinGW 빌드에는 설치되지 않고,
`torch`는 MSYS2 빌드 자체가 없습니다.

Windows에서 Python 설치 시 `Add python.exe to PATH`와 Python Launcher 항목을
선택하십시오. Linux에서는 배포판 패키지의 `python3`(3.11 이상)와 함께
`python3-tk`(Tkinter)가 설치되어 있어야 합니다.

```bash
sudo apt install python3 python3-venv python3-tk   # Debian/Ubuntu 예시
```

### 인터프리터를 잘못 골라도 실행됩니다

`main.py`는 무거운 라이브러리를 불러오기 전에 현재 Python을 먼저 점검합니다.
의존성이 없는 Python(예: MSYS2 Python, 패키지를 설치하지 않은 다른 Python)으로
실행하면, 의존성이 설치된 Python을 직접 찾아 그쪽으로 넘겨 실행합니다.

```text
$ C:/msys64/ucrt64/bin/python.exe main.py
[bootstrap] 의존성이 설치된 Python으로 실행합니다: C:\...\Python311\python.exe
→ 그대로 GUI가 열립니다
```

찾는 순서는 프로젝트 가상환경(`.venv`) → Windows Python Launcher(`py -0p`)가
알려 주는 설치 목록 → `PATH`의 `python`/`python3`이며, Windows와 Linux 모두
같은 방식으로 동작합니다. 쓸 수 있는 Python이 하나도 없을 때만 무엇을 설치해야
하는지 안내하고 멈춥니다.

프로젝트 최상위 폴더에는 최소한 다음 파일과 폴더가 있어야 합니다.

```text
YOLO_Test/
├─ main.py                  # 통합 GUI 실행 진입점
├─ common/                  # 전 노드 공용: 상수·메시지 규격·카메라·시리얼·로봇 통신
├─ ros2_ws/
│  └─ src/
│     ├─ project_interfaces/  # 노드 간 메시지·서비스·액션 정의
│     ├─ vision_inspection/   # YOLO 검사 노드           (1·2번)
│     ├─ omx1_loading/        # 적재 로봇 노드·좌표 변환 (3번)
│     ├─ omx2_sorting/        # 분류 로봇               (4번)
│     ├─ system_coordinator/  # 전체 순서 제어           (5번)
│     └─ system_monitor/      # 상태 표시·운영 GUI       (5번)
├─ models/                  # YOLO 가중치 (Git 제외)
├─ docs/                    # 구조·통신 규격·보정 문서
├─ requirements.txt
├─ pyproject.toml
├─ tests/
├─ train_set/
├─ object/
└─ result/
```

노드 구성과 담당은 [`docs/system_architecture.md`](docs/system_architecture.md),
노드 사이에 주고받는 값의 규격은
[`docs/communication_protocol.md`](docs/communication_protocol.md),
ROS2 빌드·실행은 [`ros2_ws/README.md`](ros2_ws/README.md)에 있습니다.

`object`와 `result` 폴더는 프로그램이 없으면 자동으로 만듭니다. 모델 파일
`yolov8n.pt`, `yolov8m.pt`, `yolo11m-seg.pt`가 없으면 프로그램을 처음 실행할 때
Ultralytics 공식 배포본을 `models/` 폴더에 자동으로 다운로드합니다.

## 2. 프로젝트 폴더에서 터미널 열기

**Windows** — 파일 탐색기에서 프로젝트 폴더를 연 뒤 주소 표시줄에
`powershell`을 입력하거나, PowerShell에서 직접 프로젝트 폴더로 이동합니다.

```powershell
Set-Location "C:\프로젝트를\저장한\경로\YOLO"
Get-Location
Get-ChildItem
```

**Linux**

```bash
cd ~/프로젝트를/저장한/경로/YOLO
pwd
ls
```

출력 목록에 `main.py`와 `requirements.txt`가 보여야 합니다. 프로젝트 복사본이
여러 개 있다면, 패키지를 설치한 폴더와 프로그램을 실행하는 폴더가 같은지 특히
확인하십시오.

## 3. 가상환경 만들기

가상환경은 OS마다 새로 만들어야 합니다. 실행 파일 경로가 Windows는
`.venv\Scripts\`, Linux는 `.venv/bin/`으로 달라서 한쪽에서 만든 `.venv`를
다른 OS로 복사해 쓸 수 없습니다. `.venv/`는 `.gitignore` 대상입니다.

**Windows** — 설치된 Python 목록을 확인하고 3.11 이상으로 만듭니다.

```powershell
py -0p
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

PowerShell 실행 정책 때문에 활성화가 차단되면 현재 PowerShell 창에서만 정책을
완화한 뒤 다시 활성화합니다.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

**Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

활성화되면 명령 프롬프트 앞에 `(.venv)`가 표시됩니다.

## 4. 패키지 설치

반드시 프로젝트 폴더에서 다음 명령을 실행합니다.

```powershell
python -m pip install --upgrade pip
python -m pip install -r .\requirements.txt
```

설치가 끝난 뒤 현재 Python과 `pip`가 모두 `.venv`를 가리키는지 확인합니다.

```powershell
python -c "import sys; print(sys.executable)"
python -m pip --version
```

두 출력 경로에 모두 프로젝트의 `.venv`가 포함되어 있어야 합니다. 이어서 주요
패키지를 실제로 import할 수 있는지 확인합니다.

```powershell
python -c "from PIL import Image; from ultralytics import YOLO; print('의존성 확인 완료')"
python -m tkinter
```

마지막 명령을 실행했을 때 작은 Tk 창이 나타나면 GUI 실행 준비가 끝난 것입니다.

### 가상환경을 활성화하지 않고 설치하는 방법

활성화 과정이 번거롭거나 셸 설정의 영향을 피하고 싶다면 가상환경의 Python을
직접 지정해도 됩니다.

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
```

이 방식을 사용했다면 실행할 때도 같은 Python을 직접 지정합니다.

```powershell
.\.venv\Scripts\python.exe .\main.py
```

Linux에서는 `.venv/bin/python`을 같은 방식으로 지정합니다.

```bash
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python main.py
```

## 5. 분석할 이미지 준비

분석할 이미지를 프로젝트의 `object` 폴더에 넣습니다. 지원 확장자는 다음과
같습니다.

- `.png`
- `.jpg`
- `.jpeg`
- `.bmp`

모델 파일은 처음 실행할 때 자동으로 준비되며, 이후에는 다운로드한 파일을
재사용합니다.

## 6. 프로그램 실행

프로젝트 폴더에서 `main.py`를 실행합니다. 가상환경을 활성화하지 않았거나
인터프리터를 잘못 골랐더라도 `main.py`가 알아서 전환하므로 아래 명령이면
됩니다.

```powershell
python .\main.py     # Windows (PowerShell)
```

```bash
python3 main.py      # Linux
```

패키지별 도구는 모듈 실행 방식을 씁니다. 노드 코드가
`ros2_ws/src/<패키지>/<패키지>/`에 있으므로, 이 명령들을 쓰기 전에 한 번만
프로젝트를 개발 모드로 설치하십시오. `main.py`는 설치 없이도 동작합니다.

```powershell
python -m pip install -e .    # 최초 1회
```

```powershell
python -m vision_inspection.train              # 학습
python -m vision_inspection.detect             # 웹캠 CLI 탐지
python -m system_coordinator.main_controller   # 장비 없이 공정 흐름 확인
yolo-app                                       # 통합 GUI (설치 후 어느 폴더에서나)
```

ROS2 노드(`vision_node`, `loading_node`) 빌드와 실행은 리눅스에서만 하며 절차는
[`ros2_ws/README.md`](ros2_ws/README.md)에 있습니다.

프로그램을 실행하면 `object` 폴더의 이미지 목록이 왼쪽에 표시됩니다. 이미지를
선택하면 오른쪽에서 원본과 분석 결과를 비교할 수 있습니다. 기존 결과가 있으면
시작할 때 유지할지 다시 분석할지 묻습니다.

처음 실행할 때 모델 파일이 없으면 GUI 하단 콘솔에 다운로드 진행 상황이
표시됩니다. 세 모델을 모두 준비한 뒤 분석을 시작하므로 첫 실행에는 인터넷 연결과
추가 시간이 필요합니다. 이미 존재하는 모델 파일은 다시 다운로드하지 않습니다.

상단의 모델 선택 목록에서 다음 모델을 전환할 수 있습니다.

- `best.pt` (Robot Custom): `python -m vision_inspection.train`으로 직접 학습한 모델.
  파일이 있을 때만 목록에 표시됩니다.
- `yolov8n.pt`: 가장 가볍고 빠른 객체 탐지 모델
- `yolov8m.pt`: 속도와 정확도의 균형을 고려한 객체 탐지 모델
- `yolo11m-seg.pt`: 객체별 마스크를 생성하는 인스턴스 세그멘테이션 모델

`best.pt`는 자동 다운로드 대상이 아닙니다. `train_set` 데이터셋을 준비한 뒤
다음 명령으로 학습하면 `runs/custom_detect/weights/best.pt`가 생성되며, 이를
`models/` 폴더에 복사하면 Robot Custom 모델이 활성화됩니다. 데이터셋 정의는
`ros2_ws/src/vision_inspection/config/data.yaml`, 이미지와 라벨은 `train_set/`에
둡니다.

```powershell
python -m vision_inspection.train
python -m vision_inspection.train --epochs 100 --batch 16  # 하이퍼파라미터 변경 예시
```

결과 파일은 다음 형식의 폴더에 저장됩니다.

```text
result/
├─ best/
├─ yolov8n/
├─ yolov8m/
└─ yolo11m-seg/
```

모델별 폴더가 분리되어 있으므로 모델을 전환해도 다른 모델의 결과를 덮어쓰지
않습니다.

### 카메라 선택

노트북 내장캠과 USB 웹캠처럼 카메라가 여러 대 연결되어 있으면 사이드바의
`카메라 선택` 목록에서 사용할 장치를 고릅니다. 여기서 고른 카메라를 `웹캠
실시간 탐지`와 `OMX 비전 제어`가 함께 사용합니다.

- 프로그램을 시작할 때 연결된 카메라를 한 번 조회합니다. 두 대 이상 잡히면
  목록이 활성화되고, 한 대뿐이면 그 장치가 자동으로 선택됩니다.
- 실행 중에 웹캠을 연결하거나 분리했다면 `다시 검색`을 누릅니다. 검색은 장치를
  실제로 열어 확인하므로 몇 초가 걸리며, 웹캠 창이나 OMX 작업이 실행 중이면
  카메라가 점유되어 검색할 수 없습니다.
- 카메라를 하나도 찾지 못하면 0~3번이 목록에 표시되므로 번호를 직접 고를 수
  있습니다.

## 7. OMX Mouse 관절 교시

메인 GUI의 `OMX 비전 제어`에서 `Mouse 관절 교시 모드`를 엽니다. 로봇을 연결한
뒤 `Mouse 위치 고정`을 먼저 누르고, 그리퍼를 수동으로 해당 위치 위에 맞춘 다음
`고정 위치 + 실제 관절값 저장`을 누릅니다. 로봇팔이 Mouse를 가려도 고정된 좌표가
유지됩니다. 화면의 좌상·상·우상, 좌·중앙·우, 좌하·하·우하에 Mouse를 놓아 9개
교시점을 만드는 것을 권장합니다.

교시점이 4개 이상이고 서로 둘러싸인 영역이 만들어지면 `교시값으로 Mouse 이동`을
사용할 수 있습니다. 자동 이동은 교시 영역 안에서만 허용되며, 카메라 위치나
해상도가 변경되면 교시 데이터를 다시 만들어야 합니다. 교시 데이터는 로컬 파일
`ros2_ws/src/omx1_loading/config/omx_mouse_teaching.json`에 저장되며, 장비마다 값이 달라
Git에는 올리지 않습니다. 좌표 보정 파일도 마찬가지로
같은 폴더의 `calibration.json`에 저장됩니다.

## 8. 자주 발생하는 오류

### `ModuleNotFoundError: No module named 'PIL'`

`PIL`은 `Pillow` 패키지가 제공하는 모듈입니다. 대부분 패키지를 설치한 Python과
프로그램을 실행한 Python이 서로 다를 때 이 오류가 발생합니다.

`main.py`로 실행하면 이 상황을 자동으로 넘겨주므로 보통은 이 오류를 보지
않습니다. `python -m vision_inspection.train`처럼 다른 진입점을 쓰다가 오류가 났다면
`python main.py`로 실행해 보십시오.

직접 고치려면 프로젝트 폴더에서 가상환경의 Python을 명시해 다시 설치하고
실행합니다.

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
.\.venv\Scripts\python.exe -c "from PIL import Image; print('Pillow 정상')"
.\.venv\Scripts\python.exe .\main.py
```

`pip install ...`처럼 `pip`만 단독으로 실행하지 말고, 항상
`python -m pip ...` 또는 `.\.venv\Scripts\python.exe -m pip ...` 형식을
사용하십시오.

### `ModuleNotFoundError: No module named 'ultralytics'`

현재 실행 중인 Python에 의존성이 설치되지 않은 상태입니다.

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
```

설치 중 오류가 발생했다면 마지막 오류 메시지를 확인합니다. Python 버전과 경로는
다음 명령으로 확인할 수 있습니다.

```powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pip --version
```

### `No module named '_tkinter'` 또는 GUI 창이 열리지 않음

현재 Python에 Tkinter가 포함되지 않았을 수 있습니다. Windows는 python.org의
64비트 Python(3.11 이상)을 설치할 때 `tcl/tk and IDLE` 항목을 포함한 뒤
가상환경을 다시 만드십시오. Linux는 Tkinter가 별도 패키지입니다.

```bash
sudo apt install python3-tk    # Debian/Ubuntu
sudo dnf install python3-tkinter    # Fedora
```

### 모델 파일이 없다는 메시지

프로그램 시작 시 누락된 모델은 자동으로 다운로드합니다. 다운로드 오류가
표시되면 인터넷 연결과 디스크 여유 공간을 확인한 뒤 프로그램을 다시 실행합니다.
파일명을 임의로 바꾸면 프로그램이 찾지 못합니다.

자동 다운로드가 계속 실패하면 프로젝트 폴더에서 다음 명령을 실행해 모델을
수동으로 준비할 수 있습니다.

```powershell
.\.venv\Scripts\python.exe -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"
.\.venv\Scripts\python.exe -c "from ultralytics import YOLO; YOLO('yolov8m.pt')"
.\.venv\Scripts\python.exe -c "from ultralytics import YOLO; YOLO('yolo11m-seg.pt')"
```

### 입력 이미지가 없다는 메시지

이미지를 `main.py` 옆이 아니라 `object` 폴더 안에 넣었는지, 파일 확장자가
지원 목록에 포함되는지 확인한 뒤 프로그램을 다시 실행합니다.

### 설치는 했는데 계속 같은 모듈 오류가 발생함

아래 두 명령의 경로가 같은 Python 환경을 가리키는지 비교합니다.

```powershell
python -c "import sys; print(sys.executable)"
python -m pip --version
```

예를 들어 프로그램은 `C:\msys64\ucrt64\bin\python3.14.exe`로 실행하면서 패키지는
다른 Python 또는 `.venv`에 설치했다면 모듈을 찾을 수 없습니다. VS Code를
사용한다면 `Python: Select Interpreter`에서 패키지를 설치한 Python을
선택하십시오. 프로젝트에 가상환경을 만들었다면 `.venv\Scripts\python.exe`,
아니면 `C:\Users\<사용자>\AppData\Local\Programs\Python\Python3xx\python.exe`
같은 표준 설치 경로를 고르면 됩니다.

**MSYS2 Python(`C:\msys64\ucrt64\bin\python.exe`)으로는 실행할 수 없습니다.**
`pip install`로 의존성을 채우려 해도 실패합니다. PyPI가 제공하는 `torch`,
`opencv-python`, `numpy` 휠은 표준 CPython(`win_amd64`) ABI용이라 MinGW로 빌드된
MSYS2 Python에는 설치되지 않고, `torch`는 MSYS2 빌드 자체가 없습니다.
[python.org](https://www.python.org/downloads/windows/) 배포판이나 가상환경을
사용하십시오.

VS Code가 자꾸 엉뚱한 Python을 고른다면 `.vscode/settings.json`에
`python.defaultInterpreterPath`로 인터프리터 경로를 박아 두지 않았는지
확인합니다. 실행 파일 경로가 리눅스는 `.venv/bin/python`, 윈도우는
`.venv\Scripts\python.exe`로 달라서, 한쪽 경로를 적어 두면 다른 OS에서는
그 경로를 찾지 못하고 PATH에 있던 다른 Python이 선택됩니다.

## 9. 개발 확인

코드를 수정한 뒤에는 최소한 문법 검사를 실행합니다.

```powershell
python -m compileall common main.py ros2_ws/src
```

단위 테스트(모델 다운로드·분석 루프 로직)는 다음과 같이 실행합니다.

```powershell
python -m pip install pytest
python -m pytest -q
```
