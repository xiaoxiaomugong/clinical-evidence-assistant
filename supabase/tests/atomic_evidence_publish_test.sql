BEGIN;
SELECT plan(17);

SELECT is(
    has_table_privilege('anon', 'public.evidence_document_staging', 'SELECT'),
    false,
    'anonymous clients cannot read staged documents'
);

SELECT is(
    has_function_privilege('anon', 'public.publish_evidence_ingestion(uuid)', 'EXECUTE'),
    false,
    'anonymous clients cannot publish staged evidence'
);

SELECT is(
    has_function_privilege(
        'service_role',
        'public.publish_evidence_ingestion(uuid)',
        'EXECUTE'
    ),
    true,
    'the backend role can publish staged evidence'
);

INSERT INTO public.ingestion_runs (id, source_id)
VALUES ('00000000-0000-0000-0000-000000000001', 'pubmed_snapshot');

INSERT INTO public.evidence_document_staging (run_id, id, payload)
VALUES
    (
        '00000000-0000-0000-0000-000000000001',
        'test:atomic:1',
        jsonb_build_object(
            'id', 'test:atomic:1',
            'source_id', 'pubmed_snapshot',
            'source_record_id', 'atomic:1',
            'title', 'First staged document',
            'abstract', 'First abstract',
            'authors', jsonb_build_array('Researcher'),
            'publication_types', '[]'::jsonb,
            'evidence_level', 'RCT',
            'url', '',
            'topic', 'test',
            'retrieved_at', now(),
            'content_hash', repeat('a', 64),
            'metadata', '{}'::jsonb,
            'is_active', true
        )
    ),
    (
        '00000000-0000-0000-0000-000000000001',
        'test:atomic:2',
        jsonb_build_object(
            'id', 'test:atomic:2',
            'source_id', 'pubmed_snapshot',
            'source_record_id', 'atomic:2',
            'title', 'Document removed in the next snapshot',
            'abstract', 'Second abstract',
            'authors', '[]'::jsonb,
            'publication_types', '[]'::jsonb,
            'evidence_level', 'Other',
            'url', '',
            'topic', 'test',
            'retrieved_at', now(),
            'content_hash', repeat('b', 64),
            'metadata', '{}'::jsonb,
            'is_active', true
        )
    );

INSERT INTO public.evidence_chunk_staging (run_id, id, payload)
VALUES
    (
        '00000000-0000-0000-0000-000000000001',
        'test:atomic:1:pdf:p1:c1',
        jsonb_build_object(
            'id', 'test:atomic:1:pdf:p1:c1',
            'document_id', 'test:atomic:1',
            'content_kind', 'full_text',
            'page_number', 1,
            'ordinal', 1,
            'text', 'Licensed full text that must later disappear',
            'content_hash', repeat('c', 64),
            'metadata', '{}'::jsonb
        )
    ),
    (
        '00000000-0000-0000-0000-000000000001',
        'test:atomic:2:chunk:1',
        jsonb_build_object(
            'id', 'test:atomic:2:chunk:1',
            'document_id', 'test:atomic:2',
            'content_kind', 'abstract',
            'page_number', null,
            'ordinal', 1,
            'text', 'Second abstract chunk',
            'content_hash', repeat('d', 64),
            'metadata', '{}'::jsonb
        )
    );

SELECT lives_ok(
    $$SELECT public.publish_evidence_ingestion(
        '00000000-0000-0000-0000-000000000001'
    )$$,
    'the first source snapshot publishes'
);

SELECT is(
    (SELECT status FROM public.ingestion_runs
      WHERE id = '00000000-0000-0000-0000-000000000001'),
    'succeeded'::text,
    'publishing completes the ingestion run'
);

INSERT INTO public.ingestion_runs (id, source_id)
VALUES ('00000000-0000-0000-0000-000000000002', 'pubmed_snapshot');

INSERT INTO public.evidence_document_staging (run_id, id, payload)
VALUES (
    '00000000-0000-0000-0000-000000000002',
    'test:atomic:1',
    jsonb_build_object(
        'id', 'test:atomic:1',
        'source_id', 'pubmed_snapshot',
        'source_record_id', 'atomic:1',
        'title', 'First staged document, revised',
        'abstract', 'Abstract-only replacement',
        'authors', jsonb_build_array('Researcher'),
        'publication_types', '[]'::jsonb,
        'evidence_level', 'RCT',
        'url', '',
        'topic', 'test',
        'retrieved_at', now(),
        'content_hash', repeat('e', 64),
        'metadata', '{}'::jsonb,
        'is_active', true
    )
);

