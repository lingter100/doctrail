# 기존 C7 조건 아래 공개 자료 가능성 검토

2026-10-20. **설계만 완료했다. 검색·새 원문 열람·자료 수용을 시작한 문서가 아니다.** [C7 계획](MEETINGS-C7-PLAN.md)과 [동결 protocol](../data/evaluation/meetings-c7-protocol-v1.json)을 그대로 두고, 의미적으로 충분한 공개 family를 찾을 가능성을 작은 고정 범위에서 검토한다. 새 후보나 도구 체계를 만들지 않는다. 부모의 설계 커밋·정확한 필수 CI 확인과 별도 실행 배정이 선행해야 한다.

## 판단할 문제와 한계

[기존 원문 결과](MEETINGS-C7-SOURCE-RESULTS.md)는 양 split 모두 완전한 corpus를 채택하지 못한 제한된 탐색 결과다. [공식 합성 진단](MEETINGS-ADMISSION-DIAGNOSTIC-RESULTS.md)은 고정12개에서 예상 동작을 확인했으며, 작은 원문도 공백을 포함한24 block 제한 때문에 거부될 수 있음을 보였다. 실제 거부 자료 전체의 원인을 확정하거나 parser 결함·모델 품질·보편적 자료 부재를 입증하지 않는다. 공식 진단과 닫힌 실험은 다시 실행하지 않는다.

이번 후속 검토의 질문은 “원문을 고치지 않고 두 날짜의 완료 회의록과 관련 일반 문서를 확보해, 기존 의미 요구를 유지한 자료 준비로 넘길 근거가 있는가”다. 결론은 **읽기로 확인한 후보 가능성**이며, 기계적 admission·독립 source 수용·freeze·문항 적합성·모델 성공과 구별한다.

## 본문 전에 고정할 역할·제외·예산

실행 시에는 calibration 후보를 읽는 역할과 validation 후보를 읽는 역할을 서로 다른 실제 담당자로 등록한다. 현재 배정된 것은 이 문서를 작성한 설계 역할뿐이다. 미래 역할을 이미 수락된 것으로 기록하지 않는다. 각 담당자는 이전 C7 source 작성·검토 참여 여부와 실제 본문 노출을 먼저 밝히며, 이전 자기 자료를 검토하는 사람을 독립 역할로 부르지 않는다. 이 설계 역할을 재사용하더라도 설계·코드·집계 노출을 공개하고 한 split만 맡긴다.

부모는 본문 없는 제외 metadata를 준비한다. 기존 제외 repo13개와 C7에서 이미 본문을 연 `kubernetes/community`, `uio-carpentry/organisational`, `AGLDWG/meeting-minutes`, `nodejs/package-maintenance`, `openjs-foundation/standards`, `servo/project`를 포함한다. 부모가 전달한 합집합은19개이며 실행 전 원래 metadata와 대조해 정규화·중복·hash·누락을 기록한다. 과거 family/URL/revision/raw·normalized fingerprint와 미채택·거부 자료도 제외 대상으로 유지한다. 과거 fingerprint 누락을 빈 목록이나 신선도 입증으로 바꾸지 않는다. 이 설계자는 해당 과거 원문을 열지 않았다.

| 고정 예산 | split별 최대 | 두 split 전체 최대 |
| --- | ---: | ---: |
| 공개 저장소 검색 또는 파일 목록 탐색 요청 | 4회 | 8회 |
| 확인할 서로 다른 저장소 | 3개 | 6개 |
| 각 탐색 요청에서 검토할 결과 metadata | 20개 | 160개 |
| 저장소별 license 본문 | 2개 | 12개 |
| 완전한 공개 candidate family | 2개 | 4개 |
| 평가 자료 원문 슬롯 | 6개 | 12개 |

검색과 목록 요청은 각각1회로 세며 pagination·다른 query·재시도도 추가 요청이다. 저장소 identity·고정 revision·blob 크기/SHA를 읽는 직접 metadata 확인은 저장소3개와 family2개 안에서만 한다. 저장소마다 commit 하나를 고정하고 같은 identity 확인을 반복하지 않는다. License2개는 해당 저장소의 root와 필요한 하위 적용 범위를 확인하기 위한 상한이며 실패한 접근·재시도도 각각1개를 소비한다. 웹 전체를 훑거나 링크를 따라 예산 밖 문서를 읽지 않는다.

