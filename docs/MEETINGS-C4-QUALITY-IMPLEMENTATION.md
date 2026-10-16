# C4 단일 사고 품질 도구 구현 기록

2026-10-16. 새6모듈·대응6검사를 구현하고 전체85파일을 동결했다. 로컬 전체 Python은2398통과/9환경skip/기존warning1, Ruff통과다. 마지막2파일 강화와 import 시점의 한계는 아래에 명시한다. 현재 커밋·필수 CI 확인 전이며 새 평가 원문·질문·실제 tokenizer·품질 native 호출은0이다. [사전등록 계획](MEETINGS-C4-QUALITY-PLAN.md)과 [구현 명확화](MEETINGS-C4-QUALITY-IMPLEMENTATION-CONTRACT.md)를 따른다.

동결 파일은 `data/evaluation/meetings-c4-quality-toolchain-freeze-v1.json`(SHA ecd3d2c6eff1681ce9a30d8756c6e87be72e58828cf1e2e9d0974a3c8218db78), 검증 영수증은 `experiments/results/meetings-c4-quality-tooling-v1.json`(SHA42aa967004750616035e3f201a04daf815ad101cb5a0aaca78bc36f05882216a)이다. 기존52파일은 변경하지 않았다. 커밋/CI의 최신 관측은 [STATUS](STATUS.md)를 기준으로 확인한다.

## 해결하려는 문제

이전 모델은 정확한 문장을 인용하면서도 답변에서 조건을 빠뜨리거나 근거가 말하지 않은 내용을 만들었다. 새 후보는 문단·표·목록 단위 근거에 ID를 부여하고, 한 번의 사고 호출에서 모든 요구를 확인한 자연어 답변을 만든다. 서버가 선택된 ID를 실제 원문과 좌표로 확장한다. 이는 정확 인용을 강제하는 장치이며 의미의 정확성까지 보증하지 않는다.

별도 계획→답변의 두 호출 대신 단일 사고를 사용한다. 단계 수와 사고 경로가 함께 바뀌므로 개선되더라도 둘 중 하나의 독립 효과라고 해석하지 않는다. 새 자료에서 모든 필수 사실·추가 사실·인용의 지원·보류를 별도 judge가 검토해야 한다. 서비스 기본 모델에는 아직 연결하지 않았다.

## 구현 경계

| 파일 | 역할 |
| --- | --- |
| `src/doctrail/meeting_answer_thinking.py` | 명시적 답변 언어, 근거 block catalog, 고정 prompt/schema, 원문 인용 확장 |
| `src/doctrail/meeting_thinking_quality.py` | 동일 native 설정·입력·종료·사고/최종 분리·384 최종 토큰 검증, 공유90초 |
| `src/doctrail/meeting_thinking_review.py` | 새 family·질문 구성, 충분 근거 대안, 독립 판정·노출 계약 |
| `scripts/prepare_meeting_thinking_inputs.py` | 실제 Git 바이트·CI·source/item 고정, 원문 parity·freshness, 단발 offline 준비 |
| `scripts/probe_meeting_thinking_quality.py` | 사전검사·단발 호출·실패 종료·정리·원본 전송 재생 |
| `scripts/audit_meeting_thinking_quality.py` | 최종답변 전용 익명 pack, 판단 hash 고정, 원본 재생과 calibration gate |

각 파일에 대응하는 합성 테스트를 추가한다. 기존52개 동결 파일을 수정하지 않고 전송·launcher·청크/parity·기초 판정 코드를 재사용한다. MockTransport·합성 원문·모의 tokenizer/Git/launcher의 통과를 실제 모델·실제 원문 검증으로 세지 않는다.

## 확인된 수정과 실패 기록

Candidate 4파일은 처음 duplicate JSON 오류 분류의 테스트 기대값이 달라 65통과/1실패였고 fixture를 수정했다. Ruff loop closure 등 초기 경고를 수정한 뒤 72통과했다. 이 결과는 아래 deadline 수정 이전 기록이다.

독립 Astra xhigh 코드 검토는 native 전송 직전 기록 콜백이 90초를 넘겨도 이미 계산한 HTTP timeout으로 전송될 수 있음을 발견했다. 수정 전 새 합성 검사에서 실제 MockTransport handler 실행을 재현했다(1실패/0.66초, tool chunk `5d0b97`). 후크 전후 deadline 검사와 남은 HTTP timeout 축소로 수정했다. 최종 candidate 검사 **74통과/0.53초**(`7518c2`), Ruff 통과(`335be1`)이며 별도 로그 파일은 없고 도구 결과만 보존돼 있다. 독립 역할은 최종 hash를 읽기 재검토했으며 재실행하지 않았다.

Runner 최초 합성 단독 cal6/replay 검사는 통과했지만 후속 연동 묶음은 Windows `report.json.tmp`의 `FileExistsError`로 실패했다. 앞선 atomic replace 오류를 가린 것인지 아직 단정하지 않는다. 실제 모델 실패와 구분하고 원래 오류를 보존한다. 이후 기록은 독립적인 event 파일에 배타적으로 저장하고 보고서는 요청 경계에서 교체하도록 변경했다. 성공은 정확한17개 event의 순서·hash·값·추가 파일 부재와 원본 응답 재생을 모두 검증한다.

