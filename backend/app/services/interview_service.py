"""
services/interview_service.py — Interview session business logic

Orchestrates the full interview flow:
  1. Create session → classify topic → generate questions
  2. Submit answer → evaluate via ML → store scores → update skill assessment
  3. Complete session → compute aggregate score → trigger roadmap regeneration

WHY a service layer?
  The endpoint calls one method; all DB queries, ML calls, and cache
  invalidation happen here. The endpoint stays under 30 lines.
  Business logic is testable without HTTP (just call the service).
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.core.metrics import metrics
from app.models.session import InterviewSession, SessionQuestion
from app.models.submission import Submission, SkillAssessment
from app.models.user import User
from app.schemas.interview import SessionCreate
from app.services.ml_client import MLClient, MLServiceError, get_ml_client
from app.services.question_bank import (
    adjust_difficulty,
    expand_question_bank,
    select_adaptive_question,
)

# ── Question bank ──────────────────────────────────────────────────────────────
# Curated questions per topic per difficulty.
# Production: store in DB so admins can add/edit questions via CMS.
# WHY not generate questions dynamically via LLM?
#   Dynamic generation risks hallucinated or poorly-calibrated questions.
#   A curated bank ensures consistent quality and difficulty calibration.
QUESTION_BANK: dict[str, dict[str, list[dict]]] = {
    "DSA": {
        "easy": [
            {"q": "What is the time complexity of binary search? When does it fail?",
             "a": "Binary search runs in O(log n) time by halving the search space each step. It requires a sorted array — it fails on unsorted data, linked lists (no random access), and when the comparison function is inconsistent."},
            {"q": "Explain the difference between a stack and a queue.",
             "a": "A stack is LIFO (Last In First Out) — push/pop from the same end. Used for: function call stacks, undo operations, DFS. A queue is FIFO (First In First Out) — enqueue at rear, dequeue from front. Used for: BFS, task scheduling, producer-consumer."},
            {"q": "What is the difference between an array and a linked list?",
             "a": "Arrays: contiguous memory, O(1) random access by index, O(n) insertion/deletion. Linked lists: nodes with pointers, O(n) access, O(1) insertion/deletion at known position. Arrays favor reads; linked lists favor dynamic size changes."},
        ],
        "medium": [
            {"q": "How does a hash table handle collisions? Compare chaining and open addressing.",
             "a": "Chaining: each bucket holds a linked list of all keys that hash to it. Simple, handles high load factors, but extra memory for pointers. Open addressing: on collision, probe for next open slot (linear, quadratic, or double hashing). Better cache performance, but degrades quickly above 70% load factor. Python dicts use open addressing; Java HashMap uses chaining."},
            {"q": "Explain dynamic programming. How do you identify if a problem has optimal substructure?",
             "a": "Dynamic programming solves problems by breaking them into overlapping subproblems, solving each once, and storing results (memoization or tabulation). Optimal substructure: optimal solution contains optimal solutions to subproblems. Overlapping subproblems: same subproblems recur (unlike divide-and-conquer). Indicators: 'minimum/maximum', 'how many ways', 'is it possible'."},
            {"q": "What is the difference between BFS and DFS? When do you choose each?",
             "a": "BFS explores level by level using a queue — finds shortest path in unweighted graphs. DFS explores as deep as possible using a stack (or recursion) — better for topological sort, cycle detection, and path existence. BFS uses O(w) space (w=width), DFS uses O(h) space (h=height). Choose BFS for shortest path, DFS for exhaustive search or tree operations."},
        ],
        "hard": [
            {"q": "Explain Dijkstra's algorithm. What are its limitations and how does A* improve on it?",
             "a": "Dijkstra's finds shortest paths from a source in graphs with non-negative edges. Uses a min-heap, relaxing edges greedily. O((V+E) log V) with a binary heap. Limitations: fails with negative edges (use Bellman-Ford), explores all directions equally. A* adds a heuristic h(n) estimating cost to goal — only explores promising directions. A* is optimal if h is admissible (never overestimates). Used in GPS navigation, game pathfinding."},
            {"q": "How would you find the k-th largest element in an unsorted array efficiently?",
             "a": "QuickSelect: partition around a pivot (like QuickSort), recurse only into the partition containing k-th element. Average O(n), worst O(n²). Use median-of-medians pivot for guaranteed O(n). Alternative: min-heap of size k — O(n log k). For streaming data where n is unknown: maintain a min-heap of k elements. For near-sorted data: partial sort is faster."},
        ],
    },
    "OS": {
        "easy": [
            {"q": "What is the difference between a process and a thread?",
             "a": "A process is an independent program in execution with its own memory space, file descriptors, and resources. A thread is a lightweight unit of execution within a process, sharing the process's memory and resources but with its own stack and registers. Processes are isolated (crash doesn't affect others); threads share state (one crash can kill all threads). Context switching between threads is cheaper than between processes."},
            {"q": "What are the four necessary conditions for deadlock?",
             "a": "Coffman conditions — ALL four must hold: (1) Mutual exclusion: resources can't be shared simultaneously. (2) Hold and wait: process holds a resource while waiting for another. (3) No preemption: resources can't be forcibly taken. (4) Circular wait: process A waits for B, B waits for C, C waits for A. Breaking any one condition prevents deadlock."},
        ],
        "medium": [
            {"q": "Explain how virtual memory works. What role does the page table play?",
             "a": "Virtual memory gives each process the illusion of its own large contiguous address space, independent of physical RAM. The OS divides memory into fixed-size pages (typically 4KB). The page table maps virtual page numbers to physical frame numbers. On memory access: CPU checks TLB (cache of recent translations) — hit=fast, miss=page table walk. If the page isn't in RAM (page fault), the OS loads it from disk (swap). Benefits: isolation, larger-than-RAM programs, simplified memory allocation."},
            {"q": "What is the difference between a mutex and a semaphore?",
             "a": "Mutex (mutual exclusion): binary lock, only the thread that locked it can unlock it. Used for protecting shared resources — ensures exclusive access. Semaphore: counter that can be incremented/decremented by any thread. Binary semaphore ≈ mutex but without ownership. Counting semaphore controls access to a pool of N resources. Key difference: mutex has ownership (can't release another thread's mutex), semaphore doesn't. Use mutex for mutual exclusion, semaphore for signaling between threads."},
        ],
        "hard": [
            {"q": "Explain the Linux completely fair scheduler (CFS). How does it achieve fairness?",
             "a": "CFS uses a red-black tree ordered by 'virtual runtime' — the amount of CPU time a process has received, weighted by priority (nice value). The scheduler always runs the task with lowest virtual runtime (leftmost node in the tree). After a time slice, the task's virtual runtime increases and it's reinserted. Lower-priority tasks have virtual runtime increase faster, so they run less. This achieves O(log n) scheduling decisions and true proportional fairness rather than discrete priority levels."},
        ],
    },
    "DBMS": {
        "easy": [
            {"q": "What are the ACID properties of a database transaction?",
             "a": "Atomicity: all operations in a transaction succeed or all fail — no partial states. Consistency: transaction brings DB from one valid state to another, respecting all constraints. Isolation: concurrent transactions execute as if sequential — no dirty reads. Durability: committed transactions survive crashes — written to durable storage. These four properties guarantee reliable transaction processing."},
            {"q": "What is the difference between a primary key and a foreign key?",
             "a": "Primary key: uniquely identifies each row in a table. Cannot be NULL, must be unique. Creates a clustered index automatically. A table has exactly one PK. Foreign key: a column in one table that references the primary key of another table. Enforces referential integrity — you can't insert a FK value that doesn't exist in the referenced table. A table can have many FKs."},
        ],
        "medium": [
            {"q": "How does a B-tree index improve query performance? When would you not use one?",
             "a": "A B-tree index stores data in a balanced tree where all leaves are at the same depth. Binary search finds any key in O(log n) instead of O(n) full table scan. Supports range queries (BETWEEN, >, <) unlike hash indexes. Not useful when: selectivity is low (boolean column — index skipped for <5% selectivity), write-heavy tables (every insert updates all indexes), full-table scans are needed, or columns have many NULLs. Also avoid indexing every column — index write overhead can outweigh read benefit."},
            {"q": "Explain the difference between INNER JOIN, LEFT JOIN, and a subquery. When do you prefer each?",
             "a": "INNER JOIN: returns only rows with matches in both tables. LEFT JOIN: returns all rows from left table, NULLs for unmatched right-side columns — use when you need all records regardless of match (e.g., all users with their order count, including users with no orders). Subquery: a query nested inside another — use for complex filtering or when result of one query feeds another. Prefer JOINs over correlated subqueries (correlated subqueries run once per row — O(n²)). Use EXISTS instead of IN for large sets."},
        ],
        "hard": [
            {"q": "Explain MVCC (Multi-Version Concurrency Control). How does PostgreSQL implement it?",
             "a": "MVCC allows concurrent reads without blocking writes by maintaining multiple versions of each row. In PostgreSQL: each row has xmin (transaction that created it) and xmax (transaction that deleted/updated it). A SELECT sees rows where xmin is committed and precedes the reader's snapshot, and xmax is either not set or not yet committed. Writers create new row versions rather than updating in place. Result: readers never block writers, writers never block readers. Downside: dead row versions accumulate — VACUUM reclaims them. This is why PostgreSQL's VACUUM process is critical."},
        ],
    },
    "CN": {
        "easy": [
            {"q": "What is the difference between TCP and UDP? When would you choose UDP?",
             "a": "TCP: connection-oriented, reliable delivery, ordered packets, flow control, congestion control. Three-way handshake before data. Used for: HTTP, email, file transfer. UDP: connectionless, no reliability guarantees, no ordering, no handshake, lower overhead. Used when: speed > reliability, application handles its own reliability, or multicast needed. Examples: DNS (single request/response), video streaming (stale frames useless), gaming (latency > reliability), VoIP."},
            {"q": "Walk me through the TCP three-way handshake.",
             "a": "Client sends SYN with random initial sequence number (ISN). Server responds SYN-ACK: acknowledges client's ISN+1, sends its own ISN. Client sends ACK: acknowledges server's ISN+1. Connection established. Purpose: synchronize sequence numbers for reliable ordered delivery, verify both sides can send and receive. Teardown uses four-way FIN/ACK exchange because each direction closes independently."},
        ],
        "medium": [
            {"q": "What happens step-by-step when you type 'https://example.com' in a browser?",
             "a": "1. DNS resolution: browser checks cache → OS cache → recursive DNS resolver → authoritative NS → IP address. 2. TCP connection: three-way handshake to server port 443. 3. TLS handshake: negotiate cipher suite, server sends certificate, client verifies CA chain, exchange session keys. 4. HTTP request: GET / HTTP/1.1 with headers. 5. Server processes request, returns HTML response. 6. Browser parses HTML, discovers resources (CSS/JS/images), makes parallel requests for each. 7. Render: parse DOM, apply CSSOM, layout, paint. Critical rendering path: minimize render-blocking resources."},
        ],
        "hard": [
            {"q": "Explain TCP congestion control. What are the four phases and why does this matter for application performance?",
             "a": "TCP congestion control prevents senders from overwhelming the network. Four phases: (1) Slow start: begin with cwnd=1 MSS, double cwnd each RTT until ssthresh. (2) Congestion avoidance: increase cwnd by 1 MSS per RTT — linear growth. (3) Fast retransmit: 3 duplicate ACKs indicate loss — retransmit without waiting for timeout. (4) Fast recovery: set ssthresh=cwnd/2, continue from new ssthresh. CUBIC (Linux default) uses cubic function for faster recovery on high-bandwidth links. Impact: bandwidth-delay product determines maximum throughput; TCP tuning (socket buffers, initial window size) is critical for high-latency connections like satellite links."},
        ],
    },
    "OOP": {
        "easy": [
            {"q": "Explain the four pillars of object-oriented programming with a concrete example of each.",
             "a": "Encapsulation: bundling data and methods, hiding internal state. Example: BankAccount with private balance, public deposit()/withdraw() — can't set balance directly. Inheritance: subclasses inherit from parent. Example: Vehicle → Car, Truck (share drive() logic). Polymorphism: same interface, different behavior. Example: shape.draw() calls Circle.draw() or Rectangle.draw() based on runtime type. Abstraction: exposing only necessary details. Example: List interface hides whether it's an ArrayList or LinkedList."},
            {"q": "What is the Liskov Substitution Principle? Give an example of a violation.",
             "a": "LSP: subclasses must be substitutable for their base class without breaking the program. Violation example: Square extends Rectangle — setWidth(5) on a Square also sets height=5, breaking the Rectangle contract. Any code assuming width and height are independent breaks. Fix: use a common Shape interface instead of inheritance. Another violation: ReadOnlyList extends List but throws on add() — violates the List contract. LSP violations indicate the inheritance hierarchy is wrong."},
        ],
        "medium": [
            {"q": "Compare composition and inheritance. Why is composition often preferred?",
             "a": "Inheritance ('is-a'): subclass tightly coupled to parent. Changes to parent break subclasses — fragile base class problem. Difficult to change at runtime. Composition ('has-a'): object contains instances of other objects. Loose coupling, swappable implementations, testable with mocks. Example: Logger injected into Service (composition) vs Service extends Logger (inheritance). Composition preferred when: behavior needs to vary at runtime, multiple behaviors needed (multiple inheritance problem), or you can't modify the class you'd inherit from. Rule of thumb: prefer composition, use inheritance only for true 'is-a' relationships with stable hierarchies."},
        ],
        "hard": [
            {"q": "Explain the SOLID principles and how they relate to each other.",
             "a": "SRP (Single Responsibility): one class, one reason to change — limits blast radius of changes. OCP (Open/Closed): open for extension, closed for modification — add behavior via new classes, not edits. Violating OCP often means missing an abstraction. LSP (Liskov Substitution): subtypes must honor their contracts — ensures polymorphism is safe. ISP (Interface Segregation): many specific interfaces > one general interface — clients shouldn't depend on methods they don't use. DIP (Dependency Inversion): depend on abstractions not concretions — enables testing (inject mocks) and flexibility (swap implementations). They reinforce each other: DIP requires abstractions (OCP), ISP makes abstractions granular (SRP), LSP makes abstractions safe."},
        ],
    },
    "System Design": {
        "easy": [
            {"q": "Explain the CAP theorem with a real database example for each combination.",
             "a": "CAP: in a distributed system, you can guarantee at most 2 of: Consistency (all nodes see same data), Availability (every request gets a response), Partition tolerance (system works despite network failures). Since network partitions always happen in practice, real systems choose CP or AP. CP (consistent, partition-tolerant): HBase, ZooKeeper — reject requests during partition to stay consistent. AP (available, partition-tolerant): Cassandra, DynamoDB — serve potentially stale data during partition. Traditional RDBMS (single node): CA — consistent and available, but can't tolerate partitions."},
        ],
        "medium": [
            {"q": "Design a URL shortening service. Walk through your architecture.",
             "a": "Core: encode long URL → 6-7 char short code (base62: a-z, A-Z, 0-9 = 62^7 = 3.5T unique URLs). Storage: PostgreSQL for URL mappings (short_code → long_url, created_at, user_id, click_count). On redirect: Redis cache (short_code → long_url, TTL=24h) — cache hit ratio >95% for popular URLs. Cache miss: DB lookup, populate cache. Write path: generate short code (hash or counter + base62 encode), check collision, store. Scale: read-heavy (100:1 read/write), Redis cluster handles reads. Analytics: async — write click events to Kafka, consume into analytics DB. Rate limit: 10 shortens/min per IP."},
            {"q": "How would you design a distributed rate limiter?",
             "a": "Token bucket in Redis: INCRBY key 1 EX 60 — atomic increment with TTL. If count > limit → 429. Problem: race between GET/SET — use INCR which is atomic. Sliding window: sorted set of timestamps per user — ZADD + ZREMRANGEBYSCORE + ZCARD. More accurate but more memory. Distributed: use Redis cluster, hash user_id to shard. At Nginx layer: limit_req_zone for IP-based limiting before Python wakes up. At application layer: user-based limiting for authenticated endpoints. Return Retry-After header so clients back off intelligently. Fail open if Redis is down — don't block legitimate traffic."},
        ],
        "hard": [
            {"q": "Design a notification system for a social media platform handling 10M daily active users.",
             "a": "Fan-out on write vs read: fan-out on write (push to followers' feeds on post) works for <10K followers — Kafka topic per event type, workers push to user notification queues. Celebrity problem: fan-out on read for accounts with >1M followers — too expensive to push to 1M queues synchronously. Hybrid: push for normal users, pull for celebrities. Storage: Redis sorted set per user (notification_id, timestamp as score) for inbox. Postgres for durable notification records. Delivery: WebSocket for real-time (connected users), APNs/FCM push for mobile, email via SendGrid for offline. Deduplication: exactly-once with idempotency keys. Prioritization: DLQ for failed deliveries, retry with exponential backoff."},
        ],
    },
}

QUESTION_BANK = expand_question_bank(QUESTION_BANK)


def get_questions_for_session(topic: str, difficulty: str, count: int = 3) -> list[dict]:
    """Return questions for a session. Returns up to `count` questions."""
    topic_bank = QUESTION_BANK.get(topic, {})
    difficulty_questions = topic_bank.get(difficulty, [])
    if not difficulty_questions:
        # Fall back to medium if difficulty not found
        difficulty_questions = topic_bank.get("medium", [])
    return difficulty_questions[:count]


class InterviewService:
    """
    Orchestrates the complete interview session lifecycle.

    Dependencies injected so they can be mocked in tests:
      db: async SQLAlchemy session
      ml_client: ML service HTTP client
      cache: CacheService for Redis operations
    """

    def __init__(self, db: AsyncSession, ml_client: MLClient = None, cache=None):
        self.db = db
        self.ml = ml_client or get_ml_client()
        self.cache = cache

    # ── Session management ─────────────────────────────────────────────────────

    async def create_session(self, user: User, data: SessionCreate) -> InterviewSession:
        """
        Create a new adaptive interview session.

        Steps:
          1. Create the InterviewSession row
          2. Let the client request one adaptive question at a time
          3. Update metrics
        """
        session = InterviewSession(
            user_id=user.id,
            topic=data.topic,
            difficulty=data.difficulty,
            status="active",
        )
        self.db.add(session)
        await self.db.flush()  # Get session.id without committing

        metrics.interviews_started.inc()
        log = logger.bind(
            session_id=str(session.id),
            topic=data.topic,
            difficulty=data.difficulty,
            user_id=str(user.id),
        )
        log.info("interview.session_started")

        return session

    async def get_sessions(self, user_id: uuid.UUID) -> list[InterviewSession]:
        """Fetch all sessions for a user, newest first."""
        result = await self.db.execute(
            select(InterviewSession)
            .where(InterviewSession.user_id == user_id)
            .order_by(InterviewSession.started_at.desc())
        )
        return result.scalars().all()

    async def get_session(self, session_id: uuid.UUID, user_id: uuid.UUID) -> Optional[InterviewSession]:
        """Fetch a single session — enforces ownership."""
        result = await self.db.execute(
            select(InterviewSession)
            .where(
                InterviewSession.id == session_id,
                InterviewSession.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_questions(self, session_id: uuid.UUID) -> list[SessionQuestion]:
        """Get all questions for a session, in order."""
        result = await self.db.execute(
            select(SessionQuestion)
            .where(SessionQuestion.session_id == session_id)
            .order_by(SessionQuestion.order_index)
        )
        return result.scalars().all()

    async def next_question(
        self,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> SessionQuestion | None:
        """
        Issue one adaptive question, or return None when the bank is exhausted.

        Returning an existing unanswered question makes retries idempotent: a
        refresh cannot skip a question or create duplicate attempts.
        """
        from fastapi import HTTPException, status

        session = await self.get_session(session_id, user_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        if session.status != "active":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Session is already {session.status}",
            )

        unanswered = await self._get_unanswered_question(session_id)
        if unanswered is not None:
            return unanswered

        last_score = await self._get_latest_session_score(session_id)
        target_difficulty = adjust_difficulty(session.difficulty, last_score)
        attempted_ids = await self._get_attempted_question_ids(user_id, session.topic)
        skill_scores = await self._get_skill_scores(user_id, session.topic)
        selected = select_adaptive_question(
            QUESTION_BANK,
            session.topic,
            target_difficulty,
            attempted_ids,
            skill_scores,
        )
        if selected is None:
            return None

        existing_questions = await self.get_questions(session_id)
        question = SessionQuestion(
            session_id=session.id,
            question_bank_id=selected["id"],
            question_text=selected["q"],
            ideal_answer=selected["a"],
            skill_topic=session.topic,
            skill_tag=selected["skill"],
            difficulty=selected["difficulty"],
            order_index=len(existing_questions) + 1,
        )
        session.difficulty = selected["difficulty"]
        self.db.add(question)
        await self.db.flush()
        return question

    async def _get_unanswered_question(
        self,
        session_id: uuid.UUID,
    ) -> SessionQuestion | None:
        result = await self.db.execute(
            select(SessionQuestion)
            .outerjoin(Submission, Submission.question_id == SessionQuestion.id)
            .where(
                SessionQuestion.session_id == session_id,
                Submission.id.is_(None),
            )
            .order_by(SessionQuestion.order_index)
        )
        return result.scalars().first()

    async def _get_latest_session_score(self, session_id: uuid.UUID) -> float | None:
        result = await self.db.execute(
            select(Submission.similarity_score)
            .join(SessionQuestion, Submission.question_id == SessionQuestion.id)
            .where(
                SessionQuestion.session_id == session_id,
                Submission.similarity_score.is_not(None),
            )
            .order_by(Submission.submitted_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _get_attempted_question_ids(
        self,
        user_id: uuid.UUID,
        topic: str,
    ) -> set[str]:
        result = await self.db.execute(
            select(SessionQuestion.question_bank_id)
            .join(Submission, Submission.question_id == SessionQuestion.id)
            .join(InterviewSession, SessionQuestion.session_id == InterviewSession.id)
            .where(
                InterviewSession.user_id == user_id,
                InterviewSession.topic == topic,
                SessionQuestion.question_bank_id.is_not(None),
            )
        )
        return {question_id for question_id, in result.all()}

    async def _get_skill_scores(
        self,
        user_id: uuid.UUID,
        topic: str,
    ) -> dict[str, float]:
        result = await self.db.execute(
            select(SessionQuestion.skill_tag, func.avg(Submission.similarity_score))
            .join(Submission, Submission.question_id == SessionQuestion.id)
            .join(InterviewSession, SessionQuestion.session_id == InterviewSession.id)
            .where(
                InterviewSession.user_id == user_id,
                InterviewSession.topic == topic,
                SessionQuestion.skill_tag.is_not(None),
                Submission.similarity_score.is_not(None),
            )
            .group_by(SessionQuestion.skill_tag)
        )
        return {skill_tag: score for skill_tag, score in result.all()}

    # ── Answer submission ──────────────────────────────────────────────────────

    async def submit_answer(
        self,
        question_id: uuid.UUID,
        user_id: uuid.UUID,
        answer_text: str,
    ) -> Submission:
        """
        Submit and score one answer.

        Flow:
          1. Verify the question belongs to this user's session
          2. Save the answer immediately (don't wait for ML)
          3. Call ML service for scoring — graceful degradation if unavailable
          4. Update submission with scores
          5. Update aggregate SkillAssessment for this topic

        WHY save before scoring?
          If the ML service is slow or down, the answer is preserved.
          Scoring can be retried asynchronously. User's work is never lost.
        """
        from fastapi import HTTPException, status

        # Verify ownership via session → question relationship
        question_result = await self.db.execute(
            select(SessionQuestion)
            .join(InterviewSession, SessionQuestion.session_id == InterviewSession.id)
            .where(
                SessionQuestion.id == question_id,
                InterviewSession.user_id == user_id,
            )
        )
        question = question_result.scalar_one_or_none()

        if question is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Question not found or doesn't belong to your session",
            )

        # 1. Save submission immediately
        submission = Submission(
            question_id=question_id,
            answer_text=answer_text,
        )
        self.db.add(submission)
        await self.db.flush()

        # 2. Score via ML service (graceful degradation)
        similarity_score = None
        confidence_score = None
        ai_feedback = None

        try:
            ml_result = await self.ml.evaluate_answer(
                candidate_answer=answer_text,
                ideal_answer=question.ideal_answer,
                topic=question.skill_topic,
                question=question.question_text,
            )
            similarity_score = ml_result.get("similarity_score")
            confidence_score = ml_result.get("confidence_score")
            final_score = ml_result.get("final_score")

            # Compose feedback as a JSON string for storage
            import json
            feedback_data = ml_result.get("feedback", {})
            if isinstance(feedback_data, dict):
                ai_feedback = json.dumps(feedback_data)
            else:
                ai_feedback = str(feedback_data)

            metrics.answers_scored.inc()

            # 3. Update skill assessment
            if similarity_score is not None:
                await self._update_skill_assessment(
                    user_id=user_id,
                    topic=question.skill_topic,
                    new_score=final_score / 100.0 if final_score else similarity_score,
                )

        except MLServiceError as e:
            metrics.ml_service_errors.inc()
            logger.warning(
                "ml_service.evaluation_failed",
                question_id=str(question_id),
                error=str(e)[:200],
            )
            # Continue — submission is saved, scores will be null

        # 4. Persist scores
        submission.similarity_score = similarity_score
        submission.confidence_score = confidence_score
        submission.ai_feedback = ai_feedback
        await self.db.flush()

        logger.info(
            "interview.answer_submitted",
            question_id=str(question_id),
            score=similarity_score,
            ml_available=similarity_score is not None,
        )

        return submission

    async def _update_skill_assessment(
        self,
        user_id: uuid.UUID,
        topic: str,
        new_score: float,
    ) -> None:
        """
        UPSERT a SkillAssessment row using running weighted average.

        WHY weighted average and not simple average?
          Recent performance matters more than old performance.
          A user who scored 0.3 ten times then 0.9 twice is improving —
          simple average (0.42) understates their current level.
          Running average with decay: new_avg = 0.7 * old_avg + 0.3 * new_score
          This is the exponential moving average formula used in monitoring.
        """
        result = await self.db.execute(
            select(SkillAssessment)
            .where(
                SkillAssessment.user_id == user_id,
                SkillAssessment.skill_topic == topic,
            )
        )
        assessment = result.scalar_one_or_none()

        if assessment is None:
            assessment = SkillAssessment(
                user_id=user_id,
                skill_topic=topic,
                proficiency_score=new_score,
                attempts=1,
            )
            self.db.add(assessment)
        else:
            # Exponential moving average: emphasises recent performance
            alpha = 0.3  # Weight for new observation
            assessment.proficiency_score = (
                (1 - alpha) * assessment.proficiency_score + alpha * new_score
            )
            assessment.attempts += 1

        await self.db.flush()

        # Invalidate cached skill assessments — data has changed
        if self.cache:
            await self.cache.invalidate_skill_assessments(user_id)

    # ── Session completion ─────────────────────────────────────────────────────

    async def complete_session(
        self,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> InterviewSession:
        """
        Mark a session as completed and compute aggregate score.

        Aggregate score = average of all submission final scores.
        Uses similarity_score if final_score is not stored directly.
        """
        from fastapi import HTTPException, status

        session = await self.get_session(session_id, user_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        if session.status != "active":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Session is already {session.status}",
            )

        # Fetch all submissions for this session's questions
        result = await self.db.execute(
            select(Submission)
            .join(SessionQuestion, Submission.question_id == SessionQuestion.id)
            .where(SessionQuestion.session_id == session_id)
        )
        submissions = result.scalars().all()

        scored = [s for s in submissions if s.similarity_score is not None]
        if scored:
            avg = sum(s.similarity_score for s in scored) / len(scored)
            session.score = round(avg * 100)

        session.status = "completed"
        session.ended_at = datetime.now(timezone.utc)
        await self.db.flush()

        metrics.interviews_completed.inc()
        logger.info(
            "interview.session_completed",
            session_id=str(session_id),
            score=session.score,
            questions_answered=len(submissions),
        )

        # Invalidate roadmap cache — skill scores may have changed
        if self.cache:
            await self.cache.invalidate_roadmap(user_id)

        return session

    async def abandon_session(
        self,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> InterviewSession:
        """Mark a session as abandoned (user left mid-session)."""
        session = await self.get_session(session_id, user_id)
        if session is None:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Session not found")
        session.status = "abandoned"
        session.ended_at = datetime.now(timezone.utc)
        await self.db.flush()
        return session

    async def get_submissions_for_session(
        self,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[dict]:
        """
        Get all Q&A pairs with scores for a completed session.
        Used by the results page to show full session review.
        """
        # Verify ownership
        session = await self.get_session(session_id, user_id)
        if session is None:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Session not found")

        result = await self.db.execute(
            select(SessionQuestion, Submission)
            .outerjoin(Submission, Submission.question_id == SessionQuestion.id)
            .where(SessionQuestion.session_id == session_id)
            .order_by(SessionQuestion.order_index)
        )
        rows = result.all()

        import json
        return [
            {
                "question": q.question_text,
                "skill_topic": q.skill_topic,
                "order_index": q.order_index,
                "answer_text": s.answer_text if s else None,
                "similarity_score": s.similarity_score if s else None,
                "confidence_score": s.confidence_score if s else None,
                "ai_feedback": json.loads(s.ai_feedback) if s and s.ai_feedback else None,
                "submitted_at": s.submitted_at.isoformat() if s and s.submitted_at else None,
            }
            for q, s in rows
        ]
