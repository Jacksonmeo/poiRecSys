# User Trajectory API

Base URL: `/api`

## `GET /users`

Query users from PostgreSQL.

Parameters:

- `keyword?: string`
- `skip: number = 0`
- `limit: number = 20`, max `100`

Response:

```json
{
  "items": [
    {
      "id": 1,
      "user_id": "470"
    }
  ],
  "total": 1082,
  "skip": 0,
  "limit": 20
}
```

## `GET /users/{user_id}/checkins`

Query check-ins for one user, joined with POI display fields.

Parameters:

- `start_time?: datetime`, ISO 8601
- `end_time?: datetime`, ISO 8601
- `limit: number = 5000`, max `5000`

Response:

```json
[
  {
    "id": 1001,
    "user_id": "470",
    "venue_id": "4f0fd5a8e4b03856eeb6c8cb",
    "display_name": "Coffee Shop e6c8cb",
    "venue_category_id": "4bf58dd8d48988d1e0931735",
    "venue_category": "Coffee Shop",
    "longitude": 139.7012,
    "latitude": 35.6586,
    "timezone_offset": 540,
    "utc_timestamp": "2012-05-01T08:30:00Z"
  }
]
```

## `GET /users/{user_id}/sessions`

Query persisted sessions for one user.

Parameters:

- `skip: number = 0`
- `limit: number = 20`, max `100`

Response:

```json
{
  "items": [
    {
      "session_id": "470_00001",
      "user_id": "470",
      "start_time": "2012-04-03T02:00:00Z",
      "end_time": "2012-04-03T12:00:00Z",
      "checkin_count": 5,
      "dataset": "TKY"
    }
  ],
  "total": 12,
  "skip": 0,
  "limit": 20
}
```

## `GET /sessions/{session_id}/trajectory`

Query ordered trajectory points for one session.

Response:

```json
{
  "session": {
    "session_id": "470_00001",
    "user_id": "470",
    "start_time": "2012-04-03T02:00:00Z",
    "end_time": "2012-04-03T12:00:00Z",
    "checkin_count": 5,
    "dataset": "TKY"
  },
  "points": [
    {
      "sequence_no": 1,
      "venue_id": "4f0fd5a8e4b03856eeb6c8cb",
      "display_name": "Coffee Shop e6c8cb",
      "venue_category": "Coffee Shop",
      "longitude": 139.7012,
      "latitude": 35.6586,
      "utc_timestamp": "2012-04-03T02:00:00Z"
    }
  ]
}
```

## Error Codes

- `404`: user or session not found.
- `422`: invalid query parameter, empty path value, bad datetime, or limit out of range.
- `500`: database query failure. The API returns a readable message and does not expose raw stack traces.

## Swagger Checks

After migration and backfill:

1. Start backend: `uvicorn app.main:app --reload --port 8000`.
2. Open `http://127.0.0.1:8000/docs`.
3. Test `GET /api/users?skip=0&limit=20`.
4. Pick a `user_id` and test `GET /api/users/{user_id}/sessions`.
5. Pick a `session_id` and test `GET /api/sessions/{session_id}/trajectory`.
