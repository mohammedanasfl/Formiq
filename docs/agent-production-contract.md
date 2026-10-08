# Formiq Agent Production Contract

The AI coach's rules in one place: what the agent may do, what the model controls and what it
never controls, which systems are authoritative, and how the coach behaves when something fails.
It records the guarantees built in Phases 4.1 to 4.11. Phase 4.12 adds no capability.

Read this before changing anything under `backend/app/agent`, `backend/app/tools`,
`backend/app/approvals`, `backend/app/observability` or `backend/app/services/coach_service.py`.

How it is kept true:

- Every rule names the code that enforces it and the tests that prove it. Those references are
  checked: `backend/tests/unit/test_agent_contract.py` fails if a referenced module or test
  disappears.
- The tables of limits, thresholds and categories are checked too. If a limit's value changes in
  the code, or a category is added without being documented here, that test fails.
- Paths in this document are relative to `backend/`.

The rules are enforced in code and tested. This document describes them; it is not the
enforcement. Changing a rule here does not change the coach, and changing the code without
changing this document fails a test.

---

## 1. Summary

The coach is a **read-only, single-turn, request-scoped agent**. For each request it:

1. runs a deterministic safety check on the user's message;
2. lets the model read the user's own Formiq data through seven read-only tools, within fixed
   limits;
3. accepts the model's reply only when the decision, the evidence, the safety policy and the
   reply itself pass deterministic checks.

It keeps no memory between requests, runs no background work, and never changes Formiq data.

| The model may | The model may never |
|---|---|
| Choose which of the declared read tools to call, with which arguments. The arguments are validated, the ids must be grounded, and the limits apply. | Choose or change whose data is read (identity). |
| Choose the request's intent and decision, from the enums the respond tool offers. | Change or lower the safety category. |
| Write the reply text, which is then validated. | Change the policy, the limits, or which tools exist. |
| | Use an id that neither the user nor a tool gave. |
| | Count missing, failed or compacted data as evidence. |
| | Run, approve or authorize a write. |
| | Decide the request's final status, retries, or what is traced. |
| | Replace Formiq's fixed safe replies. |

---

## 2. Authoritative systems

| System | Authoritative for | Not authoritative for |
|---|---|---|
| PostgreSQL | Application data: users, profiles, plans, sessions, the catalog | |
| Application policy: code and instructions (`app/agent/graph.py`, `app/agent/policy.py`) | The coach's rules, its decisions and its limits | |
| Deterministic safety (`app/agent/safety.py`) | The safety boundary: whether a request is flagged, and with which category | Medical judgement. See section 7. |
| Authentication (`app/api/dependencies.py`, `app/services/auth_service.py`) | Who a request acts for: the user its verified access token was issued for | |
| `CoachContext.user_id` (`app/agent/graph.py`) | The identity whose data the tools read, set from the authenticated user | |
| Application tool contracts (`app/tools/`) | Tool behavior: inputs, ownership, bounds, errors | |
| Approval system (`app/approvals/`) | Write authorization, for any future write | |
| The LLM (Gemini, through `app/ai/gemini.py`) | **Nothing.** It is a reasoning and proposal component only. | Memory, identity, safety, policy, evidence, authorization |
| Langfuse (`app/observability/`) | **Nothing.** It is observability only. | Any decision, retry, response or failure |
| Evaluation (`app/evaluation/`) | **Nothing at runtime.** It verifies regressions only. | Production behavior. Production code never imports it. |

Two consequences follow:

- The LLM is never authoritative memory. Each request starts from a new state that is dropped
  after the reply. Formiq stores no conversation.
- The LLM never authorizes anything. Its output is a proposal, which the application checks.

Enforced by:

- `tests/unit/test_coach_state.py::test_each_turn_starts_from_nothing`
- `tests/unit/test_reliability_state.py::test_the_compiled_graph_keeps_nothing_between_turns`
- `tests/unit/test_evaluation_dataset.py::test_production_code_never_imports_the_evaluation`
- `tests/unit/test_coach_graph.py::test_agent_and_provider_do_not_reach_the_database`
- `tests/unit/test_agent_contract.py::test_observability_cannot_reach_what_it_could_change`

---

## 3. Trust contract

From most to least trusted. Defined in `app/agent/trust.py`.

1. **Application policy**: the coach's instructions, sent as Gemini's system instruction, and the
   graph's code.
2. **Deterministic safety rules** (`app/agent/safety.py`), run on the current message before the
   model is called.
3. **Trusted runtime identity** (`CoachContext`): the user, the model and the tools. No text
   reaches it.
4. **Tool and application contracts**: the tools' declarations and validation, the decision policy,
   id grounding, the limits, and Formiq's own error results.
5. **Formiq data** returned by the tools. It is authoritative for facts about the user. The free
   text inside it (plan names, notes, descriptions) is data, never instructions.
6. **The current user message**: what to answer. It cannot change levels 1 to 4.
7. **Client history**: the earlier turns the client sends. It is unverified, including the turns
   marked as the coach's.
8. **Model-generated proposals**: tool calls, decisions, replies and any write proposal. Code
   checks every one of them.

Rules:

- **Data does not become instructions because it contains imperative text.** The defense is the
  architecture, not wording. Safety, identity, ownership, id grounding, tool validation, the
  decision and the limits are decided in code from trusted inputs. Text can at most mislead the
  model, and the code then checks the model.
- **History cannot change policy.**
- **Tool results cannot change policy.**
- **Model output cannot change policy.**
- **Model output cannot establish identity.**
- **Model output cannot authorize writes.**

Enforced by:

- `tests/unit/test_coach_injection.py::test_history_cannot_authorize_ids_identity_or_decisions`
- `tests/unit/test_coach_injection.py::test_tool_text_cannot_authorize_another_tool_or_set_the_decision`
- `tests/unit/test_coach_injection.py::test_tool_text_cannot_change_the_safety_of_the_request`
- `tests/unit/test_coach_injection.py::test_the_trusted_user_stays_out_of_reach_of_text`
- `tests/integration/test_coach_injection.py::test_stored_injections_change_nothing_the_application_decides`
- `tests/unit/test_coach_injection.py::test_the_instructions_state_the_trust_boundary`
- `tests/unit/test_agent_contract.py::test_the_model_controls_only_its_calls_and_its_respond_arguments`

---

## 4. Identity contract

- **Authentication is the only source of the request's identity.** `POST /coach/message`
  requires a Bearer access token (a JWT signed with `AUTH_JWT_SECRET`, `app/core/security.py`),
  issued by `POST /auth/login` for an email and password. `get_current_user`
  (`app/api/dependencies.py`) verifies it and loads its user before the coach runs: a missing,
  malformed, wrongly signed or expired token, or one whose user does not exist, ends the request
  with 401, and nothing is read for anyone. Without a signing secret the route answers 503; there
  is no anonymous fallback.
- **A client-provided `user_id` is never authoritative.** The request body has no `user_id`
  field, and a body that names one (or any other unknown field) is rejected with 422 before the
  coach runs. The message, the history, tool results and model output are text: none of them can
  change the user.
