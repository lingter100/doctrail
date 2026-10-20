# C6 새 원문 준비

2026-10-20. 도구 source d3e4e2e 양쪽 필수 CI와 별도 CI 영수증1d9227b의 양쪽 필수 CI를 확인했다. 아직 실제 원문·문항·tokenizer·모델 실행은0이다.

## 목적과 방법

회의와 일반 문서를 함께 읽는 답변을 검증한다. 질문에 맞춰 근거를 만들지 않도록 split마다 공개 family와 명시적 합성 조직을 하나씩 선정하고 각각 날짜가 다른 회의2개와 일반 문서1개를 먼저 확정한다. 전체12문서의 출처·이용조건·고정 revision·Java/Python 처리 일치·독립 검토 뒤 질문을 작성한다. 토큰 계수나 모델 출력으로 원문을 바꾸지 않는다.

과거 출처 index659fef38은 metadata4개·98행(canonical95)·정규화 hash30행·누락3항목·제외repo11개다. 거부된 C5 validation v1과 채택v2를 모두 보존했고 동일 공개3행도 남겼다. 과거68행에는 정규화 hash가 없어 완전한 중복 부재를 증명하지 못한다. 과거 본문은 재개방하지 않는다.

## 실제 역할과 경계

| Split | 작성(source, 이후 item) | 별도 사전검토(source, 이후 item) |
| --- | --- | --- |
| calibration | /root/c6_calibration_author | /root/c6_calibration_prereviewer |
| validation | /root/c6_validation_author | /root/c6_validation_prereviewer |

모두 새 fork none, GPT-6 Astra xhigh를 도구가 수락했다. [역할 등록](../data/evaluation/meetings-c6-role-registration-v1.json)에 실제 수락시각·영수증·노출·허용 경로를 남겼다. 같은 split 역할 재사용을 공개하며 자기검토·split 간 겸임·최종 답변 judging을 금지한다. 부모는 원문/질문/oracle 의미를 열지 않는다. Validation 검토자의 이후 명시적 source 신선도 비교만 finalized C6 calibration SOURCE를 허용하며 문항/oracle은 금지한다.

## 순서와 확인

역할/index 커밋 뒤 각 작성자가 실제 code_contract/GitProof/role 계약을 검증한다. 부모는 이 동안 HEAD를 유지한다. 공개 repo를 본문 전에 예약하고 출처·이용조건을 확인한다. Java parity는 한 명씩 실행한다. 독립 source 검토·동결·커밋 후 item 작성·독립 검토·동결·공식 offline 준비1회·조건부 native 평가로 이어간다. 닫힌 실험과 원본 실패는 재실행/수정하지 않는다.

AI 작성·AI 독립 검토와 사용자 직접 검수는 다르다. 이번 등록은 모델 답변 품질을 입증하지 않으며 Phase1과 PR14는 미완료/draft다. 실제 준비·실패·수용 결과는 이후 절에 추가한다.

## 역할 커밋과 원문 준비 시작

역할/index0755660의 push39359700463/PR39359707085 필수3job을 실제 확인했다. 두 작성자 모두 실제77개 코드 binding·159개 Git revision/path proof·81개 snapshot과 역할/과거 index 검증을 수행하고 동일 HEAD를 확인했다. 부모의 선행 검증을 작성자 자신의 증거로 재사용하지 않았다.

본문 전 예약은 calibration openjs-foundation/cross-project-council, validation jupyter/community-committee다. 최초 validation jupyter/governance는 회의 파일 부재로 제외했고 jupyter/leadership404도 보존했다. 이용조건/원문/처리 일치/독립검토는 작성자와 검토자의 실제 후속 결과로만 기록한다. 아직 source 동결과 문항 작성은 시작하지 않았다.

## 원문 처리와 실제 Java 일치 검사

작성자가 source6개씩을 반환했다. Calibration20청크·Java2통과/0.343초, validation13청크·Java2통과/0.312초다. 각 Maven1회·실패/오류/skip0, 소유 새 JVM0이며 공유 폴더 경합을 피하려고 순차 실행했다. 다른 프로젝트 Java 프로세스는 건드리지 않았다. 문항·tokenizer·native0이며 독립 source 검토는 진행 중이다.

부모는 저자 산출물36개와 staged bytes의 일치를 hash로만 확인했다. 첫 whitespace 오류를 보존하고 공개 원본/처리 사본6개의 upstream 공백, 실제 Java영수증2개의 CRLF에만 경로별 예외를 적용했다. 원본 정규화나 의미 변경은0이다. Java영수증에는 좁은 -text 속성을 추가해 Git 자동 줄바꿈 변환을 막았다. 이 절의 처리/검사 성공은 독립 의미 신선도 수용을 대신하지 않는다.

## 독립 검토 결과와 동결

각 source 작성자가 아닌 별도 Astra xhigh 검토자가 6개씩 수용했다. 거부0·원문 변경0이다. Calibration 동결14개 SHAecf4a08d8d5edc8598646e3be2d25b0203af633ae39d298014c479befcf49b53, validation 동결15개 SHA1ef3cea7d156fd6b84ae19e188e0930a6b2bb9541292cf31f61603c8dd701625다. Validation 검토자는 자기 자료 검토를 마친 뒤 명시적 허용을 받아 확정된 현재 calibration SOURCE6만 추가로 비교했다. 질문/oracle 접근은 없었다.

새 자료 사이 exact/의미 근접중복 발견0이며 각 공개 family 내부의 공통 문단1쌍은 이유를 기록하고 수용했다. 과거 자료는 metadata만 비교했으므로 누락3항목과 semantic coverage 한계를 유지한다. 이 결과가 모든 과거 문서의 완전한 중복 부재를 증명하지 않는다. 원문/문항 작성자는 자기 자료를 검토하거나 최종 답변 judge를 맡지 않는다.

저장된 실제 Java2개씩의 XML·로그·영수증과 문서 재처리를 확인했다. Review 단계의 Maven·모델·tokenizer 재실행은0이다. [공개 결과 영수증](../experiments/results/meetings-c6-source-review-v1.json)은 source46개·원본36개와 freeze를 묶는다. 원래 실패·Java CRLF·upstream 공백은 보존했고 사람 검수는0이다.

다음은 이 source/freeze 커밋·필수 CI를 확인한 뒤 새 calibration6/validation8 질문과 oracle을 작성하고 별도 사전검토·동결하는 단계다. 현재 실제 질문·tokenizer·native·답변 의미 판정0이며 Phase1·실서비스 채택·배포는 완료되지 않았다.

## Source 커밋과 CI

887e89f795b22ba043a0f62fa1b65c7d62e8cc75에54파일을 커밋·push했다. Push39361887466/PR39361890912 필수 backend/java-service/web이 모두 성공했고 사용자 GitHub author·committer lingter100을 확인했다. 공개 산출물46+동결 코드77개의 Git/working123개 bytes 일치도 확인했다. [실제 CI 관측](../experiments/results/meetings-c6-source-ci-v1.json)은 source 수용/모델 품질과 분리한다.

후속 문항 작성자는 최신 HEAD와 이 source commit의 증명을 새로 수행한다. Validation 작성자는 교차 비교 사유를 읽어 calibration 내용을 배우지 않도록 해당 파일은 hash만 확인한다. 현재 승인된 자기 source6을 질문·oracle·전체 청크 선택의 근거로 사용하고, 별도 사전검토·동결 전에 tokenizer나 실제 모델을 실행하지 않는다.
