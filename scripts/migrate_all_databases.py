#!/usr/bin/env python3
"""
FRIDAY Universe — Master Database Migration Runner
Provisions and migrates schemas across all 10 isolated PostgreSQL 18 databases.
Each database gets its native domain tables, foreign keys, indexes, and user grants.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Any

SSH_KEY = r"USER_HOME\.ssh\friday_universe_oracle.key"
SSH_USER = "ubuntu"
SSH_HOST = "140.245.208.100"
CREDENTIALS_FILE = Path(r"FRIDAY_UNIVERSE_HOME\CREDENTIALS_PHASE3_POSTGRES.json")

# =====================================================================
# DDL DEFINITIONS FOR ALL 10 AGENT DATABASES
# =====================================================================

SCHEMAS: Dict[str, str] = {
    # 1. FRIDAY Core Hub
    "friday_db": """
    CREATE TABLE IF NOT EXISTS conversations (
        id VARCHAR(64) PRIMARY KEY,
        title TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        metadata JSONB DEFAULT '{}'::jsonb
    );

    CREATE TABLE IF NOT EXISTS messages (
        id VARCHAR(64) PRIMARY KEY,
        conversation_id VARCHAR(64) NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        role VARCHAR(32) NOT NULL,
        content TEXT NOT NULL,
        name VARCHAR(128),
        tool_calls JSONB,
        tool_call_id VARCHAR(64),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        metadata JSONB DEFAULT '{}'::jsonb
    );

    CREATE TABLE IF NOT EXISTS memory_nodes (
        id VARCHAR(64) PRIMARY KEY,
        conversation_id VARCHAR(64) NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        memory_type VARCHAR(32) NOT NULL,
        content TEXT NOT NULL,
        source VARCHAR(64) DEFAULT 'user',
        importance DOUBLE PRECISION DEFAULT 0.5,
        confidence DOUBLE PRECISION DEFAULT 1.0,
        privacy VARCHAR(32) DEFAULT 'private',
        recency TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        metadata JSONB DEFAULT '{}'::jsonb
    );

    CREATE TABLE IF NOT EXISTS embeddings (
        id VARCHAR(64) PRIMARY KEY,
        conversation_id VARCHAR(64) NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        message_id VARCHAR(64) REFERENCES messages(id) ON DELETE CASCADE,
        source_text TEXT NOT NULL,
        embedding_vector JSONB,
        model VARCHAR(128) NOT NULL,
        dimension INTEGER NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        metadata JSONB DEFAULT '{}'::jsonb
    );

    CREATE TABLE IF NOT EXISTS task_checkpoints (
        checkpoint_id VARCHAR(64) PRIMARY KEY,
        task_id VARCHAR(64) NOT NULL,
        goal TEXT NOT NULL,
        state VARCHAR(32) NOT NULL,
        active_step_id VARCHAR(64),
        plan_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        completed_json JSONB NOT NULL DEFAULT '[]'::jsonb,
        pending_json JSONB NOT NULL DEFAULT '[]'::jsonb,
        results_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        env_hash VARCHAR(64) NOT NULL,
        interruption_reason TEXT,
        recovery_state_json JSONB,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS daily_goals (
        id BIGSERIAL PRIMARY KEY,
        goal_date DATE NOT NULL,
        title TEXT NOT NULL,
        description TEXT DEFAULT '',
        status VARCHAR(32) DEFAULT 'in_progress',
        progress DOUBLE PRECISION DEFAULT 0.0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        notes TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS experiments (
        id VARCHAR(64) PRIMARY KEY,
        experiment_name TEXT NOT NULL,
        task_prompt TEXT NOT NULL,
        task_type VARCHAR(64) NOT NULL,
        provider_name VARCHAR(64) NOT NULL,
        model_name VARCHAR(128) NOT NULL,
        accuracy DOUBLE PRECISION DEFAULT 0.0,
        success BOOLEAN NOT NULL DEFAULT FALSE,
        latency_ms DOUBLE PRECISION NOT NULL DEFAULT 0.0,
        token_usage INTEGER DEFAULT 0,
        failure_mode TEXT,
        response_content TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        metadata JSONB DEFAULT '{}'::jsonb
    );

    CREATE TABLE IF NOT EXISTS execution_traces (
        id VARCHAR(64) PRIMARY KEY,
        goal TEXT NOT NULL,
        task_type VARCHAR(64),
        tools_used JSONB DEFAULT '[]'::jsonb,
        models_used JSONB DEFAULT '[]'::jsonb,
        provider VARCHAR(64),
        latency_ms DOUBLE PRECISION,
        success BOOLEAN NOT NULL DEFAULT FALSE,
        error_message TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        metadata JSONB DEFAULT '{}'::jsonb
    );

    CREATE INDEX IF NOT EXISTS idx_messages_conv_created ON messages(conversation_id, created_at);
    CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations(updated_at DESC);
    CREATE INDEX IF NOT EXISTS idx_memory_nodes_type ON memory_nodes(memory_type, recency DESC);
    CREATE INDEX IF NOT EXISTS idx_memory_nodes_conv ON memory_nodes(conversation_id, memory_type);
    CREATE INDEX IF NOT EXISTS idx_task_checkpoints_task ON task_checkpoints(task_id);
    CREATE INDEX IF NOT EXISTS idx_daily_goals_date ON daily_goals(goal_date);
    """,

    # 2. Inference Routing Engine
    "inference_db": """
    CREATE TABLE IF NOT EXISTS agents (
        id VARCHAR(64) PRIMARY KEY,
        name VARCHAR(128) NOT NULL,
        role VARCHAR(64) NOT NULL,
        provider VARCHAR(64) NOT NULL,
        model VARCHAR(128) NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'active',
        config_json JSONB DEFAULT '{}'::jsonb
    );

    CREATE TABLE IF NOT EXISTS tasks (
        id VARCHAR(64) PRIMARY KEY,
        question TEXT NOT NULL,
        mode VARCHAR(64) NOT NULL,
        status VARCHAR(32) NOT NULL,
        result TEXT,
        confidence DOUBLE PRECISION,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        completed_at TIMESTAMPTZ,
        metadata_json JSONB DEFAULT '{}'::jsonb
    );

    CREATE TABLE IF NOT EXISTS runs (
        id VARCHAR(64) PRIMARY KEY,
        task_id VARCHAR(64) NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        agent_id VARCHAR(64) NOT NULL,
        provider VARCHAR(64) NOT NULL,
        model VARCHAR(128) NOT NULL,
        stage VARCHAR(64) NOT NULL,
        latency DOUBLE PRECISION NOT NULL DEFAULT 0.0,
        status VARCHAR(32) NOT NULL DEFAULT 'completed',
        error TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS messages (
        id VARCHAR(64) PRIMARY KEY,
        run_id VARCHAR(64) NOT NULL,
        task_id VARCHAR(64) NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        role VARCHAR(32) NOT NULL,
        agent_id VARCHAR(64),
        content TEXT NOT NULL,
        stage VARCHAR(64),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS memories (
        id VARCHAR(64) PRIMARY KEY,
        agent_id VARCHAR(64) NOT NULL,
        content TEXT NOT NULL,
        memory_type VARCHAR(32) NOT NULL DEFAULT 'fact',
        importance DOUBLE PRECISION NOT NULL DEFAULT 0.5,
        tags JSONB DEFAULT '[]'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS strategies (
        id VARCHAR(64) PRIMARY KEY,
        task_type VARCHAR(64) NOT NULL UNIQUE,
        strategy TEXT NOT NULL,
        score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
        sample_size INTEGER NOT NULL DEFAULT 1,
        recommended_agents JSONB DEFAULT '[]'::jsonb,
        recommended_provider VARCHAR(64) NOT NULL DEFAULT 'gemini',
        recommended_model VARCHAR(128) NOT NULL DEFAULT 'gemini-3.8-flash',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        metadata_json JSONB DEFAULT '{}'::jsonb
    );

    CREATE TABLE IF NOT EXISTS experiments (
        id VARCHAR(64) PRIMARY KEY,
        hypothesis TEXT NOT NULL,
        configuration JSONB DEFAULT '{}'::jsonb,
        status VARCHAR(32) NOT NULL DEFAULT 'completed',
        result_json JSONB DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS evaluations (
        id VARCHAR(64) PRIMARY KEY,
        run_id VARCHAR(64) NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
        criterion VARCHAR(128) NOT NULL,
        score DOUBLE PRECISION NOT NULL,
        feedback TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS idx_inference_memories_agent ON memories(agent_id);
    CREATE INDEX IF NOT EXISTS idx_inference_tasks_status ON tasks(status);
    CREATE INDEX IF NOT EXISTS idx_inference_runs_task ON runs(task_id);
    CREATE INDEX IF NOT EXISTS idx_inference_messages_task ON messages(task_id);
    """,

    # 3. Memora Memory Authority
    "memora_db": """
    CREATE TABLE IF NOT EXISTS agents (
        id VARCHAR(64) PRIMARY KEY,
        tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
        name VARCHAR(128) NOT NULL,
        description TEXT,
        role VARCHAR(64) NOT NULL DEFAULT 'worker',
        parent_agent_id VARCHAR(64) REFERENCES agents(id) ON DELETE SET NULL,
        bounded_scope VARCHAR(256),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_agents_tenant_name UNIQUE (tenant_id, name)
    );

    CREATE TABLE IF NOT EXISTS namespaces (
        id VARCHAR(64) PRIMARY KEY,
        tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
        path VARCHAR(256) NOT NULL,
        agent_id VARCHAR(64) REFERENCES agents(id) ON DELETE CASCADE,
        type VARCHAR(32) NOT NULL DEFAULT 'agent-private',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_namespaces_tenant_path UNIQUE (tenant_id, path)
    );

    CREATE TABLE IF NOT EXISTS access_grants (
        id VARCHAR(64) PRIMARY KEY,
        tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
        agent_id VARCHAR(64) NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
        namespace_id VARCHAR(64) NOT NULL REFERENCES namespaces(id) ON DELETE CASCADE,
        actions JSONB NOT NULL DEFAULT '["read"]'::jsonb,
        purpose VARCHAR(256),
        expires_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS memory_records (
        id VARCHAR(64) PRIMARY KEY,
        tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
        user_id VARCHAR(64) NOT NULL DEFAULT 'default_user',
        agent_id VARCHAR(64) NOT NULL DEFAULT 'friday',
        workspace_id VARCHAR(64) NOT NULL DEFAULT 'default_workspace',
        device_id VARCHAR(64) NOT NULL DEFAULT 'default_device',
        task_id VARCHAR(64),
        idempotency_key VARCHAR(128),
        namespace_id VARCHAR(64) NOT NULL REFERENCES namespaces(id) ON DELETE CASCADE,
        owner_id VARCHAR(64) NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
        memory_type VARCHAR(32) NOT NULL,
        content_text TEXT NOT NULL,
        content_hash VARCHAR(64),
        source VARCHAR(128) NOT NULL DEFAULT 'unknown',
        provenance JSONB DEFAULT '{}'::jsonb,
        entities JSONB DEFAULT '[]'::jsonb,
        confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
        importance DOUBLE PRECISION NOT NULL DEFAULT 0.5,
        lifecycle_state VARCHAR(32) NOT NULL DEFAULT 'candidate',
        observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        valid_from TIMESTAMPTZ,
        valid_until TIMESTAMPTZ,
        expires_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        last_verified_at TIMESTAMPTZ,
        superseded_by_id VARCHAR(64) REFERENCES memory_records(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS memory_relationships (
        id VARCHAR(64) PRIMARY KEY,
        source_memory_id VARCHAR(64) NOT NULL REFERENCES memory_records(id) ON DELETE CASCADE,
        target_memory_id VARCHAR(64) NOT NULL REFERENCES memory_records(id) ON DELETE CASCADE,
        relationship_type VARCHAR(64) NOT NULL DEFAULT 'relates_to',
        weight DOUBLE PRECISION NOT NULL DEFAULT 1.0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS audit_logs (
        id VARCHAR(64) PRIMARY KEY,
        tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
        actor_id VARCHAR(64) REFERENCES agents(id) ON DELETE SET NULL,
        memory_id VARCHAR(64) REFERENCES memory_records(id) ON DELETE SET NULL,
        action VARCHAR(64) NOT NULL,
        timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        details JSONB DEFAULT '{}'::jsonb
    );

    CREATE TABLE IF NOT EXISTS deletion_tombstones (
        id VARCHAR(64) PRIMARY KEY,
        tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
        memory_id VARCHAR(64) NOT NULL,
        relational_deleted BOOLEAN NOT NULL DEFAULT FALSE,
        vector_deleted BOOLEAN NOT NULL DEFAULT FALSE,
        cache_deleted BOOLEAN NOT NULL DEFAULT FALSE,
        graph_deleted BOOLEAN NOT NULL DEFAULT FALSE,
        turso_deleted BOOLEAN NOT NULL DEFAULT TRUE,
        status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
        retry_count INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS event_log (
        id BIGSERIAL PRIMARY KEY,
        event_id VARCHAR(64) UNIQUE NOT NULL,
        event_type VARCHAR(128) NOT NULL,
        tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
        target_agent VARCHAR(64),
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        cloud_synced BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS event_consumer_cursors (
        tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
        agent VARCHAR(64) NOT NULL,
        consumer_id VARCHAR(64) NOT NULL DEFAULT 'default',
        last_event_id BIGINT NOT NULL DEFAULT 0,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (tenant_id, agent, consumer_id)
    );

    CREATE INDEX IF NOT EXISTS uq_memory_idempotency_scope ON memory_records (tenant_id, agent_id, idempotency_key);
    CREATE INDEX IF NOT EXISTS ix_memory_owner_type ON memory_records (owner_id, memory_type);
    CREATE INDEX IF NOT EXISTS ix_memory_ns_state ON memory_records (namespace_id, lifecycle_state);
    CREATE INDEX IF NOT EXISTS ix_memory_tenant_created ON memory_records (tenant_id, created_at);
    CREATE INDEX IF NOT EXISTS ix_relationship_src_tgt ON memory_relationships (source_memory_id, target_memory_id);
    CREATE INDEX IF NOT EXISTS ix_event_log_tenant_cursor ON event_log (tenant_id, id);
    """,

    # 4. Stratex Market Engine
    "stratex_db": """
    CREATE TABLE IF NOT EXISTS order_intents (
        client_order_id TEXT PRIMARY KEY,
        payload_hash TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        status TEXT NOT NULL,
        result_json TEXT,
        error_text TEXT,
        created_at DOUBLE PRECISION NOT NULL,
        updated_at DOUBLE PRECISION NOT NULL
    );

    CREATE TABLE IF NOT EXISTS order_audit_events (
        event_id BIGSERIAL PRIMARY KEY,
        client_order_id TEXT NOT NULL REFERENCES order_intents(client_order_id),
        event_type TEXT NOT NULL,
        previous_status TEXT,
        new_status TEXT,
        details_json TEXT NOT NULL,
        created_at DOUBLE PRECISION NOT NULL
    );

    CREATE TABLE IF NOT EXISTS bridge_orders (
        client_order_id TEXT PRIMARY KEY,
        request_hash TEXT NOT NULL,
        request_json TEXT NOT NULL,
        status TEXT NOT NULL,
        response_json TEXT,
        error_text TEXT,
        created_at DOUBLE PRECISION NOT NULL,
        updated_at DOUBLE PRECISION NOT NULL
    );

    CREATE TABLE IF NOT EXISTS portfolio_equity_state (
        account_key TEXT NOT NULL,
        reporting_currency TEXT NOT NULL,
        utc_day TEXT NOT NULL,
        day_start_equity DOUBLE PRECISION NOT NULL,
        high_water_equity DOUBLE PRECISION NOT NULL,
        updated_at DOUBLE PRECISION NOT NULL,
        PRIMARY KEY (account_key, reporting_currency, utc_day)
    );

    CREATE INDEX IF NOT EXISTS idx_order_intents_status ON order_intents(status);
    CREATE INDEX IF NOT EXISTS idx_order_audit_client_time ON order_audit_events(client_order_id, created_at);
    """,

    # 5. Forge Software Engineer
    "forge_db": """
    CREATE TABLE IF NOT EXISTS projects (
        id VARCHAR(64) PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        description TEXT,
        workspace_path TEXT NOT NULL,
        config JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS tasks (
        id VARCHAR(64) PRIMARY KEY,
        goal TEXT NOT NULL,
        requirements JSONB NOT NULL DEFAULT '[]'::jsonb,
        mode VARCHAR(32) NOT NULL DEFAULT 'autonomous',
        workspace_path TEXT NOT NULL,
        max_budget DOUBLE PRECISION NOT NULL DEFAULT 10.0,
        budget_consumed DOUBLE PRECISION NOT NULL DEFAULT 0.0,
        state VARCHAR(32) NOT NULL DEFAULT 'PENDING',
        progress_percentage INTEGER NOT NULL DEFAULT 0,
        error_message TEXT,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS audit_events (
        id VARCHAR(64) PRIMARY KEY,
        task_id VARCHAR(64) NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        event_type VARCHAR(128) NOT NULL,
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS artifacts (
        id VARCHAR(64) PRIMARY KEY,
        task_id VARCHAR(64) NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        name VARCHAR(255) NOT NULL,
        path TEXT NOT NULL,
        file_type VARCHAR(64) NOT NULL DEFAULT 'text/plain',
        size_bytes BIGINT NOT NULL DEFAULT 0,
        checksum VARCHAR(64),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS task_graphs (
        id VARCHAR(64) PRIMARY KEY,
        project_id VARCHAR(64) NOT NULL,
        goal TEXT NOT NULL,
        nodes JSONB NOT NULL DEFAULT '{}'::jsonb,
        edges JSONB NOT NULL DEFAULT '[]'::jsonb,
        status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
        current_node_id VARCHAR(64),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS checkpoints (
        id VARCHAR(64) PRIMARY KEY,
        project_id VARCHAR(64) NOT NULL,
        task_id VARCHAR(64),
        step_number INTEGER NOT NULL DEFAULT 0,
        state_data JSONB NOT NULL DEFAULT '{}'::jsonb,
        checksum VARCHAR(64),
        timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        description TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_tasks_state ON tasks(state);
    CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_audit_events_task ON audit_events(task_id, timestamp);
    CREATE INDEX IF NOT EXISTS idx_artifacts_task ON artifacts(task_id);
    """,

    # 6. Cortex Observation Hub
    "cortex_db": """
    CREATE TABLE IF NOT EXISTS sessions (
        id VARCHAR(64) PRIMARY KEY,
        tenant_id VARCHAR(64) NOT NULL,
        site_id VARCHAR(64) NOT NULL,
        visitor_id VARCHAR(64) NOT NULL,
        user_agent TEXT,
        ip_address VARCHAR(45),
        started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        ended_at TIMESTAMPTZ,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS events (
        id VARCHAR(64) PRIMARY KEY,
        tenant_id VARCHAR(64) NOT NULL,
        site_id VARCHAR(64) NOT NULL,
        session_id VARCHAR(64) REFERENCES sessions(id) ON DELETE SET NULL,
        type VARCHAR(128) NOT NULL,
        occurred_at TIMESTAMPTZ NOT NULL,
        actor_type VARCHAR(32) NOT NULL DEFAULT 'visitor',
        actor_id VARCHAR(64) NOT NULL,
        source VARCHAR(64) NOT NULL DEFAULT 'web-sdk',
        data JSONB NOT NULL DEFAULT '{}'::jsonb,
        consent JSONB,
        trace_id VARCHAR(64),
        server_received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        client_ip VARCHAR(45),
        user_agent TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_sessions_tenant_site ON sessions (tenant_id, site_id);
    CREATE INDEX IF NOT EXISTS idx_sessions_visitor ON sessions (visitor_id);
    CREATE INDEX IF NOT EXISTS idx_sessions_started_at ON sessions (started_at DESC);
    CREATE INDEX IF NOT EXISTS idx_events_tenant_site_time ON events (tenant_id, site_id, occurred_at DESC);
    CREATE INDEX IF NOT EXISTS idx_events_type ON events (type);
    """,

    # 7. Sentinel Security & Defensive Operator
    "sentinel_db": """
    CREATE TABLE IF NOT EXISTS sentinel_targets (
        id VARCHAR(64) PRIMARY KEY,
        type VARCHAR(32) NOT NULL,
        value VARCHAR(512) NOT NULL,
        resolved_ips JSONB DEFAULT '[]'::jsonb NOT NULL,
        parent_asset_id VARCHAR(64),
        criticality VARCHAR(32) DEFAULT 'medium' NOT NULL,
        environment VARCHAR(32) DEFAULT 'production' NOT NULL,
        owner VARCHAR(128),
        description TEXT,
        tags JSONB DEFAULT '{}'::jsonb NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS sentinel_targetsets (
        id VARCHAR(64) PRIMARY KEY,
        name VARCHAR(256) NOT NULL,
        description TEXT,
        context_notes JSONB DEFAULT '{}'::jsonb NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS sentinel_targetset_targets (
        targetset_id VARCHAR(64) REFERENCES sentinel_targetsets(id) ON DELETE CASCADE,
        target_id VARCHAR(64) REFERENCES sentinel_targets(id) ON DELETE CASCADE,
        PRIMARY KEY (targetset_id, target_id)
    );

    CREATE TABLE IF NOT EXISTS sentinel_scopes (
        id VARCHAR(64) PRIMARY KEY,
        name VARCHAR(256) NOT NULL,
        allowed_targets JSONB DEFAULT '[]'::jsonb NOT NULL,
        in_scope_declarations JSONB DEFAULT '[]'::jsonb NOT NULL,
        out_of_scope_declarations JSONB DEFAULT '[]'::jsonb NOT NULL,
        environment VARCHAR(32) DEFAULT 'production' NOT NULL,
        authorization_type VARCHAR(64) DEFAULT 'owned' NOT NULL,
        reference_ticket_id VARCHAR(128),
        authorized_by VARCHAR(128),
        expiry TIMESTAMPTZ,
        max_intensity DOUBLE PRECISION DEFAULT 5.0 NOT NULL,
        offensive_actions_enabled BOOLEAN DEFAULT FALSE NOT NULL,
        scope_contract JSONB DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS sentinel_policies (
        id VARCHAR(64) PRIMARY KEY,
        name VARCHAR(256) NOT NULL,
        allowed_module_classes JSONB DEFAULT '[]'::jsonb NOT NULL,
        allowed_action_classes JSONB DEFAULT '[]'::jsonb NOT NULL,
        rate_limit_rps DOUBLE PRECISION DEFAULT 50.0 NOT NULL,
        max_intensity DOUBLE PRECISION DEFAULT 5.0 NOT NULL,
        credential_handling_rules JSONB DEFAULT '{}'::jsonb NOT NULL,
        require_approval_for_offensive BOOLEAN DEFAULT TRUE NOT NULL,
        kill_switch_active BOOLEAN DEFAULT FALSE NOT NULL,
        policy_contract JSONB DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS sentinel_tasks (
        id VARCHAR(64) PRIMARY KEY,
        objective TEXT NOT NULL,
        target_set_id VARCHAR(64) REFERENCES sentinel_targetsets(id) NOT NULL,
        scope_id VARCHAR(64) REFERENCES sentinel_scopes(id) NOT NULL,
        policy_id VARCHAR(64) REFERENCES sentinel_policies(id) NOT NULL,
        mode VARCHAR(64) DEFAULT 'assessment' NOT NULL,
        status VARCHAR(32) DEFAULT 'submitted' NOT NULL,
        requested_output_type VARCHAR(64) DEFAULT 'comprehensive_report' NOT NULL,
        progress_percentage DOUBLE PRECISION DEFAULT 0.0 NOT NULL,
        correlation_id VARCHAR(64) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        completed_at TIMESTAMPTZ
    );

    CREATE TABLE IF NOT EXISTS sentinel_task_checkpoints (
        task_id VARCHAR(64) PRIMARY KEY REFERENCES sentinel_tasks(id) ON DELETE CASCADE,
        version INTEGER DEFAULT 1 NOT NULL,
        payload JSONB DEFAULT '{}'::jsonb NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS sentinel_action_requests (
        id VARCHAR(64) PRIMARY KEY,
        task_id VARCHAR(64) REFERENCES sentinel_tasks(id) ON DELETE CASCADE NOT NULL,
        agent VARCHAR(128) NOT NULL,
        action_type VARCHAR(128) NOT NULL,
        parameters JSONB DEFAULT '{}'::jsonb NOT NULL,
        target_refs JSONB DEFAULT '[]'::jsonb NOT NULL,
        expected_impact_level VARCHAR(32) DEFAULT 'low' NOT NULL,
        requires_approval BOOLEAN DEFAULT FALSE NOT NULL,
        status VARCHAR(32) DEFAULT 'pending_approval' NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS sentinel_approvals (
        approval_id VARCHAR(64) PRIMARY KEY,
        task_id VARCHAR(64) REFERENCES sentinel_tasks(id) ON DELETE CASCADE NOT NULL,
        action_id VARCHAR(64) NOT NULL,
        action_type VARCHAR(128) NOT NULL,
        target_refs JSONB DEFAULT '[]'::jsonb NOT NULL,
        requested_by VARCHAR(128) NOT NULL,
        action_fingerprint VARCHAR(64),
        status VARCHAR(32) DEFAULT 'PENDING' NOT NULL,
        justification_needed TEXT NOT NULL,
        justification_provided TEXT,
        approved_by VARCHAR(128),
        authorization_reference VARCHAR(256),
        requested_at TIMESTAMPTZ NOT NULL,
        decided_at TIMESTAMPTZ,
        expires_at TIMESTAMPTZ NOT NULL
    );

    CREATE TABLE IF NOT EXISTS sentinel_action_results (
        action_id VARCHAR(64) PRIMARY KEY,
        task_id VARCHAR(64) REFERENCES sentinel_tasks(id) ON DELETE CASCADE NOT NULL,
        success BOOLEAN NOT NULL,
        output_summary TEXT NOT NULL,
        raw_output_uri VARCHAR(512),
        duration_seconds DOUBLE PRECISION NOT NULL,
        error_info JSONB,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS sentinel_evidence (
        id VARCHAR(64) PRIMARY KEY,
        task_id VARCHAR(64) REFERENCES sentinel_tasks(id) ON DELETE CASCADE NOT NULL,
        target_ref VARCHAR(512) NOT NULL,
        source_agent VARCHAR(128) NOT NULL,
        source_module VARCHAR(128) NOT NULL,
        source_tool VARCHAR(128) NOT NULL,
        timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        artifact_storage_key VARCHAR(512) NOT NULL,
        content_type VARCHAR(128) NOT NULL,
        sha256_hash VARCHAR(64) NOT NULL,
        integrity_metadata JSONB DEFAULT '{}'::jsonb NOT NULL,
        collected_by VARCHAR(128) NOT NULL,
        chain_of_custody JSONB DEFAULT '[]'::jsonb NOT NULL,
        context_metadata JSONB DEFAULT '{}'::jsonb NOT NULL
    );

    CREATE TABLE IF NOT EXISTS sentinel_findings (
        id VARCHAR(64) PRIMARY KEY,
        task_id VARCHAR(64) REFERENCES sentinel_tasks(id) ON DELETE CASCADE NOT NULL,
        title VARCHAR(512) NOT NULL,
        description TEXT NOT NULL,
        target_ref VARCHAR(512) NOT NULL,
        severity VARCHAR(32) NOT NULL,
        confidence DOUBLE PRECISION DEFAULT 1.0 NOT NULL,
        exploitability_context TEXT,
        impact TEXT,
        evidence_refs JSONB DEFAULT '[]'::jsonb NOT NULL,
        related_cves JSONB DEFAULT '[]'::jsonb NOT NULL,
        related_cwes JSONB DEFAULT '[]'::jsonb NOT NULL,
        remediation TEXT,
        status VARCHAR(32) DEFAULT 'open' NOT NULL,
        first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS sentinel_risks (
        id VARCHAR(64) PRIMARY KEY,
        finding_id VARCHAR(64) REFERENCES sentinel_findings(id) ON DELETE CASCADE NOT NULL,
        task_id VARCHAR(64) REFERENCES sentinel_tasks(id) ON DELETE CASCADE NOT NULL,
        severity VARCHAR(32) NOT NULL,
        asset_criticality VARCHAR(32) NOT NULL,
        exposure_score DOUBLE PRECISION DEFAULT 1.0 NOT NULL,
        exploitability_score DOUBLE PRECISION DEFAULT 1.0 NOT NULL,
        confidence_score DOUBLE PRECISION DEFAULT 1.0 NOT NULL,
        computed_risk_score DOUBLE PRECISION DEFAULT 0.0 NOT NULL,
        risk_tier VARCHAR(32) NOT NULL,
        rationale TEXT DEFAULT '' NOT NULL
    );

    CREATE TABLE IF NOT EXISTS sentinel_events (
        event_id VARCHAR(64) PRIMARY KEY,
        event_type VARCHAR(64) NOT NULL,
        topic VARCHAR(128) NOT NULL,
        source VARCHAR(128) NOT NULL,
        payload JSONB DEFAULT '{}'::jsonb NOT NULL,
        correlation_id VARCHAR(64) NOT NULL,
        timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS sentinel_audit_logs (
        entry_id VARCHAR(64) PRIMARY KEY,
        timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        event_type VARCHAR(128) NOT NULL,
        actor VARCHAR(128) NOT NULL,
        target VARCHAR(256),
        action_type VARCHAR(128) NOT NULL,
        scope_policy VARCHAR(128) NOT NULL,
        decision VARCHAR(64) NOT NULL,
        details JSONB DEFAULT '{}'::jsonb NOT NULL,
        previous_hash VARCHAR(128) NOT NULL,
        current_hash VARCHAR(128) NOT NULL,
        signature VARCHAR(256) NOT NULL,
        verified BOOLEAN DEFAULT TRUE
    );

    CREATE INDEX IF NOT EXISTS idx_sentinel_targets_type ON sentinel_targets(type);
    CREATE INDEX IF NOT EXISTS idx_sentinel_tasks_status ON sentinel_tasks(status);
    CREATE INDEX IF NOT EXISTS idx_sentinel_findings_severity ON sentinel_findings(severity);
    """,

    # 8. IntelX Investigation & Synthesis
    "intelx_db": """
    CREATE TABLE IF NOT EXISTS research_runs (
        id VARCHAR(36) PRIMARY KEY,
        objective TEXT NOT NULL,
        scope_json JSONB DEFAULT '{}'::jsonb NOT NULL,
        status VARCHAR(32) DEFAULT 'queued' NOT NULL,
        outcome VARCHAR(32),
        parent_run_id VARCHAR(36) REFERENCES research_runs(id),
        plan_json JSONB,
        idempotency_key VARCHAR(128) UNIQUE,
        input_tokens INTEGER DEFAULT 0 NOT NULL,
        output_tokens INTEGER DEFAULT 0 NOT NULL,
        usd_cost DOUBLE PRECISION DEFAULT 0.0 NOT NULL,
        tool_calls INTEGER DEFAULT 0 NOT NULL,
        error_json JSONB,
        created_by VARCHAR(128),
        started_at TIMESTAMPTZ,
        completed_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS tasks (
        id VARCHAR(36) PRIMARY KEY,
        run_id VARCHAR(36) NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
        type VARCHAR(64) NOT NULL,
        status VARCHAR(32) DEFAULT 'pending' NOT NULL,
        attempt INTEGER DEFAULT 1 NOT NULL,
        max_attempts INTEGER DEFAULT 3 NOT NULL,
        error_class VARCHAR(64),
        error_json JSONB,
        payload_json JSONB,
        result_json JSONB,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        started_at TIMESTAMPTZ,
        finished_at TIMESTAMPTZ
    );

    CREATE TABLE IF NOT EXISTS sources (
        id VARCHAR(36) PRIMARY KEY,
        kind VARCHAR(32) NOT NULL,
        location TEXT NOT NULL,
        domain VARCHAR(255),
        publisher VARCHAR(255),
        title TEXT,
        published_at TIMESTAMPTZ,
        retrieved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        content_type VARCHAR(128) DEFAULT 'text/html' NOT NULL,
        fingerprint VARCHAR(64) UNIQUE NOT NULL,
        trust_tier VARCHAR(32) DEFAULT 'quarantine' NOT NULL,
        robots_ok BOOLEAN DEFAULT TRUE NOT NULL,
        license_note TEXT,
        injection_risk BOOLEAN DEFAULT FALSE NOT NULL,
        raw_path TEXT,
        created_by_run_id VARCHAR(36) REFERENCES research_runs(id)
    );

    CREATE TABLE IF NOT EXISTS documents (
        id VARCHAR(36) PRIMARY KEY,
        source_id VARCHAR(36) NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
        text TEXT NOT NULL,
        language VARCHAR(16) DEFAULT 'en' NOT NULL,
        version INTEGER DEFAULT 1 NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS chunks (
        id VARCHAR(36) PRIMARY KEY,
        document_id VARCHAR(36) NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        idx INTEGER NOT NULL,
        start_char INTEGER NOT NULL,
        end_char INTEGER NOT NULL,
        text TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS entities (
        id VARCHAR(36) PRIMARY KEY,
        canonical_name VARCHAR(255) NOT NULL,
        type VARCHAR(64) NOT NULL,
        created_by_run_id VARCHAR(36) REFERENCES research_runs(id)
    );

    CREATE TABLE IF NOT EXISTS entity_aliases (
        id VARCHAR(36) PRIMARY KEY,
        entity_id VARCHAR(36) NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
        alias VARCHAR(255) NOT NULL
    );

    CREATE TABLE IF NOT EXISTS entity_relations (
        id VARCHAR(36) PRIMARY KEY,
        subject_entity_id VARCHAR(36) NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
        predicate VARCHAR(128) NOT NULL,
        object_entity_id VARCHAR(36) NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
        claim_id VARCHAR(36),
        confidence DOUBLE PRECISION DEFAULT 1.0 NOT NULL
    );

    CREATE TABLE IF NOT EXISTS entity_merges (
        id VARCHAR(36) PRIMARY KEY,
        kept_entity_id VARCHAR(36) NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
        merged_entity_id VARCHAR(36) NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
        score DOUBLE PRECISION NOT NULL,
        status VARCHAR(32) DEFAULT 'proposed' NOT NULL,
        created_by_run_id VARCHAR(36) REFERENCES research_runs(id)
    );

    CREATE TABLE IF NOT EXISTS claims (
        id VARCHAR(36) PRIMARY KEY,
        run_id VARCHAR(36) NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
        source_id VARCHAR(36) NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
        document_id VARCHAR(36) NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        chunk_id VARCHAR(36) NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
        text TEXT NOT NULL,
        subject VARCHAR(255),
        predicate VARCHAR(255),
        object VARCHAR(255),
        claim_type VARCHAR(64) NOT NULL,
        entities_json JSONB DEFAULT '[]'::jsonb NOT NULL,
        quote TEXT NOT NULL,
        span_start INTEGER NOT NULL,
        span_end INTEGER NOT NULL,
        confidence DOUBLE PRECISION DEFAULT 1.0 NOT NULL,
        confidence_method VARCHAR(64) DEFAULT 'v1-composite' NOT NULL,
        origin VARCHAR(32) DEFAULT 'extracted' NOT NULL,
        status VARCHAR(32) DEFAULT 'active' NOT NULL,
        superseded_by VARCHAR(36) REFERENCES claims(id),
        retraction_reason TEXT,
        created_by_agent VARCHAR(64) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS evidence (
        id VARCHAR(36) PRIMARY KEY,
        claim_id VARCHAR(36) NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
        source_id VARCHAR(36) NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
        document_id VARCHAR(36) NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        chunk_id VARCHAR(36) NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
        span_start INTEGER NOT NULL,
        span_end INTEGER NOT NULL,
        quote TEXT NOT NULL,
        support_type VARCHAR(32) DEFAULT 'supports' NOT NULL,
        independent_of_json JSONB DEFAULT '[]'::jsonb NOT NULL,
        created_by_run_id VARCHAR(36) NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
        created_by_agent VARCHAR(64) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS findings (
        id VARCHAR(36) PRIMARY KEY,
        run_id VARCHAR(36) NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
        conclusion TEXT NOT NULL,
        confidence DOUBLE PRECISION NOT NULL,
        confidence_method VARCHAR(64) DEFAULT 'v1-composite' NOT NULL,
        claim_ids_json JSONB DEFAULT '[]'::jsonb NOT NULL,
        gaps_json JSONB DEFAULT '[]'::jsonb NOT NULL,
        contradictions_json JSONB DEFAULT '[]'::jsonb NOT NULL,
        unverified_json JSONB DEFAULT '[]'::jsonb NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS artifacts (
        id VARCHAR(36) PRIMARY KEY,
        run_id VARCHAR(36) NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
        type VARCHAR(64) NOT NULL,
        format VARCHAR(32) NOT NULL,
        path TEXT NOT NULL,
        schema_version VARCHAR(32) DEFAULT 'v1.0' NOT NULL,
        sha256 VARCHAR(64) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS events (
        id BIGSERIAL PRIMARY KEY,
        run_id VARCHAR(36) NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
        type VARCHAR(64) NOT NULL,
        payload_json JSONB DEFAULT '{}'::jsonb NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS audit_events (
        id BIGSERIAL PRIMARY KEY,
        ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        actor VARCHAR(128) NOT NULL,
        action VARCHAR(128) NOT NULL,
        object_type VARCHAR(64) NOT NULL,
        object_id VARCHAR(64) NOT NULL,
        detail_json JSONB DEFAULT '{}'::jsonb NOT NULL,
        prev_hash VARCHAR(64) NOT NULL,
        hash VARCHAR(64) NOT NULL
    );

    CREATE TABLE IF NOT EXISTS review_decisions (
        id VARCHAR(36) PRIMARY KEY,
        run_id VARCHAR(36) NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
        decision VARCHAR(64) NOT NULL,
        notes TEXT,
        decided_by VARCHAR(128) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS policies (
        id VARCHAR(36) PRIMARY KEY,
        key VARCHAR(128) UNIQUE NOT NULL,
        value_json JSONB DEFAULT '{}'::jsonb NOT NULL,
        version INTEGER DEFAULT 1 NOT NULL,
        updated_by VARCHAR(128) NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS api_keys (
        id VARCHAR(36) PRIMARY KEY,
        key_hash VARCHAR(64) UNIQUE NOT NULL,
        name VARCHAR(128) NOT NULL,
        role VARCHAR(32) DEFAULT 'member' NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        revoked BOOLEAN DEFAULT FALSE NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_intelx_runs_status ON research_runs(status);
    CREATE INDEX IF NOT EXISTS idx_intelx_claims_run ON claims(run_id);
    CREATE INDEX IF NOT EXISTS idx_intelx_evidence_claim ON evidence(claim_id);
    """,

    # 9. Futuris Forecasting Engine
    "futuris_db": """
    CREATE TABLE IF NOT EXISTS scenarios (
        scenario_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name VARCHAR(255) NOT NULL,
        scenario_type VARCHAR(64) NOT NULL,
        assumptions_override JSONB DEFAULT '{}'::jsonb NOT NULL,
        created_by VARCHAR(255) NOT NULL,
        parent_forecast_id UUID
    );

    CREATE TABLE IF NOT EXISTS forecasts (
        forecast_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        target VARCHAR(255) NOT NULL,
        as_of TIMESTAMPTZ NOT NULL,
        horizon INTERVAL NOT NULL,
        expires_at TIMESTAMPTZ NOT NULL,
        prediction DOUBLE PRECISION NOT NULL,
        range_lower DOUBLE PRECISION NOT NULL,
        range_upper DOUBLE PRECISION NOT NULL,
        probability DOUBLE PRECISION,
        confidence VARCHAR(32) NOT NULL,
        model_version VARCHAR(255) NOT NULL,
        assumptions JSONB DEFAULT '[]'::jsonb NOT NULL,
        review_at TIMESTAMPTZ NOT NULL,
        status VARCHAR(32) NOT NULL,
        scenario_id UUID REFERENCES scenarios(scenario_id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        drivers JSONB DEFAULT '[]'::jsonb NOT NULL,
        predictive_distribution JSONB DEFAULT '{}'::jsonb NOT NULL,
        intervals JSONB DEFAULT '[]'::jsonb NOT NULL,
        calibration_metrics JSONB DEFAULT '{}'::jsonb NOT NULL,
        model_metadata JSONB DEFAULT '{}'::jsonb NOT NULL,
        idempotency_key VARCHAR(255),
        evidence_class VARCHAR(32),
        evidence_source VARCHAR(255)
    );

    CREATE TABLE IF NOT EXISTS evidence_refs (
        evidence_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        forecast_id UUID NOT NULL REFERENCES forecasts(forecast_id) ON DELETE CASCADE,
        source VARCHAR(255) NOT NULL,
        source_trust VARCHAR(32) NOT NULL,
        signal_class VARCHAR(64) NOT NULL,
        as_of TIMESTAMPTZ NOT NULL,
        snapshot_path VARCHAR(1024) NOT NULL,
        content_hash VARCHAR(64) NOT NULL,
        evidence_class VARCHAR(32)
    );

    CREATE TABLE IF NOT EXISTS outcomes (
        outcome_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        forecast_id UUID UNIQUE NOT NULL REFERENCES forecasts(forecast_id) ON DELETE CASCADE,
        observed_value DOUBLE PRECISION,
        event_occurred BOOLEAN,
        resolved_at TIMESTAMPTZ NOT NULL,
        resolution_method VARCHAR(64) NOT NULL,
        ambiguity_note TEXT,
        resolution_rule_version VARCHAR(64) NOT NULL
    );

    CREATE TABLE IF NOT EXISTS forecast_events (
        event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        forecast_id UUID REFERENCES forecasts(forecast_id) ON DELETE CASCADE,
        event_type VARCHAR(128) NOT NULL,
        payload JSONB DEFAULT '{}'::jsonb NOT NULL,
        emitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS intelx_notices (
        event_id VARCHAR(128) PRIMARY KEY,
        source_agent VARCHAR(64) NOT NULL,
        payload JSONB DEFAULT '{}'::jsonb NOT NULL,
        received_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS observations (
        observation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        series_id VARCHAR(255) NOT NULL,
        source VARCHAR(255) NOT NULL,
        observed_at TIMESTAMPTZ NOT NULL,
        value DOUBLE PRECISION NOT NULL,
        unit VARCHAR(64) NOT NULL,
        tags JSONB DEFAULT '{}'::jsonb NOT NULL
    );

    CREATE TABLE IF NOT EXISTS signal_sources (
        source_id VARCHAR(255) PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        signal_class VARCHAR(64) NOT NULL,
        trust_level VARCHAR(32) NOT NULL,
        first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        last_seen_at TIMESTAMPTZ
    );

    CREATE TABLE IF NOT EXISTS model_registry (
        model_version VARCHAR(255) PRIMARY KEY,
        family VARCHAR(255) NOT NULL,
        config_hash VARCHAR(64) NOT NULL,
        is_active BOOLEAN DEFAULT FALSE NOT NULL,
        promoted_at TIMESTAMPTZ,
        benchmark_scores JSONB DEFAULT '{}'::jsonb NOT NULL
    );

    CREATE TABLE IF NOT EXISTS evaluation_runs (
        run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        model_version VARCHAR(255) NOT NULL REFERENCES model_registry(model_version) ON DELETE CASCADE,
        dataset_name VARCHAR(255) NOT NULL,
        metrics JSONB DEFAULT '{}'::jsonb NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS api_keys (
        key_hash VARCHAR(64) PRIMARY KEY,
        label VARCHAR(255) NOT NULL,
        role VARCHAR(32) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        revoked_at TIMESTAMPTZ
    );

    CREATE TABLE IF NOT EXISTS audit_logs (
        audit_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        actor_label VARCHAR(255) NOT NULL,
        action VARCHAR(128) NOT NULL,
        entity VARCHAR(128) NOT NULL,
        entity_id VARCHAR(255) NOT NULL,
        payload_hash VARCHAR(64) NOT NULL,
        timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS ix_forecasts_target_as_of ON forecasts(target, as_of);
    CREATE INDEX IF NOT EXISTS ix_forecasts_idempotency_key ON forecasts(idempotency_key);
    CREATE INDEX IF NOT EXISTS ix_observations_series_time ON observations(series_id, observed_at);
    """,

    # 10. VyralX Media Production & Autonomous Publisher
    "vyralx_db": """
    CREATE TABLE IF NOT EXISTS sources (
        id BIGSERIAL PRIMARY KEY,
        title VARCHAR(300) NOT NULL,
        source_url VARCHAR(2048) DEFAULT '',
        platform VARCHAR(40) DEFAULT 'manual',
        creator VARCHAR(300) DEFAULT '',
        license_name VARCHAR(200) DEFAULT '',
        permission_reference VARCHAR(2048) DEFAULT '',
        repeat_use_allowed BOOLEAN DEFAULT FALSE,
        repeat_use_reviewed_at TIMESTAMPTZ,
        repeat_use_review_notes TEXT DEFAULT '',
        rights_verified BOOLEAN DEFAULT FALSE,
        status VARCHAR(40) DEFAULT 'discovered',
        notes TEXT DEFAULT '',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS assets (
        id BIGSERIAL PRIMARY KEY,
        source_id BIGINT,
        title VARCHAR(300) NOT NULL,
        file_path VARCHAR(2048) NOT NULL,
        duration_seconds DOUBLE PRECISION DEFAULT 0,
        width INTEGER DEFAULT 0,
        height INTEGER DEFAULT 0,
        rights_verified BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS render_jobs (
        id BIGSERIAL PRIMARY KEY,
        asset_id BIGINT NOT NULL,
        preset VARCHAR(40) NOT NULL,
        status VARCHAR(40) DEFAULT 'queued',
        output_path VARCHAR(2048) DEFAULT '',
        error TEXT DEFAULT '',
        attempts INTEGER DEFAULT 0,
        started_at TIMESTAMPTZ,
        completed_at TIMESTAMPTZ,
        updated_at TIMESTAMPTZ,
        options_json TEXT DEFAULT '{}',
        project_id BIGINT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS publish_jobs (
        id BIGSERIAL PRIMARY KEY,
        asset_id BIGINT NOT NULL,
        render_job_id BIGINT NOT NULL,
        title VARCHAR(100) NOT NULL,
        description TEXT DEFAULT '',
        tags_json TEXT DEFAULT '[]',
        privacy_status VARCHAR(20) DEFAULT 'private',
        scheduled_at VARCHAR(64) DEFAULT '',
        status VARCHAR(40) DEFAULT 'pending_approval',
        youtube_video_id VARCHAR(100) DEFAULT '',
        error TEXT DEFAULT '',
        attempts INTEGER DEFAULT 0,
        approved_at TIMESTAMPTZ,
        started_at TIMESTAMPTZ,
        completed_at TIMESTAMPTZ,
        updated_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS content_packs (
        id BIGSERIAL PRIMARY KEY,
        topic VARCHAR(500) NOT NULL,
        video_format VARCHAR(20) DEFAULT 'shorts',
        status VARCHAR(40) DEFAULT 'generated',
        pack_json TEXT NOT NULL,
        provider_model VARCHAR(200) DEFAULT '',
        voiceover_path VARCHAR(2048) DEFAULT '',
        voiceover_status VARCHAR(40) DEFAULT 'not_generated',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS video_metrics (
        id BIGSERIAL PRIMARY KEY,
        publish_job_id BIGINT,
        youtube_video_id VARCHAR(100),
        view_count INTEGER DEFAULT 0,
        like_count INTEGER DEFAULT 0,
        comment_count INTEGER DEFAULT 0,
        fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS agent_tasks (
        id BIGSERIAL PRIMARY KEY,
        task_id VARCHAR(120) UNIQUE NOT NULL,
        task_type VARCHAR(80) NOT NULL,
        input_json TEXT DEFAULT '{}',
        idempotency_key VARCHAR(160) UNIQUE,
        authorization_context_json TEXT DEFAULT '{}',
        correlation_id VARCHAR(120) DEFAULT '',
        trace_id VARCHAR(120) DEFAULT '',
        parent_task_id VARCHAR(120) DEFAULT '',
        request_id VARCHAR(120) DEFAULT '',
        actor VARCHAR(120) DEFAULT 'operator',
        capability VARCHAR(120) DEFAULT '',
        objective VARCHAR(500) DEFAULT '',
        trust_level VARCHAR(40) DEFAULT 'untrusted',
        deadline VARCHAR(80) DEFAULT '',
        requested_mode VARCHAR(20) DEFAULT 'async',
        priority VARCHAR(20) DEFAULT 'normal',
        source_agent VARCHAR(120) DEFAULT 'friday',
        target_agent VARCHAR(120) DEFAULT 'vyralx',
        action VARCHAR(120) DEFAULT '',
        status VARCHAR(40) DEFAULT 'queued',
        result_json TEXT DEFAULT '{}',
        error TEXT DEFAULT '',
        attempts INTEGER DEFAULT 0,
        started_at TIMESTAMPTZ,
        completed_at TIMESTAMPTZ,
        updated_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS video_projects (
        id BIGSERIAL PRIMARY KEY,
        project_key VARCHAR(120) UNIQUE NOT NULL,
        topic VARCHAR(500) NOT NULL,
        auto_discover_trend BOOLEAN DEFAULT FALSE,
        trend_query VARCHAR(200) DEFAULT '',
        trend_max_results INTEGER DEFAULT 10,
        trend_source_video_id VARCHAR(100) DEFAULT '',
        trend_source_url VARCHAR(2048) DEFAULT '',
        trend_score DOUBLE PRECISION DEFAULT 0.0,
        video_format VARCHAR(20) DEFAULT 'shorts',
        target_seconds INTEGER DEFAULT 45,
        audience VARCHAR(200) DEFAULT 'general audience',
        tone VARCHAR(200) DEFAULT 'clear, energetic and factual',
        scene_count INTEGER DEFAULT 4,
        confirm_pexels_license BOOLEAN DEFAULT FALSE,
        confirm_pexels_repeat_use BOOLEAN DEFAULT FALSE,
        use_voiceover BOOLEAN DEFAULT TRUE,
        status VARCHAR(40) DEFAULT 'queued',
        content_pack_id BIGINT,
        render_job_id BIGINT,
        primary_asset_id BIGINT,
        thumbnail_path VARCHAR(2048) DEFAULT '',
        memora_memory_id VARCHAR(128) DEFAULT '',
        memora_memory_status VARCHAR(32) DEFAULT 'disabled',
        asset_ids_json TEXT DEFAULT '[]',
        error TEXT DEFAULT '',
        attempts INTEGER DEFAULT 0,
        started_at TIMESTAMPTZ,
        completed_at TIMESTAMPTZ,
        updated_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS idx_vyralx_video_projects_key ON video_projects(project_key);
    CREATE INDEX IF NOT EXISTS idx_vyralx_agent_tasks_id ON agent_tasks(task_id);
    """
}

def get_schema_ddl(db_name: str) -> str:
    """Return the schema DDL for a given database name."""
    if db_name not in SCHEMAS:
        raise KeyError(f"Unknown database: {db_name}")
    return SCHEMAS[db_name]

def run_remote_python(script_str: str) -> str:
    """Execute Python code on the remote Oracle VM host via SSH."""
    res = subprocess.run(
        ["ssh", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=no", f"{SSH_USER}@{SSH_HOST}", "python3"],
        input=script_str.encode("utf-8"),
        capture_output=True
    )
    if res.returncode != 0:
        err = res.stderr.decode("utf-8", errors="replace")
        print("Remote error:", err)
        raise RuntimeError(f"Remote command failed with code {res.returncode}: {err}")
    return res.stdout.decode("utf-8", errors="replace")

def migrate_databases(schemas_dict: Dict[str, str], creds_file: Path = CREDENTIALS_FILE) -> Dict[str, Any]:
    """Execute migrations on all target databases."""
    if creds_file.exists():
        with open(creds_file, "r", encoding="utf-8") as f:
            creds = json.load(f)
    else:
        creds = {}

    remote_runner = f"""
import subprocess
import json

schemas = {json.dumps(schemas_dict)}
creds = {json.dumps(creds)}

cid = subprocess.check_output('docker ps -q -f name=dokploy-postgres', shell=True).decode().strip()
print(f"Targeting PostgreSQL Container: {{cid}}")

results = {{}}

for db_name, ddl in schemas.items():
    user = creds.get(db_name, {{}}).get("username", "postgres")
    print(f"\\n=== Migrating {{db_name}} (Owner: {{user}}) ===")
    
    # 1. Execute DDL as dokploy superuser
    try:
        p = subprocess.run(
            ['docker', 'exec', '-i', cid, 'psql', '-U', 'dokploy', '-d', db_name],
            input=ddl.encode('utf-8'),
            capture_output=True
        )
        if p.returncode != 0:
            print(f"  [ERROR] DDL Execution failed: {{p.stderr.decode()}}")
            results[db_name] = {{"status": "ERROR", "error": p.stderr.decode()}}
            continue
            
        # 2. Grant permissions on all newly created tables and sequences to db owner
        grant_sql = f'''
        GRANT ALL ON ALL TABLES IN SCHEMA public TO {{user}};
        GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO {{user}};
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO {{user}};
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO {{user}};
        '''
        subprocess.check_call(['docker', 'exec', '-i', cid, 'psql', '-U', 'dokploy', '-d', db_name, '-c', grant_sql])
        
        # 3. Query table list and count
        table_list_raw = subprocess.check_output(
            ['docker', 'exec', cid, 'psql', '-U', 'dokploy', '-d', db_name, '-tAc', 
             "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name;"]
        ).decode().strip()
        
        tables = [t.strip() for t in table_list_raw.splitlines() if t.strip()]
        print(f"  [SUCCESS] Migrated {{len(tables)}} tables: {{', '.join(tables)}}")
        results[db_name] = {{"status": "SUCCESS", "table_count": len(tables), "tables": tables}}
        
    except Exception as e:
        print(f"  [EXCEPTION] {{e}}")
        results[db_name] = {{"status": "EXCEPTION", "error": str(e)}}

print("\\n" + "=" * 70)
print("MIGRATION SUMMARY JSON:")
print(json.dumps(results))
print("=" * 70)
"""
    output = run_remote_python(remote_runner)
    return output

if __name__ == "__main__":
    print("=" * 70)
    print("FRIDAY UNIVERSE — EXECUTING MASTER DATABASE MIGRATIONS")
    print("=" * 70)
    out = migrate_databases(SCHEMAS)
    print(out)