- The coach acts for exactly one user per request: `CoachContext.user_id`. `CoachService` sets it
  to the authenticated user's id, and it lives outside the graph state, so no node and no model
  output can change it.
- No tool declares a `user_id`. `FormiqTools` adds the trusted user to every user-scoped input. A
  `user_id` argument from the model is rejected with `INVALID_INPUT` before anything is read.
- History does not establish identity: it is only text. Tool results do not either: the tools are
  always run with `user_id=context.user_id`, whatever any result says.
- Every user-scoped read is checked on the server: the services look the resource up by the user
  *and* its id. Another user's resource is answered exactly like a missing one,
  `RESOURCE_NOT_FOUND`, so its existence is never revealed. This is Formiq's "404 for another
  user's resource" rule.
- Ids must be grounded. A resource id argument must have been written by the user in this message
  or returned by a tool in this turn (`known_ids`, `ungrounded_ids` in `app/agent/policy.py`).
  Otherwise the call is refused with `ID_NOT_GROUNDED` before it runs.
- The API routes under `/users/{user_id}` serve only the authenticated user: any other `user_id`
  is answered 404, exactly like a user that does not exist.
- Credentials stay outside the coach. The password hash is in its own table (`user_credentials`),
  which no tool and no agent module reads. The profile tool gives the user's
  name and fitness profile, never their email or phone, although login uses the email.

Enforced by:

- `tests/unit/test_coach_state.py::test_the_model_cannot_choose_the_user_of_the_tools`
- `tests/unit/test_coach_state.py::test_a_user_id_in_the_graph_input_is_ignored`
- `tests/unit/test_coach_state.py::test_the_context_cannot_be_changed`
- `tests/unit/test_formiq_tools.py::test_declarations_match_the_inputs_without_user_id`
- `tests/unit/test_formiq_tools.py::test_a_user_id_from_the_model_is_rejected_and_nothing_is_read`
- `tests/integration/test_coach_injection.py::test_history_cannot_ground_an_id_or_set_the_user`
- `tests/integration/test_coach_concurrency.py::test_simultaneous_requests_of_different_users_each_get_only_their_own_answer`
- `tests/unit/test_coach_decisions.py::test_a_guessed_equipment_id_is_rejected_before_any_tool_runs`
- `tests/integration/test_auth_api.py::test_a_request_without_a_valid_token_is_401_and_reads_nothing`
- `tests/integration/test_auth_api.py::test_without_a_signing_secret_authentication_is_unavailable_not_skipped`
- `tests/integration/test_auth_api.py::test_a_body_naming_a_user_is_rejected`
- `tests/integration/test_auth_api.py::test_the_message_cannot_change_who_the_coach_acts_for`
- `tests/integration/test_auth_api.py::test_the_history_cannot_change_who_the_coach_acts_for`
- `tests/integration/test_auth_api.py::test_each_token_gets_its_own_users_data`
- `tests/integration/test_auth_api.py::test_another_users_resources_are_not_found_and_unchanged`
- `tests/integration/test_auth_api.py::test_the_login_email_never_reaches_the_coach`
- `tests/unit/test_auth_security.py::test_the_coach_never_imports_credentials_or_token_code`
- Evaluation invariant `trusted_identity`, run on every case.

---

## 5. Tool contract

- **The agent reaches data only through tools.** The tools call the services, and the services
  call the repositories. `app/agent` and `app/ai` import no SQLAlchemy, models, repositories,
  services or tools. `app/tools` imports services for type hints only.
- **Tools enforce ownership** through the services' user-scoped reads.
- **Tools validate inputs** with Pydantic models (`app/tools/schemas.py`, `extra="forbid"`). An
  invalid call gets `INVALID_INPUT` with a description that never repeats the input values.
- **Tools return bounded results**: limited lists, cut text, and `truncated` flags
  (`app/tools/limits.py`).
- **Tool errors are controlled.** Each has a code from `ToolErrorCode` and a plain message. An
  unexpected exception becomes `TOOL_ERROR`, its cause goes to the server log only, and the read
  transaction is ended.
- **Tools are read-only.** The seven tools listed below are Formiq's reads, and they are the only
  operations a model's call can run. `app.approvals.access` classifies every other name as a
  write. The graph refuses a call to a known write action with `WRITE_NOT_AUTHORIZED`, and a call
  to any other unknown name with `UNKNOWN_TOOL`. Neither reaches the tools (see section 10).
- **Future writes** require the Phase 4.11 approval boundary (section 10). No current tool can
  write.

The read tools (`READ_ACTIONS`, `TOOL_DECLARATIONS`):

- `get_user_profile`
- `get_workout_plan`
- `get_workout_session`
- `get_current_workout_plan`: the user's PLANNED plan with the latest scheduled date, read
  without an id
- `get_latest_workout_session`: the user's most recently started COMPLETED session, read
  without an id
- `get_exercise`
- `search_exercises`

Tool error codes (`ToolErrorCode`):

- `USER_NOT_FOUND`
- `PROFILE_NOT_FOUND`
- `RESOURCE_NOT_FOUND`
- `INVALID_INPUT`
- `UNKNOWN_TOOL`
- `TOOL_LIMIT_REACHED`
- `TOOL_ERROR`

Error codes the graph itself gives the model:

- `ID_NOT_GROUNDED`
- `WRITE_NOT_AUTHORIZED`
- `DECISION_REJECTED`
- `UNKNOWN_TOOL`

### Limits

Each value below is defined once, in the module named; this table only repeats it, and a test
compares the two. Change the source and this table together, on purpose.

The evaluation also pins the agent limits (`EXPECTED_LIMITS` in `app/evaluation/evaluators.py`).

