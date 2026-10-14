# 공통 입력 예산 후속의 실행 안내

이 문서는 실행 방법과 최신 구현 범위를 설명한다. 사전등록 조건은 [변경하지 않는 설계](MEETINGS-C2-INPUT-BUDGET-FOLLOWUP.md)와 [프로토콜](../data/evaluation/meetings-c2-input-budget-protocol-v1.json)에 있다. **전수 입력 준비40/40은 통과했다. 새 중립4회도 통과했으며 품질 비교는 별도 봉인 계획으로 진행한다. 최신 실측과 CI는 STATUS에 기록한다.**

## 현재 구현

- `meeting_input_budget`: 고정 Qwen3.5 신원/비생각 template 확인을 보존하는 새 5,120 backend와 L0/C2 요청 runtime. 기존 prompt·grammar·mapper는 그대로 재사용한다.
- `prepare_meeting_budget_inputs`: 모든 측정 가능한 입력을 확인하며 첫 실패 뒤에도 나머지 길이를 기록한다. 성공일 때만 새 `input.json`, 성공/실패 모두 한 번만 `receipt.json`을 쓴다. 원래4,096와 새5,120 판정을 함께 보존한다.
- 새 비교 runner/audit와 중립 자원 도구도 합성 회귀·상호 코드 검토를 마쳤다. 전체 회귀/코드 고정과 원격 CI 이전에는 실제 데이터 조사를 시작하지 않는다. 새 source freeze는 `data/evaluation/meetings-c2-input-budget-source-freeze-v1.json`이며72개 코드/metadata를 바인딩한다.

## 실행 순서

1. 새 코드·테스트와 기존 source41/processing18을 바인딩하는 source freeze를 commit한다. Freeze의 `bound_files`에는 코드/설계 metadata만, 별도 `baseline_inputs`에는 기존 calibration input의 경로/hash만 둔다. 입력 파일을 코드 바인딩으로 열어 검증 자료 접근 경계를 섞지 않는다.
2. 부모는 calibration8, 격리 담당자는 validation12의 새 입력 조사를 각 한 번 수행한다. 두 split의 새 영수증이 전수 성공일 때만 다음 단계로 간다. 원문·oracle 전체 바이트의 별도 before/after hash 대조는 본문을 열지 않은 준비 도구 검증과 구분한다.
3. 두 성공 영수증과 runtime receipt를 연결해 새 중립 fixture/plan을 준비하고 commit한다. 공식 tokenizer만 사용하며 가중치 로딩/생성/다운로드는 없다. 정상 입력과 기계적으로 길이를 구성한 부하 입력을 봉인한다.
4. 새 자원 도구가 normal-L0 → normal-C2 → stress-C2 → stress-L0 순서로 최대4회 실행한다. 성공한 실제 원본 영수증을 보존한다. 하나라도 실패하면 남은 호출을 실행하지 않는다. 이전 중립2회를 반복하지 않는다.
5. 양 split의 prepared input, oracle, source freeze, 준비/자원 영수증, 서로 다른 독립 판정자, 익명화 seed와 출력 위치를 함께 실행계획에 고정한다. Calibration16회와 잠긴 익명 의미 판정을 수행하고, 등록된 선택 기준을 만족할 때만 격리 validation12회를 수행한다.
6. 품질 기준을 통과한 경우 기존 Java/React 권한·문서 수정/삭제·회의/일반 문서 검색·인용·작업 편집·실패 복구를 실제 서비스에서 검증한다. Python 실험 시간을 Java 응답 시간이라고 부르지 않는다.

아래 경로는 실행 시 봉인할 산출물 경로를 넣는 형식이며, 실행됐다는 뜻이 아니다. `uv run --locked --group retrieval --no-sync`는 이미 설치된 로컬 환경을 사용한다. 다운로드/의존성 동기화를 모델 실행과 동시에 하지 않는다.

```powershell
uv run --locked --group retrieval --no-sync python -m scripts.prepare_meeting_budget_inputs --draft <draft> --output <new-local-directory> --phase calibration --item-freeze <item-freeze> --source-freeze <code-freeze> --baseline-input <preserved-calibration-input>
uv run --locked --group retrieval --no-sync python -m scripts.prepare_meeting_budget_inputs --draft <isolated-draft> --output <new-isolated-directory> --phase validation --item-freeze <isolated-item-freeze> --source-freeze <code-freeze>
uv run --locked --group retrieval --no-sync python -m scripts.probe_meeting_budget_resources prepare --plan <new-plan> --output <new-local-directory> --source-freeze <code-freeze> --calibration-receipt <cal-receipt> --validation-receipt <val-receipt> --runtime-receipt <local-runtime-receipt>
uv run --locked --group retrieval --no-sync python -m scripts.probe_meeting_budget_resources run --plan <committed-new-plan>
```

격리 validation 명령은 해당 담당자만 실행한다. 부모/후보 구현자는 질문·원문·oracle·상세 판정 설명 대신 수량/hash/통과 여부만 확인한다. 준비 단계에서 내용을 잘라 통과시키거나 새 상한을 추가하지 않는다.

## 측정과 한계

Native 요청의 실제 token ID 직렬화는 호출 직전에 바이트 제한을 확인한다. 공식 token 수로 계산한 최소 바이트는 실제 요청 바이트 측정이 아니다. CPU RSS와 시스템 가용 RAM은0.25초 표본으로 수집하며 peak가 아니다. 사용 가능한 NVIDIA 도구가 있으면 요청 전후 장치 전체 VRAM 수치를 기록한다. 요청 중 VRAM peak나 해당 프로세스의 전용 사용량을 측정했다고 주장하지 않는다.

부하 출력은 별도의 기계적 문법으로384-token 길이 종료를 요구하는 자원 검사다. 정상 답변이나 의미 품질 통과로 세지 않는다. 마지막 정리 후 신원 확인 재시작도 생성0인 확인이며 실제 timeout이 발생하지 않았다면 timeout 복구 실측이라고 쓰지 않는다.

같은 동결8/12문항을 유지한 길이 노출 후 프로토콜 변경이다. 원래4,096 비교의 성공이나 완전 미노출 검증으로 보고하지 않는다. 사용자 검수0, 유료 호출0, 공개 서비스 배포0을 유지한다. 1차 기능/PR14는 아직 미완료다.
