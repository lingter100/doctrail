# 요약 문법 엔진 검증 도구 구현

2026-10-27. 모델 출력의 문법 제약이 실제 고정 엔진에서도 같은 문자열을 허용하는지 확인하기 위한 도구를 구현했다. **코드 검증과 정확 소스 CI는 통과했다. 실제 도구 취득은 LLVM 압축 해제 중 시간 한도로 실패했으며, 컴파일·실제 엔진 실행은 아직 없다.**

## 해결하는 문제와 방법

순수 Python 검사가 통과해도 생성 엔진의 Unicode 처리·부분 문자열·완료 판정이 같다고 보장할 수 없다. 고정 llama.cpp 소스의 문법 처리 부분만 CPU로 빌드하고 공개 합성 입력106개를 검사하도록 준비했다. 잘못된 UTF-8 입력1개는 전달 전에 거부하고 나머지105개를 엔진에서 검사한다. 완성 문자열10개의 접두사 판정을 함께 확인한다. 기대 결과와 입력은 실행 전에 고정한다.

프로젝트 소유 폴더에만 도구·소스·임시 파일을 두며 다운로드 크기, 전체 디스크, 시간·메모리, 실행 가능한 자식 경로를 제한한다. 전역 설치나 기존 모델을 변경하지 않는다. 취득한 파일 해시와 실행 목록을 별도로 검토하기 전에는 빌드하지 않는다. 정확한 명령·단계별 한계는 [도구 README](../tools/summary_grammar/README.md)와 [사전 계획](MEETINGS-LOCAL-SUMMARY-ENGINE-VALIDATION-PLAN.md)에 있다.

## 구현 검증과 수정

기존73개에29개를 더해102개 합성 검사가8.36초에 통과했고 Ruff도 통과했다. 네트워크·프로세스·자원 관측은 모형으로 검사했다. 최초 검사 실패와 원본 구현을 보존했다.

독립 코드 검토에서 Windows compiler wrapper가 호출하는 실제 driver 식별, CMake의 고정된 선택적 linker 조회, 상위 프로세스에서 상속된 외부 임시 폴더 문제를 발견했다. 정확한 취득 경로/해시와 고정 모듈/인자를 검증하고 TEMP/TMP를 소유 폴더 안으로 제한해 수정했다. 재검토 결과 남은 blocker0/advisory0이다. [기계 판독 결과](../experiments/results/meetings-summary-engine-preparation-v1.json)에 코드 해시와 검증 범위를 기록했다.

## 아직 증명하지 않은 것

실제 배포 파일의 구조·호환성·컴파일·엔진 판정은 미검증이다. 관측한 자원 값은 OS의 강제 격리나 순간 최대치를 보장하지 않는다. 문법 통과 역시 모델 출력 토큰 비용이나 요약의 의미 정확성을 입증하지 않는다. 기존 실패 후보, 입력, 최종 평가와 모델 예산은 그대로 유지한다. 다음은 취득 실패 원인에 대한 수정·검증, 완전한 취득 파일의 검토와 실제 엔진 검증이다. 사용자 검수와 실제 모델 실험은0이다.


## 게시 바이트 불일치와 수정

최초 게시9a6ba117의 양쪽 CI에서 web/java-service는 통과했지만 Python검사는1실패·4491통과·21skip이었다. Git 게시 줄바꿈에 맞춰 pins.json을 LF로 정규화한 뒤 고정 raw SHA를 갱신하지 않은 부모의 게시 오류다. JSON 의미는 같아도 원시 바이트 검사는 달라지는 점을 누락했다. [최초 실패](../experiments/results/meetings-summary-engine-preparation-ci-v1.json)와 원본·로그를 보존했다.

runtime.PINS_SHA 한 문자열만 게시된 LF 파일의 정확한 SHA로 맞췄다. 바이트 guard·정책·테스트를 완화하지 않았고102합성검사5.39초/Ruff·독립 검토 blocker0/advisory0을 확인했다. [수정 결과](../experiments/results/meetings-summary-engine-binding-repair-v1.json)는 새 커밋 CI와 실제 취득·빌드·엔진 실행의 성공을 아직 주장하지 않는다.

## 첫 실제 취득 결과와 다음 작업

