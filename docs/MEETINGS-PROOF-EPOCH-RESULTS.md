# Bounded snapshot reader: 단발 합성 비교 결과

2026-10-20. 실행 commit64e3454b5dae36b53e8ebd31e6e899292c777cdd에서 공식 CLI를1회 실행해 네 경계 모두 완료했다. **합성 비교에서는 candidate가 더 짧은 시간을 보였지만 서비스 채택·답변 품질 평가는 아직0이다.** 기존 C5 및 다른 닫힌 실험은 재실행하지 않았다.

| 경계 | 기존 한 번 읽기 |64KiB 읽기 |동일하게 확인한 값 |
|---|---:|---:|---|
|request_start |12.531초 |10.969초 |snapshot326/hash244, 반환3,222,840bytes, Git86회 |
|before_dispatch |3.141초 |2.047초 |snapshot244/hash244, 반환2,410,704bytes, Git4회 |

양쪽 모두 경계별 hash2,410,704bytes·AST8·manifest JSON1·HEAD4·alias162·import candidate616검사를 수행했다. Path/stat 및 Git event 기록도 짝별로 동일했다. 기존 read 요청은16,777,217bytes씩326/244회, candidate는65,536bytes씩652/488회였다. Candidate는 EOF를 확인하므로 read 호출 수가 늘지만 실제 반환 bytes는 같다. 요청 크기를 실제 할당량·RSS·디스크 읽기량으로 부르지 않는다.

## 실행 증거와 해석

별도 observer CLI59.634초/exit0, terminal persistence 포함58.922초/저장0.016초이며 측정 시작점이 달라 두 시간을 섞지 않는다. Terminal summary와 raw receipt SHA92fda0c9a3a065f5dfb4201b4396c563edf899234cb263603634363d9d0b8e46가 일치했다. 실행 HEAD·동결27·기존 union106은 unchanged이고 소유 CLI 종료를 확인했다. Native/tokenizer/HTTP/품질 판정/사용자 검수0이다.

고정 순서 reference/start→reference/pre-send→candidate/start→candidate/pre-send, 각1회다. OS cache·백그라운드 부하·순서 효과를 통제하지 않았으며 안정적인 개선율이나 C5의 시간을 몇 초 줄였을 것이라는 인과 주장은 하지 않는다. 같은 synthetic core에서 비읽기 검증을 생략하지 않았다는 코드/계수 증거와 관측된 지연 차이만 확인했다. 이 실험은 닫혔고 재측정하지 않는다.

원래 first-v1/마지막delta 테스트 실패와 skip은 [구현 문서](MEETINGS-PROOF-EPOCH-IMPLEMENTATION.md)에 보존했다. 모델 품질 관문·90초·입출력 한도·일반 문서와 여러 회의·KO/EN·근거/보류·ACL/revision 요구는 그대로다.

## 원본과 재현

- [원본 결과](../experiments/results/meetings-proof-epoch-v1.json), [별도 CLI 관측](../experiments/results/meetings-proof-epoch-cli-v1.json)은 로컬 생성본과 exact copy다.
- [메타데이터](../experiments/results/meetings-proof-epoch-results-metadata-v1.json)와 [공개 영수증](../experiments/results/meetings-proof-epoch-publication-v1.json)에 hash·허용 해석을 남겼다. 경로/credential pattern 검사는 보편적인 개인정보 보증이 아니다.
- [설계](MEETINGS-PROOF-EPOCH-PLAN.md), [구현](MEETINGS-PROOF-EPOCH-IMPLEMENTATION.md), 동결 source27/fixture spec으로 생성 방법과 회귀를 확인할 수 있다. 공식 출력이 이미 존재하므로 해당 CLI를 다시 실행하지 않는다. 새 실험은 새 사전등록이 필요하다.

다음은 허용 코드/집계만 보는 별도 Astra xhigh 검토로 reader를 새 품질 후보에 연결할 근거와 범위를 결정하는 것이다. 아직 새 품질 설계·자료·토큰 준비·생성을 시작하지 않았으며 전체 goal ACTIVE·Phase1/PR14 draft다.
