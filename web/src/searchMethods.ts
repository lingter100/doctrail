import type { EmbeddingProfile, SearchMethod } from './types';

export function profileLabel(profile?: EmbeddingProfile | null): string {
  return profile?.id === 'base' ? '기본 모델' : profile?.id === 'm4-terminal-v1' ? '학습 실험 모델' : '모델 정보 없음';
}

export const searchMethods: Record<SearchMethod, { label: string; description: string }> = {
  bm25: { label: '키워드 검색', description: '문서에 쓰인 표현으로 찾아요 · BM25' },
  dense: { label: '의미 검색', description: '표현이 달라도 비슷한 의미를 찾아요 · E5' },
  hybrid: { label: '통합 검색', description: '키워드와 의미 검색 결과를 함께 살펴요' },
  hybrid_rerank: { label: '통합 검색 + 재정렬', description: '관련성을 다시 비교해 순서를 정해요 · E5 + BGE' },
};
