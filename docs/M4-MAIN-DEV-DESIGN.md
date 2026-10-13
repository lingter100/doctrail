# M4 · 마지막 E5 저장본의 한 번의 main-dev 비교

기준일: 2026-10-13. **기존 base E5와 실제16회 갱신한 마지막 저장본을 동일 조건에서 각각 한 번 새로 평가한다.** [내부 calibration](M4-CALIBRATION-ANALYSIS.md)의 진행 조건을 통과한 뒤 수행하는 별도 비교다. 이 문서는 결과를 보기 전의 정책이며, 실행 여부·실제 수치는 별도 보고서와 [STATUS](STATUS.md)에 기록한다.

주 비교는 새로 실행한 base와 terminal의 dense 검색이다. 저장된 M3 dense 순위는 과거 결과 재생과 수치 차이 확인에 사용한다. 새 base가 불리하다는 이유로 과거 순위를 기준선으로 대신하거나 과거·새 점수를 섞지 않는다. BM25·BGE 추론, hybrid 정책 변경, 추가 학습·checkpoint 선택·calibration 재튜닝은 수행하지 않는다. Test는 잠금 상태이며 사용자 검수는0개다.

## 1. 변경할 수 없는 입력

새 실행 계획 `data/evaluation/m4-main-dev-evaluation-v1.json`에 다음 원본 파일의 경로와 SHA-256을 고정한다. 질문 파일은 정확한 경로·해시를 먼저 확인한 뒤 읽는다. 다른 dev 파일, test 질문, 경로 이탈, 누락·중복 ID와 분모 변화는 모델 로드 전에 거부한다.

| 입력 | 원본 SHA-256 |
|---|---|
| `data/manifests/kubernetes-v1.json` | `e4d33997b5589bd8d9cc5c56691da5940eba3a7b6554c671b8c39b78910fe69a` |
| `data/evaluation/m2-dev-v1.1.jsonl` | `9cce5a304f3f430c626aae2c1c0f267e0f3abc2dba16ccd7f9ec2f3989d28cb2` |
| `experiments/results/m3-retrieval-dev-v1.json` | `76aa4bbc0f827fc4022dbab289eb730072ded56122b8ed8107f72f67ee32a63f` |
| `data/models/m3-models.json` | `9140036af43711a12702ee6cf12d0ce2073acf7d9ef3269c3c297ad1dbe065a1` |
| `data/models/m4-terminal-v1.json` | `62e530d3094e98b336d039f10956c8e0e2a39d24d66b07818e92a46f0aac10fb` |
| `data/training/m4-calibration-evaluation-v1.1.json` | `3b57c5b2bb2a256b19340edcfbec20943bd7bf39c1d56296dbdbe5959f88e4f4` |
| `experiments/results/m4-calibration-v1.json` | `bc322c0b3767a617c26bf67fefc41bc7f43d6af3e5c024538a4ae5f485cc55ee` |
| `uv.lock` | `a226a23939e13dca873131fc0f908d52d46ab00a98efd5510f1967d255bcb499` |
| `pyproject.toml` | `db45870df5b6d4fd543e14b9d837d25614033f9049692cead50e1a366a72308d` |

Terminal manifest에 연결된 실행 계획·readiness·probe·train 보고서의 해시도 그대로 연결한다. `sole_terminal_after_16_verified_updates`와 fixed-scale1024 실행 증거를 확인하고 실패한 준비 v1·GPU v1.1 기록은 보존한다. 과거 계획의 `preregistered_not_run`은 당시 선언이며 실제 완료 여부는 별도 저장 보고서로 확인한다.

기존 `prepare_inputs`로 **313문서·3,588청크·dev79질문**을 원래 순서대로 재구성한다. 양성59개는 단일 문서52개·다중 문서7개이며, 근거 없음12개·조건 불명확8개가 별도로 있다. 원래72개 필수 근거 그룹과 청크 경계 문제를 분모에서 빼지 않는다. 전체 청크 digest는 `88e474c05922354de77eeb6d0c4e3b915c74133cb361aa85cc88b0fbcd11f2af`다. 문서별 raw·normalized·ingested 해시, 청크 수·offset·본문·page도 M3와 일치해야 한다.

검색 인덱스는 원래 manifest의 train/dev/test/smoke 공개 문서 전체다. Test 분할의 공개 문서가 인덱스에 있는 것과 test 질문·정답을 평가하는 것은 다르다. 이번에는 test 질문·qrels를 읽지 않는다. Train/dev 문서만 남겨 검색 범위를 줄이지 않는다.

## 2. 새 실행기와 소스 동결

