# 무료 QA 모델 자산 취득의 외부 성공 확인

2026-10-27. [자산 준비 계획](MEETINGS-FREE-QA-PREPARATION-PLAN.md)에 추가하는 필수 운영 조건이다. 기존 무료·로컬 개발 범위에서 담당자가 확인하며, 실제 모델 실행과는 별도다. 현재 실제 새 모델 취득은0이다.

## 필요한 이유와 확인 경계

준비 도구는 마지막 파일 읽기·기록·전체 목록 확인 뒤에도 같은 마감을 검사한다. 늦거나 실패하면 별도 무효 기록을 남긴다. 저장 장치 오류로 그 무효 기록 자체를 쓸 수 없는 경우, 디스크에 앞선 `TERMINAL_CLEAN`만 남을 수 있다. 따라서 파일 하나나 무효 기록의 부재만으로 실제 취득 완료를 판정하지 않는다.

`verify-only`의 현재 소스는 내부 파일·바이트·정리 기록을 검사하지만 이 외부 종료 증거를 인자로 받아 자동 검증하지 않는다. 이 문서는 담당 실행자가 다음 단계 전에 지켜야 하는 운영 gate이며, CLI에 이미 구현된 추가 보장이라고 주장하지 않는다.

## 실제 취득 수용에 모두 필요한 증거

- 한 번 배정한 취득의 정확한 실행 소스/커밋과 프로필 SHA, 명령·시작/종료시각·canonical root를 기록한다. root의 `attempt.json` token·operation·root·profile SHA와 해당 외부 실행을 결속한다. 비공개 원문이나 사용자 자격증명은 포함하지 않는다.
- 외부 관찰기가 실제 CLI의 종료 코드 **0**을 확인한다. 관찰기 자체의 종료 코드0만으로 대체하지 않는다. 관찰 중 일시적인 읽기 실패는 같은 실행을 계속 확인하며 새로운 실행을 시작하지 않는다.
- 외부 관찰기에 저장된 stdout이 해당 CLI의 마지막 성공 JSON `status=ACQUIRED_VERIFIED_METADATA_UNREVIEWED`, `execution_approved=false`와 일치한다. 중간 worker 파일이나 성공 문구 일부를 대체 증거로 쓰지 않는다. stdout/stderr와 실행 기록은 제한된 파일로 보존하고 hash를 묶는다.
- 같은 attempt의 acquisition/profile/두 shard/metadata/terminal-clean 기록과 소유 프로세스 종료·부재, 최종 자산 상태 및 보존 대상 대조를 하나의 custody 기록으로 확인한다. 기록된 shared deadline과 자원·파일 조건도 충족해야 한다. 불명확한 관측을 성공으로 바꾸지 않는다.
- 실제 GGUF metadata는 별도 검토한다. 원본 모델의 template/현재 revision으로 빈칸을 채우지 않는다. 취득 완료도 모델 로딩·GPU 적합성·답변 품질·서비스 채택을 뜻하지 않는다.

## 실패·중단·기록 누락

실제 CLI가 nonzero이거나 중단됐고, 최종 stdout·정확 attempt 결속·종료/custody 중 하나라도 확인되지 않으면 해당 취득은 FAILED 또는 UNKNOWN으로 유지한다. `TERMINAL_CLEAN` 존재나 invalidation 파일 부재가 이 판정을 뒤집지 않는다. 오류·부분 파일·관찰 실패를 보존한다.

그 root의 `verify-only` 실행이나 새 성공 영수증으로 원래 실패를 복구하지 않는다. 별도 원인 분석과 다음 실행 배정은 새 root/새 attempt를 쓰며 자동 재시도·재다운로드·shard 병합을 하지 않는다. 원래 취득의 소비 상태는 유지한다.

## 후속 단계

담당자는 위 외부 성공 gate를 확인한 뒤에만 같은 성공 root의 명시적인 offline verify-only 또는 모델 준비 등록을 배정한다. offline 검증도 자신의 실제 CLI 종료0·최종 `VERIFIED_BYTES_METADATA_UNREVIEWED` stdout·종료/custody가 필요하다. 실패하거나 근거가 없으면 별도의 실패로 보존한다.

원래30분·5GiB 전송·6GiB 새 디스크·32MiB metadata·정리5초와 기존 모델 예산은 그대로다. OS 강제 시간/메모리 보장이나 장애 중 기록 성공을 약속하지 않는다. 현재 구현의 합성 검사와 독립 코드 검토, 실제 취득 gate, 내장 metadata 검토, 실제 모델 비교는 각각 별도 근거다.

독립 재검토 최종 범위: `receipt-final.json` SHA `8e33262776a5cf4dada6e86b94272d042a46aed7b728ae8f0d4cfe8701014d01`. 소스 B1/B2 일반 경로는 수용됐고 이 외부 운영 조건은 당시 미완료였으므로, 이 문서·README 연결을 별도 검토·게시한 후 실제 취득을 배정한다. 최초 v2 검토와 원래 구현/실패 기록은 보존한다.
