# C2 calibration 출처 채택과 처리 등록

2026-10-14. 담당 역할: `/root/c2_calibration_source`. **공개 출처의 개별 파일 채택 확인과 처리 규칙 등록만 완료했다. 질문·oracle·평가 context·합성 본문·모델 호출은 0이다.** 부모가 이 문서와 [manifest](../data/evaluation/meetings-c2-calibration-v1/source-manifest.json)를 commit하기 전에는 자료 작성으로 넘어가지 않는다.

[비교 계획](MEETINGS-C2-COMPARISON-PLAN.md), [검토 계약](MEETINGS-C2-REVIEW-CONTRACT.md), `meetings-c2-family-registry-v1`의 calibration 구성은 그대로다. C2-F01과 C2-F02 각각 4문항, 한국어2·영어2, 답변 가능3·근거 부족1이다. 전체 calibration에서는 답변 가능한 복수 사실 항목 최소4개, 복수 문서가 반드시 필요한 항목 최소2개를 유지한다. 각 계열에 복수 사실·복수 문서·부분 정보만 있는 보류를 각각 포함한다. 아직 이 조건을 만족하는 문항이 작성됐다고 주장하지 않는다.

## 확인한 공개 출처

OpenTelemetry 공식 `open-telemetry/community`의 고정 commit `df3343ccbecb84a6e25dcd9610cb9a93ad377a93`만 조회했다. Commit API의 tree는 `53a78862176b9fe860aff208d28f2ab27a3062c4`이고, 해당 tree의 재귀 목록은 260개·잘림 없음이었다. 두 파일의 직접 받은 바이트에서 계산한 Git blob SHA1이 기존 registry와 일치했다.