새 진입점은 `scripts/evaluate_main_dev.py`, 검사는 `tests/test_main_dev_evaluation.py`다. 기존 M2/M3/M4 실행·평가 계획에 연결된 소스와 결과·journal은 수정하지 않는다. 새 계획에 실행기·검사·이 문서 및 호출하는 프로젝트 소스의 해시를 고정하고, 구현·모델 없는 검사 후 실제 비교 전에 커밋한다. 보고서는 그 계획 해시와 실행 Git SHA를 기록한다. 계획 자체의 해시를 계획 안에 넣는 순환 참조는 만들지 않는다.

원래 `prepare_inputs`, `build_outcome`, `candidate_coverage`, `rank_dense`와 시간 측정 함수를 재사용한다. `evaluate_candidates.replay_source`로 저장된 M3 다섯 방법의 순위·지표를 재생하며, 이 작업은 모델 추론이 아니다. `evaluate_training`의 calibration 전용 `outcome`은 단일 근거만 허용하므로 dev 점수 계산에 사용하지 않는다.

계획은 정확한 configuration·입력 목록·소스 목록·판정 규칙을 검증한다. 프로젝트 소스는 LF 정규화 SHA-256, 데이터·계획·모델 파일은 원본 바이트 SHA-256으로 구분한다. Corpus/question/split 검증기 등 실제 호출하는 전이 의존성도 연결하고 기존 M3·M4 소스 바인딩을 보존한다. `preflight`와 `replay`는 기본 잠금 의존성에서 동작하며 Torch·Transformers·NumPy·가중치가 필요 없어야 한다. 실제 snapshot 검증과 모델 로드는 `run`에서 추가한다. 가중치를 요구하는 기존 calibration `load_evaluation()`을 CI 재생 경로로 호출하지 않는다.

## 3. 동일 조건의 두 번의 측정

| 항목 | 고정 정책 |
|---|---|
| 비교 순서 | `base_fresh` 다음 `terminal_fresh`, 모델별 새 인스턴스, 동시성1 |
| 횟수 | 모델마다 전체 청크 임베딩1회·질문79개1순회 |
| 모델 | 원래 pinned E5 base / manifest가 가리키는 terminal 하나 |
| Tokenizer | 두 모델 모두 검증한 원래 base snapshot의 tokenizer |
| 입력 | 원 질문·청크 그대로, `query: ` / `passage: `, 최대512토큰·오른쪽 잘림 |
| 벡터 | attention-masked mean pooling 후 L2 정규화 |
| 실행 | 같은 로컬 CUDA 장치, FP32, eager attention, eval/inference mode |
| Batch | 문서8·질문1 |
| 순위 | 전체3,588청크 exact cosine, 후보50·반환10·근거 지표5, 동점은 원래 코퍼스 순서 |
| Seed / warmup | 42 / 원래 합성 Pod 질문·passage로 모델마다2회 |

원래 M3 추론 설정을 두 모델에 동일 적용한다. CUDA matmul TF32=false, cuDNN TF32=true, deterministic algorithms=false, cuDNN deterministic=false, benchmark=false다. 실제 dtype/device, 라이브러리·CUDA/cuDNN·장치 정보, CPU thread 수와 적용된 flag를 기록한다. GPU의 bitwise 결정성을 보장하지 않는다. CPU 전환, batch·길이 축소, 추가 다운로드·의존성 변경을 실행 중 대안으로 쓰지 않는다.

각 모델은 자기 가중치로 문서 벡터와 질문 벡터를 모두 만든다. Terminal 질문을 base 문서 벡터에 대조하지 않는다. Tokenizer 입력 ID·mask의 fingerprint와 길이·잘림 기록을 두 방법에서 대조한다. 질문 잘림, 비유한/영벡터, 차원·입력 순서·설정 불일치는 실패다. 다른 추론 서버·학습 작업과 중복 실행하거나 추론 중 의존성을 동기화하지 않는다.

## 4. 지표와 단일 판정 규칙

주 지표는 **양성59질문의 모든 필수 grade2 근거가 후보50 안에 있는 질문 수**다. 보조 통과 조건은 같은59질문의 전체 근거 @5 질문 수다. 같은 근거 그룹의 대안 span은 OR, 서로 다른 필수 그룹은 AND다. 하나의 span 전체가 같은 문서의 한 청크 안에 있어야 한다. Grade1, 문서 ID만 적중, 인접 청크의 부분 span 합치기, 미주석 대체 답변을 정답으로 대체하지 않는다.

진행 조건은 다음 둘을 모두 만족하는 것이다.

