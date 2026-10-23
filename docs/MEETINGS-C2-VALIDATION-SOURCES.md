# C2 격리 validation 출처 채택

2026-10-14. **공개 원문 4개의 출처·개별 라이선스·전체 본문 적합성 검토와 기존 서비스 정규화만 완료했다.** 합성 본문, 선택 context, 질문, oracle, tokenizer, 품질 모델 호출은 모두 0이다. 이 문서는 부모에게 공개 가능한 메타데이터이며 원문 내용이나 문항 후보를 포함하지 않는다.

기준은 [비교 계획](MEETINGS-C2-COMPARISON-PLAN.md), [검토 계약](MEETINGS-C2-REVIEW-CONTRACT.md), 사전 등록된 [family registry](../data/evaluation/meetings-c2-family-registry-v1.json)다. 실제 채택 메타데이터는 [validation source manifest](../data/evaluation/meetings-c2-validation-v1/source-manifest.json)에 기록했다. 기존 registry의 당시 HOLD 상태와 비교 source41/v2는 수정하지 않았다.

## 공개 원문 확인

`C2-F03`의 등록된 `apache/arrow` commit `7ee15283bc9fac8b4e523b0b4640439b547ef0ff`, tree `ef6e22983889e7e24af5983ca2d641c25c3d58e1`만 사용했다. 원문 4개와 LICENSE/NOTICE의 raw bytes, Git blob SHA1, 등록된 크기/해시를 대조했다. Tree는 5,774개 항목이며 잘리지 않았다. Commit을 주소로 한 trees API의 최상위 SHA는 commit을 그대로 반환하여, 별도로 고정된 tree SHA를 주소로 조회하고 개별 blob을 대조했다. 이 API 응답 차이는 원문 불일치가 아니다.

| source ID | upstream path | bytes | 정규화 code points | raw 및 processed SHA256 |
|---|---|---:|---:|---|
| C2-F03-S01 | `CONTRIBUTING.md` | 3,359 | 3,359 | `ac458e4903846aef4cbbc13c7289186f3a0bbe0f47dd76afc27fc44a88d9e917` |
| C2-F03-S02 | `docs/source/developers/overview.rst` | 10,468 | 10,466 | `c5ccc1fe63ddeda50f8a46463aaf769ffd65fb2484216a08b30892ce51edebdb` |
| C2-F03-S03 | `docs/source/developers/reviewing.rst` | 15,187 | 15,187 | `a3886eb8d5dbd37c66aa48915a3c82aa0fb13cd6fa810d780030c2971a905ce5` |
| C2-F03-S04 | `docs/source/developers/release.rst` | 29,948 | 29,948 | `787b8b5cf6a234855aec00ecf34c6854310280cfff0afa41d42be787e47dec19` |

합계는 58,962bytes/58,960code points다. 개별 `document_id`는 `c2-f03-doc-01`부터 `04`, revision은 각각 1이다. 출처 commit 시각을 사건일·회의일로 사용하지 않으며 `meeting_date`와 `page`는 null이다. 등록 순서는 registry의 원문 순서 그대로다.

네 파일 각각의 ASF Apache-2.0 고지와 전체 본문을 읽었고, LICENSE의 예외 적용 범위와 전체 NOTICE를 대조했다. 해당 파일 또는 상위 문서 디렉터리에 적용되는 별도 상충 고지는 발견하지 못했다. Tree의 관련 상위 경로에는 루트 LICENSE/NOTICE만 있었다. 이는 이 네 파일에 대한 출처 감사이며 링크 대상·의존성 전체에 대한 라이선스 판정이나 법률 의견이 아니다.

