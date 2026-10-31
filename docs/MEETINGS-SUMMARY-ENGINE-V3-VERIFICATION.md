# 요약 엔진 준비 v3 검증

2026-10-28. 엔진 준비 코드의 합성 검증 기록이며 실제 취득·컴파일·모델 품질 결과가 아니다. [기계 판독 결과](../experiments/results/meetings-summary-engine-v3-external-gate-v1.json)에 정확한 소스 해시와 검사 범위를 기록한다. 독립 Astra xhigh 검토는 차단0·미해결 권고0이며 B1의 v3 차단을 확인했다. 게시 소스 CI는 별도 단계다.

## 문제와 변경

처음 두 실제 취득은 압축 해제 중 시간 경계에서 실패했다. [v3 계획](MEETINGS-SUMMARY-ENGINE-V3-PLAN.md)은 고정 x64 파일과 라이선스만 선택하고 비용이 큰 자원 조회를 명시적인 50ms 간격으로 수행한다. 시간·로그·전송·디스크 경계는 매 체크포인트에서 유지한다. 이것만으로 실제 취득 속도나 성공이 입증되지는 않는다.

초기285합성 검사가 통과한 뒤 독립 검토에서 B1을 발견했다. 최종 파일 게시가 늦고 원복과 실패 표식 저장까지 실패하면, 남은 내부 성공 파일을 다음 단계가 받아들일 수 있었다. [최초 결과와 재현](../experiments/results/meetings-summary-engine-v3-review-v1.json)을 보존한다.

[외부 종료 결속](MEETINGS-SUMMARY-ENGINE-V3-EXTERNAL-GATE.md)은 v3에서 실제 CLI 종료·원래 출력·시간·소유 프로세스 정리에 결속된 외부 acceptance의 검토 SHA를 요구한다. 내부 success marker만 추가하는 방식은 같은 마지막 저장 실패를 해결하지 못하므로 선택하지 않았다. 기존 legacy의 manifest 검토 SHA는 그대로다. build 기록의 `acquisition_sha256`는 v3에서 검토 companion SHA이며 실제 취득 파일 SHA는 그 안의 별도 ref다.

## 확인한 범위

- 최종 고정 소스의 전체554합성 검사: 기존173 + 초기v3 112 + 새 외부 결속269. 실패·오류·skip0, pytest429.84초, Ruff 통과.
- 검사 시작 사본과 종료 뒤 실제 코드3개가 같다. 기존58정의·build 본문과 이번 수정 전 runtime 전체를 보존했다.
- 게시 전 테스트 파일 끝의 불필요한 LF1개만 제거했다. 검사본26dc209b와 게시본f39e5869의 AST는 같으며 원본·바이트 차이를 보존했다. 로컬 검사를 반복하지 않고 게시본의 정확 CI를 별도로 확인한다.
- 외부 기록 누락·잘못된 검토 SHA·종료 실패·시간 초과·불완전 출력·소스/신원/정리 불일치·변조와 과도한 읽기를 거부하는 경로를 확인했다.
- B1의 복합 실패, 빌드 전후 재확인, verifier의 같은 SHA 전달을 합성 실행으로 확인했다. 이전 profile/selection/terminal 변조 검사는 유효 외부 fixture를 거쳐 해당 내부 검증에 도달한다.

첫 탐색 검사는267통과·18실패였고 검사 중 소스 편집이 겹쳐 정확한 최종 소스 증거로 쓰지 않는다. Windows의 `stat` 생성시각과 `fstat` 변경시각 차이가 같은 파일을 변경으로 오판하는 원인이었다. 공통 신원·크기·mtime·실제 바이트 해시는 비교하고 각 API의 시각은 같은 API의 전후 값으로 확인하도록 고쳤다. 별도30개가 통과했고 최종 고정 실행으로 대체했다.

새 외부 검사 최초269통과·1실패는 Windows가 실제 하드링크 생성을 거부한 fixture 준비 실패였다. 원본을 보존하고 파일 신원 중복을 명시적으로 모형화해 검사했다. 실제 하드링크 생성 성공이나 운영 환경의 링크 공격 검증으로 기록하지 않는다.

## 한계와 다음 단계

잠금 의존성을 사용하는 일반 개발 환경의 검사 명령은 다음과 같다. 현재 PC의 원래 Python 연결 오류와 별도3.12 환경은 [실행 환경 복구 기록](MEETINGS-ASSET-RUNTIME-RECOVERY.md)을 따른다.

```powershell
uv sync --frozen --python 3.11
uv pip install --no-deps --require-hashes -r .github/test-runtime-requirements.txt
uv run --no-sync pytest -q tests/test_summary_grammar_engine.py
uv run --no-sync ruff check scripts/prepare_summary_grammar_engine.py tests/test_summary_grammar_engine.py
```

외부 JSON과 SHA만으로 관찰자의 진실성을 증명할 수 없다. 검토 SHA는 실제 관측·세션·관찰 코드·종료를 별도로 검토한 뒤 공급해야 한다. 테스트 fixture는 운영 승인 기록이 아니다.

새 외부 제어파일 읽기는 크기가 제한되지만 기존 내부 inventory/reference 검사는 파일을 다시 읽는다. 전체 폴더의 원자적 snapshot이나 동시 변경에 대한 전체 I/O 상한을 보장하지 않는다. 검토 폴더는 다른 작업과 공유해 수정하지 않는다. 보호된 build의900초 예산은 사전 검사 뒤 시작하므로 전체 명령의 소요시간 상한으로 확장하지 않는다.

독립 검토·정확 게시 소스 CI 뒤 새로운 폴더와 관찰 기록을 별도 배정한다. 실제 취득·빌드·고정 문법 검사와 새 모델의 답변 비교는 아직 남아 있다. 사용자 검수와 실제 모델 품질 검증은 이번 결과에 포함되지 않는다.
