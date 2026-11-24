{#
    Use a model's custom schema as-is (for example `silver`), instead of
    dbt's default `<target schema>_<custom schema>`. The catalog already
    separates the environments (corvella_dev, corvella_prod), so the schema
    names stay the same in both: landing, bronze, silver and gold.
    Models without a custom schema keep the target schema.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
