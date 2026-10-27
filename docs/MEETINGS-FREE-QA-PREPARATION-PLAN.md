# 무료 로컬 QA 비교의 준비 계약
2026-10-27 · 설계만 · [수용 결정](MEETINGS-FREE-QA-NEXT-DECISION.md) 9bcd3066을 구체화한다.

권고는 현재 Ministral3-3B Q5_K_M과 공식 Qwen2.5-7B-Instruct Q4_K_M의 새 QA6쌍 비교 하나다. 모델 우위·완료 가능성을 가정하지 않는다.
원문 전체에 근거한 충분한 자연어 답변·정확한 인용·적절한 보류가 목표다. 형식 통과·짧은 답·중립 성공으로 의미 품질을 대신하지 않는다.

## 공식 자산과 확인 범위
[Qwen GGUF 고정 metadata](https://huggingface.co/api/models/Qwen/Qwen2.5-7B-Instruct-GGUF/revision/bb5d59e06d9551d752d08b292a50eb208b07ab1f?blobs=true)의 revision은 bb5d59e06d9551d752d08b292a50eb208b07ab1f다.
| 정확 파일명 | 바이트 | SHA256 |
| --- | ---: | --- |
| qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf | 3,993,201,344 | dfce12e3862a5283ccfb88221b48480e58745165de856439950d0f22590580db |
| qwen2.5-7b-instruct-q4_k_m-00002-of-00002.gguf | 689,872,288 | 539cf93f78e887edea1c04e2d7d8cdaca9d01dae9c9025bcb8accbe29df3d72a |
합계4,683,073,632바이트다. 게시자 LFS metadata를 확인했으며 로컬 실물 검증은 아직0이다. 두 파일을 그대로 함께 두고 첫 shard만 모델 진입 경로로 지정한다.
[고정 card](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF/blob/bb5d59e06d9551d752d08b292a50eb208b07ab1f/README.md)는 원본을 Qwen/Qwen2.5-7B-Instruct로 명시하고 [LICENSE](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF/blob/bb5d59e06d9551d752d08b292a50eb208b07ab1f/LICENSE)는 Apache-2.0이다. 변환 당시 원본 commit은 명시되지 않아 unknown으로 둔다.
공식 원본 metadata 관측은 별도로 a09a35458c702b33eeacc393d103063234e8bc28에 고정했다. 이를 GGUF 변환 원본 revision으로 채우지 않는다.
[config](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct/blob/a09a35458c702b33eeacc393d103063234e8bc28/config.json)는 Qwen2ForCausalLM·28층·Q28/KV4·vocab152064·max_position32768이다. API의 repo-level context131072와 혼동하거나 ctx6144를 늘리지 않는다.
[tokenizer config](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct/blob/a09a35458c702b33eeacc393d103063234e8bc28/tokenizer_config.json)는 Qwen2Tokenizer·add_bos=false·EOS im_end151645·pad endoftext151643·im_start151644를 명시한다. vocab/merges/tokenizer 파일은 API blobID/크기 metadata만 기록했고 실행·취득하지 않았다.
원본 template UTF8 SHA cd8e9439…(2507B)와 repo-level GGUF API template d5495a1e…(2509B)는 tools 안내의 중괄호가 다르다. 어느 것도 특정 shard 내장 template의 실물 확인으로 간주하지 않는다.
후속 취득에서 두 shard의 split metadata와 첫 shard의 내장 template·tokenizer 관련 KV를 읽기 전용으로 결속한다. 원본의 최신 template로 덮어쓰거나 Qwen3 thinking suffix를 붙이지 않는다.
[고정 llama.cpp loader](https://github.com/ggml-org/llama.cpp/blob/d81235049384534c167caea52b85a694f6103d14/src/llama-model-loader.cpp#L595-L673)는 split.count와 첫 split.no=0을 확인하고 나머지 shard 이름·index·중복 tensor·총 tensor 수를 검사한다. 병합 없이 첫 파일로 로딩하는 소스 경로가 있으며, 이 PC의 실제 성공은 미검증이다.

## 새 파일만으로 준비
새 data/models/meetings-generation-qwen25-7b-q4km-v1.json에 두 shard·license·원본 provenance 상태·metadata 관측 revision·기존 b11429/d8123504 및 재사용 runtime55의 별도 참조를 담는다.
새 scripts/prepare_meeting_free_qa.py는 opt-in 취득/verify-only를 분리한다. 정확 URL/파일2개만 전송5GiB·새 소유 디스크6GiB·총30분 안에서 받고 SHA/크기 일치 후 같은 볼륨에서 원자적 이름 변경한다.
부분 파일·취득 실패·단계별 receipt를 남기고 자동 재다운로드·병합·다른 양자화·설치·기존 cache 삭제는 없다. metadata와 임시 파일도 상한에 포함하고 기존 runtime55를 복제·변경하지 않는다.
새 tools/free_qa/policy.py·adapter.py·runner.py와 scripts/probe_meeting_free_qa.py·tests/test_meeting_free_qa.py가 불변 정책, 사전 검증, QA-only 실행을 담당한다. UI/서비스 기본값과 기존 candidate/test/schema1–5/frozen 파일은 수정하지 않는다.
원본 candidate의 validate_input/diagnose/execute 및 CandidateAdapter는 자료4개·QA4회·단일 모델 SHA에 고정되어 있어 그대로 호출해6개를 우회하지 않는다. 새 adapter의 명시적 고정 profile 선택으로 처리하고 전역 monkeypatch는 금지한다.
GGUFGenerator의 bounded HTTP/_complete/GREEDY·begin/end_request와 기존 qa_request_messages(QA_COVERAGE_CONTROL)·source_wire_messages(COMPACT_WIRE)·QA_GRAMMAR·grounded_answer_refs를 재사용한다.
새 loader는 profile/정확 shard집합/전체 SHA/첫 경로/alias/내장 template·tokenizer binding과 실제 props build·ctx6144·slot1을 모두 검증한다. alias는 shard 하나가 아닌 순서 있는 전체 자산 binding digest다.
기존 단일 파일 GGUFGenerator.load는 대체 seam으로만 우회하고 transport의 오류·응답 echo·EOS 검증은 유지한다. 3B도 새 runner에서 기존 요청 바이트·설정·template 경로와 일치하는 합성 회귀로 결속한다.
worker_lease·unused_port/wait_ready·DiscardDrain·owned_create_time/cleanup_owner·Evidence·경로/hash 검증·make_resource_guard(RSS6_RESOURCES)를 재사용하고, launcher의 단일 자원 gate·guard 양쪽 지점·callback·실패 latch를 보존한다.
취득 후 bounded GGUF KV reader는 metadata만 최대32MiB까지 읽고 tensor payload를 해석하지 않는다. template 원문 SHA 및 tokenizer KV 목록/타입/값 digest·split.no/count를 receipt에 남겨 별도 검토 후 실행 등록에 고정한다.
내장 metadata가 예상과 다르거나 상한을 넘으면 중단한다. 관측값을 자동 승인하거나 임의 template/tokenizer를 주입하지 않으며, hash 통과와 실제 tokenization 적합성을 구분한다.

## 새6개와 누출 방지
자료 작성은 코드·독립 검토·정확 CI 뒤 다른 역할이 맡는다. 새 source-family6개, 답변 가능4/보류2(근거 부족·미해결 충돌)를 출력 전에 잠그고 단일 일반 문서·복수 회의·혼합 문서, 한국어/영어/혼합 원문을 포함한다.
짧고 쉬운 문제만 고르거나256에 맞춰 요구 사실을 줄이지 않는다. 기존 한국어 응답 지침은 유지하되 영어 응답·전체 제품 범위를 검증했다고 하지 않는다.
새 private/qa-paired-dev-v1 아래 정확6case manifest와 공개 가능한 opaque family/문서 revision·content/question hash/역할 노출 metadata를 분리한다. 질문·기준·출력 의미 본문은 부모/구현자가 읽지 않는다.
기존 custody 담당자가 기존 manifest의 식별자/해시/lineage만으로 제외 index를 봉인한다. C1–C5/M5/v4–v7·기존 질문/validation·예약/제외 가족·protected/finaltest의 가족·파생 revision을 모두 포함하고 누락 catalog는 진입 거부한다.
validator는 검토자가 고정한 index SHA와 신규 허용6개 목록을 사용하며 등록자가 제공한 임의 denylist를 신뢰하지 않는다. case/question 중복·family/alias/조상 중첩·내용/질문 digest 중첩·허용root 밖 경로·reparse/hardlink·추가 파일을 거부한다.
기계 hash는 변형 복사나 잘못 기입한 lineage를 모두 찾지 못한다. 새6개 사전 검토자가 provenance·범위·필수 내용 충분성을 별도 잠그고 노출을 기록하며, 보호 본문을 열어 대조하는 새 단계는 만들지 않는다.
각 case는 전체 원문·제목·문서 경계·순서·원본 document/revision/좌표와 unit ID 매핑을 사전 봉인한다. 복수 문서는 손실 없는 canonical bundle과 원문 좌표 sidecar를 고정하고 양 모델에 같은 compact 메시지 바이트를 준다.
삭제·요약·재정렬·ID 재선정은 금지한다. 기존 parser/ID 범위를 만족하지 못하면 사전 contract 실패로 남기고 문제를 쉽게 고치거나 기준을 낮추지 않는다.
criteria/필수 내용/보류 이유/packet 규칙은 별도 private lock에 둔다. executor는 요청에 필요한 자료만 읽고 judge만 봉인 기준·출력을 읽으며 부모는 해시·안전 집계만 수용한다.

## 등록·실행 순서와 고정 예산
새 comparison schema1은 exact key/type/중복key 거부, 두 허용 profile·shard·runtime55·code closure·내장 metadata·prompt/grammar/parser·입력/제외index/criteria/packet·순서·출력 경로·예산의 완전한 SHA 결속을 요구한다.
neutral1·baseline6·candidate6는 별도 불변 하위 등록/출력/once digest다. 공통 비교 계약과 선행 terminal/custody 참조가 다르면 native 전 거부하며 CLI/env 모델·cap·template override/fallback은 없다.
사전 pure verify는 import/help/검증만으로 네트워크·모델·tokenizer·자원 조회·등록 소비를 하지 않는다. metadata 취득/검토/실물 검증과 실행은 명시적 별도 단계다.
새 모델 neutral1은 사전 공개 합성 입력으로 공식 template 경로·tokenization·grammar·echo·EOS·시간/자원만 검사한다. 완전한 품질 증거나6개 예비 답변은 아니며 실패하면 품질 호출0으로 종료한다.
neutral 성공과 custody 완료 뒤, 사전 고정한 모델 블록/질문 순서로 각6개를1회 실행한다. 한 번에 한 모델만 적재하고 총 품질12·중립 포함13생성/요청 출력상한합3328토큰이다.
입력4096·QA256·요청60초·ctx6144·parallel1·GPU99·f16KV·fit off·reasoning off·cache off·no context shift·GREEDY(seed0)·EOS 필수·수선/재시도0을 유지한다. 원본 generation_config의 sampling defaults는 가져오지 않는다.
모델별 입력 token 수가 다르므로 각 요청에서 확인하며 초과면 원문을 줄이지 않고 해당 조건의 거부로 분모에 남긴다. tokenization은 별도 품질 사전 탐색을 하지 않고 실제 요청60초 안에서 수행한다.
모델별 품질 epoch startup120/active900/cleanup5/whole1025초, neutral120/60/5/185초다. 전송 준비·tokenization·생성·파싱·필수 증거 저장은 요청60초를 공유하며 모든 단계는 남은 전체 시간보다 길어질 수 없다.
각 등록 fresh gate1회에서 available8GiB, 활성 available2GiB/native RSS6GiB를 동일 guard로 실제 집행한다. 이는 표본 STOP 기준이며 메모리 예약·OS hardcap·GPU 적합성 보장이 아니다.
시간·자원·자산·protocol·cleanup 실패는 STOP, 내용/형식 거부는 고정 분모6에 남기고 계속한다. quality6회/epoch 및 neutral1회는 dispatch 직전에 차감하고 응답 유실·프로세스 실패에도 되돌리지 않는다.
fresh gate 거부는 native0으로 보존하고 통과까지 재관측하지 않는다. 한 블록의 치명적 실패는 비교 전체를 중단하며 남은 항목은 미실행으로 남긴다.
컴파일/engine validator·다운로드·Java/브라우저 작업이 만든 부하와 QA gate/run/cleanup을 겹치지 않는다. 기존 프로세스를 끄지 않고 선행 작업 종료 후 별도 배정한다.

## 검증·판정·인계
합성 회귀는 legacy 요청 바이트, strict schema/불변 정책, shard누락·교체·혼합·추가·template mismatch, 제외index 우회/중복/lineage/경로, 원문·ID·Unicode 보존,6회/1회 cap, EOS/echo, deadline·RSS latch·초기 PID 신원실패 정리·once를 포함한다.
실제 PID/create_time/exe와 원래 Popen handle의 소유 범위만 정리하고 cleanup5초·부재·전후 자산/입력/code hash·원래 실패·late invalidation을 custody에 보존한다. 실패 receipt를 정상 완료로 재해석하지 않는다.
judge는 사전 packet 규칙대로 유효 출력 전부를 개별 잠근 뒤 모델 대응표/성능을 합친다. invalid/unexecuted도 분모에서 빼지 않으며 사전·자동 문맥 노출을 밝혀 완전 맹검/사람 검수로 부르지 않는다.
새 모델만6/6이면 후속 격리 평가 후보, 둘 다6/6이면3B 유지,3B만6/6이면 새 모델 탈락, 둘 다미달이면 비교 종료다. 같은6개 재튜닝·다음 모델 자동 탐색·서비스 채택은 없다.
아직 미확정인 내장 GGUF KV·실물 SHA·runtime55의 현재 재검증·실제 split 로딩/메모리/60초/품질·새6개 및 기준은 후속 배정의 진입 조건이다. 원본 변환 commit 미공개는 provenance 한계로 남긴다.
이번에는 새 문서·공식 작은 metadata·receipt만 작성했다. 가중치/실행파일 다운로드·native/tokenizer/모델·live 자원·테스트·Java·Git·기존 파일 수정·private 본문 읽기0이며, 부모 공개·수용 뒤 별도 구현/취득/실행 배정이 필요하다.
