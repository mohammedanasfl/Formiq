// The playground's state and rules, without the page: what is sent, what is
// kept, and what an error shows. Pure functions over plain objects, so they
// run in the browser (window.Playground) and in Node's tests (require).
//
// The conversation lives only in memory: a reload or a closed tab clears it.
(function (root) {
  "use strict";

  const COACH_PATH = "/coach/message";
  // the most earlier turns one request may carry (app.schemas.coach)
  const MAX_HISTORY_TURNS = 50;

  // a development identity: chosen by hand, never authenticated
  function parseUserId(text) {
    const value = String(text).trim();
    if (!/^[1-9][0-9]{0,9}$/.test(value)) return null;
    const id = Number(value);
    return id <= 2147483647 ? id : null;
  }

  function createSession(userId) {
    return { userId, history: [], epoch: 0 };
  }

  // A new development user starts with no conversation: nothing is carried
  // over from the previous one. The epoch tells a late reply it belongs to a
  // conversation that no longer exists.
  function switchUser(session, userId) {
    if (userId === session.userId) return session;
    return { userId, history: [], epoch: session.epoch + 1 };
  }

  function clearConversation(session) {
    return { userId: session.userId, history: [], epoch: session.epoch + 1 };
  }

  // The request body, exactly as the API takes it: the user, the message and
  // the earlier turns (only role and text), the most recent ones that fit.
  function buildRequest(session, message) {
    const turns = session.history.slice(-MAX_HISTORY_TURNS);
    return {
      user_id: session.userId,
      message,
      history: turns.map((turn) => ({ role: turn.role, text: turn.text })),
    };
  }

  // After a reply: the message and the reply join the history, in order.
  function recordExchange(session, message, reply) {
    return {
      ...session,
      history: [
        ...session.history,
        { role: "user", text: message },
        { role: "coach", text: reply },
      ],
    };
  }

  // A turn added by hand, to test what the coach does with a poisoned or
  // forged history. The API accepts any history the client sends; this adds
  // nothing it would not accept from any other client.
  function addTurn(session, role, text) {
    if (role !== "user" && role !== "coach") throw new Error("role must be user or coach");
    return { ...session, history: [...session.history, { role, text, injected: true }] };
  }

  // What the page shows for a failed request: a fixed message by status, and
  // only safe technical details. Never the raw body: it could hold anything.
  const MESSAGES = {
    0: "Could not reach the backend. Is the playground server running?",
    400: "Request could not be processed.",
    404: "Development user not found.",
    422: "Request could not be processed.",
    500: "The backend failed unexpectedly.",
    502: "Coach provider failed.",
    503: "AI provider is not configured.",
  };

  function describeError(status, body, executionData) {
    const technical = { status };
    if (executionData && executionData.status) technical.category = executionData.status;
    if (executionData && executionData.request_id) technical.request_id = executionData.request_id;
    if (status === 422 && body && Array.isArray(body.detail)) {
      // which fields failed and why; never the values that were sent
      technical.fields = body.detail
        .filter((item) => item && Array.isArray(item.loc))
        .map((item) => `${item.loc.join(".")}: ${String(item.msg || "").slice(0, 120)}`);
    }
    return {
      message: MESSAGES[status] || `Unexpected response from the backend (HTTP ${status}).`,
      technical,
    };
  }

  // The X-Playground-Execution header, or null when absent or unreadable.
  function parseExecution(header) {
    if (!header) return null;
    try {
      const value = JSON.parse(header);
      return value && typeof value === "object" && !Array.isArray(value) ? value : null;
    } catch {
      return null;
    }
  }

  const Playground = {
    COACH_PATH,
    MAX_HISTORY_TURNS,
    parseUserId,
    createSession,
    switchUser,
    clearConversation,
    buildRequest,
    recordExchange,
    addTurn,
    describeError,
    parseExecution,
  };

  if (typeof module !== "undefined" && module.exports) module.exports = Playground;
  else root.Playground = Playground;
})(typeof window !== "undefined" ? window : globalThis);
