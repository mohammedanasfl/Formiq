# Formiq Documentation

Project documentation will be added here as each development phase is completed.

- [Agent Production Contract](agent-production-contract.md): the AI coach's architectural
  guarantees (identity, data ownership, safety, tools, decisions, limits, context, write approval,
  observability) and its known limitations.
- [Agent trajectory observability](agent-trajectory-observability.md): how to explain a coach turn:
  the model requests and their cost, the tools requested, executed, blocked and failed, and why.
- [Debugging the coach locally](agent-debug.md): `AGENT_DEBUG`, an opt-in terminal view of one turn
  (the prompt's identity, the request sent, the tools, the guards, who wrote the reply), what it
  redacts and why Langfuse still receives metadata only.
- [Warm-up and cool-down activities](warm-up-cool-down.md): the activities the catalog offers for
  those two sections, the rules and sources behind them, what is not verified, what the live
  Gemini QA changed, and how to apply it to a database.
- [Exercise fields](exercise-fields.md): an audit of the catalog's exercise fields (description,
  movement pattern, sections, steps, images), what was filled and how, what is left on purpose.