정확 소스3d331e8의 양쪽 필수 CI를 통과한 뒤 도구 취득1회를 실행했다. LLVM-MinGW ZIP171,028,561B의 공식 SHA는 일치했지만 압축 해제 중 공유 시간 한도에 도달했다. supervisor595.75초, wrapper596.890초, official exit1이며 CMake·Ninja·선택한 엔진 소스와 완전한 취득 manifest는 없다. [실제 준비 실패 결과](../experiments/results/meetings-summary-engine-acquisition-v1.json)에 원래 오류와 부분 파일 보존 여부를 남겼다.

공식 자식 정리와 별도 소유7신원의 부재를 확인했고 고정396개 파일은 바뀌지 않았다. 부분335파일은 실행 승인 상태가 아니며 재시도하거나 내려받은 프로그램을 실행하지 않았다. 모델 품질 실패나 Docker 장애로 해석할 근거는 없다. 저장된 기록과 코드에서 원인을 분석한 뒤 원래 자원·시간 한도를 유지하는 수정을 검토한다. 실제 성능 원인을 아직 확정하지 않았다.

## 취득 경계 보완과 외부 성공 확인

첫 취득의 반복 전체 탐색은 작업자 쓰기 전 바이트 장부와 단계별 전체 검사로 바꿨다. supervisor의 독립 전체 검사는 유지한다. ZIP 선언 크기의 이중 합산과 redirect 본문의 미계상 읽기를 보완했다. 별도 검토에서 발견한 마지막 supervision receipt 용량 사전 검사와 최종 manifest 공유 deadline 누락도 수정했다. 준비 시작부터 최종 읽기·쓰기·전체 검사·게시까지 같은600초 마감을 전달한다. 늦은 게시에는 pending 복구와 failure marker를 적용한다.

최종173합성검사19.91초와 Ruff를 통과했고 기존145개 합성 사례(42개 함수) 및 OwnedTree/safe_path/build 본문은 보존했다. 새 검사 작성 과정의6개 기대 오류와 Ruff 실패도 별도 보존했다. 이 결과는 모형 프로세스·시계·파일 시스템 검사이며 실제 취득 속도나 성공을 측정하지 않는다. 정확한 게시 소스 CI와 다음 실제 취득은 별도 확인한다.

저장소가 응답하지 않거나 늦은 게시의 rollback과 failure 기록이 함께 실패하면 내부 acquisition.json만 남을 수 있다. 다음 실제 취득은 아래 조건을 모두 확인해야 수용한다. 현재 check_acquired가 외부 실행 증거를 자동으로 받거나 검증한다고 주장하지 않는다.

- 새 canonical root의 acquisition-attempt.json worker_token·명령·정확한 소스/커밋·pins SHA·시작/종료시각을 외부 관찰 기록에 결속한다. 원래 실패 root와 부분 파일은 재사용하지 않는다.
- 그 실제 acquire CLI 종료 코드0과 마지막 stdout JSON status=ACQUIRED_UNREVIEWED_DO_NOT_EXECUTE를 모두 확인한다. wrapper 종료0, 중간 worker 결과, 내부 acquisition.json 또는 failure marker 부재만으로 대체하지 않는다.
- 같은 root/token의 supervision·cleanup·취득 manifest와 원본 보존/최종 자산 대조, 관측 소유 프로세스의 종료·부재, 원래 시간·용량·메모리 조건을 확인한다. 원래 취득의 마지막 실행부터 기록 종료까지 실제 경과도 보존한다. 실제 CLI 실패·중단 또는 확인 근거 누락은 FAILED/UNKNOWN으로 유지한다.
- 위 외부 수용이 확인된 취득 manifest의 정확한 SHA만 별도 파일/실행 목록 검토와 build 배정에 전달한다. build --reviewed-acquisition-sha256 인자는 외부 검토를 자동 증명하지 않는다. 같은 실패 root의 새 검증이나 파일상의 성공으로 실패를 복구하지 않는다.
- 취득 완료는 다운로드한 실행파일의 실행 승인이나 컴파일·엔진 판정·모델 품질 통과가 아니다. 파일/실행 목록 검토와 명시적인 다음 단계 배정이 필요하다.

이 운영 조건은 기존 무료 로컬 개발 범위이며 추가 유료 승인 절차가 아니다. OS 강제 시간 보장이나 저장소 고장 중 기록 성공을 약속하지 않는다. 원래600초·512MiB 전송·4GiB 디스크·RSS2GiB/host reserve2GiB·정리5초와 빌드/validator 예산은 유지한다.