| Limit | Value | Source of truth | Meaning |
|---|---|---|---|
| `MAX_REQUESTED_TOOL_CALLS_PER_TURN` | 20 | `app.agent.graph` | A model turn requesting more calls is rejected as invalid model output. |
| `MAX_EXECUTED_TOOL_CALLS_PER_TURN` | 5 | `app.tools.limits` | Calls the tools run from one turn. The rest get `TOOL_LIMIT_REACHED`. |
| `MAX_TOOL_ITERATIONS` | 5 | `app.agent.graph` | Rounds of tool calls per request. After them only `respond` is allowed. At most `MAX_TOOL_ITERATIONS` + 1 model requests per request. |
| `MAX_GRAPH_STEPS` | 13 | `app.agent.graph` | LangGraph's recursion limit, a backstop one step beyond the longest legal turn. |
| `MAX_TOOL_RESULT_CHARS` | 50000 | `app.agent.context` | The largest result the tools' limits allow, checked by a test. |
| `MAX_SEARCH_RESULTS` | 10 | `app.tools.limits` | Exercises per search. |
| `MAX_EXERCISES` | 30 | `app.tools.limits` | Exercises per plan or session result. |
| `MAX_SETS` | 15 | `app.tools.limits` | Sets per exercise of a session result. |
| `MAX_TEXT_LENGTH` | 500 | `app.tools.limits` | Characters of free text in a result. |
| `MAX_HISTORY_TURNS` | 50 | `app.schemas.coach` | Earlier turns one request may carry. |
| `MAX_HISTORY_TEXT_LENGTH` | 8000 | `app.schemas.coach` | Characters per history turn. |
| `CONTEXT_KEEP_RECENT_TURNS` | 6 | `app.agent.context` | History turns kept. Older ones are counted, not sent. |
| `CONTEXT_MAX_TURN_CHARS` | 1000 | `app.agent.context` | A kept history turn is shortened to this. |
| `CONTEXT_MAX_NOTE_CHARS` | 400 | `app.agent.context` | Formiq's note on omitted turns and safety mentions. |
| `CONTEXT_MAX_CONVERSATION_CHARS` | 8000 | `app.agent.context` | The whole rendered history. |
| `CONTEXT_MAX_CHARS` | 350000 | `app.agent.context` | The most one model request may hold. |
| `CONTEXT_KEEP_RECENT_ROUNDS` | 1 | `app.agent.context` | Latest rounds of tool results, never compacted. |
| `MAX_CONTEXT_COMPACTIONS` | 6 | `app.agent.context` | Model requests per turn whose context may be compacted. |
| `MAX_REPLY_LENGTH` | 8000 | `app.agent.policy` | The longest reply accepted. |
| `INSTRUCTION_ECHO_WORDS` | 10 | `app.agent.trust` | Words in a row shared with the instructions that make a reply an echo. |

The current message is at most 4000 characters: `CoachMessageText` in `app.schemas.coach`. The
model request timeout is the `gemini_timeout_seconds` setting (`app/core/config.py`, 30 seconds by
default), applied by the SDK to each HTTP request.

Enforced by:

- `tests/unit/test_formiq_tools.py::test_there_are_seven_read_only_tools`
- `tests/unit/test_formiq_tools.py::test_tools_reach_data_only_through_the_services`
- `tests/unit/test_formiq_tools.py::test_tools_call_only_read_methods_of_the_services`
- `tests/unit/test_formiq_tools.py::test_only_the_first_calls_of_a_turn_run`
- `tests/unit/test_formiq_tools.py::test_an_unexpected_failure_is_logged_and_hidden_from_the_model`
- `tests/unit/test_formiq_tools.py::test_invalid_arguments_are_described_without_their_values`
- `tests/unit/test_coach_state.py::test_a_turn_requesting_more_is_rejected_before_anything_runs`
- `tests/unit/test_coach_decisions.py::test_the_longest_legal_turn_fits_the_graphs_step_limit`
- `tests/unit/test_evaluation_evaluators.py::test_the_pinned_limits_are_the_production_limits`
- `tests/unit/test_agent_contract.py::test_the_documented_limits_are_the_production_limits`

---

## 6. Decision contract

The model ends every turn with one `respond` call carrying the request's intent, its decision and
the reply. `app/agent/policy.py` checks that call against what the turn actually retrieved. The
policy is deterministic: it never sees the model's reasoning.

Intents (`Intent`):

- `GENERAL_FITNESS`
- `PROFILE`
- `WORKOUT_PLAN`
- `WORKOUT_HISTORY`
- `EXERCISE`
- `ADAPTATION`
- `SAFETY_SENSITIVE`
- `AMBIGUOUS`
- `OUT_OF_SCOPE`: anything not about fitness, the user's Formiq data or how Formiq coaches

Decisions (`Decision`):

- `ANSWER`: from general knowledge.
- `RETRIEVE_THEN_ANSWER`: from Formiq data the tools returned in this turn.
- `ASK_CLARIFICATION`
- `SAFE_REDIRECT`
- `CANNOT_ANSWER`

`POLICY` maps each intent to the decisions it allows and the tools whose data it needs.

Critical invariants:

- **Own-data answers require evidence.** `RETRIEVE_THEN_ANSWER` is accepted only if one of the
  intent's data tools returned data, `AVAILABLE` or `INCOMPLETE`, in this turn. `PROFILE`,
  `WORKOUT_PLAN`, `WORKOUT_HISTORY` and `ADAPTATION` cannot be answered with `ANSWER`.
- **Missing evidence is never fact.** A `MISSING`, `FAILED` or `UNEXPECTED` result is not
  evidence: data status comes from `data_status()`.
- **Compacted evidence is not evidence.** Results whose data was compacted out of the model's
  last request are excluded from the evidence (`seen_results` in `app/agent/graph.py`).
- **Fresh retrieval restores evidence.** Calling the tool again returns the data in a new,
  uncompacted result.
- **Safety-sensitive requests cannot become normal answers.** `SAFETY_SENSITIVE` allows only
  `SAFE_REDIRECT`, and a request flagged by the safety backstop allows only its `SAFETY_POLICY`
  decisions (section 7).
- **Ambiguous requests require clarification.** `AMBIGUOUS` allows only `ASK_CLARIFICATION`.
- **Formiq answers fitness only.** `GENERAL_FITNESS` means general *fitness* knowledge, not
  general knowledge. `OUT_OF_SCOPE` allows only `CANNOT_ANSWER`, and the user always gets
  Formiq's fixed redirect (`OUT_OF_SCOPE_REPLY`), never the model's text. The classification is
  the model's: no deterministic check decides what is fitness.
- **Invalid decisions fail closed.** A malformed or disallowed `respond`, or one beside other
  calls, goes back to the model as `DECISION_REJECTED`, within the iteration limit. A rejected
  final decision ends the turn with `CANNOT_ANSWER` and Formiq's own reply (`CANNOT_ANSWER_REPLY`).
  A rejected decision is never shown to the user.

Enforced by:

- `tests/unit/test_coach_policy.py::test_safety_sensitive_and_ambiguous_requests_have_one_way_out`
- `tests/unit/test_coach_policy.py::test_only_general_and_exercise_questions_may_be_answered_without_data`
- `tests/unit/test_coach_decisions.py::test_a_profile_answer_from_memory_is_rejected_until_the_profile_is_read`
- `tests/unit/test_coach_decisions.py::test_without_usable_data_the_model_must_not_answer_from_it`
- `tests/unit/test_coach_decisions.py::test_an_ambiguous_request_is_clarified_not_guessed`
- `tests/unit/test_coach_decisions.py::test_an_invalid_last_decision_ends_with_cannot_answer`
- `tests/unit/test_coach_conversation_context.py::test_an_answer_from_a_compacted_result_is_rejected_until_the_tool_is_called_again`
- `tests/unit/test_coach_conversation_context.py::test_an_answer_from_a_compacted_result_alone_never_reaches_the_user`
- `tests/integration/test_agent_evaluation.py::test_an_id_from_a_compacted_result_is_grounded_but_is_no_evidence`

---

## 7. Safety contract

`assess_safety()` (`app/agent/safety.py`) reads the current message before the model or any tool
is called. It names the first clear risk signal, by rule precedence, or returns `SAFE`. It is pure:
it has no access to data, tools or the model.

