# 무료 QA 모델 자산 준비 구현과 검증

2026-10-27. 다른 무료 로컬 모델을 같은 조건으로 비교하기 위한 파일 준비 도구를 구현했다. **현재는 코드·합성 검사·운영 문서 검토까지 완료했고, 새 모델 가중치 다운로드와 실제 모델 검증은 아직0이다.**

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

## 실행과 다음 단계

설치된 프로젝트 Python 환경에서 `python -B scripts/prepare_meeting_free_qa.py inspect`로 프로필만 확인할 수 있다. 실제 취득·offline 검증 명령은 [도구 README](../tools/free_qa/README.md)에 있고, [운영 gate](MEETINGS-FREE-QA-ACQUISITION-GATE.md)를 충족한 별도 실행에만 사용한다.

다음은 정확 소스 CI, 별도 취득, 실제 내장 metadata 검토다. 그 뒤에도 실제 로딩·자원 적합성·새6개 개발 비교·격리 평가·Java 서비스 채택은 남아 있다. 더 큰 모델의 우위·응답 속도·정확성·새 하드웨어 적합성을 아직 주장하지 않는다. 사용자 직접 검수는0이다.
