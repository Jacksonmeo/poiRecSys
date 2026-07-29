-- 离线 Next-POI 模型输出表，请在 20260714_user_sessions.sql 之后执行。
-- 每个 session/model 保存 Top-K 行，rank 和 poi_id 均不允许重复。

CREATE TABLE IF NOT EXISTS recommendation_results (
    id BIGSERIAL PRIMARY KEY,
    session_id VARCHAR(150) NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    user_id VARCHAR(100) NOT NULL,
    dataset VARCHAR(20) NOT NULL DEFAULT 'TKY',
    model_name VARCHAR(100) NOT NULL,
    target_poi_id VARCHAR(100) NOT NULL REFERENCES pois(venue_id),
    poi_id VARCHAR(100) NOT NULL REFERENCES pois(venue_id),
    rank INTEGER NOT NULL CHECK (rank > 0),
    score DOUBLE PRECISION NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_recommendation_result_rank UNIQUE (session_id, model_name, rank),
    CONSTRAINT uq_recommendation_result_poi UNIQUE (session_id, model_name, poi_id)
);

-- 兼容项目早期已经创建、但尚未写入数据的旧版结果表字段名。
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'recommendation_results' AND column_name = 'candidate_poi_id'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'recommendation_results' AND column_name = 'poi_id'
    ) THEN
        ALTER TABLE recommendation_results RENAME COLUMN candidate_poi_id TO poi_id;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'recommendation_results' AND column_name = 'rank_no'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'recommendation_results' AND column_name = 'rank'
    ) THEN
        ALTER TABLE recommendation_results RENAME COLUMN rank_no TO rank;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'recommendation_results' AND column_name = 'created_at'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'recommendation_results' AND column_name = 'generated_at'
    ) THEN
        ALTER TABLE recommendation_results RENAME COLUMN created_at TO generated_at;
    END IF;
END $$;

ALTER TABLE recommendation_results
    ADD COLUMN IF NOT EXISTS dataset VARCHAR(20) NOT NULL DEFAULT 'TKY';

ALTER TABLE recommendation_results
    ALTER COLUMN target_poi_id SET NOT NULL,
    ALTER COLUMN score SET NOT NULL,
    ALTER COLUMN generated_at SET DEFAULT NOW();

-- PostgreSQL 不支持 ADD CONSTRAINT IF NOT EXISTS，因此通过系统表判断。
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_recommendation_result_rank') THEN
        ALTER TABLE recommendation_results
            ADD CONSTRAINT uq_recommendation_result_rank UNIQUE (session_id, model_name, rank);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_recommendation_result_poi') THEN
        ALTER TABLE recommendation_results
            ADD CONSTRAINT uq_recommendation_result_poi UNIQUE (session_id, model_name, poi_id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_recommendation_results_user
    ON recommendation_results(user_id);

CREATE INDEX IF NOT EXISTS idx_recommendation_results_session_rank
    ON recommendation_results(session_id, rank);