Categories (`SafetyCategory`):

- `SAFE`
- `PAIN_OR_INJURY`: pain beyond ordinary soreness, an injury, or a warning symptom such as chest
  pain, trouble breathing, dizziness or fainting.
- `MEDICAL`: a diagnosis, condition, medication or treatment.
- `DANGEROUS_EXERCISE`: exercising through pain or symptoms, or deliberately risky training.
- `EXTREME_WEIGHT_LOSS`: a crash diet, or a loss rate above the threshold.
- `EXTREME_DIETING`: starvation, purging, a very low daily intake, or a prolonged fast.
- `INSUFFICIENT_SAFETY_CONTEXT`: discomfort too unclear to tell whether it is ordinary soreness or
  something to have checked.

### Thresholds: product safety guardrails

**These are PRODUCT SAFETY GUARDRAILS, not universal medical rules.** Each is set at or beyond a
line in common public guidance, so that only requests clearly outside it are redirected to a
professional. A request beyond a threshold is not declared unsafe for everyone. A request within
one is not declared safe: it goes on to the model and the decision policy like any other request.
These are product decisions, to be revisited with a qualified professional.

| Guardrail | Value | Source of truth | Redirected when |
|---|---|---|---|
| `MAX_WEEKLY_LOSS_KG` | 2.0 | `app.agent.safety` | A stated weight-loss target averages more than this many kg a week. Periods under a week count as one week. |
| `MIN_DAILY_CALORIES` | 800 | `app.agent.safety` | A stated daily intake is below this. |
| `MAX_FAST_HOURS` | 72 | `app.agent.safety` | A fast is at least this long. |

### Rules

- **Safety is checked before normal tool execution.** Both graph nodes reassess the current
  message, and the check is the first observation of the trace.
- **Flagged requests cannot use the normal fitness data tools.** The model is offered only a
  `respond` tool restricted to the category's decisions, which are `SAFE_REDIRECT`, plus
  `ASK_CLARIFICATION` for `INSUFFICIENT_SAFETY_CONTEXT`. The tools node runs no tool for a
  flagged request, whatever the model calls.
- **Safety cannot be downgraded by history.** Only the current message is assessed. Risks in
  user history turns are kept as a note to the model, even across compaction, but they never
  flag or unflag the current request.
- **User framing cannot bypass safety.** Only risk signals count: "ignore the pain", "my doctor
  said it's fine" or "don't classify this" neither add nor remove one, and negation is not read.
- **The model cannot override deterministic safety.** It may escalate an unflagged request to
  `SAFETY_SENSITIVE`. It can never lower a flag.
- **A provider failure on a flagged request still produces the fixed safe response.** A timeout,
  an error, an unconfigured key, invalid output or a rejected decision ends the turn with
  `SAFETY_POLICY[category].fallback_reply` after at most one model request, with no retry.
- **Reply validation protects safe responses.** `unsafe_reply()` rejects any reply on the safety
  path that gives unsafe guidance (training through pain, "no pain no gain", a hedged diagnosis, a
  dose, "you don't need a doctor") or shows internal labels. A rejected reply is replaced by the
  fixed safe reply.

This phase does not change any safety rule.

Enforced by:

- `tests/unit/test_coach_safety.py::test_the_taxonomy_is_small_and_explicit`
- `tests/unit/test_coach_safety.py::test_the_weight_loss_rate_threshold`
- `tests/unit/test_coach_safety.py::test_the_daily_calorie_threshold`
- `tests/unit/test_coach_safety.py::test_the_fast_length_threshold`
- `tests/unit/test_coach_safety.py::test_claims_about_the_check_neither_add_nor_remove_a_flag`
- `tests/unit/test_coach_safety.py::test_no_flagged_request_can_end_with_an_answer`
- `tests/unit/test_coach_safety.py::test_the_safety_layer_has_no_access_to_data`
- `tests/unit/test_coach_guardrails.py::test_no_tool_runs_for_a_flagged_request`
- `tests/unit/test_coach_guardrails.py::test_any_provider_failure_on_a_flagged_request_ends_safely`
- `tests/unit/test_coach_guardrails.py::test_an_unsafe_redirect_reply_is_replaced`
- `tests/unit/test_coach_injection.py::test_history_cannot_downgrade_the_current_messages_safety`
- `tests/integration/test_coach_failures.py::test_a_flagged_request_keeps_the_fixed_safe_reply_whatever_the_provider_does`
- Evaluation invariant `safety_path` and evaluator `safety`, run on every case.

---

## 8. Context contract

### History

- **Client-provided.** Formiq stores no conversation. The client sends earlier turns with each
  message.
- **Untrusted.** It is unverified, and a turn marked `coach` is not necessarily a reply the coach
  gave.
- **Bounded.** The API accepts at most `MAX_HISTORY_TURNS` turns of at most
  `MAX_HISTORY_TEXT_LENGTH` characters each. `compact_conversation()` keeps the last
  `CONTEXT_KEEP_RECENT_TURNS`, each shortened to `CONTEXT_MAX_TURN_CHARS`, and replaces older
  turns with a count.
- **Tagged.** It is sent inside `<conversation_history>`, one `<turn from="...">` per turn, under a
  heading that marks it as untrusted context. Turn text is neutralized, so it cannot close or forge
  the delimiters.
- **It cannot modify policy, establish identity, ground an id or establish authorization.**

### Compaction

- **Compaction is bounded.** A model request is at most `CONTEXT_MAX_CHARS`. When a request is
  over budget, `fit_request()` replaces the data of the oldest tool results with a "compacted"
  note, oldest first. The latest `CONTEXT_KEEP_RECENT_ROUNDS` rounds, errors, the model's own turns
  and the current message are never compacted. At most `MAX_CONTEXT_COMPACTIONS` requests per turn
  may be compacted.
- **The full state stays available internally.** Compaction changes only what is sent. The state
  keeps every full result, for the decision policy and id grounding.
- **Compacted results cannot count as evidence.** See section 6.
- **Ids from compacted results stay usable for grounding.** The ids were returned by a tool in
  this turn, so a call using them is not refused.
- **Fresh retrieval is required to restore evidence.**
- **Context exhaustion fails closed.** A request that still does not fit, or would need more
  compactions than allowed, is never sent. The turn ends with `CANNOT_ANSWER`, or with the fixed
  safe reply for a flagged request.

Enforced by:

