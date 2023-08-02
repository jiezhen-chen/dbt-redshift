{% macro redshift__get_relations() -%}

{%- call statement('relations', fetch_result=True) -%}

select view_schema as dependent_schema,
       view_name as dependent_name,
       table_schema as referenced_schema,
       table_name as referenced_name
       from information_schema.view_table_usage

{%- endcall -%}

{{ return(load_result('relations').table) }}

{% endmacro %}
