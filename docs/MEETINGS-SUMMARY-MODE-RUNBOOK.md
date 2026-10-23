# 요약 추론 모드 비교 도구

이 도구는 무료 로컬 모델의 같은 입력에서 추론 모드만 비교하기 위한 별도 진단이다. 서비스 기본값을 바꾸지 않는다. [원계획](MEETINGS-SUMMARY-QUALITY-NEXT.md)과 [실행 전 보완](MEETINGS-SUMMARY-MODE-LAUNCHER-REPAIR.md)을 유지하고, [자료 이력 경계](MEETINGS-SUMMARY-MODE-PROVENANCE-BOUNDARY.md)를 별도 필수 등록 참조로 적용한다. 실제 모델 결과와 도구 검증은 구분한다.

## 현재 확인한 범위

신규 `scripts/probe_meeting_summary_mode.py`와 대응 테스트를 구현했다. 계약 바인딩을 추가한 로컬 합성 검사는176개/3.93초이며 Ruff도 통과했다. 기존167개가 포함되므로 합산하지 않는다. 독립 재검토와 정확한 소스 CI 상태는 [현재 진행](STATUS.md) 및 구현 결과 기록을 따른다. 아직 새 진단의 실제 모델 실행·입력 토큰 적합성·의미 품질은 검증하지 않았다.

진단은 같은 고정 Qwen 가중치·원문·요약 계약·출력 상한을 유지하고 생성의 추론 모드만 비교한다. 문서4개마다 예정된 A/B 순서를 사용한다. 생성1회와 필수 근거 검토1회이며 추가 재작성·재시도는 없다. 정상적인 근거 검토 거부는 실패한 arm으로 남기고 다음 예정 arm을 관측할 수 있다. 통신·자료 무결성·자원·시간 실패는 전체를 중단한다. 생성 단계의 답변 보류도 남은 arm을 실행하지 않는다.

## 모델 없이 재현하는 검사

저장소의 기존 Python 개발 환경에서 실행한다. 모델 가중치나 GPU를 불러오지 않는다.

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_probe_meeting_summary_mode.py
.\.venv\Scripts\python.exe -m ruff check scripts/probe_meeting_summary_mode.py tests/test_probe_meeting_summary_mode.py
```

가짜 HTTP·시계·프로세스 handle로 요청 대조, 토큰/시간 경계, 근거 검토, 자원 관측, 소유 프로세스 정리와 종료 결과를 검사한다. 실제 native 호환이나 AI 정확성을 증명하는 검사는 아니다. 최초102개 검사 뒤 발견한5개 문제,155개 검사 뒤 발견한 종료 기록 유실과 각 수정 전 실패를 로컬 증거에 보존했다.

## 실제 실행 전 필요한 자료

원문4개의 출처·이용 조건·누락 없는 파싱과 현재 보호 split 분리, 향후 평가 제외, 명시적 source disposition과 독립 source-only 기준을 먼저 확정한다. 과거 일부 실행의 입력 버전 미확정과 원래 L2 보류는 보존하며 새로운 개발 비교를 전체 역사 미노출 평가로 부르지 않는다. 이어 정확한 source CI와 코드·자산·원문·기준·순서·설정의 해시를 실행 등록에 묶는다. 기존 진단 결과 디렉터리를 재사용하지 않는다. 현재 실제 실행용 최종 등록은 준비 중이다.

등록에는 원래 `plan`·`amendment`와 함께 필수 `provenance_boundary`가 있어야 한다. 경로는 `docs/MEETINGS-SUMMARY-MODE-PROVENANCE-BOUNDARY.md`, 크기는7,014B, SHA256은 `ab191c4aa424d2ca16a874683feb3c88eb6064a89bcb47e9bae0e2fdfa9a11ac`다. 누락·다른 값·파일 변경은 실행 전에 거부하며 종료 후에도 같은 바이트인지 검사한다. 이 바인딩이나 `prepared=true` 자체가 자료 수용을 뜻하지 않는다.

CLI는 `--registration`과 `--execute-once-sha256`을 모두 요구한다. 후자는 실제 등록 파일의 SHA256이어야 한다. 임의의 예시 등록이나 잠긴 과거 입력으로 시험 실행하지 않는다. 등록 경로·해시와 별도의 once 배정이 완료된 뒤 실제 명령과 환경을 실행 기록에 남긴다. 서비스의120초 한도는 이 진단의180초 arm 한도와 별개다. 요청된 reasoning512token은 독립적인 강제 상한으로 주장하지 않는다.

## 실패 기록과 해석

프로세스를 만든 직후부터 원래 handle의 정리 의무를 유지한다. 다른 실행의 PID를 검색해 종료하거나 정리 시간을 새로 부여하지 않는다. 모델 근거 검토 거부와 운영상 실패를 별도로 기록하며, 나중에 연결 종료나 파일 저장이 실패해도 최초 원인·등록 해시가 담긴 종료 결과를 유지한다.

파일 저장에 실패하면 일부 파일이 남을 수 있다. 이를 완전한 seal이나 성공으로 표현하지 않고 `sealing_status`, `evidence_sealed`와 운영 실패를 명시한다. 등록 전 거부는 `unbound_rejection`, 등록된 실행의 종료 결과는 `bound_terminal`로 구분한다. CLI 종료 결과도 외부 실행 담당이 별도로 보존해야 한다.

운영상 정상 종료와 모델 자기검토 수용은 요약 품질의 독립 검증이 아니다. 개별 후보의 근거 지원·핵심 충분성·읽기 쉬움을 먼저 판단해 잠근 뒤 쌍을 공개한다. 진단 성공도 실제 서비스 전체 흐름·격리 validation·최종 test·사용자 검수를 대신하지 않는다.
