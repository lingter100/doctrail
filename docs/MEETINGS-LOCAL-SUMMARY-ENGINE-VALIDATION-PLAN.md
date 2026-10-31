# 요약 경계 문법의 고정 엔진 검증 준비
2026-10-27 · 설계만 · 다운로드·빌드·엔진 실행·제품 채택 0

현재 순수 검사 106개와 배분 경계 288,956건의 통과는 생성된 GBNF 실행 증거가 아니다.
목표는 기존 허용 언어를 줄이지 않고, 같은 문법을 고정 llama.cpp가 해석·수용하는지 모델 없이 확인하는 것이다.
기준은 [공개 결과](MEETINGS-LOCAL-SUMMARY-BOUNDARY-RESULTS.md)와 [집계](../experiments/results/meetings-local-summary-boundary-feasibility-v1.json)이며, 최초 실패와 수정본은 보존한다.

선택: 프로젝트 전용 휴대형 C++ 도구로 공식 소스를 정적 빌드하고, 작은 독립 검사 프로그램을 연결한다.
부모의 PATH 조회와 이번 알려진 VS Installer·설치 레지스트리·CMake·LLVM·MSYS2 위치 조회에서 도구를 찾지 못했다. 시스템 전체 부재를 뜻하지 않는다.
준비된 b11429 배포물에는 해당 검증기가 없다. 기다리기만으로 검증이 진행되지 않으며, 다른 엔진·정규식 검사를 대신 채택하지 않는다.
전역 Visual Studio 설치나 유료·클라우드 빌드는 선택하지 않는다. 아래 준비도 별도 배정 전에는 실행하지 않는다.

