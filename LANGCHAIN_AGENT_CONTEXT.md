# LangChain Agent Context: Factory Failure Neo4j Graph

This file is the handoff context for any LangChain agent that needs to query or operate on this local Neo4j graph database.

## Purpose

The database stores a small factory-failure knowledge graph built from `data/factory_failures.csv`.

The agent should answer questions such as:

- What action fixes a specific machine failure?
- Which equipment shares the same cause?
- Which causes map to a given repair action?
- What are all failures, causes, and actions for one equipment item?

## Runtime Environment

Project root:

```text
/Users/twilightin/TruthSetYouFree/AI-App/graphdb
```

Python/runtime:

```bash
uv run load_graph.py
uv run ask.py "ポンプAが過熱したときの対策は？"
```

Neo4j is installed with Homebrew:

```bash
brew services start neo4j
brew services stop neo4j
brew services restart neo4j
brew services list | grep neo4j
```

Expected local endpoints:

```text
Neo4j Browser: http://127.0.0.1:7474/browser/
HTTP discovery: http://127.0.0.1:7474/
Bolt URI:       neo4j://localhost:7687
```

Connection values used by this project:

```text
NEO4J_URI=neo4j://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your-neo4j-password
```

Do not expose real credentials outside the local development context.

## Health Checks

Before querying, confirm Neo4j is running:

```bash
brew services list | grep neo4j
lsof -nP -iTCP:7474 -sTCP:LISTEN
lsof -nP -iTCP:7687 -sTCP:LISTEN
curl -I http://127.0.0.1:7474/browser/
```

Expected `curl` result after the Browser fix:

```text
HTTP/1.1 200 OK
```

If the data needs to be reloaded:

```bash
uv run load_graph.py
```

Expected output:

```text
Loaded 15 rows.
Nodes -> Equipment: 9, Failure: 15, Cause: 8, Action: 8
```

Warning: `load_graph.py` clears the graph first with `MATCH (n) DETACH DELETE n`, then reloads from CSV.

## Important Local Neo4j Browser Fix

Homebrew Neo4j 2026.05.0 installed Neo4j Browser as a zip:

```text
/opt/homebrew/Cellar/neo4j/2026.05.0/libexec/web/neo4j-browser-2026.05.26+0.zip
```

If `/browser/` returns `403 Forbidden` or `/browser/index.html` returns `404 Not Found`, unpack the browser files:

```bash
cd /opt/homebrew/Cellar/neo4j/2026.05.0/libexec/web
unzip -n neo4j-browser-2026.05.26+0.zip
brew services restart neo4j
```

If restart races and leaves Homebrew in `error 1`, check:

```bash
brew services list
tail -n 80 /opt/homebrew/var/log/neo4j.log
```

If the log says Neo4j was already running during restart, kickstart the loaded LaunchAgent:

```bash
launchctl kickstart -k gui/501/homebrew.mxcl.neo4j
```

## Graph Schema

The graph has exactly four node labels:

```cypher
(:Equipment {name})
(:Failure {id, name, equipment})
(:Cause {name})
(:Action {name})
```

The graph has exactly three relationship types:

```cypher
(:Equipment)-[:HAS_FAILURE]->(:Failure)
(:Failure)-[:CAUSED_BY]->(:Cause)
(:Cause)-[:RESOLVED_BY]->(:Action)
```

Full path shape:

```cypher
(:Equipment)-[:HAS_FAILURE]->(:Failure)-[:CAUSED_BY]->(:Cause)-[:RESOLVED_BY]->(:Action)
```

## Modeling Rules

The LangChain agent must preserve these rules when generating Cypher:

1. Use only labels `Equipment`, `Failure`, `Cause`, and `Action`.
2. Use only relationships `HAS_FAILURE`, `CAUSED_BY`, and `RESOLVED_BY`.
3. Follow relationship directions exactly as defined above.
4. `Equipment`, `Cause`, and `Action` are shared by `name`.
5. `Failure` is scoped per equipment. Do not treat `Failure.name` as globally unique.
6. If the user asks about a specific equipment failure, always start from `Equipment`.

Correct:

```cypher
MATCH (:Equipment {name:'ポンプA'})-[:HAS_FAILURE]->(:Failure {name:'過熱'})-[:CAUSED_BY]->(:Cause)-[:RESOLVED_BY]->(a:Action)
RETURN a.name
```

Incorrect:

```cypher
MATCH (:Failure {name:'過熱'})-[:CAUSED_BY]->(:Cause)-[:RESOLVED_BY]->(a:Action)
RETURN a.name
```

The incorrect query can mix failures from different machines.

## Expected Counts

After `uv run load_graph.py`, expected counts are:

```text
Equipment: 9
Failure:   15
Cause:     8
Action:    8
```

Validation query:

```cypher
MATCH (n)
RETURN labels(n)[0] AS label, count(*) AS count
ORDER BY label
```

Relationship count query:

```cypher
MATCH ()-[r]->()
RETURN type(r) AS relationship, count(*) AS count
ORDER BY relationship
```

