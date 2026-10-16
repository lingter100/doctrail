# GPU 배치 비교 도구 구현

2026-10-16. [사전등록 설계](MEETINGS-GPU-PLACEMENT-PLAN.md)에 따라 새 launcher/probe와 테스트 4개를 구현했다. 이 기록 시점에 공식 tokenizer 준비와 실제 모델 실행은 각각 0회다. 완료된 C4와 host 프로파일은 재실행하지 않는다.

`serve_meeting_gpu_placement.py`는 검증된 기존 실행 명령에서 GPU layers 요청값만 24→28로 바꾼다. 기존 모델·runtime·문법·토큰·90초 요청 제한·로그 비활성화·폐기 방식을 유지한다. 실제 offload 수와 Flash Attention 적용 여부는 unknown이며 요청값과 구분한다. 다운로드와 자동 재시도는 없다.

`probe_meeting_gpu_placement.py`는 고정된 새 중립 입력을 한 번 준비하고, 같은 입력으로 control→candidate를 각 최대 한 번 실행한다. 소스 동결 JSON 자체의 Git 증명 후 허용된 코드와 의존성만 확인한다. 준비 결과와 실행계획도 커밋된 바이트에 연결한다. 원문·token IDs·native 응답은 ignored 로컬 경로에 보관하며 공개 결과는 시간·계수·hash·오류 코드로 제한한다. 닫힌 평가 자료를 읽는 기존 orchestration은 호출하지 않는다.

요청 시간은 검증, template/input tokenize, 전송 직전 증명·예약, native HTTP, 최종 검증·retokenize·필수 저장의 다섯 구간으로 기록한다. 미관측 경계는 null이다. 모두 관측되면 요청 총시간과 단계 합계의 차이를 따로 남긴다. HTTP 상세와 native 자체 시간은 위 구간에 중첩되므로 더하지 않는다. GPU는 장치 전체의 네 시점 관측값이며 프로세스 VRAM이나 최대 사용량이 아니다. RSS는 소유 프로세스의 제한된 표본이다.

실패 후 다음 arm을 실행하려면 소유 프로세스와 drain·watchdog·sampler의 정리가 확인되어야 한다. 전체 cleanup 5초와 요청 시작부터 cleanup 종료까지 120초 조건을 확인한다. 일반 파일 I/O의 강제 선점 중단을 보장하지 않는다. 공통 identity·입력·소스·저장 실패는 나머지 arm도 중단한다.

최종 합성 검사는 **75통과/0실패/0skip, 8.77초**다. 신규37개와 변경하지 않은 transport/launcher 회귀38개이며 Ruff도 통과했다. 검사 전후 NEW4 hash가 같다. Python 자식 프로세스, mock HTTP, 가짜 tokenizer·RSS·GPU를 사용했으므로 실제 자원 적합성이나 품질 통과로 세지 않는다.

초기 pytest27통과와 Ruff18건, 중간 Ruff1건, 이후32/36통과 및 Ruff PIE807을 최종 결과와 분리 보존했다. 부모 검토에서 전체 cleanup 시간, GPU 조회 시간, 최초 저장 오류 보존, asset identity 실패 분류, 의존성 lock 동결, HTTP 구간 중복, 미관측 시간 표시를 보완했다. 앞선 실행 횟수를 최종75에 더하지 않는다.

[구현 영수증](../experiments/results/meetings-gpu-placement-implementation-v1.json) SHA `e410d064ee6fd977986511bc1b74979b5fefb61cf05b22dae369ca9267bbb4a9`, [소스 동결](../data/evaluation/meetings-gpu-placement-source-freeze-v1.json) SHA `116b5325b8b9c1de39c27d486b17d614d9bdef49b32274b14d2838c5a4e9cfaf`다. 코드54+설계/모델/환경5=59bindings, import 후보1420개를 기록했다. 기존85/52바인딩의 working tree와 HEAD 바이트가 같다. 원본 검사 로그는 `.local/gpu-placement-implementation-v1/`에 있다.

```powershell
uv run --no-sync python -m pytest tests/test_meeting_gpu_placement_launcher.py tests/test_probe_meeting_gpu_placement.py tests/test_meeting_thinking_transport.py tests/test_meeting_thinking_compat_launcher.py -q
uv run --no-sync ruff check scripts/serve_meeting_gpu_placement.py scripts/probe_meeting_gpu_placement.py tests/test_meeting_gpu_placement_launcher.py tests/test_probe_meeting_gpu_placement.py
```

소스·동결 커밋과 필수 CI가 통과한 뒤 `python -m scripts.probe_meeting_gpu_placement register`를 한 번 실행한다. 입력이4992–5120tokens 범위를 벗어나면 실패로 닫으며 filler를 조정하거나 다시 준비하지 않는다. 준비 결과와 plan을 커밋한 뒤에만 `run`을 한 번 실행한다. CLI 종료코드뿐 아니라 `resources_all_passed`와 각 arm 상태를 확인한다. 두 실행 완료는 두 자원 검사 성공과 다르다. 성공해도 짧은 marker 출력은928-token decode 부하나 일반 질의응답 품질의 증거가 아니다.