| 출처 | 바이트 / code points | raw SHA256 = processed SHA256 |
|---|---:|---|
| [governance-charter.md](https://github.com/open-telemetry/community/blob/df3343ccbecb84a6e25dcd9610cb9a93ad377a93/governance-charter.md) | 15,223 / 15,215 | `ccb43c8d7c0b27797c5202f14e7767f692dbf0869f31688cbe5c02a50f0e17de` |
| [guides/contributor/membership.md](https://github.com/open-telemetry/community/blob/df3343ccbecb84a6e25dcd9610cb9a93ad377a93/guides/contributor/membership.md) | 25,854 / 25,854 | `5a55a6a7a8a83e1c4c1b73fefbf4d71ed7adca400fc3c558c9e342ff6c00042f` |

실제 두 원문은 UTF-8, BOM 없음, CR 없음, LF 유지, 끝 LF 있음이며 NFC 정규화 결과가 원문과 같았다. 각각 LF307·449개다. Web 도구의 표시 줄번호는 원래 파일의 빈 줄을 생략할 수 있으므로 좌표를 만드는 데 쓰지 않는다. 바이트를 직접 읽어 얻은 Unicode code point만 위치의 기준이다.

고정 [LICENSE](https://github.com/open-telemetry/community/blob/df3343ccbecb84a6e25dcd9610cb9a93ad377a93/LICENSE)의 Apache-2.0 원문을 확인했다. SHA256은 `c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4`다. 고정 tree에서 LICENSE/NOTICE/COPYING/COPYRIGHT 이름을 찾았을 때 루트 LICENSE만 있었다. 두 대상 본문에는 별도 라이선스, 저작권 고지, 제3자 자료를 가져왔다는 표시가 없었다. 링크된 외부 문서의 본문은 가져오지 않았고, 그 문서의 이용 조건이나 사실까지 채택하지 않는다.

따라서 **등록된 두 파일은 Apache-2.0 출처로 채택 가능**하다. 현재 commit 대상에는 출처의 본문을 복사하지 않는다. 원본 snapshot과 LICENSE는 `.local/c2-source-adoption/calibration/`에만 있다. 나중에 재현 가능한 공개 평가 자료로 원문을 포함할 때에는 고정 LICENSE 전문, 저장소·commit·원래 경로의 출처 표시, 발췌/구조화했다는 변경 고지를 함께 포함해야 한다. 공개용 source record에는 이 정보를 원문 문자열 바깥의 provenance 필드에 넣고 원문의 좌표를 바꾸지 않는다. 이름·로고 사용 권한이나 공식 협력 관계를 주장하지 않는다.

## 본문 적합성과 해석 제한

두 파일은 역할, 자격, 절차, 조건과 예외를 담은 영어 정책 문서다. 자연스러운 문단, Markdown 목록·중첩 목록, 링크, 표가 이미 존재한다. 역할의 책임 범위와 조직의 운영 절차가 서로 다른 문서에 있어, 두 문서를 함께 근거로 삼는 제한된 비교를 구성할 수 있다. 한국어 질문의 근거도 영어 원문 그대로 쓰고 원문 번역본을 새 근거로 만들지 않는다.

이 출처는 실제 특정 회의·특정 인물의 선임·작업 완료를 증명하지 않는다. 공개 파일의 commit 시각을 사건일이나 회의일로 쓰지 않는다. Charter 본문에 있는 업데이트 표기는 월 단위이므로 임의의 일자를 보충하지 않는다. 두 source 모두 `meeting_date: null`이다.

Membership의 일반적인 회원 투표 문구와 charter의 Members of Standing 자격 범위를 무조건 같은 것으로 취급해서는 안 된다. 표의 요약, 상세 규칙, 예외·재량·SIG별 범위, 규정된 절차와 실제 발생 여부를 구별한다. 질문 작성자는 관련 범위 전체를 확인하고 충돌을 조용히 제거하거나 외부 지식으로 해결하지 않는다. 모호함이 정답을 하나로 고정하지 못하게 하면 작성 실패로 기록한다.

보류 문항은 일부 관련 정보가 있어도 필수 부분이 실제로 없는 경우에만 만든다. 허용된 두 원문에 있는 답을 일부러 제공 context에서 빼서 보류로 만들지 않는다. 외부 링크를 방문하면 알 수 있을 것이라는 추정, 개인 이름·결과·날짜 등의 상식 보충은 금지한다. 이 단계에서는 구체적인 질문·답·누락 사실을 정하지 않았다.

## 기존 서비스와 동일한 처리·청크 규칙

처리 규칙은 `c2-cal-source-processing-v1`이다. 원문 UTF-8 bytes와 SHA를 보존하고 엄격하게 decode한다. 서비스의 `Ingest.extract`와 동일하게 선행 BOM 제거, CRLF/CR→LF, NFC만 적용한다. 이번 두 파일에서는 모두 항등 변환임을 확인했으므로 raw/processed SHA가 같다. 공백 정리, Markdown 렌더링, 링크 확장, 줄 연결, 재줄바꿈, 번역, 요약은 하지 않는다. 이후 합성 원문도 처음부터 UTF-8/LF/NFC로 작성하고 처리 전후 동일성을 검사한다.

문맥 후보는 **처리된 전체 문서에 기존 Java `Retrieval.chunkContent`를 그대로 적용한 청크**다. 평가를 위해 문서를 먼저 절/문단 단위로 잘라 별도 문서로 만들지 않는다. Markdown은 page가 null인 단일 page이며 시작0·끝은 처리 원문 전체 code point 길이다.

1. `start=0`, `end=min(start+1000, document_end)`로 시작한다.
2. 마지막 청크가 아니면 `end-1`부터 `start+500`까지 역순으로 처음 만난 ASCII LF 또는 space의 바로 다음으로 end를 이동한다. 없으면 기존 end를 유지한다.
3. 비어 있지 않은 원문 `[start,end)`를 그대로 하나의 청크로 등록한다.
4. 문서 끝이 아니면 `start=max(start+1,end-150)`으로 진행한다. 서로 겹친 원문도 유지한다.

1000/150은 이미 서비스에 존재하는 규칙이며 C2의1024 상한에 맞춰 새로 정한 값이 아니다. 기존 Python `doctrail.ingest.extract`/`normalize`, `doctrail.retrieval.chunk_content`와 Java 기준 파일의 SHA를 manifest에 고정했다. 새 source-processing helper는 이 함수를 재사용하되 기존 동결 파일을 고치지 않고 별도 새 파일로 구현한다. **helper 구현·문서 전체에 대한 Java 결과와의 text/offset/ordinal 동등성 검증·helper 동결은 질문 작성 전 필수 준비 단계**다. 현재 이 실행 검증은 아직 하지 않았다. Python에서 동일하게 재현한 청크도 Java 서비스 검색이나 운영 성능을 측정했다는 뜻은 아니다.

## context 선택과 좌표의 고정 규칙

각 source는 고정 document ID와 revision1을 가진다. 이 revision은 평가 snapshot의 번호이며 Git commit 횟수가 아니다. 청크 ID는 `{document_id}-r1-c{ordinal:04d}`다. 모든 좌표는 처리 원문 전체에서의 Unicode code point 반열린 구간 `[start,end)`다. 원본과 처리본이 같다는 확인 때문에 이번 공개 두 파일의 좌표도 같다.

자료 작성 시에만 전체 청크 목록에서 관련 원문 범위를 포함하는 **완전한 서비스 청크**를 고른다. 조건·주체·시간·상태를 해석하는 데 필요한 범위의 청크도 함께 포함한다. 주제 범위와 선택 이유, 모든 chunk ID·offset·text SHA를 원문/질문 동결 기록에 남긴다. 순서는 manifest의 source 등록 순서, 이어서 ordinal 오름차순으로 고정한다.

- 청크 내부를 잘라내거나 합치지 않는다. 같은 문서의 겹친 청크를 별도 문서로 세지 않는다. 겹친 부분을 삭제하거나 인용 뒤에 누락된 문맥을 덧붙이지 않는다.
- C2 block/line ID 수·크기, 후보 출력, 두 정책의 token 차이를 보고 청크를 선택하거나 바꾸지 않는다. 원래 표·목록·문단과 청크가 중간에서 만나는 경계를 그대로 유지한다.
- 양쪽에 동일한 context 문자열·순서·제목·리비전·날짜·좌표를 준다. 원문 밖의 제목·각주·선택 이유를 근거 text에 삽입하지 않는다.
- `AnswerRequest`의 context 최대10개와 두 정책의 공통 입력 상한을 넘으면 준비 실패다. 질문 작성 뒤 내용을 줄이거나 청크를 바꿔 통과시키지 않으며, 분모를 줄이거나 대체 문항을 끼우지 않는다.
- source corpus의 표와 목록을 처리본에서 지우지 않는다. 제공 context의 자연스러운 문단·목록 등 혼합 구조를 유지한다. 구조를 맞추기 위한 인위적인 줄바꿈이나 표 재구성은 금지한다.

정답 가능한 복수 source 항목은 어떤 허용 근거 대안을 골라도 서로 다른 document/revision 두 개 이상이 필요해야 한다. 질문 작성자·자기 검토자의 판단만으로 충족했다고 하지 않고 별도 사전 검토를 받는다.

## 새 합성 계열의 작성 제약만 등록

C2-F02는 하나의 새로운 가상 실내 빙상장과 제빙·세션 조정 업무다. 원문은 한국어로 작성하고 각 문서에 AI 작성 합성 평가 자료임을 표시한다. 실제 조직·사람·사용자 업로드나 기존 pool의 문구·사건·숫자를 재사용하지 않는다. 다음 ID만 먼저 고정했으며 조직 이름, 인물, 날짜, 시간표, 수치, 사건과 본문은 아직 만들지 않았다.

| document ID | 향후 문서 성격 | 날짜 규칙 |
|---|---|---|
| `c2-cal-f02-rink-rules` | 운영 기준 문서 | 문서일과 규칙 적용일을 구별. `meeting_date:null` |
| `c2-cal-f02-rink-coordination` | 조정 회의록 | 본문에 명시한 회의일만 `meeting_date`로 복사 |
| `c2-cal-f02-rink-handoff` | 인계·실행 상태 기록 | 기록일과 실제 수행일을 구별. `meeting_date:null` |

모든 source는 revision1이다. 같은 사건의 반복 기재로 모든 사실을 한 문서에 다시 모으지 않는다. 기준과 결정/실행 상태를 서로 다른 문서에 분담해 복수 source가 실제로 필요한 자료를 만들되, 구체적인 평가 질문을 먼저 쓰고 거기에 답을 끼워 넣지 않는다. 자연스러운 문단·목록·필요한 경우 표를 사용하며 후보의 단위 크기를 보고 문장이나 블록 길이를 조정하지 않는다.

제안, 결정, 보류/미해결, 배정, 완료를 구별한다. 담당자 배정이나 계획을 완료로 쓰지 않고 마감일을 실제 수행일로 바꾸지 않는다. 수정·취소가 있으면 적용 대상과 이전/이후 관계를 본문에 명시한다. 특정 필요한 정보가 없다는 것을 숨은 상식으로 메우지 않는다. 합성 본문 작성 후에도 source와 날짜/상태 일관성을 먼저 검토하고 hash를 고정한 다음 질문/oracle를 작성한다.

## 다음 준비 순서와 역할 경계

최초 비교 source 동결 `48aa4f6`의 Linux CI에서 합성 fake 실행시간 fixture 문제가 발견됐다. 부모는 정책/runtime 검사를 유지하고 해당 테스트 fixture만 고친 `8582e602906d465a43684bef20b69ded0aaa46b1`을 commit/push했으며, push/PR의 backend·web·java-service 필수 CI가 모두 성공했다고 전달했다. 활성 동결은 `meetings-c2-comparison-source-freeze-v2.json`이다. 이 작성자는 부모가 확인한 Git/CI 결과를 전달받았고 직접 Git이나 CI를 실행하지 않았다. v1과 실패 CI는 보존한다.

다음 순서는 이 manifest와 처리 규칙 commit → 새 helper 및 Java 동등성 검사·동결 → 합성 원문 작성과 모든 source inventory 고정 → 새 calibration 질문/oracle 작성 및 독립 사전 검토 → 공식 tokenizer만 사용하는 두 정책 입력 준비 → 실행 계획 봉인이다. 이 문서 작성에서 tokenizer, weights, 생성 프로세스는 실행하지 않았고 모델 다운로드도 없다.

이 작성자는 공개 calibration 본문을 보았고 source/처리·자료 설계에 참여했다. 후속 독립 semantic scorer나 격리 validation 작성자가 될 수 없다. Validation의 프로젝트명/경로 등 registry 메타데이터만 보았고 C2-F03/F04 본문·질문·oracle, 과거 pool과 raw 응답은 열지 않았다. 요청된 도구 역할 설정은 `gpt-6-astra / xhigh`이며 실제 spawn 설정 증거는 부모가 기록한다. 인간 검수0, 유료 사용0, 새 품질 호출0이다.

출처 적합성은 문항 적합성·정답률·채택·서비스 운영 검증과 다르다. 공개 절차 문서의 사전학습 가능성, 소규모 목적 표집과 AI 자료 작성 편향을 남긴다. Phase1과 PR14는 계속 미완료/draft다.