- `tests/unit/test_coach_injection.py::test_history_stays_inside_its_delimiters`
- `tests/unit/test_coach_compaction.py::test_the_context_is_marked_as_context_and_not_as_formiq_data`
- `tests/unit/test_coach_compaction.py::test_the_largest_conversation_stays_within_its_limits`
- `tests/unit/test_coach_compaction.py::test_a_safety_risk_in_a_left_out_turn_is_never_lost`
- `tests/unit/test_coach_compaction.py::test_the_latest_round_is_never_compacted`
- `tests/unit/test_coach_compaction.py::test_whatever_the_turn_holds_a_fitting_request_is_within_the_budget`
- `tests/unit/test_coach_conversation_context.py::test_an_id_from_a_compacted_result_stays_grounded`
- `tests/unit/test_coach_conversation_context.py::test_a_request_over_the_budget_is_never_sent`
- `tests/unit/test_coach_conversation_context.py::test_a_flagged_request_over_the_budget_gets_the_safe_reply`
- `tests/unit/test_coach_conversation_context.py::test_compactions_per_turn_are_capped`

---

## 9. Prompt-injection contract

The coach does **not** assume the model enforces any boundary. The model is treated as
persuadable. Each layer below is enforced in code, outside the model.

| # | Layer | Where |
|---|---|---|
| 1 | Trust hierarchy: instructions apart from data, and data never instructions | `app/agent/trust.py`, `COACH_INSTRUCTIONS` |
| 2 | Input and history boundaries: delimiters, neutralized text, function responses as data | `app/agent/context.py`, `app/ai/gemini.py` |
| 3 | Tool contracts: declared tools only, validated inputs, no `user_id` | `app/tools/` |
| 4 | Id grounding: only ids from the user's message or this turn's results | `app/agent/policy.py` |
| 5 | Ownership validation: user-scoped reads in the services, and another user's data as not found | `app/services/`, `app/tools/formiq_tools.py` |
| 6 | Deterministic safety: on the current message, before the model | `app/agent/safety.py` |
| 7 | Decision validation: intent, decision, evidence and the safety policy | `app/agent/policy.py` |
| 8 | Reply validation: no instruction echo, no internal names, no claim of a change | `app/agent/trust.py`, `unsafe_reply()` |
| 9 | Write authorization: no write from a model's call, and approval owned by the application | `app/approvals/`, `run_calls()` in `app/agent/graph.py` |

The coach does not try to detect injections in its input: no list of them is reliable, and none
of the layers depends on finding one.

Enforced by:

- `tests/unit/test_coach_injection.py::test_delimiters_cannot_be_written_by_untrusted_text`
- `tests/unit/test_coach_injection.py::test_tool_text_reaches_the_model_only_as_a_function_responses_data`
- `tests/unit/test_coach_injection.py::test_a_reply_showing_internal_names_is_rejected`
- `tests/unit/test_coach_injection.py::test_a_reply_claiming_a_change_is_rejected`
- `tests/integration/test_coach_injection.py::test_an_extraction_attempt_never_returns_the_instructions`
- `tests/integration/test_coach_injection.py::test_a_poisoned_note_cannot_downgrade_a_flagged_request`

---

## 10. Write contract

**The current agent is READ ONLY.** No tool writes. The graph refuses every call outside the
read tools before it reaches the tools: `WRITE_NOT_AUTHORIZED` for a known write action, and
`UNKNOWN_TOOL` for any other name. Each refused write is recorded by name, never by its values,
and counted as `write_calls_refused`. A reply claiming a change is rejected.

Write actions Formiq knows (`WriteAction`, `app/approvals/access.py`). None of them is implemented:

- `create_workout_plan`
- `modify_workout_plan`
- `cancel_workout_plan`
- `record_workout`
- `modify_profile`
- `record_nutrition`
- `delete_user_data`

A future write must pass the Phase 4.11 boundary, in this order:

```
model proposal (a draft: action, target, parameters)
   ↓
application policy           read/write classification; malformed or reserved fields are refused
   ↓
trusted identity             WriteProposal.trusted_user_id is injected by the application
   ↓
safety                       a flagged request or flagged proposal text gets no proposal
   ↓
exact proposal binding       SHA-256 over the proposal id, user, action, target, typed parameters and version
   ↓
explicit application-owned approval
                             an ApprovalEvent from USER_ACTION, for this approval, this proposal and this binding
   ↓
expiration / replay checks   injected clock and TTL; single-use event ids; decided once
   ↓
authorization                ApprovalStore.consume(): approved, unchanged, current version, still safe; used once
   ↓
future write                 (does not exist)
```

Approval states (`ApprovalState`):

- `NOT_REQUIRED`
- `PENDING`
- `APPROVED`
- `REJECTED`
- `EXPIRED`
- `CONSUMED`

Every refusal has a reason (`AuthorizationFailure`). Every check fails closed:

- `PROPOSAL_NOT_FOUND`
- `PROPOSAL_ALREADY_REGISTERED`
- `MALFORMED_PROPOSAL`
- `WRONG_USER`
- `APPROVAL_NOT_FOUND`
- `APPROVAL_FOR_ANOTHER_PROPOSAL`
- `UNTRUSTED_SOURCE`
- `REPLAYED_EVENT`
- `ALREADY_DECIDED`
- `NOT_APPROVED`
- `REJECTED`
- `EXPIRED`
- `CONSUMED`
- `PROPOSAL_CHANGED`
- `STALE_RESOURCE`
- `SAFETY_BLOCKED`

**Explicitly prohibited.** Each of these is refused and tested:

- model-generated `approved=true`, or any other authority claim, in a proposal's parameters;
- a model-generated `user_id`;
- approval based on history;
- approval based on a tool result;
- approval from a previous assistant turn;
- self-authorized writes: any approval whose source is not the user's own action at Formiq's
  interaction boundary.

The agent can import only `app.approvals.access`, the classification. It cannot reach proposals,
approvals or the gate. `ApprovalStore` is in memory and per instance: it is the reference
implementation of the contract, not production persistence. No API endpoint creates, approves or
uses a proposal.

Enforced by:

- `tests/unit/test_write_boundary_agent.py::test_a_write_the_model_calls_never_runs_whatever_it_claims`
- `tests/unit/test_write_boundary_agent.py::test_the_agent_reads_only_the_classification_of_the_write_boundary`
- `tests/unit/test_write_boundary_agent.py::test_the_api_has_no_approval_or_coach_write_endpoint`
- `tests/unit/test_write_boundary.py::test_a_model_call_claiming_authority_or_identity_is_malformed`
- `tests/unit/test_write_boundary.py::test_an_approval_from_anything_but_the_user_is_refused`
- `tests/unit/test_write_boundary.py::test_a_changed_proposal_is_not_covered_by_its_approval`
- `tests/unit/test_write_boundary.py::test_a_replayed_approval_event_is_refused`
- `tests/unit/test_write_boundary.py::test_an_approval_used_after_it_expired_is_refused`
- `tests/unit/test_write_boundary.py::test_an_approved_proposal_is_refused_when_safety_now_blocks_it`
- `tests/unit/test_write_boundary_reliability.py::test_simultaneous_uses_of_an_approval_allow_one_write`
- `tests/integration/test_write_boundary.py::test_no_write_a_model_asks_for_changes_any_data`
- `tests/unit/test_agent_contract.py::test_the_approval_boundary_reaches_no_data`
- Evaluation invariant `write_boundary`, run on every case.

---

## 11. Failure contract