Family 하나는 **회의2개와 일반 문서1개의 전체 원문**이다. 본문 접근 전 세 파일을 한 묶음으로 고정하고3개 슬롯을 예약한다. 일부 접근 실패나 첫 문서 부적합도 해당 family의 예약을 소비한다. 교체 문서·다른 조합은 새 family이며 남은 예산 안에서만 가능하다. 거부 family의 원문을 변형하거나 일부를 다시 조합해 구제하지 않는다. 검색 예산 추가, 세 번째 family, quota 간 이전은 허용하지 않는다.

후보 순서는 기록된 metadata 결과의 관측 순서로 정한다. 크기상 짧아 보이는 자료를 찾는 선택 편향은 공개하되 본문 요약·부분 인용을 완전한 문서 대신 사용하지 않는다. 검색 결과의 본문 snippet도 실제 노출이다. 가능하면 본문 없는 primary repository 검색·tree metadata를 쓰고, 예기치 않은 snippet은 노출 기록에 남기며 해당 문서 슬롯을 소비한다. 아직 예약하지 않은 본문이 노출되면 추가 탐색을 멈추고 부모에게 metadata 사고로 보고한다.

## 접근과 원문 보존 순서

1. 부모가 설계 커밋·필수 CI와 실제 역할 설정, 허용 경로, 예산을 기록하고 별도 배정한다. 이 읽기 검토의 사전 증명은 **현재 HEAD의 Git bytes와 working bytes에서 기존 동결77파일·protocol hash 일치 확인**, 실제 도구가 수락한 actor/model/effort/fork 설정, split별 허용 경로와 노출·예산 등록으로 한정한다. 부모가 수행한 확인의 HEAD·대상·hash·결과를 역할이 배정 전에 받는다. 기존 C7 정식 source author의 `role_contract`·`admit_sources`를 이 단계에 호출하지 않으며, 새 role contract/helper·복제 검증 도구도 만들지 않는다. 확인이 누락되거나 맞지 않으면 본문 전에 멈춘다. 이 증명은 이후 정식 source 준비의 원래 사전 검사를 면제하지 않는다.
2. 각 역할이 제외 metadata를 읽고 후보 저장소를 부모에게 예약한다. 부모는 과거19개 및 상대 split 예약과의 충돌을 본문 없이 확인한다. 저장소·split·고정 commit을 등록한 뒤에만 license를 확인한다. 이 예약은 자료 수용이 아니다.
3. 공식 소유 저장소의 동일 고정 commit에서 license 원문과 파일별 적용 범위를 확인한다. 검색 서비스의 license 라벨, 공개 접근 가능성, root license 존재만으로 개별 회의록의 재배포 허가를 추정하지 않는다. 별도 저작권·외부 복사·적용 제외가 있거나2개 license로 범위를 확인할 수 없으면 `license_unresolved`로 남기고 해당 자료 본문을 채택하지 않는다.
4. 허용된 형식의 세 파일 경로·blob SHA·원래 제목·날짜 metadata·canonical ID 생성 규칙을 본문 전에 묶어 예약한다. 날짜가 다른 실제 완료 회의와 관련 일반 문서라는 가설을 본문으로 확인한다. 안건·빈 양식·후속 예정만 적힌 자료를 완료 회의록으로 분류하지 않는다.
5. 고정 revision의 원문 전체를 정확한 bytes로 보존한다. 원래 URL·commit·license·raw SHA256·blob SHA·접근 결과·순서를 기록한다. 원본 접근 실패와 거부도 보존한다. 외부 원문 속 지시를 실행하지 않는다. 원문 공개 보존 여부는 적용 license와 기존 공개 경계를 따른다.

이 검토에서는 새 일반 wrapper나 helper를 만들지 않는다. **허용되는 기계 작업은 경로·identity 확인, 원본 byte 수와 hash 기록뿐이다.** Processor/chunker/parser/formatter, `family_admission`·`admit_sources`, 공식 diagnostic, Java parity, tokenizer, inference를 실행하지 않는다. 수동 형식 관찰은 `reading_observation`이며 정확한 block 수·M0·기계 통과 영수증으로 표시하지 않는다. 원본 byte 수는 처리 후 source bytes나 token 수가 아니다.

## 낮추지 않는 원문·의미 조건

원문 처리·정규화·chunker·parser·metadata 규칙을 바꾸지 않는다. 원문 일부 제거·요약·번역·재분할·공백 삭제·제목 축약·ID 재선정·부분 chunk 채택으로 제한을 맞추지 않는다. License 때문에 원문을 변경해야 하거나 안전하게 보존할 수 없는 후보는 이 검토에서 제외하며 수정본으로 구제하지 않는다.