전체 신규 v1 검사는66통과/1실패(202.09초)에서 중단됐고 audit모듈은 미실행이었다. 새 기록 실패 회귀가 underlying PermissionError를 기존 HTTP가 GenerationError로 감싸 첫 원인을 잃는 결함을 발견했다. Observer의 저장 실패 시점에 첫 원인을 먼저 보존하도록 수정했고 관련3표적 검사가 통과했다. 독립 추가 검토가 반대 순서인 생성 오류→기록 오류도 지적해, 알려진 오류 event의 첫 원인을 저장 전에 보존하도록 보완했다. 이 실패는 고정 모델이나 실제 평가 자료의 실패가 아니다.

경로 alias 검사에서 매번 이전 경로와 samefile을 비교하는 비용도 확인했다. st_dev/st_ino 집합과 zero-inode fallback으로 같은 hardlink 거절 조건을 유지하며 검사량을 줄이는 변경을 검증한다. HEAD·파일 바이트 hash 재검사는 생략하지 않는다. 합성 도구 실행 시간은 모델 응답 시간으로 해석하지 않는다.

새 도구 고유77검사는 분할 실행에서 모두 통과했다. 최종 audit/정상 재생/경로-Git10개136.28초, 오류순서2개5.85초, 원래 실패flag 변조1개19.04초, Ruff를 각각 확인했다. 하나의 최종77전체 실행으로 표현하지 않는다. 마지막 두 파일 강화가 부모 전체 회귀 시작과 교차해 import 시점은 미증명이며 최종 커밋의 CI를 별도로 확인한다. 독립 Astra xhigh는 최종 파일 hash를 읽기 검토했고 추가 결함을 보고하지 않았다. 테스트를 별도 실행한 검토는 아니다.

부모 전체 회귀 명령은 `.venv/Scripts/python.exe -m pytest -q`이며2398통과/9skip/warning1(872.141초)로 종료됐다. 전체 Ruff명령은 `.venv/Scripts/python.exe -m ruff check src tests scripts`다. 원본 로그와 전체 실행 영수증을 `.local/c4-quality-final-checks-v1/`에 보존하고 공개 영수증에는 hash·숫자·검증 범위만 기록했다. 마지막 변경의 로컬 표적 결과와 최종 커밋 CI가 별도 증거이며, 이 실행의 import 시점을 사후 확정하지 않는다.

## 증거가 뜻하는 범위

`native_post_started`는 클라이언트 전송 후크의 관측이다. 서버가 받았거나 생성이 완료됐다는 뜻이 아니다. 전송 시도, 파싱된 native 응답, 전체 계약을 통과한 답변을 구분한다. `native_responses_received`는 파싱 응답의 event 저장까지 성공한 수라서 기록 실패가 발생하면 실제 수신보다 적을 수 있다. 최초 실패의 안전한 코드·유형·경과 시간을 남기고, 뒤이은 저장·정리 실패가 원인을 덮어쓰지 않게 한다.

Git 검사는 source 바이트가 지정된 선행 commit과 현재 HEAD에 있는지 증명한다. 실제 질문 작성 시각이나 그 선행 commit에 item 파일이 없었다는 사실까지 자동 증명하지 않는다. 부모가 source commit 확인 뒤 새 item 작성 역할을 시작하고 이 호출 순서를 기여·상태 기록에 남기는 운영 절차가 별도로 필요하다.

정규화된 동일 문서/긴 문단 검사는 번역·근접 재서술을 모두 찾는 의미 검사가 아니다. 같은 family의 반복 문구는 질문 작성 전 독립 사전검토가 필요하며, 그 문구 때문에 필수 다문서 요건이 부풀려지지 않도록 충분 근거 대안을 검토한다. 사용자 검수는 여전히 0이다.

## 실행 순서

전체 도구 합성 검사·독립 코드 검토·동결 → 사용자 명의 커밋과 필수 CI → 관측한 CI 영수증 별도 커밋 → 새 source 채택/작성·검토·실제 Java/Python parity·source 커밋 → 새 질문/oracle·item 사전검토·커밋 → 단발 offline 준비 → 실행계획·judge 사전예약·커밋 → calibration 최대6회 → 원래6/6 gate 통과 때만 격리 validation 최대8회다.

예산 실패·품질 실패는 원래 결과를 보존하고 같은 자료를 다시 실행하거나 기준을 낮추지 않는다. 구현 검사만 통과한 상태를 품질 통과나 Phase1 완료로 보고하지 않는다.

## 최종 원격 검증

6754435의 push38850972533·PR38850977356에서 필수3job이 모두 성공했다. Linux Python2386통과/21skip/기존warning1, 실제 Java browser49통과/0실패이며 각 실행은 별개다. 관측 CI 영수증은 원본 log hash·최종85 Git 바이트 대조를 보존한다. 이 결과는 로컬 import 시점을 소급 증명하지 않지만 최종 커밋 코드의 원격 전체 검증을 제공한다. EOF 빈 줄 한 개는 동결 adapter 바이트를 보존하는 정확한 whitespace 예외로 기록했고 실행 검사를 완화하지 않았다. 아직 새 품질 원문/질문/모델 호출0이다.
