# C6 calibration 원문 독립 사전검토

2026-10-20. 검토자 `/root/c6_calibration_prereviewer`, 작성자 `/root/c6_calibration_author`. 작성과 검토는 별도 역할이며, 검토자는 같은 split의 향후 item 사전검토 역할을 재사용하도록 등록되어 있다. 이번 검토는 source에 한정된다. 최종 답변 judge에서 제외되며 질문·oracle·답변·trace·mapping 및 validation 의미자료는 읽지 않았다. 자동 AGENTS·memory 요약과 공개 metadata 노출이 있으므로 pristine 또는 완전 맹검이라고 주장하지 않는다.

## 판정과 범위

원문 6개를 수정 없이 수용한다. 공개 3개와 AI 작성 허구 3개, family마다 다른 날짜의 회의 2개와 일반 문서 1개라는 구성이 충족된다. 처리된 전체 20개 청크를 보존한다. 이 판정은 자료의 출처·일관성·완전성·제한된 신선도에 관한 것으로, 아직 작성하지 않은 문항의 정답 가능성·token 상한·모델 품질 또는 서비스 완성을 승인하지 않는다.

사전 실제 code proof 영수증 SHA는 `ca709528685d9f93edfb4ddd3534359c71c38385e387f54f5cbbecf1140a2006`이다. 당시 frozen77, Git159 revision/path 증명, snapshot82를 수행했다. 이번에는 HEAD `0755660866488bb83fb2d7330c008b2ba1da192f`와 해당 82개 binding의 연속성을 다시 확인했고, 비싼 전체 proof를 불필요하게 반복하지 않았다. 작성자 handoff SHA `57591c90d528265c6897919019ead87f2b0e8004c3611498a9adbbdf98e2933e`가 묶은 18개 artifact를 검토 전후 그대로 유지한다. Git은 자료 생성 시각이나 과거 부재를 증명하지 않는다.

## 공개 family의 출처와 대표성

OpenJS cross-project-council의 고정 commit `dd739e6e90d8e44e557a561348940991f0da3bb1`에 있는 전체 회의록 2개와 지원 안내 1개다. 저장된 repository·commit·전체 tree metadata를 대조하고 각 원문의 Git blob SHA1 및 크기를 직접 재계산했다. 전체 MIT 저작권·허가·면책 문구의 raw SHA256와 Git blob도 별도로 대조했으며 manifest와 inventory provenance에 보존되어 있다. 원문은 해당 local acquisition 사본과 byte 단위로 같다. 링크된 이슈·영상·외부 서비스의 본문은 가져오지 않았고, 그 안에 있을 법한 사실을 원문으로 간주하지 않는다. 이번 검토에서 원격 서버를 다시 조회하지 않았으므로 저장된 취득 증거를 재검증한 것이며 독립적인 원격 인증이라고 과장하지 않는다.

- `c6-cal-doc-01`: 2025-01-07 회의록의 날짜·참석·안건·후속 작업·정기 점검 부분이 함께 남아 있다. 여러 안건의 미해결 상태와 짧은 의견이 자연스러운 회의 기록이다. 인프라 과정에 관한 새 PR 언급은 당시 진행 상태로 읽어야 하며, 구현 완료나 모든 안건의 최종 승인으로 확대하지 않는다.
- `c6-cal-doc-02`: 2025-02-04 회의록은 별도 날짜와 참석자를 갖고, 예산·조직·과정 관련 기록을 온전히 보존한다. 후속 인프라 과정 논의는 앞선 회의와 연결되지만 종료 제안과 실제 종료 결정은 구분해야 한다. 비어 있는 Recording 항목과 적히지 않은 private-session 세부사항은 원문 한계로 남긴다. 검토자가 채우거나 고치지 않는다.
- `c6-cal-doc-03`: 지원 대상·일반/기밀/비공식 연락·우선순위·상태 확인·긴급 절차가 한 문서 안에 있어 일반 문서로서 완결성이 있다. 다만 이는 고정 repository revision에서 취득한 안내이며 2025년 회의 당시의 문서판이라고 증명되지 않았다. 두 회의와 같은 인프라 지원 맥락으로 묶는 것은 타당하지만, 이 안내가 특정 회의 결론 때문에 만들어졌거나 그 날짜부터 시행됐다고 추론해서는 안 된다. 원문의 철자·공백·표기를 보존한다.

공개 family는 선택한 세 문서의 대표적 전체본이다. repository 전체나 모든 안건을 포괄하는 표본이라는 주장은 하지 않는다. 관계없는 안건도 잘라내지 않았으며 선택 후 token feedback이나 문항에 맞춘 본문 편집은 없었다.

## 허구 family의 일관성과 의미 검토

돌림빛 그림자극 보존모임 기록은 AI가 작성한 허구임이 각 원문 및 provenance에 명시되어 있다. 실제 기관·실험 또는 실제 보존 전문가의 판단으로 제시하지 않는다.

