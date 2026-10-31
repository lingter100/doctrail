# 무료 QA 모델 자산 준비 구현과 검증

2026-10-28 갱신. 고정된 무료 모델 파일을 준비하는 도구를 구현했다. 첫 실제 취득은 `download_origin`·전송0B로 실패했고 원본을 보존했다. 정확한 CDN 호스트 추가는129합성검사·독립 코드 검토·수정 소스 CI를 통과했다. 새 폴더의 실제 취득과 별도 내장 metadata 검토를 완료했으며 실제 모델 로딩·품질 검증은 남아 있다.

## 해결하려는 문제와 선택

기존 작은 개발 비교에서 답변 내용 기준을 충족하지 못해 [새 모델 비교 계획](MEETINGS-FREE-QA-NEXT-DECISION.md)을 세웠다. 공식 Qwen2.5-7B-Instruct Q4_K_M의 고정된 두 shard(합계4,683,073,632B)를 그대로 사용하도록 [프로필](../data/models/meetings-generation-qwen25-7b-q4km-v1.json)을 추가했다. 모델을 합치거나 전역 런타임을 바꾸지 않는다.

변환에 사용된 원본 모델 commit은 공개되지 않아 unknown으로 남긴다. 별도로 관찰한 원본 revision이나 repository template를 실제 GGUF 내장 정보로 대신하지 않는다. 실제 취득 후 제한된 header/KV 읽기로 split·template·tokenizer 관측을 결속하고 별도로 검토한다.

## 구현과 검증

- 명시적 취득과 네트워크 없는 verify-only를 분리했다. 공유30분, 소비 body5GiB, 새 작업 폴더6GiB, 두 shard metadata 합32MiB와 정리5초를 유지한다.
- 정확한 크기/SHA·파일 집합·경로와 프로세스 소유 신원을 검사하고 실패·부분 파일을 보존한다. 자동 retry·재다운로드·병합·모델 실행은 없다.
- 최초 구현69개를 보존하면서 최종104합성검사7.04초/Ruff를 통과했다. 네트워크·프로세스·자원은 모형이며 실제 호환성 증거로 세지 않는다.
- 독립 검토가 redirect 본문의 미계상 read와 마지막 I/O 뒤 deadline 검사 누락을 발견했다. 본문을 읽지 않고 닫는 redirect와 늦은 종료 무효화를 추가해 일반 경로의 source blocker0을 확인했다.
- 무효 기록 자체의 저장 실패는 파일만으로 수용할 수 없으므로 [외부 성공·종료 기록 조건](MEETINGS-FREE-QA-ACQUISITION-GATE.md)을 추가했다. 이 운영 문서도 별도 검토 blocker0이다. 기존 검토 범위 정정과 원본을 보존했다.
- 실제 CLI `inspect`는 종료0, `PROFILE_ONLY_ASSETS_NOT_READ`를 반환했다. 프로필/진입점 확인이며 가중치·GGUF·모델을 실행하거나 검증한 결과가 아니다.

[기계 판독 결과](../experiments/results/meetings-free-qa-assets-preparation-v1.json)에 최종 소스 해시·원래 helper·검토·실제/합성 구분을 기록했다. README 운영 조건 추가는 코드 검사와 구분한 문서 검토다. 별도 수정 중인 공통 엔진 runtime는 자신의 검토와 최종 결합 소스 CI가 필요하다.

## 첫 실제 취득과 수정 범위

[첫 취득 결과](../experiments/results/meetings-free-qa-acquisition-v1.json)는 CLI1·전송0B의 소비된 실패다. 거부된 URL이 기록되지 않아 당시 GET의 정확한 redirect를 복원할 수 없다. 이후 별도 HEAD1회에서 현재 공식 URL의302 응답이 `us.aws.cdn.hf.co`로 안내함을 확인했고, 정확한 호스트 한 개만 추가했다. 본문 다운로드나 redirect 추적은 수행하지 않았다.

[수정 결과](../experiments/results/meetings-free-qa-origin-repair-v1.json)는 기존104+추가25검사129통과·Ruff·독립 검토 blocker0을 기록한다. 기존 테스트21함수의 원본 전체 prefix와 그 외 생산 코드가 그대로다. 와일드카드나 임의 하위 도메인을 허용하지 않으며, 성공하는 실제 다운로드를 입증한 검사는 아니다.

실패 폴더 `models/meetings-qwen25-7b-q4km-v1`은 재사용하지 않았다. 수정 소스0c34174의 양쪽 CI 이후 새 v2 폴더·실행 기록으로 취득1회를 수행했다. 실패 파일을 offline verify로 성공 상태로 바꾸지 않았다.

[새 실제 취득](../experiments/results/meetings-free-qa-acquisition-v2.json)은 CLI0·wrapper0,862.985초,두 shard4,683,073,632바이트다. 부모는 전체 SHA·결과17파일·보존5,390참조·소스4개·실행환경5개·소유 프로세스6개 부재를 확인했다. 기존 Python 시작 오류는 [자산용 격리 환경](MEETINGS-ASSET-RUNTIME-RECOVERY.md)으로 분리했으며 원래 환경을 수정하지 않았다. 모델 추론과 내용 검수는 아직0이다.

## 실행과 다음 단계

설치된 프로젝트 Python 환경에서 `python -B scripts/prepare_meeting_free_qa.py inspect`로 프로필만 확인할 수 있다. 실제 취득·offline 검증 명령은 [도구 README](../tools/free_qa/README.md)에 있고, [운영 gate](MEETINGS-FREE-QA-ACQUISITION-GATE.md)를 충족한 별도 실행에만 사용한다.

[내장 metadata 검토](MEETINGS-FREE-QA-METADATA-REVIEW.md)와 별도 환경의 고정 소스 합성 검사는 마쳤다. 다음은 현재 runtime·외부 gate 결속과 새 코드 회귀 확인이다. 그 뒤에도 실제 로딩·자원 적합성·새6개 개발 비교·격리 평가·Java 서비스 채택은 남아 있다. 더 큰 모델의 우위·응답 속도·정확성·새 하드웨어 적합성을 아직 주장하지 않는다. 사용자 직접 검수는0이다.
