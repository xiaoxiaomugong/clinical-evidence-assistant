-- These tables are backend-only. Explicit deny policies make that intent
-- visible to reviewers and the Security Advisor in addition to table grants.
create policy source_catalog_deny_public
on public.source_catalog
as restrictive
for all
to anon, authenticated
using (false)
with check (false);

create policy ingestion_runs_deny_public
on public.ingestion_runs
as restrictive
for all
to anon, authenticated
using (false)
with check (false);
