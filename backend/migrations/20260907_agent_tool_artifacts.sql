-- Agent 工具完整结果。模型检查点只保存摘要和 artifact_id。

CREATE TABLE IF NOT EXISTS agent_tool_artifacts (
    artifact_id VARCHAR(64) PRIMARY KEY,
    thread_id VARCHAR(64) NOT NULL,
    user_id_hash VARCHAR(64),
    tool_name VARCHAR(100) NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_tool_artifacts_thread
    ON agent_tool_artifacts(thread_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_tool_artifacts_user
    ON agent_tool_artifacts(user_id_hash, created_at DESC);
