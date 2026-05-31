# DevMentor AI — Indexing Strategy

## What is a database index?

An index is a separate data structure (usually a B-tree) that the database
maintains alongside the table. It stores a sorted copy of one or more columns,
with pointers back to the full row.

**Without an index:** PostgreSQL reads EVERY row (full table scan) — O(n)
**With an index:** PostgreSQL jumps directly to matching rows — O(log n)

At 1,000 users: negligible difference.
At 1,000,000 users: the difference between 2ms and 4,000ms.

## Index cost tradeoff

Indexes are NOT free:
- **Write overhead:** Every INSERT/UPDATE/DELETE must update all indexes on that table
- **Storage overhead:** Each index is a copy of (some) data
- **Memory:** Postgres tries to keep frequently-used indexes in shared_buffers (RAM)

Rule of thumb: index columns you filter or sort by in WHERE/ORDER BY/JOIN ON.
Don't index columns you never query on.

## Our indexes and why they exist

### `users` table
| Index | Columns | Reason |
|---|---|---|
| PRIMARY KEY | id | All FK lookups |
| UNIQUE ix_users_email | email | Login query: `WHERE email = ?` |
| ix_users_role_active | role, is_active | Admin dashboard: `WHERE role='admin' AND is_active=true` |

### `interview_sessions` table
| Index | Columns | Reason |
|---|---|---|
| PRIMARY KEY | id | All FK lookups |
| ix_..._user_id | user_id | `WHERE user_id = ?` — most common query |
| ix_..._status | status | `WHERE status = 'active'` — background job query |
| ix_sessions_user_topic_status | user_id, topic, status | Analytics page composite query |

**Composite index order matters:** PostgreSQL can use a composite index for
queries on the LEADING columns. `(user_id, topic, status)` supports:
- `WHERE user_id = ?` ✓
- `WHERE user_id = ? AND topic = ?` ✓
- `WHERE user_id = ? AND topic = ? AND status = ?` ✓
- `WHERE topic = ?` ✗ (topic is not the leading column)

### `skill_assessments` table
| Index | Columns | Reason |
|---|---|---|
| UNIQUE ix_..._user_topic | user_id, skill_topic | Enforces one row per (user, topic) — enables UPSERT |

The UNIQUE constraint here is doing double duty: it's both an index (fast lookup)
AND a constraint (prevents duplicate assessments per user-topic pair).

## EXPLAIN ANALYZE — how to verify an index is being used

```sql
EXPLAIN ANALYZE
SELECT * FROM interview_sessions
WHERE user_id = '...' AND topic = 'DSA' AND status = 'completed';
```

Look for: `Index Scan using ix_sessions_user_topic_status` ← index used ✓
Avoid:     `Seq Scan on interview_sessions` ← full table scan, needs an index

## Interview questions

1. **"What is the difference between a clustered and non-clustered index?"**
   PostgreSQL doesn't have clustered indexes in the SQL Server sense.
   The primary key in Postgres is always a B-tree index. CLUSTER command
   physically reorders rows to match an index — one-time operation.

2. **"When would adding an index make things SLOWER?"**
   On tables with very high write rates (e.g., a logs table getting 10k inserts/sec).
   Every insert must update every index. Use partial indexes or write to a staging
   table first, then batch-move to the indexed table.

3. **"What is a partial index?"**
   An index with a WHERE clause — only indexes rows matching the condition.
   `CREATE INDEX ix_active_sessions ON interview_sessions(user_id) WHERE status = 'active'`
   Much smaller than a full index when only a fraction of rows match.

4. **"What is a covering index?"**
   An index that contains all columns a query needs — Postgres can answer
   the query from the index alone without touching the actual table rows.
   Dramatically reduces I/O.
