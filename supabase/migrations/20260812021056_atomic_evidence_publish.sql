-- Stage each source snapshot in backend-only tables, then replace the public
-- source atomically.  Batched HTTP uploads never touch searchable rows.

create table public.evidence_document_staging (
    run_id uuid not null references public.ingestion_runs(id) on delete cascade,
    id text not null,
    payload jsonb not null
        check (jsonb_typeof(payload) = 'object'),
    created_at timestamptz not null default now(),
    primary key (run_id, id),
    check (length(btrim(id)) > 0),
    check (payload ->> 'id' = id)
);

create table public.evidence_chunk_staging (
    run_id uuid not null references public.ingestion_runs(id) on delete cascade,
    id text not null,
    payload jsonb not null
        check (jsonb_typeof(payload) = 'object'),
    created_at timestamptz not null default now(),
    primary key (run_id, id),
    check (length(btrim(id)) > 0),
    check (payload ->> 'id' = id)
);

create index evidence_document_staging_created_idx
    on public.evidence_document_staging (created_at);

create index evidence_chunk_staging_created_idx
    on public.evidence_chunk_staging (created_at);

alter table public.evidence_document_staging enable row level security;
alter table public.evidence_chunk_staging enable row level security;

revoke all on table public.evidence_document_staging
    from public, anon, authenticated;
revoke all on table public.evidence_chunk_staging
    from public, anon, authenticated;

grant select, insert, update, delete on table public.evidence_document_staging
    to service_role;
grant select, insert, update, delete on table public.evidence_chunk_staging
    to service_role;

-- The invoker needs DELETE only so this function can remove chunks that are no
-- longer present in the staged source snapshot. Public roles retain no writes.
grant delete on table public.evidence_chunks to service_role;

create or replace function public.publish_evidence_ingestion(p_run_id uuid)
returns jsonb
language plpgsql
security invoker
set search_path = pg_catalog, public
as $$
declare
    v_source_id text;
    v_started_at timestamptz;
    v_document_count integer;
    v_chunk_count integer;