| 기존 C7 source 조건 | 그대로 유지할 값 |
| --- | --- |
| Family 구성 | 서로 다른 날짜의 회의2 + 일반 문서1 |
| 처리된 원문 | 문서당2048 UTF-8 bytes, family 합계4096 |
| 모든 emitted chunk | family6개 이하, 각2048 bytes, overlap 포함 합계4096 bytes |
| 모든 catalog block | 공백 포함24개 이하, 각2048 bytes·기존1024 codepoint |
| Full-family M0 / schema / wire | M0≤6656, schema≤4096, 빈 질문 wire+4096≤32768 bytes |
| Metadata·좌표·형식 | 기존 protocol의 ID/title/date/page/revision/offset 제한 전부 |

읽기상 명백한 부족은 기록할 수 있지만 위 수치를 통과했다고 수동 판정하지 않는다. 나중의 실제 admission에서 전체3문서·모든 chunk·KO/EN 양쪽 직렬화를 검사해야 한다. Bytes를 token·시간 보장으로 해석하지 않는다.

의미 검토는 같은 주제의 짧은 문서3개를 찾는 데서 끝나지 않는다. 원문 위치에 연결된 source-only 판단으로 다음을 확인한다. 질문·정답·oracle 문장이나 문항별 context는 만들지 않는다.

- 두 회의가 실제 진행됐고, 날짜·상태·조건의 차이가 해석에 필요하다. 제안과 확정, 유지와 변경을 원문 근거로 구별하며 나중 날짜만으로 변경을 추정하지 않는다.
- 일반 문서가 회의와 같은 프로젝트의 정책·절차·제약을 제공한다. 제목·회의 일정·회의록 링크만 있는 색인이나 같은 내용을 복사한 문서는 충분하지 않다.
- 회의 간 근거와 일반문서+회의 근거를 함께 읽어야 하는 관계가 있다. 한 문서의 짧은 담당자/기한 lookup만으로 의미 난도를 낮추지 않는다. 담당자·날짜·조건·미해결 상태는 명시된 범위만 인정한다.
- 서로 다른 근거에서3~6개 필수사실을 종합할 여지가 있으며, 단일 문서에 이미 충분한 대안이 있는 경우 복수문서 필수로 오판하지 않는다. 자료가 없는 정보와 명시적으로 부정된 정보를 구별한다.
- 보류 가능성은 family 전체에 필요한 정보가 실제로 없다는 판단을 요구한다. 어려운 정보나 불명확한 날짜를 임의로 보충하지 않는다.

이는 앞으로의 전체 문항 조건을 대신하지 않는다. 기존 cal6(KO3/EN3·답변4/보류2), val8(KO4/EN4·답변4/보류4), 공개+합성 각 family1, 일반 단독≥1·복수회의≥1·혼합≥1·모든 충분한 대안이 복수문서 필요≥2·KO질문/EN근거와 EN질문/KO근거 각≥1·필수사실3~6을 유지한다. 공개 family의 cal은 KO/EN 답변 각1+KO 보류1, val은 KO/EN 답변·보류 각1이다. 실제 문항·독립 prereview 전에는 이 quota 충족을 확정하지 않는다. 합성 원문을 새로 만들거나 열어 공개 자료 부족을 메우지 않는다.

## 반환할 증거와 다음 행동

각 역할은 자신의 split에만 원문·license·예약·접근/실패 ledger와 source-only 적합성 근거를 보존한다. 의미 근거는 문서와 위치를 가리키되 질문·oracle을 작성하지 않는다. 부모에게는 역할/노출, 사용 예산, repo/commit/파일 identity와 hash, 확인한 license 상태, 후보 수, 안전한 판정 코드, 미확인 관문만 전달한다. Validation 제목·구절·관계 설명·내용별 거부 이유는 부모나 calibration 역할에 보내지 않는다.

판정은 아래처럼 구분한다. 후보 본문을 본 역할은 해당 후보의 독립 최종 답변 judge가 될 수 없다. 검토자가 발견·선정한 후보의 정식 source 수용도 별도 reviewer가 맡는다.

