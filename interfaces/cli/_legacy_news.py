# pyright: reportUnsupportedDunderAll=false
from __future__ import annotations

from interfaces.cli.news import *  # noqa: F403
from interfaces.cli.news import __all__ as _news_all
from interfaces.cli.news import main
from interfaces.cli.commands import (
    api as _api_commands,
    approvals as _approval_commands,
    artifacts as _artifact_commands,
    dev as _dev_commands,
    diagnose as _diagnose_commands,
    entities as _entity_commands,
    mcp as _mcp_commands,
    memory as _memory_commands,
    reports as _report_commands,
    run as _run_commands,
    runs as _runs_commands,
    schedules as _schedule_commands,
    sources as _source_commands,
    storage as _storage_commands,
    subscriptions as _subscription_commands,
    tools as _tool_commands,
    workers as _worker_commands,
)


_run_test_no_llm = _dev_commands.run_test_no_llm
_run_test_agent_loop = _dev_commands.run_test_agent_loop
_run_live_smoke = _dev_commands.run_live_smoke

_run_daily = _run_commands.run_daily
_run_weekly = _run_commands.run_weekly

_latest_report = _report_commands.latest_report_from_cli
_reports_search = _report_commands.search_reports_from_cli
_reports_list = _report_commands.list_reports_from_cli
_reports_show = _report_commands.show_report_from_cli

_subscriptions_create = _subscription_commands.create_subscription_from_cli
_subscriptions_list = _subscription_commands.list_subscriptions_from_cli
_subscriptions_enable = _subscription_commands.enable_subscription_from_cli
_subscriptions_disable = _subscription_commands.disable_subscription_from_cli
_subscriptions_set_enabled = _subscription_commands.set_subscription_enabled_from_cli
_subscriptions_delete = _subscription_commands.delete_subscription_from_cli
_print_subscription = _subscription_commands.print_subscription

_entities_create = _entity_commands.create_entity_from_cli
_entities_list = _entity_commands.list_entities_from_cli
_entities_enable = _entity_commands.enable_entity_from_cli
_entities_disable = _entity_commands.disable_entity_from_cli
_entities_set_enabled = _entity_commands.set_entity_enabled_from_cli
_entities_delete = _entity_commands.delete_entity_from_cli
_entities_match_reports = _entity_commands.match_entity_reports_from_cli
_print_entity = _entity_commands.print_entity

_api_serve = _api_commands.serve_api
_api_openapi = _api_commands.export_openapi

_worker_enqueue_daily = _worker_commands.enqueue_daily
_worker_enqueue_memory_reindex = _worker_commands.enqueue_memory_reindex
_worker_enqueue_source_health = _worker_commands.enqueue_source_health
_worker_run_once = _worker_commands.run_once
_worker_run = _worker_commands.run_loop
_worker_heartbeat = _worker_commands.heartbeat
_worker_status = _worker_commands.status
_worker_queues = _worker_commands.queues

_schedules_list = _schedule_commands.list_schedules_from_cli
_schedules_add_daily = _schedule_commands.add_daily_schedule_from_cli
_schedules_tick = _schedule_commands.tick_schedules_from_cli
_schedules_run = _schedule_commands.run_schedules_from_cli
_schedules_trigger = _schedule_commands.trigger_schedule_from_cli

_approvals_list = _approval_commands.list_approvals
_approvals_submit = _approval_commands.submit_approval
_approvals_show = _approval_commands.show_approval
_approvals_resume_context = _approval_commands.resume_context
_approvals_resume_workflow = _approval_commands.resume_workflow
_approvals_approve = _approval_commands.approve
_approvals_reject = _approval_commands.reject
_approvals_modify = _approval_commands.modify
_approval_decision = _approval_commands.approval_decision
_print_approval_detail = _approval_commands.print_approval_detail

_memory_search = _memory_commands.search_memory
_memory_reindex = _memory_commands.reindex_memory
_memory_bootstrap = _memory_commands.bootstrap_memory
_parse_filters = _memory_commands.parse_filters
_parse_key_values = _subscription_commands.parse_key_values

_add_storage_backup_arguments = _storage_commands._add_storage_backup_arguments
_add_storage_lineage_base_arguments = _storage_commands._add_storage_lineage_base_arguments
_add_storage_retention_arguments = _storage_commands._add_storage_retention_arguments
_retention_policy_from_args = _storage_commands.retention_policy_from_args
_storage_metrics = _storage_commands.storage_metrics
_storage_migrate = _storage_commands.storage_migrate
_storage_backup_create = _storage_commands.storage_backup_create
_storage_backup_restore = _storage_commands.storage_backup_restore
_print_storage_backup_result = _storage_commands.print_storage_backup_result
_storage_lineage_list = _storage_commands.storage_lineage_list
_storage_lineage_upstream = _storage_commands.storage_lineage_upstream
_storage_lineage_downstream = _storage_commands.storage_lineage_downstream
_print_storage_lineage_result = _storage_commands.print_storage_lineage_result
_storage_retention_plan = _storage_commands.storage_retention_plan
_storage_retention_apply = _storage_commands.storage_retention_apply
_print_storage_retention_result = _storage_commands.print_storage_retention_result

_diagnose = _diagnose_commands.diagnose

_sources_list = _source_commands.list_sources
_sources_arxiv = _source_commands.fetch_arxiv
_sources_github = _source_commands.fetch_github
_sources_health = _source_commands.source_health
_sources_check_health = _source_commands.check_source_health
_sources_validate = _source_commands.validate_sources

_runs_list = _runs_commands.list_runs
_runs_show = _runs_commands.show_run
_runs_events = _runs_commands.run_events
_run_events_sse_frames = _runs_commands.run_events_sse_frames
_sse_frame = _runs_commands.sse_frame
_runs_replay = _runs_commands.replay_run
_runs_diagnostics = _runs_commands.run_diagnostics
_runs_health = _runs_commands.run_health
_runs_catalog_health = _runs_commands.run_catalog_health
_runs_compare = _runs_commands.compare_runs
_runs_artifacts = _runs_commands.run_artifacts
_runs_cancel = _runs_commands.cancel_run
_runs_rerun_from_step = _runs_commands.rerun_from_step
_print_run_operation_result = _runs_commands.print_run_operation_result

_artifacts_list = _artifact_commands.list_artifacts
_artifacts_show = _artifact_commands.show_artifact

_add_tool_policy_args = _tool_commands.add_tool_policy_args
_tools_list = _tool_commands.list_tools
_tools_schema = _tool_commands.schema
_tool_policy_from_args = _tool_commands.tool_policy_from_args

_mcp_catalog = _mcp_commands.mcp_catalog
_mcp_capabilities = _mcp_commands.mcp_capabilities
_mcp_tools_list = _mcp_commands.mcp_tools_list
_mcp_prompts_list = _mcp_commands.mcp_prompts_list
_mcp_call = _mcp_commands.mcp_call
_mcp_read_resource = _mcp_commands.mcp_read_resource
_mcp_get_prompt = _mcp_commands.mcp_get_prompt
_parse_json_object = _mcp_commands.parse_json_object
_parse_cli_datetime = _schedule_commands.parse_cli_datetime
_mcp_serve_stdio = _mcp_commands.mcp_serve_stdio


__all__ = list(_news_all)


if __name__ == "__main__":
    raise SystemExit(main())