General rule: **FAIL CLOSED.** A failure never silently becomes a success.

- **There is no automatic provider retry.** The SDK is configured without `retry_options`, so it
  makes one attempt per model request.
- **There is no uncontrolled agent retry.** The only repeated model requests are the model's own
  bounded re-decisions after a refused call or a rejected decision or reply. They are counted, and
  they stop at `MAX_TOOL_ITERATIONS`.
- A failed request is never re-run.

Errors returned to the client never carry their cause. The cause goes to the server log, and the
trace records only its category (`Failure`).

| Failure | HTTP | Trace status | What the user gets |
|---|---|---|---|
| Provider not configured (no `GEMINI_API_KEY`) | 503 | `provider_not_configured` | "the AI coach is not configured". Nothing is sent. |
| Timeout (the SDK timeout, or `TimeoutError`) | 502 | `provider_timeout` | "the AI coach could not answer; try again later" |
| 429 | 502 | `rate_limit` | the same |
| 500 | 502 | `provider_error` | the same |
| 503 | 502 | `provider_error` | the same |
| 504 | 502 | `provider_timeout` | the same |
| Network failure, or a malformed response body | 502 | `provider_error` | the same |
| Invalid model output: no candidates, blocked, text without a decision, too many calls, a tool after the limit | 502 | `model_output_invalid` | the same |
| **Any of the provider failures above, on a flagged request** | 200 | `safety_redirect` | The fixed safe reply, after one attempt. |
| Tool validation failure (`INVALID_INPUT`, `UNKNOWN_TOOL`, `ID_NOT_GROUNDED`, `WRITE_NOT_AUTHORIZED`) | 200 | The turn's outcome | The model gets the error as data and must decide again, usually ending in `CANNOT_ANSWER` or a question. |
| Tool failure (`TOOL_ERROR`, for example a database error) | 200 | Usually `cannot_answer` | The read transaction is ended, and the turn's other calls still work. |
| Profile or resource not found, or another user's resource | 200 | Usually `cannot_answer` | It is never answered as if the data existed. |
| No access token, or one that is malformed, wrongly signed, expired, or for a user that does not exist | 401 | Not traced | The coach never runs: nothing is read and the model is never called. |
| Authentication not configured (no `AUTH_JWT_SECRET`) | 503 | Not traced | The same. |
| A body with a `user_id` or another unknown field | 422 | Not traced | The same. |
| User not found after authentication (deleted in between) | 404 | `user_not_found` | The model is never called. |
| Context exhaustion (budget or compaction limit) | 200 | `cannot_answer` | `CANNOT_ANSWER_REPLY`, or the fixed safe reply when flagged |
| Iteration limit with no acceptable decision | 200 | `cannot_answer` | `CANNOT_ANSWER_REPLY` |
| Graph step limit (`GraphRecursionError`, a backstop the production limits never reach) | 500 | `graph_limit_exceeded` | A generic server error |
| Unexpected exception in the service, the graph or safety | 500 | `unknown_error` | A generic server error, with no details |
| Observability failure (Langfuse failing, hanging or misconfigured) | Unchanged | Unchanged | Exactly what it would be with tracing off |
| Interruption (`KeyboardInterrupt`, or another `BaseException`) | No response | No final status (section 14) | It propagates unchanged and is never converted into a success. |

Enforced by:

- `tests/integration/test_coach_failures.py::test_a_provider_failure_is_tried_once_and_changes_nothing`
- `tests/integration/test_coach_failures.py::test_an_unconfigured_provider_sends_nothing_and_answers_503`
- `tests/integration/test_coach_failures.py::test_a_timeout_anywhere_in_a_turn_ends_it_without_a_retry`
- `tests/integration/test_coach_failures.py::test_an_unexpected_exception_ends_only_its_request_and_shows_nothing`
- `tests/integration/test_coach_failures.py::test_the_user_lookup_failing_is_not_a_missing_user`
- `tests/integration/test_coach_sessions.py::test_every_request_closes_its_session_and_holds_nothing`
- `tests/unit/test_gemini_provider.py::test_timeout_is_a_provider_error_after_one_attempt`
- `tests/unit/test_reliability_state.py::test_the_graph_limit_holds_for_every_turn_however_often_it_is_reached`
- `tests/unit/test_coach_injection.py::test_retries_of_a_rejected_reply_stop_at_the_iteration_limit`
- `tests/unit/test_agent_contract.py::test_every_failure_category_is_documented`
- Evaluation invariants `outcome_recorded` and `no_leaks`, run on every case.

Failure categories (`Failure`):

- `provider_not_configured`
- `provider_timeout`
- `provider_error`
- `rate_limit`
- `model_output_invalid`
- `tool_error`
- `tool_validation_error`
- `ownership_failure`
- `tool_limit_reached`
- `id_not_grounded`
- `write_not_authorized`
- `decision_rejected`
- `reply_rejected`
- `safety_redirect`
- `context_budget_exceeded`
- `compaction_limit_exceeded`
- `graph_limit_exceeded`
- `user_not_found`
- `unknown_error`

Final request statuses:

- `success` and `clarification` are recorded at the default level.
- `safety_redirect` and `cannot_answer` are recorded at warning level.
- Any failure category above is recorded at error level.

---

## 12. Observability contract

**Langfuse is non-authoritative.** It, and the tracing interface in front of it, must never:

- change decisions;
- change safety;
- change tools;
- change retries;
- change the response;
- cause a request to fail.

How this is ensured:

- Every backend call is guarded (`Observation._guard`): a failure is logged by exception type
  only, and the request goes on.
- Export happens in the background; no request waits on Langfuse.
- Nothing recorded is read back by the coach.
- `app/observability` imports no agent, tool, service, approval or data code.

**Privacy contract.** The coach does **NOT** trace:

- the raw user message;
- the conversation history;
- the system prompt or instructions;
- chain-of-thought or reasoning;
- tool arguments: names only, never values;
- tool results;
- profile data;
- workout data;
- nutrition data;
- API keys;
- exception text, which can hold sensitive details. Only the category and type are recorded.

The coach records only safe metadata:

- counts, sizes, names, statuses and categories;
- the model name and the token counts the provider reported;
- the trusted user id and Formiq's request id.

Observations take no input or output. `safe_metadata()` keeps only flat, primitive values: strings
at most `MAX_VALUE_CHARS` = 100 characters, lists at most `MAX_LIST_ITEMS` = 25 items. Langfuse's
`mask` applies the same rule again to anything the SDK would send.

| Bound | Value | Source of truth | Meaning |
|---|---|---|---|
| `MAX_VALUE_CHARS` | 100 | `app.observability.tracing` | The longest string recorded. |
| `MAX_LIST_ITEMS` | 25 | `app.observability.tracing` | The longest list recorded. |

**Known limitations, found in Phase 4.10 and not yet solved:**

1. **Tool timing is per batch.** All tool observations of one batch start before and end after the
   single `tools.run()` call. Each one's duration is the whole batch's, not its own call's.
