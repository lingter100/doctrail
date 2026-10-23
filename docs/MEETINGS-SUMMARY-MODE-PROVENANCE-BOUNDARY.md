# 추론 모드 개발 진단의 자료 이력 경계

2026-10-23. **부모 수용·커밋 전인 전향적 추가 계약**이다. `current-split-review-v1` 독립 감사는 배정됐으나 결과가 반환되지 않았다. 이 문서는 source admission·동결·실행 준비 완료나 실제 실행을 선언하지 않으며, 구현 배정도 아직 없다.

[원래 계획](MEETINGS-SUMMARY-QUALITY-NEXT.md)(18,650B, SHA-256 `fb32d66f4c2264edec160b908b83fa1050731c455099636b985793db40d0b329`)과 [launcher amendment](MEETINGS-SUMMARY-MODE-LAUNCHER-REPAIR.md)(11,215B, `7bbd6e2c35c4cea5970a2150bdbbdb74296085eb11a40ca4426aba93fb340a5b`), 기존 source reviewer의 잠긴 L2 원판정과 모든 원본 증거는 그대로 보존한다. 원래 line50/L2를 충족한 것으로 소급 변경하지 않는다. 부모가 이 추가 계약을 수용하고 별도 자료 disposition을 내린 뒤 새 등록으로 수행할 `summary-mode-development-v1`에만 아래 경계를 적용한다.

1. **확인된 이력의 한계.** 안전한 최종 custody 기록 `.local/meeting-summary-mode-prior-source-inventory-v1/historical-binding-custody-closure-v1.json`은 5,323B, SHA-256 `a3712c5c04360d6b94e6f28766e0cc7cc0849b3a3ef4cfda4511160589d88175`다. 마지막 허용 selector에서 제품 코드 hash 6행과 context identity 3행을 확인했으나, 전체 역사적 probe 실행→원문·요청·probe 버전의 결속은 증명하지 못했다. 이 조사는 허용 selector에서 종료·반환됐으며, 그 제한된 범위의 기록 한계를 남긴다. 미기록 이력 전체의 부재, 과거 보호 자료 미사용 또는 오염 발생을 어느 쪽으로도 단정하지 않는다. 현재 코드·DB ID·관측 일치 0건을 과거 실행 원문의 대용으로 쓰지 않는다.

2. **새 계약의 line50 적용 범위.** 승인된 유한한 known pool metadata, 실제로 기록된 input/source/version 연결, 허용된 중복 비교와 남은 공백을 함께 동결한다. 확인 가능한 누락 증거를 생략하거나 실제 중복을 공백으로 바꾸지 않는다. 모든 과거 개발 실행의 완전한 복원과 모든 미기록 노출의 부재 증명은 이 별도 개발 진단의 선행조건으로 삼지 않는다. 전체 역사 미노출·완전한 역사적 분리·과거 평가 적격성 주장은 보류한다. 기존 L2 미증명 기록은 이 새 범위에서도 사라지지 않는다.

3. **현재 보호 split과의 직접 분리는 필수다.** 별도 source reviewer가 이미 알려진 declared22의 split/assignment 안전 metadata만으로 `current-split-review-v1`을 작성한다. 유효한 manifest/registry 버전, 현재 source/family의 split 배정 및 실제 배정 여부, 비교 대상 범위와 새4의 식별자·버전·호환 지문 연결을 명시해야 한다. 목록이 현재 보호 집합을 포괄하는지 확인되지 않으면 해당 범위는 미확정으로 남긴다. 관측 일치 0건만으로 감사 완료를 선언하지 않는다. 현재 보호 source/family와 직접 중복되거나 그 분리 판단에 필요한 구체적 배정 증거가 미해결이면 admission을 보류한다. 이 문서는 새4를 교체하거나 기존 split을 재배정하는 권한을 주지 않는다.

