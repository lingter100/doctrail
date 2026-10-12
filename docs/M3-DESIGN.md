# M3 밀집·혼합·재순위화 비교 설계

기준일: 2026-10-12. **이 문서는 실행 전 설계다.** 공식 모델 카드·Hub 메타데이터·구현 문서를 확인했고, 이 문서 작성 작업에서는 모델 다운로드·설치·추론·학습을 수행하지 않았다. 모델 실행 가능성, 개선 폭, 메모리·지연은 실측 보고서가 생기기 전까지 미검증이다. 실제 구현이 아래 계약과 다르면 실행 전에 차이·이유·설정 해시를 남긴다.

목적은 M2의 주석상 교차언어 실패가 사전학습 임베딩으로 줄어드는지, 어휘 검색과 혼합하면 어떤 질문을 회복하거나 잃는지, 같은 후보의 재순위화가 추가 비용에 맞는지 확인하는 것이다. 서비스 추론 모델과 개발 보조 AI는 별개다. 설계 위임에 도구가 수락한 개발 보조 설정은 `gpt-6-astra / xhigh`이며, 부모 채팅 모델 변경이나 사람 검토의 증거는 아니다.

진행은 **프로토콜·모델 manifest 커밋 → 오프라인 비교 → 결과 검토 → 별도 서비스 통합·권한 회귀** 순서다. 오프라인 비교가 끝나도 서비스의 추가 검색 경로에서 ACL·수정·삭제가 확인되기 전에는 M3 전체 완료로 표시하지 않는다.

## 1. 고정 입력과 해석 범위

| 항목 | 첫 M3 비교의 고정값 |
|---|---|
| 코퍼스 | `data/manifests/kubernetes-v1.json`, 313문서 전체·3,588청크 |
| 질문 | `data/evaluation/m2-dev-v1.1.jsonl`, dev 79개 |
| 주 지표 분모 | 근거 있음 59개; 근거 없음 12개·조건 불명확 8개는 별도 |
| 검토 출처 | AI 작성·자동 검사 완료·사용자 검토 0개 |
| 청킹 | 서비스 `chunk_content`; 최대 1,000 codepoint, 겹침 150, 현재 경계 탐색 그대로 |
| BM25 | 서비스 `rank_chunks`; ASCII 단어·한국어 bigram, k1=1.5, b=0.75, 점수 반올림·동점 순서 유지 |
| 반환 단위 | 청크; 최종 10개, 주 근거 지표는 첫 5개 |
| test | 160개 후보의 검색 실행·모델 선택·오류 분석을 계속 거부 |

본문·manifest·질문·청크 목록과 순서·chunker·ranker·의존성 잠금 파일의 SHA-256을 기록한다. 모델 입력은 기존 `chunk.text`만 사용한다. 첫 실험에서 제목·경로 추가, query 번역·확장, 청크 변경, 라벨 수정, 점수 임계값·보류 기능을 함께 넣지 않는다. 모든 코퍼스 분할을 인덱싱할 수 있지만 test 질문·라벨은 튜닝에 사용하지 않는다.

M2의 `evidence_all_at_5_chunks=30/59`, `cross_language_only=1/23`을 보존한다. M3 실행기의 BM25 결과가 기존 질문별 순위·지표와 맞는지 먼저 확인한다. 불일치는 입력 또는 실행기 변경을 설명하기 전까지 개선 비교로 쓰지 않는다. 현재 청크에 필수 span 전체가 들어가지 않는 3질문도 분모에서 빼지 않는다. 해당 질문은 별도 청킹 연구의 대상으로 표시한다.