도구는 [LLVM-MinGW 20250709 UCRT x86_64](https://github.com/mstorsjo/llvm-mingw/releases/tag/20250709), [CMake 3.31.8 Windows x86_64 zip](https://github.com/Kitware/CMake/releases/tag/v3.31.8), [Ninja 1.12.1 ninja-win.zip](https://github.com/ninja-build/ninja/releases/tag/v1.12.1)으로 고정한다.
앞의 두 배포 SHA-256은 설계 receipt에 기록했다. Ninja 실제 바이트 해시는 아직 없으며, 향후 취득 후 실행 전에 manifest를 고정·검토한다.
엔진은 공식 commit d81235049384534c167caea52b85a694f6103d14의 CMakeLists.txt·LICENSE·cmake/include/src/ggml/vendor 소스만 고정 tree/blob manifest로 취득한다. 모델/어휘 payload는 제외하고 각 URL·blob ID·SHA-256·도구 버전·라이선스·빌드 로그·실행 파일 해시를 묶는다.
새 소유 폴더 안에서만 압축을 풀고 경로 이탈·재분석 지점을 거부한다. 영구 PATH·레지스트리 변경이나 GGUF·어휘 자산 취득·로드는 하지 않는다.
다운로드 합계 512 MiB, 압축·소스·도구·빌드 합계 4 GiB, 준비 10분·configure/build 15분, 빌드 병렬 2를 새 준비 예산으로 제안한다. 크기·속도 예측이 아니다.
준비/빌드 소유 프로세스 합산 RSS 예산 2 GiB + 호스트 여유 2 GiB로 시작 조건 4 GiB를 둔다. 초과·관측 실패는 중단하고 자동 증액하지 않는다.
이 준비 한도는 모델 실행의 RSS 6/start 8/host 2 GiB 정책과 별개다. QA v7의 새 자원 확인·한 번 실행·정리와 빌드/검증을 겹치지 않는다.

작은 CMake 상위 프로젝트에서 고정 소스를 add_subdirectory하고, CPU 정적 llama와 검사 프로그램 한 target만 빌드한다.
common/tests/tools/examples/server/app/UI 및 GPU·외부 backend·OpenMP·OpenSSL·llguidance·ccache·native CPU 튜닝은 끈다. 전체 ctest나 모델 테스트는 실행하지 않는다.
[공식 CMake](https://github.com/ggml-org/llama.cpp/blob/d81235049384534c167caea52b85a694f6103d14/CMakeLists.txt)의 archive 빌드는 상위 저장소 Git 정보를 오인할 수 있다. standalone 경로를 피하고 Git 발견을 끈다.
구체적으로 CMAKE_DISABLE_FIND_PACKAGE_Git=TRUE, GIT_EXECUTABLE/GIT_EXE를 빈 cache 값으로 고정하고 build commit/number는 명시한다. configure trace에 Git/추가 다운로드/비대상 실행이 있으면 실패다.
이는 정적 준비안이며 이 도구 조합의 configure·link 성공은 미검증이다. 수정이 필요하면 원본·오류를 보존하고 별도 검토하며 엔진 소스를 임의 변경하지 않는다.

문법은 e744497da34d0af79e2cc0419de0241d093136ec84b62a51bad905b982f8e290, corpus는 722fd6f6ac6ac5c2a39c7ab23efcdc32a79dc8776df638b0a99c28a8c43c65cb로 고정한다.
910,051바이트·명시 규칙 1,452개·분기 구분자 58,325개를 그대로 사용한다. 원래 2 MiB/20,000규칙 한도와 예상값을 유지하고 실제 확장 규칙 수도 기록한다.
[공식 검증기](https://github.com/ggml-org/llama.cpp/blob/d81235049384534c167caea52b85a694f6103d14/tests/test-gbnf-validator.cpp)는 vocab=nullptr로 초기화하지만 정상/비정상 문자열 모두 exit 0이다. 종료 코드만으로 통과시키지 않는다.
새 검사 프로그램은 같은 init/Unicode 변환/accept/get_stacks 경로를 사용하고, 초기 상태를 한 번 만든 뒤 공식 clone/free로 사례별 상태를 분리한다. 토큰·모델 API는 호출하지 않는다.
초기화 실패·예외·중단·프로토콜 오류는 검사 실패다. 유효 문자열은 입력 소진 후 빈 stack 존재, 거부는 살아 있는 stack 없음으로 구분한다.
빈 stack 없이 살아 있는 상태는 미완결 prefix다. 고정 prefix 10개는 이 상태와, 결과를 보기 전에 고정한 기존 corpus 완결 witness까지 이어 수용됨을 모두 확인한다.
각 사례의 complete/prefix 예상값과 실제 세 가지 판정을 비교한다. 예상 밖 prefix도 통과로 바꾸지 않는다. 기존 parser 예상값과 문법 예상값의 알려진 차이는 합치지 않는다.
전체 106개 manifest를 유지한다. raw-surrogate 1개는 UTF-8 strict encoding에서 거부되어 native 검사 대상이 될 수 없으므로 carrier rejection 1/native 최대 105로 별도 집계한다.
그 문자를 escape로 고치거나 surrogatepass로 전송하지 않는다. ASCII JSON escape로 표현된 단독 surrogate·정상 pair 사례는 원래 바이트 그대로 엔진에 전달한다.
입력 파일은 binary로 읽고 해시를 대조한다. Unicode 정규화·CRLF 치환·JSON 재직렬화 없이 literal/escape/pair/비BMP/결합 문자와 escape 중간 prefix를 비교한다.
JSON 해석 후 코드포인트 수, JSON 표기 문자 수, UTF-8 바이트 수, 모델 토큰 수를 구분한다. 문법 검증은 토큰 수·단어 의미·문장 충분성을 증명하지 않는다.

실행 배치는 기존 60초를 초기화·clone·모든 사례·witness·정리에 공유하고 마지막 5초를 소유 정리에 남긴다. 사례마다 시간을 새로 주지 않는다.
validator 프로세스 트리 합산 sampled RSS 512 MiB 이하와 호스트 available 2 GiB 이상을 감시한다. 시작 여유는 2.5 GiB 이상이며 준비/빌드 종료·부재를 먼저 확인한다.
910 KB라는 파일 크기나 순수 검사 0.109초로 엔진 속도를 추정하지 않는다. 초기화·확장 규칙 수·clone·최장 사례·전체 시간·관측 RSS 최고값을 분리 기록한다.
이 한도는 운영 중 관측·중단 예산이며 순간 peak를 놓치지 않는 OS hard limit 보장은 아니다. 측정 부재·초과·60초 만료·결과 누락도 실패로 보존한다.
해시/예상값 불일치·내부 규칙 20,000 초과·Unicode 분류 차이·crash·메모리 증가 시 중단한다. 한도 상향·사례 삭제·문법 축소·성공까지 재시도하지 않는다.
실행 PID·생성 시각·실행 파일 경로로 소유를 확인하고 해당 하위 프로세스만 정리한다. 다른 앱 종료나 시스템 설정 변경은 하지 않는다.
실패 로그·부분 집계·종료/부재 확인을 남긴다. 정리 실패면 QA 자원 확인을 시작하지 않고 부모가 상태를 해소하도록 반환한다.

향후 공개 재현 묶음에는 동일 grammar/corpus, 고정 expected manifest, prefix witness binding, 작은 harness/controller/guard, CMake 설정과 명령, 도구·소스·결과 해시 및 라이선스를 넣는다.
기존 feasibility.py의 freeze는 Git과 .local baseline에 의존하므로 그대로 공개 실행 명령으로 내놓지 않는다. 고정 합성 입력을 복사하고 기존 순수 결과와 native 결과를 분리한다.
공개 실행 절차는 숨은 .local 파일·사설 원문·질문·판정 기준·사용자 절대 경로 없이 재현되어야 한다. binaries/toolchain은 공개 저장소에 함께 넣지 않는다.
순서는 QA 실제 실행과 정리 종료 → 별도 준비 구현·검토/출판 → 제한된 취득·빌드 → 해시 고정 → 독립 소스 검토 → 별도 엔진 검사 배정이다.
이번 산출물은 그 준비 설계만이다. 현재 제품 코드·동결 parser·원래 240/1200자·claims 1–6·근거·768/128/256토큰·시간/자원/의미 기준·소모된 v6는 그대로 보존한다.
엔진 검증이 통과해도 모든 문자열 동치, 실제 sampler의 토큰 처리 비용, 리뷰 가능성, 768토큰 내 완결, 충분한 한국어 요약이나 QA 품질은 별도 미검증이다.
