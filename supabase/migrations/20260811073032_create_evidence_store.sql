-- Cloud source-of-truth for public clinical evidence metadata and searchable text.
-- Raw PDF binaries are intentionally not stored here. Upload full-text chunks only
-- when the project has a documented right to process and redistribute that text.

create extension if not exists pgcrypto with schema extensions;

create table public.source_catalog (
    id text primary key,
    name text not null,
    source_type text not null
        check (source_type in ('api', 'snapshot', 'pdf_collection', 'curated')),
    base_url text,
    enabled boolean not null default true,
    refresh_interval interval,
    sync_cursor jsonb not null default '{}'::jsonb
        check (jsonb_typeof(sync_cursor) = 'object'),
    last_synced_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    check (length(btrim(id)) > 0),
    check (length(btrim(name)) > 0)
);

create table public.evidence_documents (
    id text primary key,
    source_id text not null references public.source_catalog(id),
    source_record_id text,
    pmid text,
    doi text,
    nct_id text,
    title text not null,
    abstract text not null default '',
    journal text,
    published_year smallint,
    authors text[] not null default array[]::text[],
    publication_types text[] not null default array[]::text[],
    study_type text,
    status text,
    evidence_level text not null default 'Other',
    url text not null default '',
    topic text not null default '',
    retrieved_at timestamptz not null default now(),
    source_updated_at timestamptz,
    content_hash text not null,
    rights_basis text,
    metadata jsonb not null default '{}'::jsonb
        check (jsonb_typeof(metadata) = 'object'),
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    search_vector tsvector generated always as (
        setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(abstract, '')), 'B') ||
        setweight(to_tsvector('simple', coalesce(topic, '')), 'C')
    ) stored,
    check (length(btrim(id)) > 0),
    check (length(btrim(source_id)) > 0),
    check (length(btrim(title)) > 0),
    check (published_year is null or published_year between 1500 and 2100),
    check (content_hash ~ '^[0-9a-f]{64}$')
);

create unique index evidence_documents_pmid_unique
    on public.evidence_documents (pmid)
    where pmid is not null and pmid <> '';

create unique index evidence_documents_doi_unique
    on public.evidence_documents (lower(doi))
    where doi is not null and doi <> '';

create unique index evidence_documents_nct_unique
    on public.evidence_documents (upper(nct_id))
    where nct_id is not null and nct_id <> '';

create index evidence_documents_source_active_idx
    on public.evidence_documents (source_id, is_active, updated_at desc);

create index evidence_documents_topic_year_idx
    on public.evidence_documents (topic, published_year desc)
    where is_active;

create index evidence_documents_search_idx
    on public.evidence_documents using gin (search_vector);

create table public.evidence_chunks (
    id text primary key,
    document_id text not null references public.evidence_documents(id) on delete cascade,
    content_kind text not null default 'abstract'
        check (content_kind in ('abstract', 'full_text', 'knowledge_claim')),
    page_number integer,
    ordinal integer not null default 1,
    text text not null,
    content_hash text not null,
    metadata jsonb not null default '{}'::jsonb
        check (jsonb_typeof(metadata) = 'object'),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    search_vector tsvector generated always as (
        to_tsvector('english', coalesce(text, ''))
    ) stored,
    check (length(btrim(id)) > 0),
    check (length(btrim(text)) > 0),
    check (page_number is null or page_number > 0),
    check (ordinal > 0),
    check (content_hash ~ '^[0-9a-f]{64}$')
);

create index evidence_chunks_document_idx
    on public.evidence_chunks (document_id, ordinal);

create index evidence_chunks_search_idx
    on public.evidence_chunks using gin (search_vector);

create table public.ingestion_runs (
    id uuid primary key default gen_random_uuid(),
    source_id text not null references public.source_catalog(id),
    status text not null default 'running'
        check (status in ('running', 'succeeded', 'partial', 'failed')),
    started_at timestamptz not null default now(),
    completed_at timestamptz,
    records_seen integer not null default 0 check (records_seen >= 0),
    records_upserted integer not null default 0 check (records_upserted >= 0),
    chunks_upserted integer not null default 0 check (chunks_upserted >= 0),
    records_failed integer not null default 0 check (records_failed >= 0),
    error_message text,
    metadata jsonb not null default '{}'::jsonb
        check (jsonb_typeof(metadata) = 'object'),
    created_at timestamptz not null default now(),
    check (completed_at is null or completed_at >= started_at)
);

