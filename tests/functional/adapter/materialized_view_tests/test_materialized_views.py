from typing import Optional, Tuple

import pytest

from dbt.adapters.base.relation import BaseRelation

from dbt.tests.adapter.materialized_view.basic import MaterializedViewBasic
from dbt.tests.adapter.materialized_view.changes import (
    MaterializedViewChanges,
    MaterializedViewChangesApplyMixin,
    MaterializedViewChangesContinueMixin,
    MaterializedViewChangesFailMixin,
)
from dbt.tests.adapter.materialized_view.files import MY_TABLE, MY_VIEW
from dbt.tests.util import assert_message_in_logs, get_model_file, set_model_file

from tests.functional.adapter.materialized_view_tests.utils import (
    query_autorefresh,
    query_dist,
    query_relation_type,
    query_sort,
    run_dbt_and_capture_with_retries_redshift_mv,
)


MY_MATERIALIZED_VIEW = """
{{ config(
    materialized='materialized_view',
    sort_type='compound',
    sort=['id'],
    dist='id',
) }}
select * from {{ ref('my_seed') }}
"""


class TestRedshiftMaterializedViewsBasic(MaterializedViewBasic):
    @pytest.fixture(scope="class", autouse=True)
    def models(self):
        yield {
            "my_table.sql": MY_TABLE,
            "my_view.sql": MY_VIEW,
            "my_materialized_view.sql": MY_MATERIALIZED_VIEW,
        }

    @staticmethod
    def insert_record(project, table: BaseRelation, record: Tuple[int, int]):
        my_id, value = record
        project.run_sql(f"insert into {table} (id, value) values ({my_id}, {value})")

    @staticmethod
    def refresh_materialized_view(project, materialized_view: BaseRelation):
        sql = f"refresh materialized view {materialized_view}"
        project.run_sql(sql)

    @staticmethod
    def query_row_count(project, relation: BaseRelation) -> int:
        sql = f"select count(*) from {relation}"
        return project.run_sql(sql, fetch="one")[0]

    @staticmethod
    def query_relation_type(project, relation: BaseRelation) -> Optional[str]:
        return query_relation_type(project, relation)

    def test_materialized_view_create_idempotent(self, project, my_materialized_view):
        # setup creates it once; verify it's there and run once
        assert self.query_relation_type(project, my_materialized_view) == "materialized_view"
        run_dbt_and_capture_with_retries_redshift_mv(
            ["run", "--models", my_materialized_view.identifier]
        )
        assert self.query_relation_type(project, my_materialized_view) == "materialized_view"

    @pytest.mark.skip(
        "The current implementation does not support overwriting materialized views with tables."
    )
    def test_table_replaces_materialized_view(self, project, my_materialized_view):
        super().test_table_replaces_materialized_view(project, my_materialized_view)

    @pytest.mark.skip(
        "The current implementation does not support overwriting materialized views with views."
    )
    def test_view_replaces_materialized_view(self, project, my_materialized_view):
        super().test_view_replaces_materialized_view(project, my_materialized_view)


class RedshiftMaterializedViewChanges(MaterializedViewChanges):
    @pytest.fixture(scope="class", autouse=True)
    def models(self):
        yield {
            "my_table.sql": MY_TABLE,
            "my_view.sql": MY_VIEW,
            "my_materialized_view.sql": MY_MATERIALIZED_VIEW,
        }

    @staticmethod
    def query_relation_type(project, relation: BaseRelation) -> Optional[str]:
        return query_relation_type(project, relation)

    @staticmethod
    def check_start_state(project, materialized_view):
        assert query_autorefresh(project, materialized_view) is False
        assert query_sort(project, materialized_view) == "id"
        assert query_dist(project, materialized_view) == "KEY(id)"

    @staticmethod
    def change_config_via_alter(project, materialized_view):
        initial_model = get_model_file(project, materialized_view)
        new_model = initial_model.replace("dist='id',", "dist='id', auto_refresh=True")
        set_model_file(project, materialized_view, new_model)

    @staticmethod
    def change_config_via_alter_str_true(project, materialized_view):
        initial_model = get_model_file(project, materialized_view)
        new_model = initial_model.replace("dist='id',", "dist='id', auto_refresh='true'")
        set_model_file(project, materialized_view, new_model)

    @staticmethod
    def change_config_via_alter_str_false(project, materialized_view):
        initial_model = get_model_file(project, materialized_view)
        new_model = initial_model.replace("dist='id',", "dist='id', auto_refresh='False'")
        set_model_file(project, materialized_view, new_model)

    @staticmethod
    def check_state_alter_change_is_applied(project, materialized_view):
        assert query_autorefresh(project, materialized_view) is True

    @staticmethod
    def check_state_alter_change_is_applied_str_false(project, materialized_view):
        assert query_autorefresh(project, materialized_view) is False

    @staticmethod
    def change_config_via_replace(project, materialized_view):
        initial_model = get_model_file(project, materialized_view)
        new_model = initial_model.replace("dist='id',", "").replace(
            "sort=['id']", "sort=['value']"
        )
        set_model_file(project, materialized_view, new_model)

    @staticmethod
    def check_state_replace_change_is_applied(project, materialized_view):
        assert query_sort(project, materialized_view) == "value"
        assert query_dist(project, materialized_view) == "EVEN"