[고정 LICENSE.txt](https://github.com/apache/arrow/blob/7ee15283bc9fac8b4e523b0b4640439b547ef0ff/LICENSE.txt)의 SHA256은 `cd03925a27219d326d622609fbcae6567279af8b8885c33d5969a9e4ef5d7525`, [고정 NOTICE.txt](https://github.com/apache/arrow/blob/7ee15283bc9fac8b4e523b0b4640439b547ef0ff/NOTICE.txt)는 `afd895d61a00101f6d5a41cf518c83865d815e8109e956f512a0ce4ea9738c06`이다. 두 파일 전체와 원문 고지를 보존한다. 나중에 원문·발췌를 배포할 때도 라이선스·고지·출처를 동반하고 실제 변경을 따로 표시해야 한다. 인용 좌표용 원문에 새 고지를 삽입하지 않는다.

본문 적합성은 등록된 계열의 실질적인 절차 텍스트로서 전체 파일을 채택할 수 있다는 수준이다. 어떤 질문이 답변 가능한지, 복수 source가 반드시 필요한지, 구조·token 상한을 통과하는지는 아직 판정하지 않았다. 문항 수를 맞추기 위한 발췌나 context 선택도 하지 않았다.

## 정규화와 후속 청크 계약

기존 `doctrail.ingest.extract`로 전체 원문을 처리했다. UTF-8 BOM 처리, CRLF/CR→LF, Unicode NFC만 적용하며 header, markup, 들여쓰기, 최종 개행을 포함한 나머지 내용을 유지한다. 이번 네 파일은 raw bytes와 processed UTF-8 bytes가 모두 동일했다. 정규화 파일은 무시되는 `.local/c2-source-adoption/validation/processed/`에 있으며, raw 원문은 같은 validation cache의 `raw/`에 있다. 부모에게는 경로·해시만 전달한다.

Upstream `.rst` 3개는 원래 경로를 manifest에 그대로 유지했다. 이들의 서비스 입력 종류를 명시적으로 `txt`로 지정하여 literal text로 처리했다. RST 렌더링, directive/include 확장, 외부 참조 내용 보충, 코드 실행은 하지 않았다. 처리본 확장자가 `.txt`라는 사실을 upstream 파일 형식 변경으로 표현하지 않는다.

후속 전체 문서 inventory는 기존 Java/Python 규칙을 사용한다. 최대 1,000 code points, 시작점+500 이후부터 잠정 끝 직전까지의 마지막 LF/ASCII SPACE에서 경계를 잡고 그 문자를 포함한다. 다음 시작점은 `max(start+1, end-150)`이다. 빈 청크만 생략하고 슬라이스는 trim·재작성·병합하지 않는다. 좌표는 정규화 전체 문서의 code point 반열린 구간이다. 청크 ID는 `{document_id}-r1-c{ordinal:04d}`다.

현재 새 helper는 upstream `.md/.txt`만 허용하므로 **원래 `.rst` 경로를 보존하는 명시적 literal-text 지원을 helper 동결 전에 등록해야 한다.** Helper는 이 validation 자료에 실행하지 않았다. 실제 Java/Python 전체 문서 청크 일치, helper 동결, 전체 청크 inventory는 아직 없다. 이후 선택도 고정된 전체 청크를 기준으로 따로 등록해야 하며, 질문·후보 출력에 맞춘 문장 재배치나 임의 단축을 허용하지 않는다.

## 합성 계열과 격리

`C2-F04`는 registry의 가상 인쇄소 교정 승인·생산 인계 계열을 유지한다. `C2-F04-S01/S02`, `c2-f04-doc-01/02`, revision1만 예약했다. 실제 조직·사람·사건·날짜·조건·수치·본문은 만들지 않았다. 향후 자료는 새 가상 조직의 AI 작성 평가 자료임을 표시하고, 실제 고객·고용주·개인 업로드나 기존 pool의 사실·이름·표현을 재사용하지 않는다.

계열별 계획은 각각 6문항, KO3/EN3, 답변 가능4/근거 부족2다. 합계 validation12 계획은 실행된 문항 수가 아니다. 원문·합성 본문·질문·oracle·항목별 설명은 격리 담당자만 열고 부모·prompt·구조 설계자에게 보내지 않는다.

작성자는 `c2_validation_source_b`다. 부모가 실제 spawn 도구의 `gpt-6-astra`, `xhigh`, `fork_turns:none` 수락을 확인해 전달했다. 이는 개발 보조 역할의 설정이며 서비스 추론 또는 부모 모델 변경 증거가 아니다. 이 역할은 calibration 본문·과거 품질 pool·부모 상태 문서·다른 역할의 대화를 읽지 않았다. 자신의 공개 원문 검토4는 독립 사전검토나 독립 의미 점수가 아니며, 후속 독립 scorer 역할에서 제외한다. 인간 검수는 0이다.

## 확인 범위와 남은 작업

무시되는 validation cache의 `fetch-receipt.json`과 `normalization-receipt.json`이 원본 검증과 정규화 결과를 기록한다. Manifest는 두 영수증과 기존 서비스 구현 4개 파일의 SHA256을 연결한다. 이번에는 raw/processed 재해시, blob/size 대조, UTF-8·개행·NFC·정규화 동일성, 경로·ID·등록 순서·0호출 상태를 확인했다. 신규 runtime 코드 또는 평가 도구를 실행한 검증은 아니다.

공개 원문의 모델 사전학습 포함 여부와 목적 표집 편향은 알 수 없다. Literal RST의 외부 참조·markup은 그대로 남는다. 소스 helper의 명시적 RST 지원과 실제 전체 문서 Java/Python 일치·동결이 완료되기 전에는 합성 본문·context·질문·oracle 작성, tokenizer 및 모델 실행을 시작하지 않는다. 이후에도 별도 사전검토, 입력 봉인, calibration 선택 게이트가 필요하다. 이 기록은 generation readiness나 서비스 채택을 뜻하지 않으며 Phase1은 계속 미완료다.