create index ingestion_runs_source_started_idx
    on public.ingestion_runs (source_id, started_at desc);

create or replace function public.touch_updated_at()
returns trigger
language plpgsql
security invoker
set search_path = pg_catalog
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

create trigger source_catalog_touch_updated_at
before update on public.source_catalog
for each row execute function public.touch_updated_at();

create trigger evidence_documents_touch_updated_at
before update on public.evidence_documents
for each row execute function public.touch_updated_at();

create trigger evidence_chunks_touch_updated_at
before update on public.evidence_chunks
for each row execute function public.touch_updated_at();

create or replace function public.search_evidence_chunks(
    search_query text,
    result_limit integer default 20
)
returns table (
    id text,
    doc_id text,
    source text,
    title text,
    text text,
    evidence_level text,
    url text,
    journal text,
    year integer,
    study_type text,
    status text,
    topic text,
    page_number integer,
    retrieval_score real
)
language sql
stable
security invoker
set search_path = public, pg_temp
as $$
    with query as (
        select websearch_to_tsquery('english', coalesce(search_query, '')) as value
    )
    select
        chunk.id,
        document.id as doc_id,
        document.source_id as source,
        document.title,
        chunk.text,
        document.evidence_level,
        document.url,
        document.journal,
        document.published_year::integer as year,
        document.study_type,
        document.status,
        document.topic,
        chunk.page_number,
        ts_rank_cd(document.search_vector || chunk.search_vector, query.value)::real
            as retrieval_score
    from public.evidence_chunks as chunk
    join public.evidence_documents as document on document.id = chunk.document_id
    cross join query
    where length(btrim(coalesce(search_query, ''))) > 0
      and document.is_active
      and (
          document.search_vector @@ query.value
          or chunk.search_vector @@ query.value
      )
    order by retrieval_score desc, document.published_year desc nulls last, chunk.id
    limit least(greatest(coalesce(result_limit, 20), 1), 100);
$$;

insert into public.source_catalog (id, name, source_type, base_url, refresh_interval)
values
    ('pubmed', 'PubMed', 'api', 'https://eutils.ncbi.nlm.nih.gov', interval '1 day'),
    ('europepmc', 'Europe PMC', 'api', 'https://www.ebi.ac.uk/europepmc', interval '1 day'),
    ('clinicaltrials', 'ClinicalTrials.gov', 'api', 'https://clinicaltrials.gov', interval '1 day'),
    ('pubmed_snapshot', 'Curated PubMed snapshot', 'snapshot', null, null),
    ('pdf_collection', 'Licensed local PDF collection', 'pdf_collection', null, null),
    ('knowledge_page', 'Curated knowledge pages', 'curated', null, null)
on conflict (id) do nothing;

-- Exposed-schema tables are locked down explicitly. Evidence is public-read;
-- ingestion state and every write path remain backend-only.
alter table public.source_catalog enable row level security;
alter table public.evidence_documents enable row level security;
alter table public.evidence_chunks enable row level security;
alter table public.ingestion_runs enable row level security;

create policy evidence_documents_public_read
on public.evidence_documents
for select
to anon, authenticated
using (is_active);

create policy evidence_chunks_public_read
on public.evidence_chunks
for select
to anon, authenticated
using (
    exists (
        select 1
        from public.evidence_documents as document
        where document.id = evidence_chunks.document_id
          and document.is_active
    )
);

revoke all on table public.source_catalog from anon, authenticated;
revoke all on table public.evidence_documents from anon, authenticated;
revoke all on table public.evidence_chunks from anon, authenticated;
revoke all on table public.ingestion_runs from anon, authenticated;

grant usage on schema public to anon, authenticated, service_role;
grant select on table public.evidence_documents to anon, authenticated;
grant select on table public.evidence_chunks to anon, authenticated;

grant select, insert, update on table public.source_catalog to service_role;
grant select, insert, update on table public.evidence_documents to service_role;
grant select, insert, update on table public.evidence_chunks to service_role;
grant select, insert, update on table public.ingestion_runs to service_role;

revoke all on function public.touch_updated_at() from public, anon, authenticated;
revoke all on function public.search_evidence_chunks(text, integer) from public;
grant execute on function public.search_evidence_chunks(text, integer)
    to anon, authenticated, service_role;
