# 회의 기능의 로컬 4B 후보 비교

## 선택 근거와 경계

기존 Qwen3-1.7B 개발 v11은 후보 안의 영어 근거를 버리는 추가 BM25 단계를 제거했지만 날짜·인용 대상을 바꾸고 담당자 미정 작업을 미해결 사항으로 분류했다. 형식 통과와 원문 인용 일치는 의미 정확성을 보장하지 않았다. v1~v11 결과와 실제 Java 운영 v1/v2 실패를 보존한다.

다음 후보 하나는 Qwen3-4B-Instruct-2507의 Q5_K_M 양자화다. [원본 Qwen 모델](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507)은 Apache-2.0이며 비사고형 지시 모델이다. GGUF는 [Unsloth 배포](https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/blob/a06e946bb6b655725eafa393f4a9745d460374c9/Qwen3-4B-Instruct-2507-Q5_K_M.gguf)이고 Qwen 공식 양자화라고 기록하지 않는다. 원본과 양자화의 revision, 파일 크기와 SHA256은 별도 manifest로 고정한다.

현재 GPU는 6GB이므로 4B BF16 전체 적재 대신 약2.69GiB의 양자화 가중치를 선택했다. 메모리 적합성과 품질·속도는 실행 전 추정이며 실측으로 확인한다. 유료 API·GPU 임대는 사용하지 않는다. 1.7B의 프롬프트를 계속 고치는 대안과 CPU BF16 대안을 비교했으며, 반복된 의미 오류 때문에 한 번의 더 큰 지시 모델 비교를 택했다. 이 선택 자체가 성공이나 운영 채택 근거는 아니다.

## 구현 계약

Java의 인증·권한·문서 데이터는 유지하고 Python AI worker가 loopback llama-server를 호출한다. [공식 llama.cpp b11429](https://github.com/ggml-org/llama.cpp/releases/tag/b11429)의 Windows CUDA12.4 배포를 hash로 고정한다. 이 tag는 공식 v0.6.0이 지정한 배포다. 기존 Python 잠금과 M2/M3/M4/M5의 동결 코드는 변경하지 않는다.

다운로드는 명시적 준비 명령에서만 실행하고 서비스 시작은 파일을 검증한다. 서버는 loopback·무작위 인증키·단일 슬롯·최대 문맥6144로 실행한다. 입력4096·출력768·요청120초 한도를 유지한다. 네이티브 template/tokenize/completion endpoint로 실제 토큰 수·종료 사유·greedy 설정을 확인한다. 라벨은 제한된 숫자 grammar로 생성하므로 기존 Transformers의 직접 logits 선택과 실행 방법이 다르다. 런타임과 양자화까지 바뀌는 비교여서 차이를 모델 크기만의 효과로 해석하지 않는다.

## 실행 전 고정할 확인 사례

`data/evaluation/meetings-gguf-development-v1.json`은 v11과 동일한 요청5개다. 실제 공개 Jupyter 자료와 별도 표시된 한국어 합성 자료를 사용한다. 공개 후보 선택은 보존된 실제 Java v1 DB에서 회수했고, 선택된 원문을 파일에 포함해 DB 없이 재실행할 수 있게 했다. 원래 fixture hash도 함께 고정한다. 질문은 AI 작성이며 사용자 검수0이다.

1. 한국어 계획 회의 분석: 미승인90일 제안과 확정30일 결정 구분, 담당자 미정 작업도 action, 없는 담당자·기한 null.
2. Jupyter 두 날짜 답변: February의 beta 계획과 June의 출시 상태를 구분하고 올바른 회의 근거 인용.
3. 근거에 없는 catering budget: 실제 모델 보류와 빈 주장.
4. Host guide: agenda 링크 지침을 적절한 원문 근거로 답변. 화면 시연에서 쓰는 흐름도 포함한다.
5. 한국어 회의2개와 영어 runbook: 30일→7일, 변경일2026-10-08, 운영 로그에 원문 질문·문서 금지, 각 사실의 올바른 인용.

사전 plan은 입력·프롬프트·스키마·실행기·manifest와 소스 hash를 묶는다. 첫 비교에서 기존 v11 프롬프트를 유지한다. 분석 요청 내부에는 여러 라벨 생성이 있으므로 요청5건을 모델5회라고 기록하지 않는다. 각 실제 출력·설정·실패를 저장하고 이름을 바꿔 실패를 숨기거나 같은 결과 파일에 덮어쓰지 않는다.

이 사례들은 개발자가 이미 읽은 실패 사례이며 held-out 평가가 아니다. 형식·정확한 인용·의미 지지·질문 완전성을 나눠 별도 AI가 검토한다. 다섯 사례가 통과한 뒤 전체 Java 운영과 실제 화면 검증으로 넘어간다. 새로운 실패는 기록하고 후속 변경·검증을 별도 버전으로 남긴다. M5-B validation과 최종 test는 열지 않는다.

## 로컬 준비와 실행

Windows x64·NVIDIA CUDA12.4 호환 장비용 고정 실행 파일이다. 다른 플랫폼을 검증한 것으로 기록하지 않는다. 의존성은 기존 retrieval group을 사용하며 설치·동기화와 모델 실행은 겹치지 않는다.

```powershell
uv run --locked --group retrieval --no-sync python -m scripts.prepare_meeting_gguf --download
uv run --locked --group retrieval --no-sync python -m scripts.prepare_meeting_gguf
uv run --locked --group retrieval --no-sync python -m scripts.serve_meetings_gguf --retrieval --port 8000
```

가중치·55개 runtime 파일·라이선스·설치 영수증은 Git에서 제외된 `models/meetings-gguf-v1`에 둔다. 서비스 시작 시 모델과 archive를 재검증하고 archive에서 검증한 runtime 파일과 설치된 파일이 같은지 확인한다. 원래 1.7B 실행 경로는 회귀 비교용으로 보존한다. 새 GGUF 경로의 `revision`은 실제 양자화 가중치 SHA256을 포함하며 원본 Qwen revision은 별도 provenance다.

설치 원본 2,889,514,080 bytes의 GGUF·실행 archive2개·license2개와 runtime55개 hash를 실제 확인했다. 이는 설치 무결성 검사이며 추론 품질 통과를 뜻하지 않는다. 독립 코드 검토에서 발견한 GPU 선점 문제를 보완한 뒤 Python 전체848개·Ruff가 통과했다. Torch worker와 native launcher는 공통 GPU 잠금을 모델 적재 전에 획득하며 실제 OS 잠금 경합 검사도 통과했다.

설정 확인용 첫 native 요청은 입력12·출력2 tokens로 `READY`를 반환하고 EOS로 종료됐다. 실제 greedy 설정·모델 alias·가중치 hash 검사를 통과했고 로드 직후 GPU 사용량 스냅샷은3733/6141MiB였다. 이는 peak 측정이나 실제 회의 처리 성능이 아니다. [준비 호출 원본](../experiments/results/meetings-gguf-readiness-v1.json)을 보존한다. 이 호출 시점에는 worker의 잠금 보완 작업이 겹쳤으므로 전체 제품 소스 동결 검증으로 쓰지 않으며 아래 후보 실행은 완성된 소스를 별도 계획으로 고정한다.