INSERT INTO public.evidence_chunk_staging (run_id, id, payload)
VALUES (
    '00000000-0000-0000-0000-000000000002',
    'test:atomic:1:chunk:1',
    jsonb_build_object(
        'id', 'test:atomic:1:chunk:1',
        'document_id', 'test:atomic:1',
        'content_kind', 'abstract',
        'page_number', null,
        'ordinal', 1,
        'text', 'Abstract-only replacement chunk',
        'content_hash', repeat('f', 64),
        'metadata', '{}'::jsonb
    )
);

SELECT lives_ok(
    $$SELECT public.publish_evidence_ingestion(
        '00000000-0000-0000-0000-000000000002'
    )$$,
    'a newer source snapshot publishes'
);

SELECT is(
    (SELECT count(*)::integer FROM public.evidence_documents
      WHERE source_id = 'pubmed_snapshot' AND is_active AND id LIKE 'test:atomic:%'),
    1,
    'documents omitted by the new snapshot are no longer active'
);

SELECT is(
    (SELECT is_active FROM public.evidence_documents WHERE id = 'test:atomic:2'),
    false,
    'the removed document is retained only as inactive audit history'
);

SELECT is(
    (SELECT count(*)::integer FROM public.evidence_chunks
      WHERE id = 'test:atomic:1:pdf:p1:c1'),
    0,
    'old full-text chunks are deleted when the replacement omits them'
);

SELECT is(
    (SELECT count(*)::integer FROM public.evidence_chunks
      WHERE document_id IN ('test:atomic:1', 'test:atomic:2')),
    1,
    'only chunks from the current source snapshot remain'
);

INSERT INTO public.ingestion_runs (id, source_id)
VALUES ('00000000-0000-0000-0000-000000000003', 'pubmed_snapshot');

INSERT INTO public.evidence_document_staging (run_id, id, payload)
VALUES (
    '00000000-0000-0000-0000-000000000003',
    'test:atomic:3',
    jsonb_build_object(
        'id', 'test:atomic:3',
        'source_id', 'pubmed_snapshot',
        'source_record_id', 'atomic:3',
        'title', 'Must roll back',
        'abstract', 'Must roll back',
        'authors', '[]'::jsonb,
        'publication_types', '[]'::jsonb,
        'evidence_level', 'Other',
        'url', '',
        'topic', 'test',
        'retrieved_at', now(),
        'content_hash', repeat('1', 64),
        'metadata', '{}'::jsonb,
        'is_active', true
    )
);

INSERT INTO public.evidence_chunk_staging (run_id, id, payload)
VALUES (
    '00000000-0000-0000-0000-000000000003',
    'test:atomic:3:chunk:1',
    jsonb_build_object(
        'id', 'test:atomic:3:chunk:1',
        'document_id', 'test:atomic:3',
        'content_kind', 'abstract',
        'page_number', null,
        'ordinal', 1,
        'text', 'Invalid chunk whose insert must roll back the whole publish',
        'content_hash', 'invalid',
        'metadata', '{}'::jsonb
    )
);

DO $$
BEGIN
    BEGIN
        PERFORM public.publish_evidence_ingestion(
            '00000000-0000-0000-0000-000000000003'
        );
        RAISE EXCEPTION 'expected evidence chunk constraint failure';
    EXCEPTION
        WHEN check_violation THEN NULL;
    END;
END;
$$;

SELECT is(
    (SELECT is_active FROM public.evidence_documents WHERE id = 'test:atomic:1'),
    true,
    'a failed publish does not deactivate the current document'
);

SELECT is(
    (SELECT count(*)::integer FROM public.evidence_documents
      WHERE id = 'test:atomic:3'),
    0,
    'a failed publish does not expose a partially inserted document'
);

SELECT is(
    (SELECT count(*)::integer FROM public.evidence_chunks
      WHERE id = 'test:atomic:1:chunk:1'),
    1,
    'a failed publish restores chunks deleted earlier in the transaction'
);

SELECT is(
    (SELECT status FROM public.ingestion_runs
      WHERE id = '00000000-0000-0000-0000-000000000003'),
    'running'::text,
    'the client may explicitly abort a failed publish run'
);

SELECT ok(
    public.abort_evidence_ingestion(
        '00000000-0000-0000-0000-000000000003',
        'constraint failure'
    ),
    'the failed run can be aborted'
);

SELECT is(
    (SELECT count(*)::integer FROM public.evidence_document_staging
      WHERE run_id = '00000000-0000-0000-0000-000000000003'),
    0,
    'aborting removes staged documents'
);

SELECT is(
    (SELECT status FROM public.ingestion_runs
      WHERE id = '00000000-0000-0000-0000-000000000003'),
    'failed'::text,
    'aborting records the failed ingestion status'
);

SELECT * FROM finish();
ROLLBACK;