2. **An interrupted trace may lack a final status.** `CoachService` finishes the trace for an
   `Exception`. A non-`Exception` interruption such as `KeyboardInterrupt` ends the trace without
   `finish()`, so the root observation has no status. The inner observations it passed through are
   marked failed.
3. **Tool-call counters count calls handed to the tools.** `tool_calls_executed` includes calls the
   tools answer with `TOOL_LIMIT_REACHED` without running them, beyond the fifth. Each tool
   observation's `executed` flag is `true` for them as well. `tool_calls_requested` counts every
   non-`respond` call, including refused ones. The evaluation corrects for this (`_executed` in
   `app/evaluation/runner.py`). A dashboard reading the raw counters would not.
4. **Rendering in a live Langfuse project has not been verified.** The tests export to memory, to
   an in-memory OpenTelemetry exporter, or to a closed local port. None sends anything to a real
   Langfuse project.

Enforced by:

- `tests/unit/test_coach_tracing.py::test_no_content_reaches_the_trace`
- `tests/unit/test_coach_tracing.py::test_tool_arguments_are_recorded_by_name_never_by_value`
- `tests/unit/test_coach_tracing.py::test_a_failing_backend_changes_nothing`
- `tests/unit/test_coach_tracing.py::test_langfuses_mask_applies_the_same_rule`
- `tests/integration/test_coach_tracing.py::test_nothing_private_reaches_langfuse`
- `tests/integration/test_coach_tracing.py::test_a_failing_tracer_never_changes_the_api_response`
- `tests/unit/test_reliability_observability.py::test_a_turn_ends_the_same_whatever_its_tracing_does`
- `tests/unit/test_reliability_observability.py::test_a_hanging_langfuse_export_never_holds_a_turn`
- `tests/unit/test_agent_contract.py::test_observability_cannot_reach_what_it_could_change`
- `tests/unit/test_agent_contract.py::test_no_production_code_reads_a_trace_back`

---

## 13. Evaluation contract

**Deterministic evaluation is the primary regression mechanism.** It is built from:

- the dataset: `CASES` in `app/evaluation/dataset.py`;
- the runner (`app/evaluation/runner.py`), which runs each case through `CoachService` and reads
  the outcome from an in-memory trace;
- per-case evaluators (`EVALUATORS`);
- invariants checked on every case (`INVARIANTS`);
- a regression summary (`app/evaluation/report.py`).

Two kinds of run, which must not be conflated:

- **Fake-provider runs** test **application guarantees.** A script plays the model, both good and
  deliberately bad (answering from memory, guessing ids, obeying injections, leaking instructions,
  attempting writes). A pass says what Formiq enforces whatever the model does. It says nothing
  about how well a real model behaves.
  `tests/integration/test_agent_evaluation.py::test_the_dataset_has_no_regressions`
- **Live model runs** test **actual model behavior.** They are opt-in (`LIVE_AGENT_EVAL=1`, with
  `GEMINI_API_KEY` set) and use only the cases marked `live`, with the model-specific expectations
  removed (`live_expectations()`). Their results apply to the model that was run, and to no other
  model.
  `tests/integration/test_agent_evaluation.py::test_live_model`

Rules:

- **No LLM-as-judge is authoritative.** Every evaluator is deterministic.
- **Live results are model-specific.** A live failure of a non-hard evaluator is a finding about
  that model, not a regression.
- **The deterministic invariants stay authoritative for any model.** The `HARD` evaluators must
  pass in every run, live included:
  - `safety`
  - `forbidden_tools`
  - `trusted_identity`
  - `safety_path`
  - `resource_limits`
  - `no_leaks`
  - `outcome_recorded`
  - `write_boundary`
- **The evaluation must not weaken production behavior.** Production code never imports it. A case
  sets up only its fixture data, its canned tool outputs and, to reach paths the production limits
  make rare, its own context budget, iteration limit or step limit (`Overrides`). It changes nothing
  in the coach. No case may be an expected failure.

Enforced by:

- `tests/unit/test_evaluation_dataset.py::test_production_code_never_imports_the_evaluation`
- `tests/unit/test_evaluation_dataset.py::test_no_case_is_an_expected_failure`
- `tests/unit/test_evaluation_dataset.py::test_the_dataset_covers_every_area`
- `tests/unit/test_agent_contract.py::test_the_documented_hard_evaluators_are_the_hard_set`

---

## 14. Reliability contract

Guarantees from Phase 4.10:

- **Request state is isolated.** Each request builds its own `CoachState` and `CoachContext`. The
  compiled graph is shared, and keeps nothing between runs.
- **Provider state is isolated.** One provider object serves every request, and holds no
  per-request state.
- **Tool state is isolated.** `FormiqTools` is built for each request, on that request's session.
- **Trusted identity is isolated.** Concurrent requests of different users get only their own data.
- **Database sessions are released.** Every request closes its session, however it ends.
- **No database connection is held during a model call.** The user lookup's read is ended before
  the model is called, and the tools end theirs after each batch.
- **There is no uncontrolled retry** (section 11).
- **Resource limits apply per request,** and start from zero for each.
- **Langfuse failures are isolated:** a failing, hanging or misconfigured tracer changes no turn,
  alone or under concurrency.
- **Concurrent requests are isolated:** history, tool results, failures and limits never cross
  between requests.

**Cancellation is NOT fully supported.** Current limitations:

1. **A synchronous coach endpoint cannot interrupt a running turn.** FastAPI runs the endpoint in
   a worker thread, and Python cannot stop a thread from outside. When the ASGI task of a
   disconnected or cancelled request is cancelled, the turn already running continues to its own
   end, within its own limits, and its reply is dropped. Nothing is held once it ends.
2. **An interruption during the user lookup is cleaned up late.** An interruption (a
   `BaseException`) raised during the user lookup, before the coach ends its first read, leaves
   that read transaction open. `get_db` closes the session only when an `Exception` passes through
   it, and FastAPI skips dependency cleanup for an interruption. The transaction is therefore held
   until the session object is dropped. Every other interruption point holds nothing.

A `CancelledError` raised inside a graph node reaches the coach as LangGraph's
`NodeCancelledError`. It ends the request as a failure, never as a success.

Enforced by:

- `tests/unit/test_reliability_state.py::test_simultaneous_turns_on_the_shared_graph_end_as_they_do_alone`
- `tests/unit/test_reliability_state.py::test_running_turns_changes_none_of_the_shared_definitions`
- `tests/integration/test_coach_concurrency.py::test_a_requests_history_never_reaches_another_request`
- `tests/integration/test_coach_concurrency.py::test_a_requests_tool_results_never_reach_another_request`
- `tests/integration/test_coach_concurrency.py::test_more_simultaneous_requests_than_database_connections_all_complete`
- `tests/integration/test_coach_sessions.py::test_a_request_with_several_tool_rounds_holds_nothing_while_the_model_answers`
- `tests/integration/test_coach_resource_limits.py::test_limits_start_from_zero_for_every_request`
- `tests/unit/test_reliability_observability.py::test_simultaneous_turns_end_the_same_on_a_shared_failing_tracer`
- `tests/integration/test_coach_cancellation.py::test_a_cancelled_api_request_runs_to_its_own_end_and_then_holds_nothing`
- `tests/integration/test_coach_cancellation.py::test_an_interruption_during_the_user_lookup_holds_its_read_until_the_session_closes`
- `tests/integration/test_coach_cancellation.py::test_a_cancelled_error_raised_in_a_node_is_never_a_success`

