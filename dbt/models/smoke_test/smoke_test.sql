-- One-row table that proves the dbt task can install packages, connect to the
-- SQL warehouse and write to Unity Catalog. dbt_utils is used on purpose, so the
-- run fails if `dbt deps` could not download the package.
select
    {{ dbt_utils.generate_surrogate_key(["'smoke_test'"]) }} as smoke_test_key,
    'ok' as status,
    current_timestamp() as created_at