## Raw Source Data

The graph is loaded from:

```text
/Users/twilightin/TruthSetYouFree/AI-App/graphdb/data/factory_failures.csv
```

Raw CSV contents:

```csv
equipment,failure,cause,action
ポンプA,過熱,潤滑不足,再潤滑
ポンプA,異音,ベアリング摩耗,ベアリング交換
ポンプB,漏れ,シール劣化,シール交換
モーターA,過熱,過負荷,負荷見直し
モーターA,振動異常,軸ずれ,芯出し調整
モーターB,異音,ベアリング摩耗,ベアリング交換
コンプレッサーA,圧力低下,フィルター詰まり,フィルター清掃
コンプレッサーA,過熱,冷却不足,冷却系点検
コンプレッサーB,漏れ,シール劣化,シール交換
ファンA,振動異常,軸ずれ,芯出し調整
ファンA,異音,ベアリング摩耗,ベアリング交換
バルブA,漏れ,シール劣化,シール交換
バルブB,作動不良,異物混入,分解清掃
ポンプB,過熱,潤滑不足,再潤滑
モーターB,振動異常,軸ずれ,芯出し調整
```

## Safe Read-Only Query Patterns

Action for a specific equipment failure:

```cypher
MATCH (:Equipment {name:'ポンプA'})-[:HAS_FAILURE]->(:Failure {name:'過熱'})-[:CAUSED_BY]->(:Cause)-[:RESOLVED_BY]->(a:Action)
RETURN a.name
```

All failures, causes, and actions for one equipment item:

```cypher
MATCH (:Equipment {name:'ポンプA'})-[:HAS_FAILURE]->(f:Failure)-[:CAUSED_BY]->(c:Cause)-[:RESOLVED_BY]->(a:Action)
RETURN f.name AS failure, c.name AS cause, a.name AS action
ORDER BY failure
```

Equipment affected by a shared cause:

```cypher
MATCH (e:Equipment)-[:HAS_FAILURE]->(:Failure)-[:CAUSED_BY]->(:Cause {name:'ベアリング摩耗'})
RETURN DISTINCT e.name
ORDER BY e.name
```

Causes fixed by a given action:

```cypher
MATCH (c:Cause)-[:RESOLVED_BY]->(:Action {name:'シール交換'})
RETURN c.name
ORDER BY c.name
```

Full graph path for visualization:

```cypher
MATCH p=(:Equipment)-[:HAS_FAILURE]->(:Failure)-[:CAUSED_BY]->(:Cause)-[:RESOLVED_BY]->(:Action)
RETURN p
LIMIT 100
```

Schema visualization:

```cypher
CALL db.schema.visualization()
```

## Query Generation Constraints

For a text-to-Cypher agent:

- Generate one Cypher query at a time.
- Prefer read-only `MATCH` queries.
- Do not generate `CREATE`, `MERGE`, `SET`, `DELETE`, `DETACH DELETE`, `DROP`, or constraint changes unless explicitly asked to modify data.
- Match Japanese names exactly when possible.
- Use `CONTAINS` only for partial or fuzzy user input.
- Return `name` properties for user-facing answers.
- For visualization in Neo4j Browser, return a path variable such as `RETURN p`.

## Existing Local LLM Prompt

The project already contains a constrained prompt in:

```text
prompt.py
```

The existing CLI flow is:

```text
natural language question -> OpenAI -> Cypher -> Neo4j -> printed result
```

Relevant files:

```text
ask.py
prompt.py
load_graph.py
GRAPHDB_GUIDE.md
WEB_UI_GUIDE.md
CYPHER_TUTORIAL.md
data/factory_failures.csv
```

## Suggested Agent Responsibilities

The LangChain agent should:

1. Check Neo4j connectivity before answering.
2. Load or reload data only when explicitly requested.
3. Generate Cypher constrained to the schema above.
4. Execute the query against `neo4j://localhost:7687`.
5. Summarize results in the user language when possible.
6. When no rows match, state that no matching graph path was found.
7. When user asks to inspect visually, provide a `RETURN p` path query.

## Common Failure Modes

Connection refused on `7687`:

```text
Neo4j is not running. Start it with `brew services start neo4j`.
```

HTTP `7474` unavailable:

```text
Neo4j HTTP server is not listening. Check `brew services list` and logs.
```

`/browser/` returns `403 Forbidden`:

```text
Neo4j Browser files may still be zipped. Unpack the browser zip in the Homebrew web directory.
```

Unauthorized:

```text
The database password does not match the project environment. Expected local password is `your-neo4j-password`.
```

Wrong answers for common failure names:

```text
The query probably matched `Failure` by name alone. Regenerate Cypher starting from `Equipment`.
```

## Minimal Connection Pseudocode

Use the official Neo4j Python driver or LangChain's Neo4j integration, depending on the agent stack.

The essential connection facts are:

```text
url:      neo4j://localhost:7687
username: neo4j
password: your-neo4j-password
database: neo4j
```

Always verify connectivity before running generated Cypher.
