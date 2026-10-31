# 서비스 RAG calibration 시작 오류에 대한 한정 변경안

2026-10-22. **부모가 수용한 사전 변경 절차이며 실제 실행 결과나 v2 dispatch 기록이 아니다.** 비동결 launcher의 인프라 수정과 정확한 수정 코드 CI 이후, 아래 조건으로 calibration v2를 한 번 별도 등록한다. 이 문서 작성만으로 모델을 실행하지 않는다.

## 근거와 원래 실패의 보존

- 원래 실행 설계 `MEETINGS-SERVICE-RAG-EXECUTION.md`의 SHA256은 `e5f3a5001755ec8c25b481a199902c8936375c9a6e0478df09e535e6ef17b5b7`이다. 그 문서의 사전 실패도 소비한다는 규칙과 같은 phase 재시작 금지는 그대로 보존한다.
- 이번 판단은 `.local/meetings-service-rag-calibration-cli-v1/safe-summary-v1.json`만 읽었다. SHA256은 `f5de6213b098d4d15fe1643b7b0f1807cba173255069da73b8a920cf2fb4b8f4`이다. 연결된 원문·문항·oracle·raw log·답변은 읽지 않았다.
- HEAD `34e689e`의 v1은 공식 CLI 1회, exit1, service startup 약0.219초, CLI 약1.703초로 실패했다. v1 실행·예약·원래 stderr/stdout·receipt·index·binding을 수정하거나 덮어쓰지 않는다.
- 원래 lifecycle은 `native_attempted=false`, service 미준비와 native 부재를 기록한다. 안전 요약은 질문 요청0, 답변 아티팩트0, 6문항 전부 `unexecuted`, tokenizer0, 의미 판정0, validation0을 보고한다. 원래 observer counts의 빈 객체는 **관측 불가**로 보존하며 측정된 0으로 바꾸지 않는다.
- 종료 후 소유 프로세스 잔류0, lease3 반환, source64/item10 및 등록 입력 해시 일치가 보고됐다. 0.5초 process sampling은 짧은 Java 탐색 자식의 전수 관측 증명이 아니다.
- UTF-8 subprocess reader의 `UnicodeDecodeError`는 확인됐고, 변경 전 호출 순서상 Java discovery로 강하게 국소화된다. 상위 caller의 정확한 예외형은 미보존이므로 이를 확정한 것으로 쓰지 않는다.

## 허용 이유와 변경 범위

답변·검색 선택·모델 출력·품질 점수를 보지 못한 시작 단계의 실패이므로, 관측한 정답률에 따라 좋은 결과를 골라 다시 생성하는 선택 편향은 이번 기록에서 확인되지 않는다. 인프라가 수정됐다는 사실만으로 품질 성공을 주장할 수는 없다. v2는 v1 실패를 포함한 개발 이력을 가진 새 실행이며, 전체 과정이 처음부터 무수정으로 성공한 실험이라고 보고하지 않는다.

이 문서는 **위 v1에 한해서만** 원래 재실행 금지 규칙에 대한 명시적·전향적 추가 허용 절차를 정의한다. 닫힌 C5/C6/C7 및 다른 source/실행 시도에는 적용하지 않는다. v1 경로를 다시 쓰거나 v1의 남은 구간을 이어 실행하지 않는다.

- 수정은 비동결 launcher의 resolver 연결·고정 오류코드, NEW `scripts/java_runtime.py`, 새 resolver 회귀검사와 기존 launcher 회귀검사의 최대4파일로 제한한다. 동결77의 `verify_java_service`와 모델 정책은 수정하지 않으며 기존 Java/model identity 검증 요건을 없애지 않는다.
- 부모가 정한 resolver 방식은 JDK21의 임시 ASCII source-file probe로 `java.home` UTF-8 bytes를 Base64 한 줄로 받고, Python이 binary capture 뒤 ASCII/Base64/UTF-8 strict 해석과 실제 `home/bin/java` 파일 resolve를 하는 것이다. 기존 startup120초 안에서 probe timeout10초를 유지한다. 컴파일·임시 정리·누락/복수 출력·nonzero/timeout·Unicode 경로 경계를 확인하며 원문이나 평가 문항을 probe에 넣지 않는다.
- 부모의 진행 보고상 진단은 기존 properties 방식1회와 새 resolver3회(이모지 절대 경로 실패, 기본 OS 임시 경로 성공, `cwd` 대안 실패)다. 기본 OS 임시 경로에서 새 resolver가 exit0/약0.625초로 성공했다. 이모지 임시 경로의 절대 source-file 인자는 MS949 경로 오류로, `cwd`와 ASCII 파일명 대안은 JDK URLClassPath percent decode 오류로 실패했으며 각각 원본을 보존한다. 최종 선택은 기본 OS 임시 경로에서 확인한 최소 helper이고 이모지 임시 경로는 미지원이다. `java.home` Unicode/이모지 값의 합성 UTF-8/Base64 보존 검사와 현재 OS 경로의 실제 Java 성공을 구분한다. 이 보고를 이 문서 작성자의 실제 실행 확인이나 임의 Unicode 경로 지원 증명으로 쓰지 않는다.
- 기존 source/item freeze, 전체 원문6개·32chunks, 원래 calibration6 문항의 내용·순서·언어·family, oracle와 근거 대안, workspace/principal/visibility 배치를 그대로 사용한다. 새 자료·문항 작성이나 재선택을 하지 않는다.
- 모델·가중치·revision·GPU28·CPU retrieval·prompt/decoder·입출력 한도·top5·`hybrid_rerank`·`base`·판정 기준을 유지한다. 코드 오류를 이용해 질문별 context나 답변 정책을 조정하지 않는다.
- 각 v2 실행 한도는 startup120초, active1500초, 전체 cleanup5초, 전체1625초다. 답변 공유90초와 분석120초도 그대로다. v1 소요시간과 실패는 별도로 합산 보고하며 새 실행 횟수를 숨기지 않는다.
- 회의 자동분석은 각 업로드1회로 4건 이하, 질문별 Java answer POST≤1/native 답변 생성 시도≤1, calibration≤6과 후속 validation≤8을 유지한다. 자동 retry·warmup·별도 native/tokenizer 예행·fallback·repair 생성은 허용하지 않는다.