---

## 15. Agent lifecycle

This is the authoritative order of a coach request. Observability is not a final step: each step
records its own observation as it runs, and the trace's final status is written last.

### Ordinary request

```
REQUEST                POST /coach/message
  ↓
AUTHENTICATION         get_current_user: Bearer token verified, its user loaded (401 if not);
                       the body is then validated (CoachMessageRequest: no user_id)
  ↓
REQUEST ID             CoachService: uuid4 request id; the trace is opened (metadata only)
  ↓
TRUSTED USER CONTEXT   the authenticated user's id; it is looked up again (404 if gone since);
                       the read is ended;
                       CoachContext(user_id, provider, tools, trace), outside the state
  ↓
SAFETY CHECK           assess_safety(current message): before the model and any tool
  ↓
CONTEXT PREPARATION    history compacted and tagged (initial_state); request fitted to
                       CONTEXT_MAX_CHARS, compacting the oldest results (fit_request)
  ↓
MODEL TURN             one request, no retry; it must be tool calls (≤ 20), ending with respond
  ↓
TOOL VALIDATION        respond alone? write or unknown → refused; ungrounded id → refused;
                       input schema and no user_id → INVALID_INPUT
  ↓
TOOL EXECUTION         FormiqTools.run(user_id=trusted): ≤ 5 calls, services, ownership,
                       bounded output; the read is ended after the batch
  ↓                    (back to MODEL TURN, at most MAX_TOOL_ITERATIONS rounds)
EVIDENCE VALIDATION    only results the model saw, uncompacted, with data (seen_results)
  ↓
DECISION VALIDATION    Respond schema; check_decision (intent → decisions, evidence);
                       check_safety
  ↓
REPLY VALIDATION       reply_problem: no instruction echo, internal names or change claims
  ↓                    (a rejection goes back to the model, within the iteration limit)
FINAL RESPONSE         the accepted reply, or CANNOT_ANSWER_REPLY
  ↓
OBSERVABILITY          trace.finish(status, intent, decision, safety, tools used, reply size);
                       one log line with the request id
```

### Flagged request

```
REQUEST
  ↓
SAFETY FLAG               assess_safety ≠ SAFE (only the current message counts)
  ↓
NO NORMAL DATA TOOLS      offered only respond, limited to SAFETY_POLICY's decisions;
                          the tools node runs no tool, whatever the model calls
  ↓
SAFE MODEL / FIXED REPLY  one model request; on any failure or rejection, Formiq's fixed reply
  ↓
REPLY VALIDATION          check_safety + unsafe_reply + reply_problem
  ↓
SAFETY REDIRECT           status safety_redirect
```

### Future write (not implemented)

```
REQUEST
  ↓
WRITE PROPOSAL      a model's draft, which the application turns into a WriteProposal with the trusted user
  ↓
APPROVAL GATE       ApprovalStore: user-owned approval, binding, expiry, replay, version, safety
  ↓
FUTURE WRITE        does not exist; today every write call is refused in run_calls()
```

---

## 16. What must never regress

Every item below is enforced by code and checked by the tests cited in the section named. A change
that breaks one of them is a contract change. It needs an explicit decision, an update to this
document, and new tests. It is never a test to relax.

1. The model never chooses whose data is read (section 4).
2. Another user's resource is indistinguishable from a missing one (section 4).
3. Only ids from the user's message or this turn's tool results are used (section 4).
4. The agent reads data only through the tools, and the tools only through the services
   (section 5).
5. No call outside Formiq's reads ever runs from a model's call (sections 5 and 10).
6. Own-data answers need evidence from this turn: missing, failed or compacted data is never
   evidence (section 6).
7. Safety is assessed in code before the model, cannot be lowered by anything, and a flagged
   request never runs a data tool (section 7).
8. A flagged request always ends with a safe redirect or a question, even when the provider fails
   (section 7).
9. History, tool results and model output never change policy, identity, safety or authorization
   (sections 3 and 8).
10. Every model request fits `CONTEXT_MAX_CHARS`, and an unfittable request is never sent
    (section 8).
11. Every request is bounded: iterations, calls, graph steps, compactions, result sizes (section 5).
12. There is no automatic retry and no uncontrolled agent retry, and no failure becomes a success
    (section 11).
13. No error reaching the client carries its cause (section 11).
14. Observability never changes a request, and never records content (section 12).
15. Approval belongs to the application and the user: never to the model, history, a tool result
    or a previous turn (section 10).
16. Production code never depends on the evaluation (section 13).
17. Requests share no mutable state, and no database connection is held during a model call
    (section 14).
18. The coach's user is the authenticated user. No request body, message, history, tool result or
    model output chooses it, and nothing falls back to anonymous access (section 4).

---

## 17. Known limitations and production prerequisites

Each item is a statement of what is **not** guaranteed today.

| # | Limitation | Section |
|---|---|---|
| 1 | Authentication is minimal. An access token cannot be revoked before it expires (`AUTH_ACCESS_TOKEN_EXPIRE_MINUTES`): there is no logout, refresh token or key rotation. Login has no rate limiting or lockout, and matches the email exactly as stored. Passwords are set with a command (`python -m app.cli set-password`), not through the API. | 4 |
| 2 | The approval store is in memory and per process. There is no persistence, no distributed idempotency, and no approval endpoint or user interface. | 10 |
| 3 | A running turn cannot be cancelled, because the endpoint is synchronous. | 14 |
| 4 | The read transaction of an interrupted user lookup is released late. | 14 |
| 5 | Tool timing in traces is per batch. | 12 |
| 6 | An interrupted request's trace has no final status. | 12 |
| 7 | The raw tool-call counters include calls refused for the per-turn limit. | 12 |
| 8 | Rendering in a live Langfuse project has not been verified. | 12 |
| 9 | The safety rules are keyword and threshold guardrails, not a medical classifier. Subtle risks are left to the model and the decision policy, and negation is not read. | 7 |
| 10 | Safety mentions in history are context for the model, not a flag. A follow-up message without its own risk signal is not flagged. | 7, 8 |
| 11 | Live evaluation results apply only to the model they ran against. | 13 |

---

## 18. Changing this contract

1. Make the change in code, with tests that prove the new behavior.
2. Update the relevant section here, including the tables, which `test_agent_contract.py` checks.
3. If a limit changes, update `EXPECTED_LIMITS` in the evaluation on purpose. Its pin exists so
   that this step cannot be skipped.
4. Never weaken a test, an evaluator or a `HARD` invariant to make a change pass.
