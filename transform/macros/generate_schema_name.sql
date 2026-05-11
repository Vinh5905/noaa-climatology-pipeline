{% macro generate_schema_name(custom_schema_name, node) -%}
    {#
        Override dbt's default schema naming so that +schema overrides in
        dbt_project.yml are used AS-IS, without prepending the profile schema.
        This means staging models go to noaa_staging, marts to noaa_marts, etc.
    #}
    {%- if custom_schema_name is none -%}
        {{ default_schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
