export class ApiError extends Error {
  constructor(public status: number, public code: string, public requestId?: string) { super(code); }
}

export function errorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return '서버에 연결하지 못했어요. 연결 상태를 확인한 뒤 다시 시도해 주세요.';
  const code = error.code.toLowerCase();
  if (error.status === 401) return '이메일 또는 비밀번호를 확인해 주세요. 세션이 만료되었다면 다시 로그인해 주세요.';
  if (error.status === 403) return '이 작업에 대한 권한이 없어요.';
  if (code.includes('member') || code.includes('user_not_found')) return '먼저 가입한 사용자의 이메일을 입력해 주세요.';
  if (error.status === 404) return '문서를 찾을 수 없거나 접근 권한이 변경되었어요.';
  if (code === 'search_context_changed') return '검색 중 문서나 접근 권한이 변경되었어요. 다시 검색해 주세요.';
  if (code === 'embedding_profile_changed') return '연결된 모델이 변경되었어요. 현재 모델을 확인한 뒤 새로 검색해 주세요.';
  if (code === 'visible_corpus_too_large') return '현재 모델 검색에서 처리할 수 있는 문서 분량을 넘었어요. 키워드 검색을 선택해 주세요.';
  if (code === 'query_too_long') return '모델이 처리할 수 있도록 검색어를 조금 줄여 주세요.';
  if (code === 'inference_timeout') return '모델 검색 시간이 초과됐어요. 잠시 후 다시 검색하거나 키워드 검색을 선택해 주세요.';
  if (code.startsWith('inference_') || code === 'model_busy') return '모델 검색을 사용할 수 없어요. 잠시 후 다시 시도하거나 키워드 검색을 선택해 주세요.';
  if (error.status === 409) return '이미 등록된 정보예요. 이메일과 현재 상태를 확인해 주세요.';
  if (error.status === 413 || code.includes('size') || code.includes('large')) return '파일은 5MB 이하로 올려 주세요.';
  if (error.status === 422 || error.status === 400) return '입력 내용을 확인해 주세요. UTF-8 TXT·MD 또는 텍스트 PDF를 지원해요.';
  return `요청을 완료하지 못했어요. 잠시 후 다시 시도해 주세요.${error.requestId ? ` (요청 ${error.requestId})` : ''}`;
}

// Session ownership stays on the server. The React controller decides whether an
// error still belongs to the active session before acting on it.
export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  const response = await fetch(`/api${path}`, { ...options, headers, credentials: 'include' });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(response.status, typeof body?.detail === 'string' ? body.detail : 'invalid_request', response.headers.get('x-request-id') || undefined);
  }
  return response.status === 204 ? undefined as T : response.json();
}
