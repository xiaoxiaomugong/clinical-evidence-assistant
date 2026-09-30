export type Audience = 'public' | 'professional';
export type Pico = Partial<Record<'population' | 'intervention' | 'comparison' | 'outcome', string>>;
export interface QueryRequest { question: string; audience: Audience; pico?: Pico }
export interface Corpus { version: string; updated_at: string | null }
export interface Source {
  id: number;
  title: string;
  url: string | null;
  year: number | null;
  source_type: string;
  study_type: string | null;
  evidence_level: string | null;
  publication_status: string | null;
  identifiers: Record<string, string>;
  excerpt: string;
}
export interface QueryResponse {
  request_id: string;
  audience: Audience;
  status: 'answered' | 'refused' | 'error';
  degraded: boolean;
  generation_method: 'extractive' | 'llm' | 'none';
  message: string | null;
  answer: {
    summary: string;
    claims: { text: string; citations: number[] }[];
    limitations: string[];
    disclaimer: string;
  } | null;
  sources: Source[];
  corpus: Corpus;
  online_search: boolean;
}
export interface Topic {
  id: string;
  title: string;
  summary: string;
  updated_at: string | null;
  review_status: string;
  reviewer: string | null;
  version: string;
  scope: string[];
}
export interface TopicDetail extends Topic {
  content: string[];
  references: { title: string; url: string | null; identifier: string | null }[];
}
export interface TopicsResponse { topics: Topic[]; corpus: Corpus }