이 평가의 점수는 **불완전 AI 주석에 대한 예비 개발 회수 지표**다. 답변 정확도·사용자 만족·일반화 성능으로 바꾸어 표현하지 않는다. dev 분석으로 라벨을 보완하면 새 버전을 만들고 모든 비교 방법을 같은 버전으로 다시 평가하며 과거 결과를 남긴다. 최종 test 개방은 [M2 계약](M2-EVALUATION.md#6-개발-평가와-테스트-격리)의 실제 사람 검토·설정 동결 조건을 별도 충족해야 한다.

## 2. 선택 모델과 근거

| 역할 | 첫 비교 모델 | 확인한 라이선스 표시 | 고정 Hub 리비전 |
|---|---|---|---|
| 임베딩 | `intfloat/multilingual-e5-small` | MIT | `614241f622f53c4eeff9890bdc4f31cfecc418b3` |
| 재순위화 | `BAAI/bge-reranker-v2-m3` | Apache-2.0 | `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e` |

E5-small은 한국어·영어를 포함하는 다국어 임베딩이며 384차원·512토큰 설정이다. 카드의 검색용 접두어·attention-mask 평균 풀링·L2 정규화 절차를 따른다. 작은 인코더로 첫 밀집 기준선을 만들 수 있어 선택했다. 이 선택은 이 코퍼스에서 우수하다는 실측 결론이 아니다. [고정 모델 카드](https://huggingface.co/intfloat/multilingual-e5-small/blob/614241f622f53c4eeff9890bdc4f31cfecc418b3/README.md), [고정 config](https://huggingface.co/intfloat/multilingual-e5-small/blob/614241f622f53c4eeff9890bdc4f31cfecc418b3/config.json).

BGE v2 m3는 다국어 질문·문서 쌍의 관련도를 내는 native `XLMRobertaForSequenceClassification` 모델이다. 약 568M 가중치를 가진 인코더형 모델로, 공식 예제는 512토큰 쌍 입력과 fp16 사용을 제공한다. 카드가 fp16의 수치·품질 차이 가능성을 명시하므로 dtype을 숨기지 않는다. 장문 최대 길이 설정을 그대로 사용하는 대신 첫 비교를 512토큰으로 제한한다. [고정 모델 카드](https://huggingface.co/BAAI/bge-reranker-v2-m3/blob/953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e/README.md), [고정 config](https://huggingface.co/BAAI/bge-reranker-v2-m3/blob/953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e/config.json).

위 라이선스는 해당 리비전의 모델 카드/Hub `cardData.license`에서 확인한 배포자 표시다. 이 문서가 학습 데이터 각각의 권리 검토를 대신하지 않는다. 모델 출처·라이선스 표시를 문서와 실행 manifest에 남기며 가중치를 Git에 재배포하지 않는다. 한국어 지원 표시나 공개 벤치마크 점수를 DocTrail의 한국어 성능 근거로 인용하지 않는다.

### 리비전과 가중치 검증

2026-10-12에 공개 Hub API `GET /api/models/{repo_id}?blobs=true`와 고정 리비전의 config를 조회했다. 모델 본체는 내려받지 않았다. 확인한 단일 가중치 파일은 다음과 같다.

| 모델 | 파일 | API에 표시된 bytes | API에 표시된 LFS SHA-256 |
|---|---|---:|---|
| E5-small | `model.safetensors` | 470,641,600 | `1a55775f53449dac10a2bcbc312469fac40b96d53198c407081a831f81c98477` |
| BGE reranker | `model.safetensors` | 2,271,071,852 | `d9e3e081faff1eefb84019509b2f5558fd74c1a05a2c7db22f74174fcedb5286` |

메타데이터 주소: [E5 API](https://huggingface.co/api/models/intfloat/multilingual-e5-small/revision/614241f622f53c4eeff9890bdc4f31cfecc418b3), [BGE API](https://huggingface.co/api/models/BAAI/bge-reranker-v2-m3/revision/953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e).

실행 준비 단계의 계약:

1. `HfApi.model_info(repo_id, revision=PINNED_SHA, files_metadata=True, token=False)`의 반환 SHA가 지정한 40자 SHA와 같은지 검사한다. `main`의 최신 SHA를 매 실행 자동 채택하지 않는다. [API 문서](https://huggingface.co/docs/huggingface_hub/package_reference/hf_api#huggingface_hub.HfApi.model_info).
2. 가중치·config·tokenizer·special-token 설정·출처 카드만 명시적 허용 목록으로 같은 SHA에서 받는다. `.bin`, 임의 Python 코드, ONNX/OpenVINO 중복 가중치는 받지 않는다. Hub의 `snapshot_download`는 revision과 허용 목록을 지원한다. [다운로드 문서](https://huggingface.co/docs/huggingface_hub/guides/download).
3. 실제 파일 bytes·SHA-256을 검증한다. 위 표는 원격 메타데이터이며 **실제 로컬 파일 해시 검증을 대신하지 않는다**. tokenizer/config에도 별도 로컬 SHA-256을 기록한다.
4. `AutoTokenizer(..., trust_remote_code=False, use_fast=True)`와 native `AutoModel`/`AutoModelForSequenceClassification`을 사용한다. 모델은 `use_safetensors=True`, `trust_remote_code=False`, `local_files_only=True`로 검증된 로컬 snapshot에서 읽는다. safetensors가 없거나 config가 원격 코드 실행을 요구하면 실패로 종료한다. [모델 로딩 문서](https://huggingface.co/docs/transformers/main_classes/model#transformers.PreTrainedModel.from_pretrained).
5. 준비 다운로드와 평가 실행을 분리한다. 평가 중에는 외부 추론 요청을 하지 않고 Hub offline 모드·로컬 파일 전용 로딩을 사용한다. 모델 cache 경로와 개인 환경 경로는 공개 보고서에 넣지 않는다.

## 3. 의존성과 입력 처리

Python 3.11·uv를 유지한다. 새 의존성은 기본 BM25 서비스와 구분한 선택적 `retrieval` 그룹으로 관리하되 하나의 검토 가능한 `uv.lock`에 정확 버전을 고정한다. 필요한 직접 의존성은 `torch`, `transformers`, `huggingface-hub`, `numpy`, `safetensors`, `psutil`이다. `tokenizers`의 실제 잠금 버전도 기록한다. fast tokenizer로 로딩이 가능한지 확인하고, `sentencepiece`는 선택한 버전이 실제 요구할 때만 잠금에 추가한다.

설계 마감 시 저장소 잠금에서 확인한 선택은 Windows `torch==2.10.0+cu128`(공식 `pytorch-cu128` index), `transformers==4.57.6`, `huggingface-hub==0.36.2`, `safetensors==0.8.0`, `psutil==7.2.2`, `tokenizers==0.22.2`다. NumPy는 Python 버전별 잠금 분기가 있어 실제 Python 3.11에서 선택한 버전을 실행 보고서에 기록한다. 이 조합은 native API를 고정하려는 선택이며 최신 버전이라는 주장이 아니다. 잠금 파일을 읽은 것과 설치·CUDA 추론 성공을 구분한다.

모델은 native Transformers로 직접 실행하므로 첫 비교에 `FlagEmbedding`, `sentence-transformers`, `accelerate`, FlashAttention, bitsandbytes, 벡터 DB를 추가할 필요는 없다. `device_map="auto"`를 쓰지 않고 명시적으로 `cpu` 또는 `cuda:0`를 선택한다. Windows/Python/CUDA 드라이버에 맞는 공식 PyTorch wheel 출처와 CUDA build를 잠근 후 CPU CI와 로컬 CUDA smoke를 확인한다. 이 문서가 설치 호환성을 검증한 것으로 읽히면 안 된다. 실제 선택 버전·wheel 출처·실행 명령은 구현 및 환경 준비 결과에 기록한다.

| 항목 | 고정 처리 |
|---|---|
| E5 query | 원 질문 앞에 `query: `; 특수 토큰·접두어 포함 최대 512 |
| E5 passage | 원 청크 앞에 `passage: `; 특수 토큰·접두어 포함 최대 512 |
| E5 벡터 | padding 제외 평균 풀링, L2 정규화, 384차원 float32; 정확 cosine(내적을 양쪽 norm으로 나눔)으로 순위 |
| E5 실행 | float32, passage batch=8·query batch=1, `eval()`·`inference_mode()`, 동적 batch padding |
| reranker | 접두어 없는 원 질문·원 청크 쌍; 총 길이 512, 오른쪽 잘림, `truncation="only_second"` |
| reranker 실행 | CUDA float16, 시작 batch=1, raw logit 내림차순; sigmoid를 확률·보류 기준으로 사용하지 않음 |
| 동점 | BM25 기존 stable key 유지; dense/RRF는 고정 코퍼스 입력 순서(document ID·청크 ordinal), 리랭커는 입력 후보 순서 유지 |

밀집 검색은 전체 가시 청크 행렬을 정확 검색한다. 작은 corpus에서 ANN 오차나 인덱스 파라미터를 함께 도입하지 않는다. 정규화 벡터의 내적과 cosine은 수학적으로 같지만 구현은 norm으로 다시 나누는 명시적 cosine이며 부동소수점 비트 동일성을 주장하지 않는다. Dense/RRF/리랭커 점수는 보고서에서 반올림하지 않는다. BM25의 기존 8자리 반올림 동점 계약은 보존한다. 반환하는 원문·오프셋·청크 ID는 모델 입력을 잘라도 바꾸지 않는다.

### 잘림을 비교에서 숨기지 않는 방법

같은 1,000 codepoint 청크라도 모델별 tokenizer와 E5 접두어, 재랭커의 query+passage 예산 때문에 실제 읽은 글자 수가 다르다. 따라서 이 실험은 동일 문서 단위의 **전체 검색 파이프라인 비교**이며, 동일한 모든 토큰을 읽은 순위 함수만의 인과 비교는 아니다. Hugging Face의 `only_second`는 쌍의 두 번째 입력만 자르는 명시적 정책이다. [잘림 문서](https://huggingface.co/docs/transformers/main/pad_truncation).

평가 전 label을 보지 않는 tokenizer 검사를 수행한다. E5 질문이 512를 넘거나 reranker 질문+쌍 특수 토큰만으로 512를 소진하면 조용히 질문을 자르지 않고 입력 부적합으로 보고한다. 해당 질문을 임의 제외한 평균을 발표하지 않는다. 장문 질문 처리가 필요하면 별도 명시적 query cap을 실행 전에 새 설정으로 동결한다. 현재 API의 500 codepoint 제한이 512 model tokens 보장을 의미하지 않는다.

첫 실행은 전체 및 단계별 모델 truncation 집계를 남긴다. E5 query/passages와 reranker query/passage 쌍을 구분하여 실제 검사한 입력 수·잘린 입력 수·분모와 구현된 토큰 길이 통계를 보고한다. E5 passage 분모는 전체 3,588청크, reranker 분모는 실제 평가한 모든 질문-후보 쌍이다. warmup 합성 입력과 측정 dev 입력의 집계를 구분하고 batch padding 수를 truncation으로 세지 않는다. 언어별 분포·고유 청크별 집계 등 추가 진단이 구현되지 않았다면 전체/단계별 수치를 그 진단의 대체물로 소개하지 않는다.

첫 실행의 근거 지표는 **반환된 원문 전체 청크의 정확한 source offset**으로 계산하는 M2 계약을 유지한다. 잘린 입력의 개수만으로 모델이 정답 span을 읽었는지는 알 수 없다. 따라서 원문 전체 청크에서의 회수를 모델이 실제로 읽은 근거의 회수라고 주장하지 않는다.

정확한 `model_visible` span coverage 지표는 현재 구현되지 않은 후속 진단이며 첫 오프라인 비교의 필수 완료 조건으로 삼지 않는다. 구현할 경우 fast tokenizer의 offset mapping과 sequence IDs로 접두어·특수 토큰을 제외한 **원문에서 읽힌 범위**를 복원하고 Unicode·한국어·공백·문장부호·중복 구절에서 원본 codepoint와 맞는지 검증한다. tokenizer decode 결과를 원문 대신 쓰지 않는다. 각 필수 span이 원 청크에는 포함되지만 읽힌 부분에는 빠졌는지 별도 이름의 지표로 계산하고, 구현·검증 전에는 해당 값을 보고하지 않는다.

첫 비교에서 긴 청크를 추가 분할하거나 여러 window의 점수를 max-pool하지 않는다. 그 변경은 청크/추론 예산을 바꾸므로 별도 실험이다. 잘림이 실패에 관여하면 dev 후속 진단에서 E5가 읽은 동일 원문 prefix를 쓰는 BM25 통제를 추가할 수 있다. 이 통제는 전체 본문 BM25 기준선을 대체하지 않는다.

## 4. 사전 지정 비교와 후보 예산

공통 최종 반환 수는 10, 주 근거 지표는 5다. 첫 비교는 아래 네 방법을 **모두** 보고한다. dev 점수를 보고 불리한 방법을 결과 표에서 제거하지 않는다.

| ID | 후보 생성 | 최종 순위 | 목적 |
|---|---|---|---|
| B | BM25 상위 50청크 | 기존 BM25 | M2 재현 기준선 |
| D | E5 exact 상위 50청크 | cosine | 다국어 밀집 기준선 |
| H | B50·D50 합집합, 중복 청크 제거 | RRF 상위 50 중 첫 10 | 혼합 검색 |
| HR | H가 만든 **동일한 50후보** | BGE 재순위화 후 첫 10 | 후보 고정 재순위화 효과 |

RRF는 1부터 시작하는 순위에 `sum(1 / (60 + rank))`를 적용한다. 두 검색기의 가중치는 같다. 해당 검색기 top-50 밖 후보의 기여는 0이며, 중복된 같은 청크는 한 결과다. BM25 양수 점수가 있는 후보가 50보다 적으면 없는 후보를 점수 0으로 채우지 않는다. 모든 방법에서 요청 수·실제 후보 수를 남긴다. 청크 중복은 안정적인 corpus document ID·revision·ordinal·offset으로 식별한다.

`H`의 fusion 입력은 최대 100개이고 `B`/`D`는 각각 50개다. 이를 동일 후보 비용이라고 쓰지 않는다. 재랭커가 실제 점수화하는 후보 수는 최대 50개로 고정하며, `H`와 `HR`의 차이는 같은 후보의 순위 변화다. 질문별 B50/D50 합집합 크기·교집합 크기·H50 선택 후 탈락 수를 보고한다.

예산 진단 `H25`도 사전 지정한다. B25·D25 합집합의 최대 50후보를 같은 RRF로 정렬하고 B50/D50/H와 비교한다. 중복 때문에 실제 크기가 50보다 작을 수 있다. 이는 fusion에 들어오는 최대 청크 수를 맞춘 **후보 예산 진단**이며 CPU/GPU 연산량·전체 corpus scoring 비용까지 같게 하는 통제는 아니다. H25가 HR의 후보를 사후 대체하지 않는다. 다른 후보 수·RRF 상수·모델을 탐색하면 dev 추가 탐색으로 새 run과 탐색 횟수를 공개한다.

### 지표와 후보 단계의 상한

주 지표는 M2 정의를 그대로 사용하는 `evidence_all_at_5_chunks`다. `evidence_any_at_5_chunks`, `evidence_group_recall_at_5_chunks`, 상위 10청크에서 중복 제거한 문서 Hit@5·Recall@5·reciprocal rank를 함께 보고한다. 근거 없음·조건 불명확 질문의 결과 유무는 따로 공개하며 검색 점수만으로 답변 가능성 성능을 주장하지 않는다.

각 B50·D50·합집합·H50에 대해 필수 근거 그룹 recall과 모든 필수 근거 포함 여부를 계산한다. `candidate_evidence_all_at_50_chunks`는 후보 원문 청크 안에 필수 span이 있는지를 재며 최종 top-5 성공의 필요조건이다. 후보에 모든 그룹이 있어도 top-5의 5청크 안에 함께 담을 수 없는 경우가 있으므로 이를 달성 가능한 oracle@5와 동일시하지 않는다. 실제 oracle@5를 추가하려면 최대 5청크로 모든 필수 그룹을 덮을 수 있는지 별도 집합 덮기 검사를 한다. 재랭커가 실제 읽은 범위에 대한 후보 진단은 위 `model_visible` 후속 구현과 함께 다룬다.

59개 전체, 한국어/영어, 기존 cross-language 분류, 단일/다중 문서의 분모·성공 개수·점수를 공개한다. 코드/명령어 유형 태그는 점수 결과를 보기 전에 규칙·ID 목록을 고정한 경우에만 별도 분석한다. 예전 데이터에 없던 태그를 결과에 맞춰 사후 정의하면 탐색적 분석으로 표시한다.

방법 간 차이는 같은 질문의 성공→실패·실패→성공 ID와 근거를 공개한다. 작은 관련 질문 집합에 독립 표본 가정을 씌운 유의성 주장을 하지 않는다. 신뢰구간을 추가할 경우 질문 계열과 공유 근거 분할 계열을 연결한 그룹 단위로 paired resampling을 하며 그룹 수·seed·반복 수를 명시한다. 그룹이 적으면 불확실성을 드러내고 확정 승자를 주장하지 않는다.

첫 비교는 작은 후보군의 결과를 확인하는 것이므로 서비스 기본값을 자동 교체하지 않는다. dev 품질, 교차언어 회복, 새 실패, 비용과 운영 회귀를 함께 보고 추천을 정한다. 주 지표가 동률인 방법은 더 단순하고 빠른 방법을 우선 검토한다. 재랭커가 개선하지 못하면 그 결과 자체로 M3 비교를 완료할 수 있다.

## 5. 6GB 로컬 GPU 실행·실패 프로토콜

FP32 E5와 FP16 BGE의 가중치 저장량은 원격 텐서 수 기준으로 합쳐 약 1.5GiB라는 계산상 추정이다. GPU context, 임시 activations, attention, allocator, tokenizer/CPU 메모리, 화면 사용량은 포함되지 않는다. 이 숫자를 peak VRAM 또는 6GB 실행 성공으로 인용하지 않는다. 다운로드 파일의 약 2.7GB와 GPU 실행 메모리도 다른 수치다.

1. 로컬 GPU 이름·총/가용 VRAM·드라이버·torch CUDA build·CPU/RAM·OS·전원 조건을 기록한다. 첫 probe는 근거 라벨 없이 원 토큰 길이가 가장 긴 청크·쌍을 포함한다.
2. E5 인덱스 구축은 batch 8로 시작하고 512토큰 최장 batch를 확인한다. OOM 시 실패를 남기고 4→2→1로 줄이는 사전 지정 순서만 허용한다. 선택 batch를 고정한 뒤 품질·성능 run을 시작한다. query batch는 서비스와 동일한 1이다.
3. 재랭커는 batch 1·512토큰·FP16로 시작한다. 50후보를 순차 처리한다. 이 단계가 성공한 후 batch 확대는 별도 속도 실험이며 품질 비교 중 자동 조정하지 않는다.
4. `model.eval()`, `torch.inference_mode()`를 적용하고 seed·연산 정밀도·TF32/attention backend를 기록한다. 첫 측정에는 quantization·compile·autocast 자동 전환을 섞지 않는다. 재현에 필요한 실제 dtype/장치/연산 backend를 보고한다.
5. CUDA OOM·비유한 벡터/점수·tokenizer 오류를 실패로 보존한다. GPU run 도중 CPU로 조용히 전환하지 않는다. CPU fallback을 한다면 별도 `device=cpu`, FP32 run·시간·사유를 남기고 GPU 통계에 합치지 않는다. GPU 오류 뒤에는 깨끗한 새 프로세스에서 재시작한다.
6. 개별 모델 probe와 실제 전체 파이프라인 resident 측정을 구분한다. E5를 내린 후 재랭커만 잰 peak를 두 모델이 함께 상주하는 서비스 peak라고 쓰지 않는다. 실제 HR 경로의 상주·언로드 정책과 모델 로드 지연을 기록한다.

유료 GPU·외부 모델 API·클라우드 실행은 이 설계의 대체 실패 경로가 아니다. 무료 로컬 범위에서 실행할 수 없으면 실패와 로컬 대안을 보고하고 비용이 드는 변경에는 별도 사용자 승인을 받는다.

## 6. 시간·메모리 측정의 경계

첫 오프라인 실행은 **각 모델에 고정 합성 질의 2개로 warmup한 뒤, 각 방법에서 전체 dev 79개를 한 번만 순회**한다. warmup에 사용할 합성 질문·재랭커용 합성 passage와 순서를 실행 설정에 고정하며 평가 질문·정답을 warmup 입력으로 사용하지 않는다. 모델 warmup 2회는 전체 dev sweep 2회라는 뜻이 아니다. E5 passage 구축은 float32 batch=8, 측정 query는 한 번에 하나씩 인코딩한다. BGE는 float16 batch=1이다. 각 방법에 같은 고정 dev ID 순서를 적용하고 질문별 순위·해당 단계 시간 표본을 보존한다.

이 단일 순회는 측정 결과를 보기 전에 정한 로컬 자원 범위 선택이다. 별도 반복 성능 run을 수행한 것으로 표시하지 않으며 반복 실행 분산·열/전력 안정성·통계 검정력을 확인했다고 주장하지 않는다. 열/전원·OS cache·다른 프로세스와 방법 실행 순서에 의한 영향은 통제하지 못한 한계로 남긴다. 반복 안정성 확인이 필요하면 첫 결과를 보존한 채 별도 사전 지정 성능 실험으로 추가한다.

| 측정명 | 포함 | 제외/구분 |
|---|---|---|
| 준비 다운로드 | 공식 모델 파일 수신·해시 검증 | 추론 지연에 합치지 않음 |
| cold load | 검증된 디스크 snapshot에서 모델 로드·장치 전송 | 네트워크 다운로드 제외; OS cold cache 보장 여부 명시 |
| index build | 전체 청크 tokenization·embedding·저장 | 반복 query 지연 제외; 캐시 hit run과 구분 |
| offline query end-to-end | query tokenization/encoding, CPU↔GPU 이동, exact scoring, BM25 tokenization, RRF, reranking, top-k 반환 | HTTP·SQL·인증·UI 제외; 방법별 해당 단계만 포함 |
| reranker-only | 이미 고정된 H50 쌍의 tokenization·전송·추론·정렬 | 후보 생성 비용 제외; HR 전체 지연과 별도로 표시 |
| loopback HTTP | 실제 세션 인증·ACL·DB·검색·직렬화·왕복 | 인터넷·TLS·UI 렌더링 제외 |

GPU 측정 경계 전후에 `torch.cuda.synchronize()`하고 monotonic wall clock을 읽어 비동기 kernel 제출 시간만 재는 오류를 막는다. 중첩 단계 계측 때문에 sync 비용이 늘어날 수 있으므로 전체 경로 측정과 상세 profiling run을 구분한다. [CUDA 동기화 문서](https://docs.pytorch.org/docs/2.14/generated/torch.cuda.synchronize.html).

메모리는 cold load, index build, query 전체 실행마다 시작 baseline과 peak를 남긴다. PyTorch의 `max_memory_allocated`와 `max_memory_reserved`를 함께 기록하고, phase 시작 전 sync 후 peak 통계를 reset한다. reset은 이미 상주한 모델을 제거하지 않는다. GPU tensor/allocator 수치는 드라이버·디스플레이·다른 라이브러리를 포함한 전체 VRAM과 다르므로 `nvidia-smi`의 총 device 사용량·프로세스 표기가 가능한 경우 별도 샘플을 함께 보존한다. Windows에서 process memory가 제공되지 않으면 `null`과 이유를 남긴다. [allocator 메모리 설명](https://github.com/pytorch/docs/blob/site/stable/notes/cuda.md), [reserved peak 문서](https://docs.pytorch.org/docs/stable/generated/torch.cuda.memory.max_memory_reserved.html).

CPU RSS는 모델 로드 전부터 같은 프로세스의 일정 주기 샘플로 수집하고 OS가 제공하는 peak working set과 구분한다. 샘플 간격·누락 가능성·자식 프로세스 포함 여부를 보고한다. Python `tracemalloc`만으로 native torch/NumPy 메모리를 포함한 전체 RAM이라고 주장하지 않는다. 독립 phase의 peak 합계를 동시에 사용한 메모리로 제시하지 않는다.

79개 단일 순회의 개별 시간 표본과 p50/p95, 성공·실패·timeout 수를 보존한다. 이 분위수는 해당 실행의 서로 다른 질문에 대한 관측치이며 같은 질문 반복의 변동성을 추정하지 않는다. 실패 질문을 제거한 성공 지연만 제시하지 않으며 OOM 등으로 완료하지 못한 방법은 `incomplete`다. 후속 반복 쿼리는 새 품질 표본이 아니다. M2의 오프라인/HTTP 수치는 당시 환경·scope가 달라 현재 CPU/GPU 비교와 동일 조건이라고 쓰지 않는다.

HTTP는 기존 M2의 언어·category별 ID 순 첫 2질문 선정 규칙을 재사용할 수 있다. 실제 선택된 ID·중복 제거 결과·warmup·반복·동시성 1·timeout을 실행 전 고정하고 동일 인증 세션·같은 코퍼스로 방법별 측정한다. 캐시 cold/warm 상태를 명시하고 캐시 hit를 제외한 첫 업로드/변경 후 검색도 별도로 확인한다. 313문서·단일 사용자 지연을 1,000문서 부하나 운영 SLO로 소개하지 않는다.

## 7. 서비스 통합의 정확성 계약

기본 BM25 경로는 계속 동작해야 한다. 모델 의존성을 설치하지 않았거나 snapshot이 없을 때 기본 업로드·BM25·근거 확인이 시작부터 실패하면 안 된다. 추가 방법은 명시적으로 선택하며 모델 로딩 실패·CUDA OOM·인덱스 불완전 상태에는 안전한 오류 코드와 request ID를 반환한다. 자동 BM25 fallback으로 HR 성공 수를 늘리지 않는다.

**권한을 먼저 정하고 그 집합만 점수화한다.** 서버 세션의 user ID로 workspace membership와 `visibility='workspace' OR owner_id=current_user`를 확인한 현재 ready 청크를 사용한다. BM25 IDF도 그 집합만으로 계산한다. dense는 허용된 vector 행만 내적에 넣고, RRF와 reranker는 이미 허용된 후보만 받는다. 전체 workspace/global top-k를 먼저 뽑고 나중에 필터링하는 구현은 금지한다. 결과·직접 근거·history·feedback도 최신 권한과 revision 검사를 유지한다.

파생 벡터/캐시의 identity에는 `document_id`, `revision`, `chunk_id` 또는 ordinal·offset, 원문 chunk hash, 모델 리비전, tokenizer/config hash, prefix·max_length·pooling·normalization·dtype 설정을 포함한다. 캐시가 있음을 현재 권한의 증거로 취급하지 않는다. corpus 전체 행렬을 cache해도 매 요청 허용 행을 먼저 선택한다. 다른 사용자·workspace의 query 결과 cache를 공유하지 않는다.

수정·재처리·삭제에서는 이전 청크를 무효화하는 기존 트랜잭션 의미를 유지한다. 새 revision의 vector 생성 중에 이전 revision을 최신으로 돌려주거나 일부 새 vector와 옛 vector를 섞지 않는다. 벡터를 저장한다면 chunk foreign key와 revision/model fingerprint를 함께 검증하고 삭제/교체가 vector에서도 원자적으로 반영되도록 한다. 인메모리 cache의 오래된 항목은 현재 청크 집합과 교차 검증한 뒤 제거한다. 파일 cache는 정해진 보존/삭제 정책으로 정리하며 Git에 넣지 않는다.

현재 서비스 검색은 `BEGIN IMMEDIATE` 안에서 권한 snapshot·ranking·history 저장을 수행한다. 가장 작은 안전한 통합은 이 경계를 유지하고 모델은 요청 전에 준비하는 방식이다. 다만 GPU 순위 계산까지 transaction이 길어져 수정·업로드가 기다릴 수 있으므로 대기·timeout·동시 수정 동작을 검증해야 한다. 이를 고성능 운영 구조로 소개하지 않는다.

긴 transaction을 없애려면 별도 변경으로 snapshot generation 검증을 설계한다. 모든 문서/ACL/membership 변경이 갱신하는 generation을 읽고, 권한을 통과한 snapshot으로 계산한 뒤 짧은 transaction에서 generation·membership·revision을 재확인한다. 바뀌면 오래된 결과/history를 버리고 제한된 재시도 또는 명시적 오류를 낸다. 모든 변경 경로가 generation을 올리지 않는 상태에서 단순히 GPU 계산만 transaction 밖으로 이동하면 안전한 대안이 아니다.

필수 회귀 시나리오는 같은 workspace의 타인 private 문서, 다른 workspace, 회원 자격/공개 범위 변경, 수정 v1→v2, 삭제, 반복 재처리, cache가 warm인 상태의 동일 작업이다. ranker/reranker spy로 권한 밖 텍스트·vector가 점수화되지 않았음을 확인하고, 동시 수정에서는 일관된 한 revision 또는 명시적 retry 오류만 허용한다. 반환 text와 현재 원문 offset의 정확 일치, history·feedback의 최신 권한/리비전 검증도 확인한다. 실제 공개 corpus 평가와 합성 보안 테스트는 구분한다.

질문·원문·vector를 운영 로그에 기록하지 않는다. 오류 stack에 tokenizer 입력·로컬 개인 경로가 섞이지 않게 하며 request ID·안전한 오류 코드·단계·소요시간·개수만 남긴다. 모델 입력을 UI에 raw HTML로 노출하지 않는다. 공개 실험 JSON에 저장하는 공개 질문별 순위와 운영 로그 정책은 별개다.

## 8. 산출물과 완료 판정

구현 단계는 모델 manifest·설정·입력/소스 해시, 덮어쓰지 않는 질문별 결과, 후보/잘림 진단, 개선·퇴보 사례, 시간·메모리·OOM/CPU 전환 기록을 남긴다. 보고서에는 모델 학습 `none`, 서비스 생성 답변 `none`, 사람 검토 수, test 실행 여부, 외부 추론 API 요청 수와 측정하지 않은 비용을 명시한다. 로컬 전력·장비·개발 AI 비용을 재지 않았다면 총비용 0원이라고 하지 않는다.

M3 완료는 네 방법의 공정한 dev 비교와 한계 공개, 원문 무결성·권한·변경·삭제 회귀, 관련 테스트와 production frontend build, 재현 안내를 근거로 판정한다. 실행이 불가능한 방법은 실패·원인·대안을 공개하고 완료 범위에서 구분한다. 모델이 존재한다거나 코드가 통과했다는 사실만으로 실측 완료라고 하지 않는다. 원격 CI는 가벼운 deterministic 테스트·입력 계약을 확인하며, GPU가 없는 CI에서 로컬 CUDA 성능을 재현했다고 기록하지 않는다.

마일스톤 정리 시 `STATUS.md`, `DECISIONS.md`, `CONTRIBUTIONS.md`, `experiments/README.md`에 실제 명령·결과·선택·미검증 항목을 업데이트한다. 설계 작성자는 이 파일만 변경한다. 후속 학습은 관찰한 실패·train 계열 데이터·로컬 자원 근거로 별도 결정하며, M3 비교 결과가 없는데 학습 대상이나 개선을 미리 확정하지 않는다.