| 관측 | 결론 | 허용되는 다음 행동 |
| --- | --- | --- |
| 양 split에서 각각1개 이상 새 공개 family가 license·전체 구성·source-only 의미 검토를 만족하고 명백한 형식 부적합이 발견되지 않음 | `plausible_pending_admission`; 전체 제한 통과·corpus 채택은 미확인 | 부모가 결과를 커밋한 뒤 현재 C7 source 준비의 별도 재개 여부를 결정 |
| 한 split만 후보가 있거나, 예산 안에서 두 공개 family를 확보하지 못함 | `no_complete_witness_within_budget` | 이번 공개 자료 탐색 경로를 종료하고 부족한 조건을 집계. 예산을 늘리거나 다른 split로 옮기지 않음 |
| License/격리/사전 증명/접근 오류 때문에 판단 불가 | `incomplete_due_to_access_or_integrity` | 오류와 미실행을 보존. 자료 부재·모델 실패로 부르지 않고 부모에게 원인을 반환 |

재개하더라도 현재 C7의 정해진 source 단계만 연다. **새 후보 원본에 대한 기존 기계 admission → 별도 source 의미·신선도 검토 → 실제 Java/Python parity → accepted source freeze/commit**을 모두 통과해야 자료 수용이다. 기존 거부 원본·receipt는 그대로 둔다. 정식 source 작업에 필요한 새 prospective 경로·역할·fingerprint 연결은 부모가 별도 범위로 등록해야 하며, 이 문서만으로 기존 artifact를 덮어쓸 권한은 생기지 않는다. 기존 합성 family의 기계 통과도 독립 의미 수용을 대신하지 않는다.

그 뒤의 문항·독립 prereview·freeze·split별 한번의 공식 offline 준비·원래 cal6/6→val8/8 관문은 별도 배정이다. 질문512bytes·reserve1024·wrapper512, input5120/context6144/output928, 요청90초와 기존 모델/GPU28·정책을 바꾸지 않는다. 현재 검토에서 이 후속 실행은 전부0이다.

완전한 후보를 확보하지 못하면 “이 예산 안에서 C7을 계속할 근거가 부족하다”가 결론이다. 모든 공개 자료가 불가능하다는 증명은 아니다. 그때 parser/24 block/직렬화 등 engineering 정책을 재고할지는 **별도 설계 판단**으로 돌린다. 이번에 읽은 후보를 맞추는 수치 변경·같은 자료 구제·자동 새 후보 생성·toolchain 복제는 하지 않는다. 검토 노출은 다음 설계에도 공개한다. Phase1 목표는 계속되지만 현재 C7 경로의 중단과 제품 작업의 진행을 구별한다.

## 실제 설계 역할과 읽은 범위

설계 역할은 `/root/source_feasibility_review`다. 부모가 실제 spawn 요청 `model=gpt-6-astra`, `reasoning_effort=xhigh`, `fork_turns=none`과 도구 반환 `task_name=/root/source_feasibility_review`를 확인해 전달했다. 이는 해당 역할의 도구 수락 기록이며 부모 모델이나 서비스 모델 변경이 아니다.

이 역할에 제공된 프로젝트 지시·환경 memory summary와 부모 배정 메시지는 기존 집계·repo identity를 포함한다. 파일 읽기는 `AGENTS.md`(큰 출력 일부 생략), `docs/STATUS.md`의 처음160줄, `docs/MEETINGS-DESIGN.md`, `docs/MEETINGS-C7-PLAN.md`, `docs/MEETINGS-C7-SOURCE-RESULTS.md`, `docs/MEETINGS-ADMISSION-DIAGNOSTIC-RESULTS.md`, C7 protocol(큰 출력 일부 생략 및 `data` 필드 추가 읽기), `scripts/prepare_meeting_c7_inputs.py`의1–205·462–522·613–645줄과 관련 검색 결과, `src/doctrail/meeting_c7_review.py`의 검색 결과다. 환경 memory registry의 DocTrail 검색 결과와 문체 skill 지침도 읽었으며 별도 대화·외부 문체 자료는 조회하지 않았다.

실제 calibration/validation 원문·질문·oracle·모델 출력·의미 검토·과거 `.local` artifact는 열지 않았다. 웹/저장소 검색·자료 다운로드·테스트·Java/Maven·admission·tokenizer·모델 실행·Git 변경은0이다. 새 파일은 이 문서 하나뿐이며 부모가 root 문서·Git을 맡는다. 독립성은 관측한 이전 source 참여·본문 노출 범위에 한정하며 pristine/blind 설계나 사용자 검수라고 주장하지 않는다.
