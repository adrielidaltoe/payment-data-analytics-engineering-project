-- One-time workspace setup, run by an admin before the first bundle deploy.
--
-- Free Edition uses Default Storage, and the catalogs API that Asset Bundles
-- call can't create catalogs there, so the two catalogs are created here.
-- Schemas and volumes inside them stay in resources/catalog.yml.
--
-- Principals are service principal application IDs:
--   06e3ba93-aa6c-4b9b-9e9f-f0b62bdf86f7  corvella-ci
--   fec3766d-e428-4609-957c-db98b1dfa9f6  corvella-deployer
--
-- Safe to run again: IF NOT EXISTS, and grants and owner changes are idempotent.

create catalog if not exists corvella_dev
comment 'Corvella Pay disputes analytics (dev)';

create catalog if not exists corvella_prod
comment 'Corvella Pay disputes analytics (prod)';

-- corvella-ci: CI runs dbt build in corvella_dev.
grant use catalog, use schema, create schema, create table, select, modify
on catalog corvella_dev
to `06e3ba93-aa6c-4b9b-9e9f-f0b62bdf86f7`;

-- Read access to prod for the admin running this script. It must come before
-- the owner change: workspace admins aren't metastore admins in Free Edition,
-- so after it only the new owner could grant access. Replace <admin user> with
-- your login email when running; never commit it.
grant use catalog, use schema, select
on catalog corvella_prod
to `<admin user>`;

-- corvella-deployer deploys prod and runs its jobs, so it owns corvella_prod.
alter catalog corvella_prod owner to `fec3766d-e428-4609-957c-db98b1dfa9f6`;
