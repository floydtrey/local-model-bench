# qwen3.6:35b-32k-compare

**Status: PLANNED**

### Task 1: Locate and Apply "General Intent" Storage Preference
**Prerequisites:** None  
**Work:** Search the provided project resources for the document or section titled "General Intent preference" regarding backend storage or database technology selection. Extract the specified preference. If the preference is not found in the resources, report back immediately; do not proceed with technology selection.  
**Acceptance Condition:** The storage engine is explicitly chosen based on the located preference. If the preference was not found, the task is paused and flagged per the missing information rule.

### Task 2: Design Core Data Model and Relationship Schema
**Prerequisites:** Task 1 completed  
**Work:** Design the internal data model/schema to support:
- Timestamped observations stored with source, entity, timestamp, and payload/context fields.
- A current-state layer that tracks the latest observation per entity/key without deleting historical records.
- A relationship/association layer linking related observations (e.g., by entity, tag, or semantic key) to enable cross-reference retrieval.
The design must use the storage engine selected in Task 1, support local execution, and require no external services.  
**Acceptance Condition:** Schema/data model is fully specified, documented, and verified to satisfy history preservation, current-state tracking, relationship association, and local-only execution constraints without requiring core redesign when new generic sources are added.

### Task 3: Implement Deterministic Indexing and Filtering Strategy
**Prerequisites:** Task 2 completed  
**Work:** Define and implement the deterministic logic required to replace AI-driven context reconstruction:
- Indexing strategy for fast filtering by entity, source, and time range.
- Deterministic relevance/scoring or filtering rules to bound retrieved context (e.g., recency weighting, entity proximity, tag overlap, or explicit query filters).
- Current-state maintenance logic that updates the latest known state atomically while archiving the prior state.  
**Acceptance Condition:** Deterministic indexing and filtering mechanisms are implemented. Retrieval queries use these mechanisms to return bounded, relevant subsets rather than unfiltered full histories. Logic is fully independent of AI inference or conversation history.

### Task 4: Implement Storage/Retrieval Interface
**Prerequisites:** Tasks 2 and 3 completed  
**Work:** Build the public backend interface/repository layer exposing methods for:
- Recording timestamped observations from multiple generic sources.
- Updating and retrieving current known state without deleting history.
- Associating and retrieving related information.
- Querying historical observations by entity, source, or time.
- Fetching bounded relevant context for trend comparison.
- Returning exact stored records on request.
Ensure the interface abstracts the underlying engine and supports adding a new generic source type by simply providing a source identifier/type without modifying core queries or schema constraints.  
**Acceptance Condition:** All required methods are implemented and callable. The interface successfully records, updates state, preserves history, links relationships, queries by entity/source/time, returns bounded context, and returns exact records. Adding a new source type is possible via source configuration/identification only.

### Task 5: Develop and Execute Automated Local Tests
**Prerequisites:** Task 4 completed  
**Work:** Write an automated test suite that programmatically validates each acceptance direction point. Tests must run entirely on the local development environment and use the exact storage engine and interface implemented in previous tasks.  
**Acceptance Condition:** All tests pass locally. Test coverage explicitly maps to:
1. Recording timestamped observations from multiple generic sources
2. Preserving observation history
3. Updating and retrieving current known state without deleting history
4. Associating related information for later retrieval
5. Querying historical observations by entity/source/time
6. Retrieving enough related history for a simple trend comparison
7. Returning bounded relevant context rather than an unfiltered full history
8. Returning exact stored records when requested
9. Adding a new generic source without redesigning the storage core
10. Running locally with automated tests for the required behaviors
