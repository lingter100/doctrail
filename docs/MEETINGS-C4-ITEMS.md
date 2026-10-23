# C4 새 문항 작성·사전검토·독립 판정 등록

2026-10-16. Source 커밋 `9a72a33`과 동결 도구85파일 이후 새 질문을 작성했다. 두 split의 원문·작성 역할·탐색 노출은 [원문 기록](MEETINGS-C4-SOURCES.md)을 따른다. 이 문서는 준비 상태이며 모델 품질 결과가 아니다.

## 작성과 최초 검토

Calibration은6문항(KO3/EN3, 답변가능4/보류2, 필수사실24), validation은8문항(KO4/EN4, 답변가능4/보류4, 필수사실34)이다. 질문 작성자와 사전검토자는 각각 별도 Astra xhigh 역할이다. 전체 청크와 필수사실의 충분 근거 대안, 일반 문서·복수 회의·혼합 자료 및 양방향 교차언어 구성을 확인했다. AI 작성과 AI 사전검토이며 사용자 검수는0이다.

최초 calibration 검토는5수락/1불수락이었다. C4-CAL-05의 한 필수사실에 충분한 다른 근거 대안이 빠져 있었다. 자동 좌표·구조 검사가 통과했어도 근거 대안 목록이 완전하다는 뜻은 아니었다. 원래 초안4개와 불수락 검토3개를 `29d7e0a`로 보존했고 이 버전의 accepted freeze는 만들지 않았다.

같은 작성자는 원래 지적된 대안1개만 `oracle-draft-v2.json`에 추가했다. `draft-v2.json`과 `context-selection-v2.json`은 원본과 바이트가 같으며 나머지5문항과 모든 질문·context·필수사실 문구도 같다. 모델 출력이나 토큰 길이는 아직 관측하지 않았으므로 이에 맞춘 수정이 아니다. 원래 사전검토자는 새v2를 독립 검토해 **6수락/0불수락/추가수정0**을 확인했다. 정확히6binding의 `item-freeze-v2.json` SHA `f37ce63b8d58db6eebb50da3e72231d95a0102502ce463a00d9d4d9461ead9a8`을 만들었으며 전체 `load_material` 실제 Git 검사는 이 커밋 뒤에 한다. 최초 불수락은 이후 수락으로 덮어쓰지 않는다.

Validation은8수락/0불수락/변경요청0이다. `item-freeze-v1.json` SHA `c29f89300f48b2f7a7706a87fb05f6f902bc470ab8ecf360e0868ad5ce65afa6`은 정확히6개 binding을 가진다. Item 커밋 뒤 격리 검토자는 실제 GitProof와 전체 `load_material`을 실행해 코드85·소스15·item6, 6문서/20청크/8문항/34필수사실을 확인했다. `.local/c4-validation-item-postcommit-v1/proof.json` SHA `b86972b5a7797553ccbfa55695690b7705b98d605727a3bea3bf5771c92c3315`로 보존했다. 이 확인은 공식 tokenizer 준비를 실행하거나 예약하지 않았다. 부모는 의미 본문 대신 hash와 개수만 받았다.

## 생성 전 최종 판정 역할 예약

새 `c4_calibration_final_judge`와 `c4_validation_final_judge`를 각각 `gpt-6-astra`/`xhigh`/`fork none`으로 생성했고 도구가 수락했다. 기존 원문·질문·사전검토·설계·구현에 참여하지 않았다. 생성 전 직접 작성한 attestation과 별도64byte seed를 [역할 등록](../data/evaluation/meetings-c4-review-registration-v1.json)에 연결했다. 원문·모델 출력·매핑·reasoning·기존 판단 본문은 열지 않았다.

자동 제공 프로젝트 지침에서 모델·가설·이전 집계 metadata를 봤다고 두 역할 모두 공개했다. 따라서 metadata-exposed, label-masked이며 완전 블라인드가 아니다. 이후 익명 최종 답변 pack만 읽고 필수사실·추가사실·주체·시점·조건·언어·보류·인용 지원을 판정한다. 판단 SHA를 잠그기 전에 reasoning이나 매핑을 공개하지 않는다. Calibration 원래6/6 및 운영 무결성 관문을 통과하지 못하면 validation 판정 역할을 예약했다는 이유로 validation을 실행하지 않는다.

## 다음 실행 순서

Calibration v2 전건수락 및 item freeze 커밋 → 실제 Git 전체 material 확인 → split별 공식 offline 계수 각1회 → 결과와 실행계획 커밋 → calibration 최대6회 → 원본 판정 잠금·관문 재생 → 조건 충족 시에만 validation 최대8회다. 상한 초과나 실행 실패를 새 질문·context 절단·재시도로 복구하지 않는다. 닫힌 자료와 기존 실험은 그대로 보존한다.

준비 과정의 최초 Windows Python alias 오류와 `.local` 직접 실행에서 `scripts` 모듈을 찾지 못한 보조 등록 오류는 tokenizer/native 이전 오류다. 등록 보조 코드는 저장소 `uv`와 프로젝트 루트의 `runpy`로 실행했으며 attestation이나 seed를 중복 생성하지 않았다. 모델 준비/실험 실패와 구분한다.
