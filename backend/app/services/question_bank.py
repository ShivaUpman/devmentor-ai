"""Curated metadata and deterministic helpers for adaptive interview questions."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

DIFFICULTIES = ("easy", "medium", "hard")
QUESTIONS_PER_BUCKET = 15

# Each concept is intentionally static. The templates vary coaching depth by
# difficulty, but no runtime LLM is involved in question generation.
SKILL_CATALOG: dict[str, dict[str, list[tuple[str, str]]]] = {
    "DSA": {
        "complexity": [
            ("asymptotic analysis", "Big-O, Big-Theta, worst-case cost, and input size"),
            ("amortized analysis", "dynamic arrays, occasional resizing, and average operation cost"),
            ("space complexity", "auxiliary memory, recursion depth, and time-space trade-offs"),
        ],
        "linear-structures": [
            ("arrays and linked lists", "random access, insertion cost, memory layout, and cache locality"),
            ("stacks and queues", "LIFO versus FIFO behavior and common traversal use cases"),
            ("heaps", "priority ordering, heap operations, and priority queue use cases"),
        ],
        "trees-graphs": [
            ("tree traversal", "preorder, inorder, postorder, breadth-first traversal, and recursion"),
            ("graph traversal", "BFS, DFS, visited sets, and disconnected components"),
            ("shortest paths", "weighted edges, negative edges, and algorithm selection"),
        ],
        "hashing": [
            ("hash tables", "hash functions, collisions, load factor, and expected lookup cost"),
            ("collision resolution", "chaining, open addressing, probing, and resize behavior"),
            ("sets and maps", "membership checks, key-value lookup, and duplicate handling"),
        ],
        "problem-solving": [
            ("dynamic programming", "overlapping subproblems, optimal substructure, memoization, and tabulation"),
            ("greedy algorithms", "local choices, proof of correctness, and counterexamples"),
            ("divide and conquer", "recursive decomposition, merge steps, and recurrence relations"),
        ],
    },
    "OS": {
        "processes-threads": [
            ("processes and threads", "address spaces, shared state, context switches, and isolation"),
            ("context switching", "register state, scheduler overhead, and cache effects"),
            ("inter-process communication", "pipes, sockets, shared memory, and synchronization"),
        ],
        "memory": [
            ("virtual memory", "pages, frames, page tables, TLBs, and page faults"),
            ("memory allocation", "stack, heap, fragmentation, and allocator behavior"),
            ("page replacement", "working sets, LRU approximations, thrashing, and swap"),
        ],
        "concurrency": [
            ("mutexes and semaphores", "ownership, counters, critical sections, and signaling"),
            ("race conditions", "interleavings, atomic operations, and synchronization"),
            ("deadlocks", "Coffman conditions, prevention, detection, and recovery"),
        ],
        "scheduling": [
            ("CPU scheduling", "throughput, latency, fairness, starvation, and preemption"),
            ("round-robin scheduling", "time quantum selection, responsiveness, and overhead"),
            ("priority scheduling", "priority inversion, starvation, and aging"),
        ],
        "storage": [
            ("file systems", "files, directories, metadata, inodes, and allocation"),
            ("disk I/O", "buffering, caching, seek cost, and batching"),
            ("journaling", "crash recovery, write ordering, and durability trade-offs"),
        ],
    },
    "DBMS": {
        "transactions": [
            ("ACID transactions", "atomicity, consistency, isolation, durability, and rollback"),
            ("isolation levels", "dirty reads, non-repeatable reads, phantom reads, and serialization"),
            ("MVCC", "snapshots, row versions, concurrent readers, writers, and cleanup"),
        ],
        "indexing": [
            ("B-tree indexes", "balanced trees, range scans, selectivity, and write overhead"),
            ("composite indexes", "column order, leftmost-prefix matching, and query patterns"),
            ("query plans", "table scans, index scans, cardinality estimates, and EXPLAIN"),
        ],
        "modeling": [
            ("normalization", "functional dependencies, update anomalies, and normal forms"),
            ("denormalization", "read performance, duplication, consistency, and maintenance cost"),
            ("database constraints", "primary keys, foreign keys, uniqueness, and check constraints"),
        ],
        "sql": [
            ("SQL joins", "inner joins, outer joins, join keys, and result cardinality"),
            ("aggregations", "GROUP BY, HAVING, aggregate functions, and filtering order"),
            ("subqueries and CTEs", "readability, correlated execution, and optimization"),
        ],
        "scaling": [
            ("replication", "primary replicas, read scaling, lag, and failover"),
            ("partitioning", "partition keys, pruning, hotspots, and operational complexity"),
            ("connection pooling", "connection cost, pool sizing, queuing, and backpressure"),
        ],
    },
    "CN": {
        "transport": [
            ("TCP and UDP", "reliability, ordering, congestion control, latency, and use cases"),
            ("TCP handshakes", "sequence numbers, SYN, ACK, connection setup, and teardown"),
            ("TCP congestion control", "slow start, congestion avoidance, packet loss, and recovery"),
        ],
        "web": [
            ("HTTP request handling", "methods, headers, status codes, connections, and caching"),
            ("HTTPS", "TLS handshakes, certificates, session keys, and trust chains"),
            ("HTTP caching", "Cache-Control, validators, intermediaries, and invalidation"),
        ],
        "routing": [
            ("IP routing", "addresses, prefixes, routing tables, hops, and gateways"),
            ("subnetting", "CIDR notation, network ranges, masks, and address allocation"),
            ("NAT", "private addresses, translation tables, ports, and inbound connectivity"),
        ],
        "naming": [
            ("DNS resolution", "recursive resolvers, authoritative servers, records, and caching"),
            ("DNS records", "A, AAAA, CNAME, MX, TXT, TTLs, and operational use"),
            ("service discovery", "health-aware lookup, registration, caching, and failure handling"),
        ],
        "reliability": [
            ("load balancing", "distribution policies, health checks, affinity, and failover"),
            ("timeouts and retries", "latency budgets, duplicate work, backoff, and jitter"),
            ("network observability", "latency, throughput, packet loss, tracing, and diagnostics"),
        ],
    },
    "OOP": {
        "foundations": [
            ("encapsulation", "state protection, public behavior, invariants, and change isolation"),
            ("polymorphism", "interfaces, substitutable implementations, dispatch, and extensibility"),
            ("abstraction", "contracts, hidden details, dependency boundaries, and maintainability"),
        ],
        "solid": [
            ("single responsibility", "reasons to change, cohesion, and maintainable class boundaries"),
            ("Liskov substitution", "behavioral contracts, substitutability, and inheritance mistakes"),
            ("dependency inversion", "abstractions, injected dependencies, testing, and flexibility"),
        ],
        "composition": [
            ("composition versus inheritance", "coupling, reuse, runtime flexibility, and stable hierarchies"),
            ("dependency injection", "construction, interfaces, mocks, and lifecycle management"),
            ("delegation", "responsibility handoff, collaboration, and reducing inheritance depth"),
        ],
        "patterns": [
            ("strategy pattern", "interchangeable algorithms, interfaces, and runtime selection"),
            ("factory pattern", "construction logic, encapsulation, and dependency creation"),
            ("observer pattern", "subscriptions, notifications, decoupling, and lifecycle cleanup"),
        ],
        "design-quality": [
            ("cohesion and coupling", "focused responsibilities, dependencies, and change impact"),
            ("interface segregation", "small contracts, client needs, and avoiding unused methods"),
            ("testable object design", "determinism, dependency boundaries, mocks, and state control"),
        ],
    },
    "System Design": {
        "scalability": [
            ("horizontal scaling", "stateless services, load balancing, coordination, and bottlenecks"),
            ("caching", "cache-aside flow, TTLs, invalidation, hit rate, and stale data"),
            ("database scaling", "indexes, replicas, partitioning, and consistency trade-offs"),
        ],
        "reliability": [
            ("fault tolerance", "redundancy, health checks, failover, degradation, and recovery"),
            ("idempotency", "duplicate requests, idempotency keys, retries, and side effects"),
            ("backpressure", "queues, overload protection, rate limiting, and load shedding"),
        ],
        "data-flow": [
            ("message queues", "producers, consumers, ordering, retries, and dead-letter queues"),
            ("event-driven architecture", "events, consumers, eventual consistency, and observability"),
            ("batch and stream processing", "latency, throughput, replay, and processing guarantees"),
        ],
        "distributed-systems": [
            ("CAP theorem", "partitions, consistency, availability, and practical system choices"),
            ("distributed locks", "ownership, leases, fencing tokens, expiry, and failure modes"),
            ("consistency models", "strong consistency, eventual consistency, reads, and user impact"),
        ],
        "api-design": [
            ("API rate limiting", "identity, quotas, token buckets, distributed counters, and headers"),
            ("pagination", "offset versus cursor pagination, consistency, and large datasets"),
            ("service boundaries", "ownership, coupling, synchronous calls, and asynchronous events"),
        ],
    },
}

CURATED_SKILL_RULES: dict[str, list[tuple[str, str]]] = {
    "DSA": [
        ("binary search", "complexity"),
        ("stack and a queue", "linear-structures"),
        ("array and a linked list", "linear-structures"),
        ("hash table", "hashing"),
        ("dynamic programming", "problem-solving"),
        ("bfs and dfs", "trees-graphs"),
        ("dijkstra", "trees-graphs"),
        ("k-th largest", "problem-solving"),
    ],
    "OS": [
        ("process and a thread", "processes-threads"),
        ("deadlock", "concurrency"),
        ("virtual memory", "memory"),
        ("mutex and a semaphore", "concurrency"),
        ("scheduler", "scheduling"),
    ],
    "DBMS": [
        ("acid", "transactions"),
        ("primary key", "modeling"),
        ("b-tree", "indexing"),
        ("join", "sql"),
        ("mvcc", "transactions"),
    ],
    "CN": [
        ("tcp and udp", "transport"),
        ("handshake", "transport"),
        ("browser", "web"),
        ("congestion control", "transport"),
    ],
    "OOP": [
        ("four pillars", "foundations"),
        ("liskov", "solid"),
        ("composition and inheritance", "composition"),
        ("solid principles", "solid"),
    ],
    "System Design": [
        ("cap theorem", "distributed-systems"),
        ("url shortening", "scalability"),
        ("rate limiter", "api-design"),
        ("notification system", "data-flow"),
    ],
}


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _stable_id(topic: str, difficulty: str, question_text: str) -> str:
    digest = hashlib.sha1(question_text.encode("utf-8")).hexdigest()[:10]
    return f"{_slug(topic)}-{difficulty}-{digest}"


def _infer_curated_skill(topic: str, question_text: str, fallback: str) -> str:
    normalized = question_text.lower()
    for phrase, skill_tag in CURATED_SKILL_RULES.get(topic, []):
        if phrase in normalized:
            return skill_tag
    return fallback


def _supplemental_question(
    topic: str,
    difficulty: str,
    skill_tag: str,
    concept: str,
    details: str,
) -> dict[str, str]:
    if difficulty == "easy":
        question = f"Explain {concept}. Cover {details}."
        depth = "Define the mechanism clearly and include one practical example."
    elif difficulty == "medium":
        question = f"How would you apply {concept} in a production scenario? Cover {details}."
        depth = "Explain the trade-offs and describe when you would choose this approach."
    else:
        question = f"Analyze the design trade-offs and failure modes of {concept}. Cover {details}."
        depth = "Discuss scaling limits, failure handling, and a reasonable mitigation strategy."

    answer = f"A strong answer explains {concept} accurately and covers {details}. {depth}"
    return {
        "id": _stable_id(topic, difficulty, question),
        "difficulty": difficulty,
        "skill": skill_tag,
        "q": question,
        "a": answer,
    }


def expand_question_bank(
    bank: dict[str, dict[str, list[dict[str, str]]]],
) -> dict[str, dict[str, list[dict[str, str]]]]:
    """Add stable metadata and deterministic supplemental questions in-place."""
    for topic, difficulties in bank.items():
        skills = SKILL_CATALOG[topic]
        skill_names = list(skills)
        for difficulty in DIFFICULTIES:
            questions = difficulties.setdefault(difficulty, [])
            for index, question in enumerate(questions):
                question.setdefault("id", _stable_id(topic, difficulty, question["q"]))
                question.setdefault("difficulty", difficulty)
                question.setdefault(
                    "skill",
                    _infer_curated_skill(topic, question["q"], skill_names[index % len(skill_names)]),
                )

            supplements: Iterable[dict[str, str]] = (
                _supplemental_question(topic, difficulty, skill_tag, concept, details)
                for skill_tag, concepts in skills.items()
                for concept, details in concepts
            )
            existing_ids = {question["id"] for question in questions}
            for question in supplements:
                if len(questions) >= QUESTIONS_PER_BUCKET:
                    break
                if question["id"] not in existing_ids:
                    questions.append(question)
                    existing_ids.add(question["id"])

    return bank


def adjust_difficulty(current: str, last_score: float | None) -> str:
    """Move one level after a strong or weak answer; otherwise stay put."""
    current_index = DIFFICULTIES.index(current) if current in DIFFICULTIES else 1
    if last_score is not None and last_score >= 0.8:
        current_index = min(current_index + 1, len(DIFFICULTIES) - 1)
    elif last_score is not None and last_score < 0.5:
        current_index = max(current_index - 1, 0)
    return DIFFICULTIES[current_index]


def select_adaptive_question(
    bank: dict[str, dict[str, list[dict[str, str]]]],
    topic: str,
    difficulty: str,
    attempted_ids: set[str],
    skill_scores: dict[str, float],
) -> dict[str, str] | None:
    """
    Select the next unused question.

    Unseen skills are treated as the weakest. Within that priority, prefer the
    requested difficulty and then nearby levels. Stable IDs break ties.
    """
    topic_bank = bank.get(topic)
    if not topic_bank:
        return None

    skill_names = list(SKILL_CATALOG[topic])
    skill_order = sorted(
        skill_names,
        key=lambda skill: (skill in skill_scores, skill_scores.get(skill, 0.0), skill),
    )
    skill_rank = {skill: index for index, skill in enumerate(skill_order)}
    difficulty_index = DIFFICULTIES.index(difficulty) if difficulty in DIFFICULTIES else 1

    candidates = [
        question
        for bucket in topic_bank.values()
        for question in bucket
        if question["id"] not in attempted_ids
    ]
    if not candidates:
        return None

    return min(
        candidates,
        key=lambda question: (
            skill_rank.get(question["skill"], len(skill_rank)),
            abs(DIFFICULTIES.index(question["difficulty"]) - difficulty_index),
            question["id"],
        ),
    )