class TestRedshiftMaterializedViewChangesApply(
    RedshiftMaterializedViewChanges, MaterializedViewChangesApplyMixin
):
    def test_change_is_applied_via_alter(self, project, my_materialized_view):
        self.check_start_state(project, my_materialized_view)

        self.change_config_via_alter(project, my_materialized_view)
        _, logs = run_dbt_and_capture_with_retries_redshift_mv(
            ["--debug", "run", "--models", my_materialized_view.name]
        )

        self.check_state_alter_change_is_applied(project, my_materialized_view)

        assert_message_in_logs(f"Applying ALTER to: {my_materialized_view}", logs)
        assert_message_in_logs(f"Applying REPLACE to: {my_materialized_view}", logs, False)

    def test_change_is_applied_via_alter_str_true(self, project, my_materialized_view):
        self.check_start_state(project, my_materialized_view)

        self.change_config_via_alter_str_true(project, my_materialized_view)
        _, logs = run_dbt_and_capture_with_retries_redshift_mv(
            ["--debug", "run", "--models", my_materialized_view.name]
        )

        self.check_state_alter_change_is_applied(project, my_materialized_view)

        assert_message_in_logs(f"Applying ALTER to: {my_materialized_view}", logs)
        assert_message_in_logs(f"Applying REPLACE to: {my_materialized_view}", logs, False)

    def test_change_is_applied_via_alter_str_false(self, project, my_materialized_view):
        self.check_start_state(project, my_materialized_view)

        self.change_config_via_alter_str_false(project, my_materialized_view)
        _, logs = run_dbt_and_capture_with_retries_redshift_mv(
            ["--debug", "run", "--models", my_materialized_view.name]
        )

        self.check_state_alter_change_is_applied_str_false(project, my_materialized_view)

        assert_message_in_logs(f"Applying ALTER to: {my_materialized_view}", logs)
        assert_message_in_logs(f"Applying REPLACE to: {my_materialized_view}", logs, False)

    def test_change_is_applied_via_replace(self, project, my_materialized_view):
        self.check_start_state(project, my_materialized_view)

        self.change_config_via_alter(project, my_materialized_view)
        self.change_config_via_replace(project, my_materialized_view)
        _, logs = run_dbt_and_capture_with_retries_redshift_mv(
            ["--debug", "run", "--models", my_materialized_view.name]
        )

        self.check_state_alter_change_is_applied(project, my_materialized_view)
        self.check_state_replace_change_is_applied(project, my_materialized_view)

        assert_message_in_logs(f"Applying REPLACE to: {my_materialized_view}", logs)


class TestRedshiftMaterializedViewChangesContinue(
    RedshiftMaterializedViewChanges, MaterializedViewChangesContinueMixin
):
    def test_change_is_not_applied_via_alter(self, project, my_materialized_view):
        self.check_start_state(project, my_materialized_view)

        self.change_config_via_alter(project, my_materialized_view)
        _, logs = run_dbt_and_capture_with_retries_redshift_mv(
            ["--debug", "run", "--models", my_materialized_view.name]
        )

        self.check_start_state(project, my_materialized_view)

        assert_message_in_logs(
            f"Configuration changes were identified and `on_configuration_change` was set"
            f" to `continue` for `{my_materialized_view}`",
            logs,
        )
        assert_message_in_logs(f"Applying ALTER to: {my_materialized_view}", logs, False)
        assert_message_in_logs(f"Applying REPLACE to: {my_materialized_view}", logs, False)

    def test_change_is_not_applied_via_replace(self, project, my_materialized_view):
        self.check_start_state(project, my_materialized_view)

        self.change_config_via_alter(project, my_materialized_view)
        self.change_config_via_replace(project, my_materialized_view)
        _, logs = run_dbt_and_capture_with_retries_redshift_mv(
            ["--debug", "run", "--models", my_materialized_view.name]
        )

        self.check_start_state(project, my_materialized_view)

        assert_message_in_logs(
            f"Configuration changes were identified and `on_configuration_change` was set"
            f" to `continue` for `{my_materialized_view}`",
            logs,
        )
        assert_message_in_logs(f"Applying ALTER to: {my_materialized_view}", logs, False)
        assert_message_in_logs(f"Applying REPLACE to: {my_materialized_view}", logs, False)


class TestRedshiftMaterializedViewChangesFail(
    RedshiftMaterializedViewChanges, MaterializedViewChangesFailMixin
):
    # Note: using retries doesn't work when we expect `dbt_run` to fail
    pass