1. `terminal의 전체 근거 @50 질문 수 ≥ fresh base의 수 + 1`
2. `terminal의 전체 근거 @5 질문 수 ≥ fresh base의 수`

완전한 유효 실행에서 조건을 통과하면 `eligible_for_separate_operational_validation`, 동점·퇴보로 실패하면 `retain_base`다. 조건 통과가 질문별 회귀0을 의미하지 않으므로 회복·회귀·동률 ID와 수를 모두 기록한다. 이 기준은 AI 라벨에 대한 제한된 개발 판단이며 통계적 우위·답변 정확도·test 일반화·서비스 채택을 뜻하지 않는다.

원래 M2의 문서 hit/recall/reciprocal rank, 근거 any/all/group recall 지표를 유지하고 @50 후보 회수를 함께 보고한다. 문서 reciprocal rank는 상위10청크에서 중복 제거한 문서 순위라는 이름을 유지한다. 언어·주석상 교차언어·단일/다중 문서별 분모·성공 수와 모든 paired change를 기록하며 빈 분모는 `null`이다.

추가 진단 `all_required_evidence_reciprocal_rank_at_10_chunks`는 각 필수 그룹의 대안 span 전체를 담은 가장 이른 청크 순위를 구하고, 모든 그룹이10위 안에 있으면 그 순위들 중 최댓값의 역수를 사용한다. 하나라도 누락되면0, 양성 근거가 없으면 `null`이다. 양성59개에서 평균하며 첫 근거 하나의 MRR이나 문서 reciprocal rank와 구분한다. 이 진단은 고정 @50/@5 진행 조건에 영향을 주지 않는다.

근거 없음12개·조건 불명확8개는 양성 recall 분모에 넣지 않고 원래 행과 후보 수·빈 결과 진단을 보존한다. 이들이 검수된 학습 음성이라는 뜻은 아니다. 보류 임계값·보류 정확도·답변 생성 품질은 측정하지 않는다. Calibration에서 확인한 대체 정답 미주석 한계를 그대로 명시하고, 결과를 본 뒤 질문·라벨·분모·모델·정책을 고치지 않는다.

후보50의 부족과 충분한 후보가 있는 top5 실패를 구분한다. 근거 그룹별로 기존 분류인 전체 span을 담는 청크 없음 / 근거 문서 없음 / 같은 문서의 다른 청크 / 회수를 사용한다. 그룹 분류는 서로 배타적이며 질문별 여러 원인은 겹칠 수 있다. 잘림은 별도 관찰이고 순위 실패의 원인으로 자동 판정하지 않는다.

## 5. 과거 기준선과 시간 해석

새 추론 전에 저장 M3 순위·지표의 정확한 재생을 통과해야 한다. 과거 dense는 전체 근거 @50 **34/59**, @5 **29/59**였다. 새 base와 과거 dense의 top50 구성·순서, top10, 질문별 지표, 공통 후보의 raw score 차이를 별도로 기록한다. 수치가 다르면 동등성을 주장하지 않으며 작은 차이를 반올림해 exact parity로 표시하지 않는다. 과거와 새 실행의 수치 차이는 기준선 교체·재실행 근거가 아니다. 입력·소스·모델 provenance 불일치는 단순 수치 변동과 달리 실패다.

두 모델의 load·합성 warmup·문서 벡터 준비·질문 encode·dense rank를 구분한다. CUDA 경계에서 동기화하고 질문79개의 encode/rank 시간과 합계, p50/p95, 실패 수를 남긴다. 메모리는 단계별 CUDA allocator allocated/reserved와 샘플링한 CPU RSS다. 옛 BM25/E5 시간과 새 시간을 더해 이번 전체 지연으로 제시하지 않는다.

Base 우선 고정 순서는 캐시·열·실행 순서 편향을 통제한 반복 속도 비교가 아니다. 저장 시료 재생은 시간 재측정이 아니다. 모든 시간은 Python 오프라인 측정이며 Java HTTP·ACL/DB·UI 지연·동시 사용자의 성능 또는 운영 SLO로 해석하지 않는다.

## 6. 권한·수정·삭제와 채택 경계

이 공개 코퍼스는 모든 문서가 보이는 고정 snapshot이며 세션·회원권·삭제·revision 사건이 없다. 점수 계산 전 정확한 전체 후보 집합·본문 해시·offset을 검증하고, 알 수 없는·중복·누락·오래된 청크 identity와 실행 중 변경을 거부한다. 저장 순위를 사후 필터링해 입력 오류를 숨기지 않는다. 이는 코퍼스 무결성 검사이며 ACL·문서 생명주기 검증의 대체물이 아니다.