begin
    select run.source_id, run.started_at
      into v_source_id, v_started_at
      from public.ingestion_runs as run
     where run.id = p_run_id
       and run.status = 'running'
       for update;

    if not found then
        raise exception 'ingestion run % does not exist or is not running', p_run_id;
    end if;

    -- Serialize publication for a source and reject an older run that finishes
    -- after a newer successful snapshot.
    perform 1
      from public.source_catalog as source
     where source.id = v_source_id
     for update;

    if exists (
        select 1
          from public.ingestion_runs as newer
         where newer.source_id = v_source_id
           and newer.status = 'succeeded'
           and newer.started_at > v_started_at
    ) then
        raise exception 'ingestion run % was superseded by a newer successful run', p_run_id;
    end if;

    if exists (
        select 1
          from public.evidence_document_staging as stage
         where stage.run_id = p_run_id
           and stage.payload ->> 'source_id' is distinct from v_source_id
    ) then
        raise exception 'staged document source does not match ingestion source %', v_source_id;
    end if;

    if exists (
        select 1
          from public.evidence_chunk_staging as chunk_stage
         where chunk_stage.run_id = p_run_id
           and not exists (
               select 1
                 from public.evidence_document_staging as document_stage
                where document_stage.run_id = p_run_id
                  and document_stage.id = chunk_stage.payload ->> 'document_id'
           )
    ) then
        raise exception 'every staged chunk must reference a document in the same run';
    end if;

    select count(*)::integer
      into v_document_count
      from public.evidence_document_staging
     where run_id = p_run_id;

    select count(*)::integer
      into v_chunk_count
      from public.evidence_chunk_staging
     where run_id = p_run_id;

    insert into public.evidence_documents (
        id,
        source_id,
        source_record_id,
        pmid,
        doi,
        nct_id,
        title,
        abstract,
        journal,
        published_year,
        authors,
        publication_types,
        study_type,
        status,
        evidence_level,
        url,
        topic,
        retrieved_at,
        source_updated_at,
        content_hash,
        rights_basis,
        metadata,
        is_active
    )
    select
        staged.id,
        staged.source_id,
        staged.source_record_id,
        staged.pmid,
        staged.doi,
        staged.nct_id,
        staged.title,
        staged.abstract,
        staged.journal,
        staged.published_year,
        staged.authors,
        staged.publication_types,
        staged.study_type,
        staged.status,
        staged.evidence_level,
        staged.url,
        staged.topic,
        staged.retrieved_at,
        staged.source_updated_at,
        staged.content_hash,
        staged.rights_basis,
        staged.metadata,
        true
      from public.evidence_document_staging as stage
      cross join lateral jsonb_populate_record(
          null::public.evidence_documents,
          stage.payload
      ) as staged
     where stage.run_id = p_run_id
    on conflict (id) do update set
        source_id = excluded.source_id,
        source_record_id = excluded.source_record_id,
        pmid = excluded.pmid,
        doi = excluded.doi,
        nct_id = excluded.nct_id,
        title = excluded.title,
        abstract = excluded.abstract,
        journal = excluded.journal,
        published_year = excluded.published_year,
        authors = excluded.authors,
        publication_types = excluded.publication_types,
        study_type = excluded.study_type,
        status = excluded.status,
        evidence_level = excluded.evidence_level,
        url = excluded.url,
        topic = excluded.topic,
        retrieved_at = excluded.retrieved_at,
        source_updated_at = excluded.source_updated_at,
        content_hash = excluded.content_hash,
        rights_basis = excluded.rights_basis,
        metadata = excluded.metadata,
        is_active = true;

    update public.evidence_documents as document
       set is_active = false
     where document.source_id = v_source_id
       and not exists (
           select 1
             from public.evidence_document_staging as stage
            where stage.run_id = p_run_id
              and stage.id = document.id
       );

    delete from public.evidence_chunks as chunk
    using public.evidence_documents as document
     where chunk.document_id = document.id
       and document.source_id = v_source_id
       and not exists (
           select 1
             from public.evidence_chunk_staging as stage
            where stage.run_id = p_run_id
              and stage.id = chunk.id
       );

    insert into public.evidence_chunks (
        id,
        document_id,
        content_kind,
        page_number,
        ordinal,
        text,
        content_hash,
        metadata
    )
    select
        staged.id,
        staged.document_id,
        staged.content_kind,
        staged.page_number,
        staged.ordinal,
        staged.text,
        staged.content_hash,
        staged.metadata
      from public.evidence_chunk_staging as stage
      cross join lateral jsonb_populate_record(
          null::public.evidence_chunks,
          stage.payload
      ) as staged
     where stage.run_id = p_run_id
    on conflict (id) do update set
        document_id = excluded.document_id,
        content_kind = excluded.content_kind,
        page_number = excluded.page_number,
        ordinal = excluded.ordinal,
        text = excluded.text,
        content_hash = excluded.content_hash,
        metadata = excluded.metadata;

    update public.source_catalog
       set last_synced_at = now()
     where id = v_source_id;

    update public.ingestion_runs
       set status = 'succeeded',
           completed_at = now(),
           records_seen = v_document_count,
           records_upserted = v_document_count,
           chunks_upserted = v_chunk_count,
           records_failed = 0,
           error_message = null
     where id = p_run_id;

    delete from public.evidence_chunk_staging where run_id = p_run_id;
    delete from public.evidence_document_staging where run_id = p_run_id;

    return jsonb_build_object(
        'source_id', v_source_id,
        'documents', v_document_count,
        'chunks', v_chunk_count
    );
end;
$$;

create or replace function public.abort_evidence_ingestion(
    p_run_id uuid,
    p_error_message text default null
)
returns boolean
language plpgsql
security invoker
set search_path = pg_catalog, public
as $$
begin
    perform 1
      from public.ingestion_runs
     where id = p_run_id
       and status = 'running'
     for update;

    if not found then
        return false;
    end if;

    delete from public.evidence_chunk_staging where run_id = p_run_id;
    delete from public.evidence_document_staging where run_id = p_run_id;

    update public.ingestion_runs
       set status = 'failed',
           completed_at = now(),
           records_failed = records_seen,
           error_message = left(p_error_message, 500)
     where id = p_run_id;

    return true;
end;
$$;

revoke all on function public.publish_evidence_ingestion(uuid)
    from public, anon, authenticated;
revoke all on function public.abort_evidence_ingestion(uuid, text)
    from public, anon, authenticated;

grant execute on function public.publish_evidence_ingestion(uuid)
    to service_role;
grant execute on function public.abort_evidence_ingestion(uuid, text)
    to service_role;
