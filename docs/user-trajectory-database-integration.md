# User Trajectory Database Integration

## Goal

This stage moves the user trajectory flow from mock CSV data to PostgreSQL:

users -> checkins -> sessions -> trajectory API -> Vue page -> Cesium layer.

The POI module remains unchanged and still reads the `pois` table. Recommendation results, model metrics, and online inference are not changed.

## Changed Files

- `backend/app/models/user.py`
- `backend/app/models/checkin.py`
- `backend/app/models/session.py`
- `backend/app/schemas/user_trajectory.py`
- `backend/app/services/user_service.py`
- `backend/app/services/session_service.py`
- `backend/app/api/users.py`
- `backend/app/api/sessions.py`
- `backend/app/main.py`
- `backend/migrations/20260714_user_sessions.sql`
- `backend/migrations/20260714_data_quality_checks.sql`
- `backend/scripts/build_sessions.py`
- `frontend/src/api/request.ts`
- `frontend/src/api/trajectory.ts`
- `frontend/src/types/index.ts`
- `frontend/src/views/TrajectoryView.vue`
- `frontend/src/components/CesiumMap.vue`

## Data Chain

`GET /api/users` queries the `users` table with pagination and optional keyword search.

`GET /api/users/{user_id}/checkins` queries `checkins` and joins `pois` on `venue_id` to return display name, category, longitude, and latitude.

`GET /api/users/{user_id}/sessions` queries the persisted `sessions` table.

`GET /api/sessions/{session_id}/trajectory` queries `sessions`, then joins `checkins` and `pois` to return ordered trajectory points without `geom`.

## Session Model

The SQL migration creates:

- `sessions(session_id, user_id, start_time, end_time, checkin_count, dataset)`
- `checkins.session_id`
- `checkins.sequence_no`

It also creates indexes for `checkins(user_id)`, `checkins(venue_id)`, `checkins(user_id, utc_timestamp)`, `sessions(user_id)`, and `checkins(session_id, sequence_no)`.

## Session Rule

No reusable preprocessing function was found in the current project, so the documented 24-hour rule is used:

1. Sort each user's check-ins by `utc_timestamp`.
2. The first check-in starts a session.
3. If the gap to the previous check-in is greater than 24 hours, start a new session.
4. Assign `sequence_no` from 1 inside each session.
5. Keep single-check-in sessions.
6. Generate stable IDs as `{user_id}_{session_index:05d}`, for example `470_00001`.

## Migration Steps

Run the schema migration first:

```bash
cd backend
psql "$DATABASE_URL" -f migrations/20260714_user_sessions.sql
```

Preview session statistics:

```bash
python scripts/build_sessions.py --dataset TKY --dry-run
```

Write sessions and backfill check-ins:

```bash
python scripts/build_sessions.py --dataset TKY
```

The script is designed to be rerunnable for the selected dataset. It clears existing rows in `sessions` for that dataset, resets `checkins.session_id` and `checkins.sequence_no`, and rebuilds them in one transaction.

## Data Quality Checks

Run:

```bash
psql "$DATABASE_URL" -f migrations/20260714_data_quality_checks.sql
```

The checks report:

- check-ins without a matching user
- check-ins without a matching POI
- check-ins with a null timestamp
- sessions whose stored `checkin_count` differs from actual check-ins

Database contents were not available in this coding environment, so the actual quality counts must be collected after running the SQL locally.

## Frontend Flow

The trajectory page now:

1. Searches users through `GET /api/users`.
2. Loads sessions through `GET /api/users/{user_id}/sessions`.
3. Loads trajectory points through `GET /api/sessions/{session_id}/trajectory`.
4. Draws ordered points and a connected polyline in Cesium.
5. Shows sequence number, POI display name, category, timestamp, and coordinates in the side timeline.

The page uses separate request sequence guards for users, sessions, and trajectories so late responses do not overwrite the current selection.

## Cesium Rendering

`CesiumMap.vue` now clears old trajectory entities before drawing a new session, adds stable entity IDs, stores trajectory metadata in entity properties, marks start and end points, draws the ordered polyline, and flies to the full trajectory bounds. A single-point session flies to that point with a fixed altitude.

## Mock Migration

The frontend trajectory page no longer reads mock trajectory endpoints. `backend/app/main.py` no longer mounts `/api/trajectories`.

Mock files and legacy trajectory service code are kept because the recommendation module still uses mock recommendation data and history. Recommendation and metrics mock logic was not removed in this stage.

## Verification

Completed in this environment:

- `python -m compileall backend\app backend\scripts`
- `npm.cmd --prefix frontend run build`
- FastAPI OpenAPI generation shows the new paths.

Not completed here:

- Live Swagger requests against PostgreSQL.
- Session backfill statistics.
- Cesium browser visual inspection with real database data.

Those require the local PostgreSQL database to be migrated and populated.

## Next Stage

The offline inference bridge is now available. Apply the result-table migration,
install both backend and model dependencies, and run it from the repository root:

```powershell
psql "$env:DATABASE_URL" -f backend/migrations/20260715_recommendation_results.sql
pip install -r backend/requirements.txt
pip install -r RecModel/requirements.txt
python backend/scripts/generate_recommendations.py --dataset TKY --top-k 10 --limit 20
python backend/scripts/generate_recommendations.py --dataset TKY --top-k 10 --write-db
```

For each session, the last check-in is held out as `target_poi_id`; the preceding
check-ins are the short-term sequence. Sessions with fewer than two joined points,
an out-of-vocabulary target, or an out-of-vocabulary final history POI are reported
and skipped. The script always exports
`backend/exports/recommendation_results_TKY.csv`; `--write-db` additionally replaces
the selected sessions' rows for model `T10e2_CausalMemoryFusion` in one transaction.

The model vocabulary is rebuilt from the bundled TKY temporal training split so
database `venue_id` values map to the same embedding rows as the checkpoint. Do not
create a new vocabulary from database rows.