4. **미배정 family와 미래 평가를 보호한다.** 원문이 아직 배정되지 않은 family는 그 상태와 기존 격리 규칙을 유지하며, 비어 있는 식별자를 임의의 원문으로 채우지 않는다. 새4와 기존 family 정의에 따라 연결되는 개발 자료를 미래 보호 평가의 제외 목록에 기록한다. 예약된 보호 family와 충돌하면 개발용으로 바꾸지 않고 보류한다. 이 확인을 위해 최종 Test를 작성·개방하거나 문제·정답·criteria·모델 출력을 읽지 않는다.

5. **사용자 요구와 주장 범위.** train/dev/final 분리와 Test 튜닝 금지는 현재 보호 자료의 직접 분리, 사전 고정된 개발 조건, 평가 내용 비사용, 역할 분리와 향후 제외로 유지한다. 앞선 “과거 보호 자료 사용 여부가 미확정이면 새 개발 비교도 차단”이라는 해석은 두 문제를 혼동해 과도했으므로 이 전향적 계약에서 정정한다. 과거 probe가 보호 자료를 썼는지 미확정이라는 사실은 새4가 현재 보호 split에 속한다는 증거가 아니다. 반대로 새4의 직접 분리가 확인돼도 과거 평가가 적격이었다는 증거가 되지 않는다. 이 조건에서 가능한 결과는 역사적 한계를 공개한 새4의 개발 비교이며, 미노출 holdout 검증이나 공식 최종 평가가 아니다. 이 구분은 품질 목표를 낮추지 않으면서 사용자 요구보다 강해진 전체 개발 이력 복원 의존성을 분리한다.

6. **바꾸지 않는 조건.** 새4의 원문·선택·표현, 후보와 mode 외 공통 조건, 완전한 자연어 요약·지원성·핵심 충분성·읽기 쉬움, 원래 품질 문턱, once·중단 규칙·예산, 담당 역할, 출력 전 source-only 기준 잠금과 익명 독립 판단 순서는 모두 그대로다. 기존 source reviewer 판정을 해시 검사로 대신하지 않는다. 일부 개선이나 개발 진단 통과로 서비스 채택·기존 calibration/validation/최종 Test gate를 대체하지 않는다. 이 문서 작성 과정의 기준 작성·원문/QA/출력 열람·제품 코드 변경/기동·테스트/모델 실행·Git은 0이다. 기존 집계 노출, 작은 표본·AI 검토·human 0 한계도 유지한다.

7. **최소 구현 경계와 실행 전 결정.** 부모 수용·커밋 뒤 별도 배정이 있을 때에만 현재 probe/test 두 파일에서 registration의 필수 exact reference `provenance_boundary` 1개를 추가한다. 값은 이 문서의 고정 path·bytes·SHA-256이며, 원래 plan과 launcher amendment 참조도 계속 필수다. 누락·잘못된 경로/크기/hash·전후 변조를 거부하고 기존 post-custody 재검사에 포함한다. 합성 회귀는 그 계약 거부와 기존 동작 보존을 확인한다. 공유 helper·frozen 파일·제품 코드는 수정하지 않는다. 이는 계약의 결속이며 자료 수용 판정이 아니다.

8. **현재 상태와 실행 전 조건.** 계약 binding 구현 배정과 자료 수용은 별개다. 실행 전에는 독립 current-split 감사 결과와 부모의 검토·새 명시적 source disposition이 필요하며, 기존 source-only 기준 잠금·증거 결속·정확한 코드 검토/CI·별도 once 배정 조건도 모두 충족해야 한다. 독립 감사와 새 disposition은 실행 전 custody 증거에 정확히 연결하고, 기존 source receipt/lock과 함께 부모가 확인한다. 미반환·미확정 상태를 `prepared=true`로 우회하지 않는다. 현재 원판정은 보존되고 새 자료 수용 결정은 대기 중이며, source2는 고정돼 있다. Phase1은 미완료이고 유료 호출·공개 서비스 배포는 0이다.
