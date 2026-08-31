import type { ConceptDetailPayload, ConceptLeaderScoresPayload, SectorRotationPayload } from '~/types/sectors'

async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(path, { cache: 'no-store' })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error((err as { error?: string }).error || `HTTP ${res.status}`)
  }
  return res.json() as Promise<T>
}

export function useSectorsApi() {
  async function fetchRotation(days = 20, topN = 10, refresh = false) {
    const qs = new URLSearchParams({
      days: String(days),
      top_n: String(topN),
      ...(refresh ? { refresh: '1' } : {}),
    })
    return apiGet<SectorRotationPayload>(`/api/sectors/rotation?${qs}`)
  }

  async function fetchConceptDetail(name: string, months = 6, refresh = false) {
    const qs = new URLSearchParams({
      months: String(months),
      ...(refresh ? { refresh: '1' } : {}),
    })
    const encoded = encodeURIComponent(name)
    return apiGet<ConceptDetailPayload>(`/api/sectors/concept/${encoded}?${qs}`)
  }

  async function fetchConceptLeaderScores(
    name: string,
    start = '2025-01-01',
    refresh = false,
    topN = 5,
  ) {
    const qs = new URLSearchParams({
      start,
      top_n: String(topN),
      ...(refresh ? { refresh: '1' } : {}),
    })
    const encoded = encodeURIComponent(name)
    return apiGet<ConceptLeaderScoresPayload>(
      `/api/sectors/concept/${encoded}/leaders?${qs}`,
    )
  }

  return { fetchRotation, fetchConceptDetail, fetchConceptLeaderScores }
}
