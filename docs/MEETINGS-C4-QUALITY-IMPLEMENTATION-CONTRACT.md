# C4 품질 도구 구현 명확화

2026-10-16. 새 source·질문·oracle·실제 tokenizer·품질 native 호출 전에 등록한다. 기존 `MEETINGS-C4-QUALITY-PLAN.md`, protocol-v1, family-registry-v1의 내용과 예산은 변경하지 않는다. 이 문서도 전체 도구 동결에 포함한다. 기존 실제 Astra xhigh 설계 역할의 추가 검토를 받았으며 사용자 검수는 0이다.

## 새 원문의 중복 검사

정규화 순서를 NFC, CRLF/CR을 LF로 통일, 연속 공백 축약, 양끝 공백 제거로 고정한다. 문단은 공백 축약 전 빈 줄 경계로 나누고 각 문단을 같은 방식으로 정규화한다. 정규화 후 200 Unicode codepoints 이상인 문단의 SHA256과 전체 문서 SHA256을 기록한다. 원문 바이트 자체를 이 정규화 결과로 대체하지 않는다.

- 정규화된 전체 문서 중복은 같은 family 안에서도 거절한다.
- 긴 문단의 cross-family 또는 cross-split 중복은 거절한다.
- 같은 family의 긴 문단 반복은 자동 승인하지 않는다. 독립 source prereviewer가 반복 그룹마다 문단 hash, 문서 식별자, source hash에 연결된 accept/reject와 이유를 기록한다. 모든 반복 그룹이 수락돼야 source freeze가 가능하다. 이 판단은 질문 작성 전에 고정한다.
- 반복을 없애기 위해 질문에 맞춰 원문을 삭제·수정하거나 다른 원문으로 교체하지 않는다.

반복 문구가 여러 문서에 나타난다는 이유로 필수 복수 문서 근거로 세지 않는다. Item prereview는 반복 구절을 포함한 모든 충분한 근거 대안을 확인한다. 하나의 문서로 충분한 대안이 있으면 해당 질문은 필수 복수 문서 기준에서 제외한다. 자동 OR/AND 문서 집합 검사는 등록된 대안을 계산할 뿐, 누락된 대안을 스스로 발견했다는 의미가 아니다.

과거 자료는 이미 공개된 family/URL/revision/raw hash와 사용 가능한 정규화 fingerprint metadata만 비교한다. 닫힌 본문을 다시 열지 않으며 fingerprint가 없는 과거 범위를 명시한다. Validation freshness는 고정된 calibration fingerprint 영수증 hash를 연결한다. 이 검사는 정규화된 동일 내용만 검출하며 번역·분할·근접 재서술의 완전 탐지를 주장하지 않는다. Source/item 독립 의미 검토의 한계와 실제 검토 역할을 함께 남긴다.

## 커밋과 CI 증명 순서

전체 코드·설정·테스트·이 문서의 바이트를 동결하고 커밋한 뒤 실제 필수 CI 결과를 관측한다. CI 영수증에는 해당 commit, 동결 파일 hash, 관측한 push/PR run과 필수 job의 성공을 기록한다. 영수증도 별도 커밋한 다음 source 준비로 넘어간다. `committed: true` 같은 자체 표시만으로 바이트 증명을 대체하지 않는다.

도구는 실제 Git object의 바이트와 작업 파일을 대조한다. 같은 실행 안에서 이미 대조한 Git 증거를 캐시할 수 있지만 HEAD와 파일 hash가 그대로인지 매 경계에서 다시 확인해야 한다. HEAD 또는 관측 파일 변경은 실패로 처리하며 검사를 건너뛰는 허용 플래그는 두지 않는다. CI 영수증은 실제 원격 관측 기록이며 원격 서비스의 암호학적 증명으로 표현하지 않는다.

Source freeze는 선행 toolchain commit을, item freeze는 선행 source commit을 가리킨다. 자기 자신의 미래 commit을 넣는 순환 요구를 만들지 않는다. Metadata·커밋·역할 검사는 semantic 자료 개방 전, 실제 dispatch 전에도 수행한다. Validation 본문 개방은 원래 calibration 6/6 판정과 운영 조건의 재생 통과가 선행한다.

## 전송 직전 기록과 시간 제한

`native_post_started`는 전송 직전 후크 진입 기록이다. 서버 수신이나 생성 완료의 증거로 세지 않는다. 기록 콜백도 동일 90초 예산에 포함하며 콜백 이후 남은 시간을 다시 확인하고 HTTP timeout을 줄인다. 콜백 중 예산이 끝나면 `native_post_aborted`로 실패를 남기고 native 요청을 전송하지 않는다. 시도·전송 관측·완료 건수를 구분한다.

성공 HTTP의 파싱된 원본 응답과 적용 설정·토큰 기록은 보존한다. 기존 HTTP primitive가 본문을 노출하지 않는 비정상 상태나 잘못된 JSON에서는 status/error와 본문 관측 불가를 표시한다. 관측하지 못한 원문을 보존했다고 주장하지 않는다. 운영 로그에 원문·질문·native 진단을 남기는 규칙은 추가하지 않는다.

이 계약·합성 검사·코드 검토는 품질 통과가 아니다. 새 자료 작성과 실제 평가에는 전체 도구 동결·커밋·CI 이후의 source-first 절차가 그대로 필요하다.
