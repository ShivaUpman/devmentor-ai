"""
ml/recommender/catalogue.py — Curated learning resource catalogue

WHY a hardcoded catalogue and not a DB table or web scrape?
  Three reasons:

  1. Quality control: scraped resources vary wildly in quality.
     A curated catalogue of 10 excellent resources per topic beats
     100 algorithmically-fetched mediocre ones. Curation IS the value.

  2. Stability: URLs change. A web scrape today breaks tomorrow.
     Vetted resources with stable URLs (O'Reilly, CS Fundamentals, etc)
     are reliable references users can trust.

  3. Metadata richness: we store type, difficulty, time estimate, and
     topic tags — metadata that's impossible to scrape reliably.

  In production: a CMS (Contentful, Strapi) manages the catalogue.
  Editors add/update resources. Engineers don't touch this file.
  The structure here mirrors what a CMS would return via API.

WHY is this a dataclass and not a SQLAlchemy model?
  The catalogue is read-only reference data — it never changes at runtime.
  It doesn't need a database. Loading it from Python is instant and
  requires no migrations, no connection pools, no queries.
  Use the right tool for the job: DB for mutable user data, Python
  constants for stable reference data.

Interview question: "How would you scale this catalogue to 10,000 resources?"
  Store in PostgreSQL with full-text search (tsvector) or Elasticsearch.
  Add user ratings, completion tracking, and collaborative filtering
  ("users who completed this also found X useful").
  Index by topic, difficulty, and type for fast filtered queries.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Resource:
    """
    One learning resource.

    frozen=True: immutable after creation — safe to share across threads,
    safe to use as dict keys, signals "this is reference data, not mutable state."
    """
    id: str                    # Stable identifier for deduplication
    title: str
    url: str
    resource_type: str         # article | video | course | book | practice
    topic: str                 # Primary topic (DSA | OS | DBMS | CN | OOP | System Design)
    difficulty: str            # beginner | intermediate | advanced
    estimated_hours: float     # Realistic time to complete
    description: str           # One-sentence description for the roadmap card
    tags: tuple[str, ...] = field(default_factory=tuple)  # Subtopic tags


# ── The catalogue ─────────────────────────────────────────────────────────────
RESOURCE_CATALOGUE: list[Resource] = [

    # ── DSA ───────────────────────────────────────────────────────────────────
    Resource(
        id="dsa-neetcode-roadmap",
        title="NeetCode 150 — Structured DSA Practice",
        url="https://neetcode.io/roadmap",
        resource_type="practice",
        topic="DSA",
        difficulty="intermediate",
        estimated_hours=40.0,
        description="150 curated LeetCode problems organized by pattern — the most efficient path to DSA interview readiness.",
        tags=("arrays", "trees", "graphs", "dynamic programming", "binary search"),
    ),
    Resource(
        id="dsa-algo-visualizer",
        title="Algorithm Visualizer",
        url="https://algorithm-visualizer.org",
        resource_type="article",
        topic="DSA",
        difficulty="beginner",
        estimated_hours=3.0,
        description="Interactive visualizations of sorting, searching, and graph algorithms — builds intuition before implementation.",
        tags=("sorting", "searching", "visualization"),
    ),
    Resource(
        id="dsa-mit-ocw",
        title="MIT 6.006 — Introduction to Algorithms",
        url="https://ocw.mit.edu/courses/6-006-introduction-to-algorithms-fall-2011/",
        resource_type="course",
        topic="DSA",
        difficulty="advanced",
        estimated_hours=30.0,
        description="MIT's rigorous algorithms course covering complexity, sorting, graphs, and dynamic programming with proof-based rigor.",
        tags=("complexity", "dynamic programming", "graphs", "sorting"),
    ),
    Resource(
        id="dsa-big-o-cheatsheet",
        title="Big-O Complexity Cheat Sheet",
        url="https://www.bigocheatsheet.com",
        resource_type="article",
        topic="DSA",
        difficulty="beginner",
        estimated_hours=0.5,
        description="Quick reference for time and space complexity of common data structures and algorithms.",
        tags=("complexity", "big-o", "reference"),
    ),
    Resource(
        id="dsa-cp-algorithms",
        title="CP-Algorithms — Competitive Programming Reference",
        url="https://cp-algorithms.com",
        resource_type="article",
        topic="DSA",
        difficulty="advanced",
        estimated_hours=20.0,
        description="Detailed explanations with proofs and implementations for advanced algorithms used in competitive programming.",
        tags=("graphs", "number theory", "string algorithms", "advanced"),
    ),

    # ── OS ────────────────────────────────────────────────────────────────────
    Resource(
        id="os-three-easy-pieces",
        title="Operating Systems: Three Easy Pieces (OSTEP)",
        url="https://pages.cs.wisc.edu/~remzi/OSTEP/",
        resource_type="book",
        topic="OS",
        difficulty="intermediate",
        estimated_hours=25.0,
        description="Free, widely-used OS textbook covering virtualization, concurrency, and persistence with clear explanations.",
        tags=("processes", "threads", "memory", "file systems", "concurrency"),
    ),
    Resource(
        id="os-concurrency-visualized",
        title="Visualizing Concurrency in Go",
        url="https://divan.dev/posts/go_concurrency_visualize/",
        resource_type="article",
        topic="OS",
        difficulty="intermediate",
        estimated_hours=1.5,
        description="Visual animations of goroutines and channels — builds intuition for concurrency patterns applicable across languages.",
        tags=("concurrency", "threads", "goroutines", "visualization"),
    ),
    Resource(
        id="os-linux-insides",
        title="Linux Insides — Kernel Deep Dive",
        url="https://0xax.gitbooks.io/linux-insides/content/",
        resource_type="book",
        topic="OS",
        difficulty="advanced",
        estimated_hours=15.0,
        description="Detailed walk through the Linux kernel internals — boot process, memory management, interrupts, and system calls.",
        tags=("kernel", "linux", "system calls", "memory management"),
    ),
    Resource(
        id="os-deadlock-explained",
        title="Deadlock: Conditions, Detection, and Prevention",
        url="https://www.cs.uic.edu/~jbell/CourseNotes/OperatingSystems/7_Deadlocks.html",
        resource_type="article",
        topic="OS",
        difficulty="beginner",
        estimated_hours=1.0,
        description="Clear explanation of the four Coffman conditions and strategies for deadlock prevention and detection.",
        tags=("deadlock", "synchronization", "mutual exclusion"),
    ),
    Resource(
        id="os-scheduling-algorithms",
        title="CPU Scheduling Algorithms Explained",
        url="https://www.geeksforgeeks.org/cpu-scheduling-in-operating-systems/",
        resource_type="article",
        topic="OS",
        difficulty="beginner",
        estimated_hours=2.0,
        description="FCFS, SJF, Round Robin, and Priority scheduling with Gantt chart examples — essential for OS interviews.",
        tags=("scheduling", "FCFS", "round robin", "priority"),
    ),

    # ── DBMS ──────────────────────────────────────────────────────────────────
    Resource(
        id="dbms-use-the-index",
        title="Use The Index, Luke — SQL Indexing Guide",
        url="https://use-the-index-luke.com",
        resource_type="article",
        topic="DBMS",
        difficulty="intermediate",
        estimated_hours=8.0,
        description="The definitive practical guide to SQL query performance and index design — every backend engineer should read this.",
        tags=("indexes", "B-tree", "query performance", "SQL"),
    ),
    Resource(
        id="dbms-designing-data-intensive",
        title="Designing Data-Intensive Applications — Part I",
        url="https://dataintensive.net",
        resource_type="book",
        topic="DBMS",
        difficulty="advanced",
        estimated_hours=12.0,
        description="Martin Kleppmann's essential book — chapters on storage engines, replication, and transactions are required reading for senior roles.",
        tags=("ACID", "replication", "transactions", "storage engines", "MVCC"),
    ),
    Resource(
        id="dbms-normalization-guide",
        title="Database Normalization — 1NF through BCNF",
        url="https://www.studytonight.com/dbms/database-normalization.php",
        resource_type="article",
        topic="DBMS",
        difficulty="beginner",
        estimated_hours=2.0,
        description="Step-by-step normalization from 1NF to BCNF with worked examples — the most-asked DBMS interview topic.",
        tags=("normalization", "1NF", "2NF", "3NF", "BCNF"),
    ),
    Resource(
        id="dbms-postgres-internals",
        title="The Internals of PostgreSQL",
        url="https://www.interdb.jp/pg/",
        resource_type="book",
        topic="DBMS",
        difficulty="advanced",
        estimated_hours=10.0,
        description="Deep dive into PostgreSQL's MVCC, WAL, vacuum, and query planning — essential for database administrator and backend roles.",
        tags=("PostgreSQL", "MVCC", "WAL", "vacuum", "internals"),
    ),
    Resource(
        id="dbms-sqlzoo",
        title="SQLZoo — Interactive SQL Practice",
        url="https://sqlzoo.net",
        resource_type="practice",
        topic="DBMS",
        difficulty="beginner",
        estimated_hours=5.0,
        description="Hands-on SQL exercises from SELECT basics to complex JOIN and aggregation queries — best beginner SQL practice site.",
        tags=("SQL", "JOIN", "aggregation", "practice"),
    ),

    # ── CN ────────────────────────────────────────────────────────────────────
    Resource(
        id="cn-computer-networks-top-down",
        title="Computer Networking: A Top-Down Approach",
        url="https://gaia.cs.umass.edu/kurose_ross/online_lectures.htm",
        resource_type="course",
        topic="CN",
        difficulty="intermediate",
        estimated_hours=20.0,
        description="Kurose & Ross's standard networking textbook with free lecture videos — covers HTTP, TCP, IP, and routing in depth.",
        tags=("HTTP", "TCP", "IP", "routing", "DNS"),
    ),
    Resource(
        id="cn-how-does-the-internet-work",
        title="How Does the Internet Work? — Explained Simply",
        url="https://cs.fyi/guide/how-does-internet-work",
        resource_type="article",
        topic="CN",
        difficulty="beginner",
        estimated_hours=1.0,
        description="Clear, concise explanation of DNS, HTTP, packets, and routing — perfect starting point for CN interview prep.",
        tags=("internet", "DNS", "HTTP", "packets"),
    ),
    Resource(
        id="cn-tcp-ip-illustrated",
        title="TCP/IP Illustrated — Chapter Summaries",
        url="https://www.cs.newpaltz.edu/~pletcha/NET_PY/the-protocols-tcp-ip-illustrated-volume-1.9780201633467.24290.pdf",
        resource_type="book",
        topic="CN",
        difficulty="advanced",
        estimated_hours=15.0,
        description="Stevens' authoritative TCP/IP reference — chapters on TCP connection management and flow control are interview gold.",
        tags=("TCP", "UDP", "IP", "flow control", "congestion control"),
    ),
    Resource(
        id="cn-http-deep-dive",
        title="HTTP: The Definitive Guide — Free Chapter",
        url="https://developer.mozilla.org/en-US/docs/Web/HTTP/Overview",
        resource_type="article",
        topic="CN",
        difficulty="beginner",
        estimated_hours=2.0,
        description="MDN's comprehensive HTTP reference — covers methods, status codes, headers, and HTTP/2 — essential for web backend roles.",
        tags=("HTTP", "HTTPS", "status codes", "headers", "REST"),
    ),
    Resource(
        id="cn-wireshark-labs",
        title="Wireshark Network Analysis Labs",
        url="https://gaia.cs.umass.edu/kurose_ross/wireshark.php",
        resource_type="practice",
        topic="CN",
        difficulty="intermediate",
        estimated_hours=4.0,
        description="Hands-on packet capture labs — seeing TCP handshakes and DNS queries in real traffic solidifies protocol understanding.",
        tags=("TCP", "DNS", "packet analysis", "hands-on"),
    ),

    # ── OOP ───────────────────────────────────────────────────────────────────
    Resource(
        id="oop-refactoring-guru-patterns",
        title="Refactoring Guru — Design Patterns",
        url="https://refactoring.guru/design-patterns",
        resource_type="article",
        topic="OOP",
        difficulty="intermediate",
        estimated_hours=6.0,
        description="Visual, clear explanations of all 23 Gang of Four patterns with real-world examples — the best free design patterns resource.",
        tags=("design patterns", "singleton", "observer", "factory", "strategy"),
    ),
    Resource(
        id="oop-solid-principles",
        title="SOLID Principles Explained with Examples",
        url="https://www.digitalocean.com/community/conceptual-articles/s-o-l-i-d-the-first-five-principles-of-object-oriented-design",
        resource_type="article",
        topic="OOP",
        difficulty="beginner",
        estimated_hours=2.0,
        description="Clear explanations of each SOLID principle with bad/good code examples — asked in virtually every senior engineering interview.",
        tags=("SOLID", "SRP", "OCP", "LSP", "ISP", "DIP"),
    ),
    Resource(
        id="oop-head-first-design",
        title="Head First Design Patterns — Preview",
        url="https://www.oreilly.com/library/view/head-first-design/0596007124/",
        resource_type="book",
        topic="OOP",
        difficulty="intermediate",
        estimated_hours=12.0,
        description="Highly visual and memorable approach to the most important design patterns — the most beginner-friendly patterns book.",
        tags=("design patterns", "OOP", "composition", "interfaces"),
    ),
    Resource(
        id="oop-composition-over-inheritance",
        title="Composition over Inheritance — The Case",
        url="https://python-patterns.guide/gang-of-four/composition-over-inheritance/",
        resource_type="article",
        topic="OOP",
        difficulty="intermediate",
        estimated_hours=1.5,
        description="Practical explanation of why composition is preferred over deep inheritance hierarchies — directly applicable to code review feedback.",
        tags=("composition", "inheritance", "coupling", "flexibility"),
    ),

    # ── System Design ─────────────────────────────────────────────────────────
    Resource(
        id="sd-system-design-primer",
        title="The System Design Primer",
        url="https://github.com/donnemartin/system-design-primer",
        resource_type="article",
        topic="System Design",
        difficulty="intermediate",
        estimated_hours=15.0,
        description="The most comprehensive free system design resource — covers scalability, load balancing, caching, databases, and common interview questions.",
        tags=("scalability", "load balancing", "caching", "databases", "CAP theorem"),
    ),
    Resource(
        id="sd-designing-data-intensive",
        title="Designing Data-Intensive Applications",
        url="https://dataintensive.net",
        resource_type="book",
        topic="System Design",
        difficulty="advanced",
        estimated_hours=20.0,
        description="Kleppmann's masterpiece — the single best book for senior system design interviews covering replication, partitioning, and consistency.",
        tags=("distributed systems", "replication", "partitioning", "consistency", "CAP"),
    ),
    Resource(
        id="sd-bytebytego",
        title="ByteByteGo System Design Newsletter",
        url="https://bytebytego.com",
        resource_type="article",
        topic="System Design",
        difficulty="intermediate",
        estimated_hours=8.0,
        description="Alex Xu's visual system design explanations — URL shortener, Twitter, YouTube. The most digestible system design content.",
        tags=("URL shortener", "Twitter", "YouTube", "visual", "case studies"),
    ),
    Resource(
        id="sd-cap-theorem",
        title="CAP Theorem: Explained with Real Systems",
        url="https://www.ibm.com/topics/cap-theorem",
        resource_type="article",
        topic="System Design",
        difficulty="intermediate",
        estimated_hours=1.5,
        description="IBM's clear explanation of CAP theorem with examples from Cassandra, MongoDB, and HBase — must-know for distributed systems interviews.",
        tags=("CAP theorem", "consistency", "availability", "partition tolerance"),
    ),
    Resource(
        id="sd-consistent-hashing",
        title="Consistent Hashing: The Intuition",
        url="https://www.toptal.com/big-data/consistent-hashing",
        resource_type="article",
        topic="System Design",
        difficulty="intermediate",
        estimated_hours=1.0,
        description="Visual explanation of consistent hashing and virtual nodes — used in DynamoDB, Cassandra, and load balancers.",
        tags=("consistent hashing", "distributed systems", "load balancing", "sharding"),
    ),
]


def get_resources_for_topic(topic: str) -> list[Resource]:
    """Filter catalogue by topic."""
    return [r for r in RESOURCE_CATALOGUE if r.topic == topic]


def get_resources_by_difficulty(
    topic: str, difficulty: str
) -> list[Resource]:
    """Filter by topic AND difficulty."""
    return [
        r for r in RESOURCE_CATALOGUE
        if r.topic == topic and r.difficulty == difficulty
    ]


def get_all_topics() -> list[str]:
    """Return the unique topics in the catalogue."""
    return sorted(set(r.topic for r in RESOURCE_CATALOGUE))


def get_catalogue_stats() -> dict:
    """Summary statistics for health checks and admin dashboards."""
    by_topic = {}
    for r in RESOURCE_CATALOGUE:
        by_topic.setdefault(r.topic, 0)
        by_topic[r.topic] += 1
    return {
        "total_resources": len(RESOURCE_CATALOGUE),
        "topics": get_all_topics(),
        "by_topic": by_topic,
        "by_type": {
            t: sum(1 for r in RESOURCE_CATALOGUE if r.resource_type == t)
            for t in {"article", "video", "course", "book", "practice"}
        },
    }