## 실행 전에 필요한 최소 연결

1. 부모가 v1 실패 기록을 보존하고 이 추가 허용을 명시적으로 채택한다. 이는 이미 허용된 로컬·무료 개발의 부모 결정이며 사용자 검수나 새 인간 승인으로 표기하지 않는다.
2. 수정 담당이 generic 회귀검사 결과를 남기고 기존 독립 코드 검토 담당이 작은 수정 범위를 검토한다. 부모가 각각 배정한 좁은 Java discovery-only 진단은 실제 자료·모델·서비스·평가 요청 없이 진행했고, 실패를 포함한 각 시도의 환경·코드 binding·결과를 모두 보존한다. 이를 한 번의 무수정 성공으로 합치거나 공식 모델 실행으로 세지 않는다. 추가 우회 실험이나 자동 retry 권한은 없으며, 진단은 해당 환경의 resolver 동작에 대한 제한적 증거다. 부모는 최종 수정 소스 commit의 정확한 push/PR 필수 CI 성공을 확인한다. 기존 검증 도구와 CI를 재사용한다.
3. 기존 calibration custodian/executor가 기존 manifest에서 실행 코드·CI·등록 연결과 v2 출력 경로만 갱신한 새 binding을 만든다. source/item/model/JAR/UI와 평가 조건의 동일성 및 v1 안전 요약 binding을 기록한다. 새 corpus·역할 모집·toolchain 복제·prepare/probe/audit 체계를 만들지 않는다.
4. 새 등록은 이 변경안의 hash, v1 실패 연결, 정확한 수정 코드/CI, 동일한 평가 입력, 새 v2 run/CLI 경로와 **추가 공식 실행1회**를 묶는다. 부모는 새 CI receipt와 v2 실행 등록을 한 commit에 함께 보존한 뒤 기존 executor에게 한 번 명시 dispatch한다. 별도 문서 전용 CI 연쇄나 새 역할·source를 추가하지 않는다. 소스 코드 CI가 검증한 commit과 receipt/등록을 보존한 commit을 구분하며 후자를 코드 CI 증명으로 쓰지 않는다. 검증 대상 코드가 바뀌면 그 코드의 정확한 CI를 다시 확인한다. 이 문서나 CI 성공만으로 자동 실행하지 않는다.
5. v2는 새 exclusive reservation·격리 DB·credentials로 시작한다. 기존 driver의 시작/종료 binding 검사를 사용하며 v1 DB·부분 산출물을 재사용하지 않는다. 실행 담당의 종전 같은 split 작성 노출과 final judge 제외를 유지한다.

기존 독립 final judge와 등록된 평가 방식을 유지한다. 실행자·작성자·수정 담당·이 문서 작성자는 최종 답변 judge가 아니다. 부모는 metadata만 읽는다. 답변 판단 lock 전 검색 진단·reasoning·시간·오류 상세를 judge에게 새로 제공하지 않으며, 이미 있었던 metadata 노출은 정직하게 기록한다.

## 중단과 해석

- 동일 입력/정책을 확인할 수 없거나 v1에서 실제 native·질문·답변 출력이 있었다는 반대 증거가 생기면 이 예외를 적용하지 않는다. 불명확한 전송을 0으로 추정하지 않는다.
- v2의 첫 인프라·입력·권한·revision·증거·시간·정리 실패에서 기존 규칙대로 종료하고 이후 문항을 `unexecuted`로 남긴다. 시작 실패라도 v2는 소비된다. 이 변경안은 세 번째 실행이나 자동 재시도를 허용하지 않는다.
- 구조적으로 유효한 답변은 기존 순서대로 수집하고 의미 판정은 독립 judge가 수행한다. 낮은 점수를 이유로 문항·자료·검색 조건을 바꾸거나 같은 질문을 다시 생성하지 않는다.
- Validation은 v2의 원래 calibration6 전체에 대한 독립 판정6/6·답변 판단 lock·운영 무결성·정리 수용 후에만 별도 등록 경로로 진행한다. v1/v2 일부 결과를 합쳐 gate를 만들지 않는다.
- 결과에는 공식 startup 시도2회(v1 실패 + v2 결과), 각 실제 소요시간/호출 수와 미실행 범위를 함께 남긴다. v2 성공도 v1 운영 실패를 없애지 않으며, synthetic 검사·실제 native·독립 의미 판정·사용자 검수를 구분한다. Phase1 완료나 채택을 이 변경안으로 주장하지 않는다.

작성 역할은 기존 `/root/source_discovery_decision` Astra xhigh 설계/읽기 검토 담당이다. 안전 요약·generic 설계·부모의 비의미적 진행 보고를 바탕으로 이 파일1개를 작성했고, 최종 수정 코드/회귀검사4개와 generic receipt의 독립 읽기 검토를 완료했다. 전달된 최종4개 hash와 검토 전후가 같으며 추가 blocker는 없었다. 실제 데이터·모델 출력·raw log 열람, 테스트·서버·Java·모델·tokenizer·Git 실행은 0이다. 이 검토는 native 품질 증거나 인간 검수가 아니며 v2 실행은 아직 수행하지 않았다.