- `c6-cal-doc-04`: 2026-06-01 일반 지침은 보관·촬영·가역적 연결부 시험·빛/시간·기록을 구분한다. 시험 재료와 원본을 구분하고 상태 기록과 관찰을 함께 요구하므로 단순한 숫자 목록이 아니라 보존 목적과 후속 판단 기준을 갖춘 문서다.
- `c6-cal-doc-05`: 2026-06-03 회의는 두 작품의 서로 다른 상태와 담당자의 역할을 구분한다. 최초 촬영, 원본 보관, 시험용 종이의 대안 비교, 장소 선택과 다음 확인이 이어진다. 연습 종이의 결과만으로 들뜬 채색층 문제를 해소하지 않는다는 제한은 일반 지침과 맞는다. 아직 정하지 않은 사항은 열린 상태로 남아 있다.
- `c6-cal-doc-06`: 2026-06-17 회의는 시험 관찰을 실제 원본 처치와 구분하고, 복제 인형의 동작 선택과 원본 보관 결정을 별도로 기록한다. 다른 작품의 제한된 점검과 관객 시연 결정도 혼동하지 않는다. 앞선 회의의 가설이 관찰에 따라 좁혀지는 흐름이며, 일반 지침의 점검/공연 구별과 충돌하지 않는다. 음원 보존과 미정 편성도 남아 있어 한 가지 답을 위해 구성한 발췌문으로 보이지 않는다.

이 family의 반복은 같은 대상의 상태 추적과 규칙 적용에 필요한 의미 연속성이다. 원본/시험용 종이/복제의 구분, 재료 손상과 동작 관찰, 조건부 결정이 서로 다른 문서 역할을 갖는다. 공개 governance·IT 문서의 사실 구조를 이름과 숫자만 바꾼 재서술로 보이지 않으며, 현재 6개 문서 사이에 의미상 거의 같은 문서를 이중 채택한 정황은 발견하지 못했다. 이 판단은 검토자가 읽은 현재 자료에 대한 실제 의미 검토이며, 닫힌 과거 본문까지 비교했다는 뜻은 아니다.

## 공유 긴 문단과 신선도의 한계

현재 family 내부에서 길이 200 codepoint 이상인 정규화 문단의 동일 hash는 공개 회의록 01/02 사이 1개다. SHA256 `17905d1e3c1b7ebe864c996f256c3ffce9ab742b96842b3f8c5d7046717c7835`, 정규화 길이 273이다. 실제 문단은 날짜/분기 검토/닫을 이슈를 가리키는 정기 점검 링크 3개의 반복이다. 두 회의의 날짜별 결정·의견·상태를 복제한 내용이 아니며 회의록의 반복 안내 부분이다. 이를 `accepted_history_repetition`으로 수용하고 원문에서 제거하지 않는다. 이 문단만으로 두 날짜에 별개의 결정이 있었다고 세어서는 안 된다.

현재 문서 전체 중복 및 family 간 긴 문단 중복은 없고, 등록된 prior metadata 98행과 family/URL/revision/raw/정규화 문서/긴 문단 지문을 대조한 정확 충돌은 0이다. 공개 repository도 prior 제외 목록과 겹치지 않는다. 원본 blank-line 기준 문단 분리와 NFC·줄바꿈·whitespace 정규화를 실제 재계산했다. hash 차이만으로 의미 신선도를 판정하지 않고 위의 문서별 역할·시간·대상·인과 내용을 별도로 읽었다.

과거 원문은 열지 않았다. prior metadata의 정규화 coverage는 30행에 한정되고, 등록된 누락 3항목을 그대로 유지한다. 따라서 과거 전체 자료와의 번역·의역·의미 근접중복 부재는 증명하지 않는다. 이번 calibration 검토는 validation 의미자료에 접근하지 않으며 cross-split 의미 검토는 지정된 격리 검토자의 후속 범위다. 신선도 수용은 이 접근 제한과 coverage 한계를 포함한 판정이다.

## 처리와 실제 Java 증거

동결된 `document_record`로 6개 전체 문서를 다시 처리하여 inventory의 content, provenance, pages, chunk text, offset, ordinal, ID 및 hash가 정확히 일치함을 확인했다. raw와 processed 사본도 모두 일치하며, 원본 정규화나 문단 절삭을 새로 적용해 고친 파일은 없다. 기존 processing receipt와 실제 Java receipt는 동결된 `validate_processing_receipts`의 기대 구조와 일치한다.

저장된 actual Java receipt의 공개 사본과 local 원본이 byte 단위로 같다. `run-receipt.json`, Surefire XML, 텍스트 보고서와 Maven log의 실제 2통과·0실패·0오류·0skip·suite 0.343초 및 exit0/BUILD SUCCESS가 일치한다. input77 before/after와 inventory before/after hash도 일치한다. 검토자는 Maven을 재실행하지 않았다. 원래 Python processing receipt의 `java_parity_verified: false`는 처리 시점의 상태로 보존하고, 별도 실제 Java 영수증과 혼동하거나 소급 수정하지 않는다. 이 증거는 문서 처리 일치이고 의미 품질이나 성능 비교가 아니다.

## 다음 단계의 경계

원문 수정 요청은 0이다. source-freeze는 C6의 정확한 source schema와 7개 역할 경로, raw6, prior metadata를 합친 14개 binding으로 만들며 toolchain source commit을 고정한다. 처리 사본·취득/실행 근거와 상세 검토 기록은 별도 hash 증거로 남긴다. source freeze와 원문이 커밋된 뒤 별도 item 지시가 있어야 질문 작성 또는 item 사전검토를 시작한다. 이번 작업의 tokenizer/native/model execution, 질문/oracle 작성, 추가 Maven, Git 변경 및 human review는 모두 0이다.