통합 전 기존 Java 세션·workspace/private ACL·revision/delete·history/feedback의 모델 없는 회귀, 관련 Python 검사, React 타입·production build와 모델 없는 실제 브라우저 회귀를 수행한다. 이는 기존 서비스 보호 확인이며 terminal을 서비스에 넣었다는 증거가 아니다. 이번 비교의 `service_adoption`은 항상 `false`이고 서비스 모델·기본 검색 방법은 유지한다.

향후 채택에는 선택한 checkpoint를 명시적으로 연결하고 검색 전 권한 검사, vector/cache/revision identity, 수정·삭제 후 이전 내용 제거, 모델 실패·fallback 거부, 실제 로컬 HTTP·브라우저와 필수 원격 CI를 별도 확인해야 한다. 기존 로드맵의 로컬 준비는 이미 위임된 범위다. 사용자 검수를 AI가 대신할 수 없으며 유료 API·GPU 임대·클라우드와 공개 서비스 배포는 별도 사용자 승인이 필요하다.

## 7. 한 번의 실행, 실패 보존과 재생

실행 전 active job·PR CI를 확인하고 고정 계획·코드·설계를 커밋한다. 모델 로드 전에 전용 출력 디렉터리/lock을 배타적으로 확보하며 기존 결과·journal·실행 중 표식을 덮어쓰지 않는다. 실행 전후 입력·소스·코퍼스·실제 모델 파일 해시를 확인한다. 시작·단계·질문 ID·완료 또는 안전한 오류 코드를 journal에 남기고 원문·질문 본문·비밀 값·개인 절대 경로를 운영 로그에 넣지 않는다.

OOM·비유한 값·오류·중단은 부분 증거와 함께 실패로 보존하고 판정하지 않는다. 자동 재시도·이어받기, 설정 변경, cached 기준선 대체, 성공 표본만의 집계를 허용하지 않는다. 모델 없는 사전 검사는 구현 중 반복할 수 있다. 새 dev 추론 전의 오류 수정도 실패 기록을 보존한 명시적 계획 개정으로 구분한다. 실제 main-dev 추론을 시작한 뒤에는 해당 기회가 사용된 것으로 기록한다. 실행기 결함·중단을 수리해 다시 실행하려면 노출된 결과와 수정 이유를 보존한 별도 사전 계획이 필요하며, 이 문서는 그 재실행이나 재튜닝을 승인하지 않는다.

새 보고서는 계획·소스·입력·checkpoint 바인딩, 질문 ID/record 해시와 순서, 각 방법의 top50 identity·raw score·top10, 원래 지표·후보 진단·paired change·판정, 실제 runtime·token·시간·자원과 전후 검사 결과를 보존한다. 실행 성공과 품질 조건 통과는 다른 필드로 기록한다. 사람이 검토하지 않은 상태와 test 잠금을 유지한다.

CI `replay`는 공개 코퍼스를 복원하고 기본 의존성만 사용한다. 다음을 다시 검증한다.

- M3 저장 결과 재생, 새 계획·소스·공개 receipt chain·보고서 payload 해시.
- 방법마다 원래79개 행, 정확히50개 허용된 고유 후보, 유한 점수·내림차순·동점 순서, top10 prefix와 원문 span 일치.
- `build_outcome`의 질문별 지표, @50/@5의59개 분모, 집단 집계·모든 회복/회귀·고정 판정의 정확한 재계산.
- 기록된 precision·token ID/길이/잘림의 coverage, 완전하고 유한한 시간·자원 필드, 저장 시료의 percentile 재계산, 성공 journal과 보고서의 일치.

순위·hash·denominator·성공 flag 조작, 질문/후보 누락·중복, NaN/Infinity, 다른 checkpoint identity는 거부한다. 모델 없는 fixture는 OR/AND·다중 문서·청크 경계·근거 없음/불명확·동점·손상 거부를 검증한다. 실제 dev 신규 점수로 구현을 맞추지 않는다.

이 재생은 **저장 순위·지표·출처의 일관성**을 확인한다. 모델 점수·tokenization·시간·메모리를 새로 측정하거나 현재 로컬 가중치 파일의 존재·동일성을 검사한 결과가 아니다. CI에서 실제 가중치를 읽지 않았으면 그렇게 표시하며 저장된 전후 해시 영수증을 현재 실측처럼 표현하지 않는다. 결과 분석과 STATUS·DECISIONS·CONTRIBUTIONS에는 실패·회귀·한계, 로컬 검사와 최종 head 원격 CI를 구분해 남긴다.
