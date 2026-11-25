# Graph Report - jev-ultrafast  (2026-11-17)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 143 nodes · 337 edges · 14 communities (9 shown, 5 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 24 edges (avg confidence: 0.87)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `cf3c406f`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Community 0
- Community 1
- Community 2
- Community 3
- Community 4
- Community 6
- Community 7
- Community 8
- Community 9
- Community 10
- Community 11
- Community 13

## God Nodes (most connected - your core abstractions)
1. `Agent` - 20 edges
2. `StalePage` - 20 edges
3. `Browser` - 14 edges
4. `page()` - 11 edges
5. `browser_operation()` - 11 edges
6. `choose()` - 10 edges
7. `field_text()` - 9 edges
8. `main()` - 9 edges
9. `main()` - 8 edges
10. `verify()` - 8 edges

## Surprising Connections (you probably didn't know these)
- `main()` --uses--> `StalePage`  [INFERRED]
  scripts/check_guards.py → jev_ultrafast/browser.py
- `test_executor_rejects_a_stale_page_before_browser_input()` --uses--> `StalePage`  [INFERRED]
  tests/test_agent.py → jev_ultrafast/browser.py
- `test_stale_decision_is_consumed_before_any_mutation()` --uses--> `StalePage`  [INFERRED]
  tests/test_agent.py → jev_ultrafast/browser.py
- `test_missing_text_credential_stops_before_guessing()` --calls--> `field_text()`  [EXTRACTED]
  tests/test_agent.py → jev_ultrafast/model.py
- `test_changed_field_context_does_not_reuse_generated_text()` --calls--> `StalePage`  [EXTRACTED]
  tests/test_agent.py → jev_ultrafast/browser.py

## Import Cycles
- None detected.

## Communities (14 total, 5 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.14
Nodes (8): main(), Agent, close_browser(), command(), load_environment(), main(), response_state(), main()

### Community 1 - "Community 1"
Cohesion: 0.15
Nodes (4): verify(), timed(), capture(), test_flight_verification_rejects_wrong_trip()

### Community 2 - "Community 2"
Cohesion: 0.21
Nodes (8): action_space(), choose(), field_context(), field_text(), post_json(), validate_choice(), test_invalid_choice_is_rejected(), test_quoted_task_text_still_uses_the_llm()

### Community 3 - "Community 3"
Cohesion: 0.22
Nodes (7): decision(), runner(), test_changed_field_context_does_not_reuse_generated_text(), test_generated_text_reused_only_for_identical_retry_context(), test_loading_waits_do_not_trigger_no_progress_stop(), test_missing_text_credential_stops_before_guessing(), test_stale_observation_preserves_executed_action()

### Community 6 - "Community 6"
Cohesion: 0.46
Nodes (7): call(), controls(), escape(), goals, percent(), perform(), render()

### Community 7 - "Community 7"
Cohesion: 0.33
Nodes (6): browser_operation(), call(), evaluate(), test_interrupted_dropdown_mutation_cannot_be_retried_as_stale(), test_observation_is_one_atomic_browser_read(), test_text_helper_rejects_invalid_values()

### Community 8 - "Community 8"
Cohesion: 0.38
Nodes (7): choice(), test_all_heads_are_one_request_and_only_matching_head_executes(), post(), test_click_cannot_consume_a_text_target(), post(), test_target_head_receives_control_state_and_full_next_step_rules(), post()

### Community 10 - "Community 10"
Cohesion: 0.50
Nodes (5): fingerprint(), page(), test_executor_rejects_a_stale_page_before_browser_input(), test_fingerprint_tracks_values_and_identity_not_screenshots(), test_one_index_per_node_with_operation_specific_targets()

### Community 11 - "Community 11"
Cohesion: 0.40
Nodes (3): StalePage, test_navigation_during_prediction_reobserves_without_action(), test_stale_decision_is_consumed_before_any_mutation()

## Knowledge Gaps
- **1 isolated node(s):** `jev-ultrafast`
  These have ≤1 connection - possible missing edges. (Counts symbols only; 39 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **5 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Agent` connect `Community 0` to `Community 1`, `Community 2`, `Community 11`, `Community 4`?**
  _High betweenness centrality (0.113) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `Agent` (e.g. with `Browser` and `StalePage`) actually correct?**
  _`Agent` has 2 INFERRED edges - model-reasoned connections that need verification._
- **What connects `jev-ultrafast` to the rest of the system?**
  _1 weakly-connected nodes found - possible missing edges._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.14022988505747128 - nodes in this community are weakly interconnected._
- **Why does `StalePage` connect `Community 11` to `Community 0`, `Community 1`, `Community 2`, `Community 3`, `Community 4`, `Community 7`, `Community 10`?**
  _High betweenness centrality (0.101) - this node is a cross-community bridge._
- **Are the 4 inferred relationships involving `StalePage` (e.g. with `Agent` and `main()`) actually correct?**
  _`StalePage` has 4 INFERRED edges - model-reasoned connections that need verification._
- **Should `Community 1` be split into smaller, more focused modules?**
  _Cohesion score 0.14619883040935672 - nodes in this community are weakly interconnected._