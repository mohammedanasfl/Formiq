// The playground's state and rules, without the page: what is sent, what is
// kept, and what an error shows. Pure functions over plain objects, so they
// run in the browser (window.Playground) and in Node's tests (require).
//
// The conversation and the access token live only in memory: a reload or a
// closed tab clears both. Nothing is written to storage or cookies.
(function (root) {
  "use strict";

  const COACH_PATH = "/coach/message";
  const LOGIN_PATH = "/auth/login";
  // the most earlier turns one request may carry (app.schemas.coach)
  const MAX_HISTORY_TURNS = 50;

  // Signed out: no token, no conversation. email only labels the page.
  function createSession() {
    return { email: null, token: null, history: [], epoch: 0 };
  }

  // Signing in, as anyone, starts a new conversation: nothing is carried over
  // from the previous user. The epoch tells a late reply it belongs to a
  // conversation that no longer exists.
  function signIn(session, email, token) {
    return { email, token, history: [], epoch: session.epoch + 1 };
  }

  // Signing out forgets the token and the conversation.
  function signOut(session) {
    return { email: null, token: null, history: [], epoch: session.epoch + 1 };
  }

  function clearConversation(session) {
    return { ...session, history: [], epoch: session.epoch + 1 };
  }

  // The login body, exactly as POST /auth/login takes it.
  function buildLogin(email, password) {
    return { email: String(email).trim(), password: String(password) };
  }

  // The coach request body, exactly as the API takes it: the message and the
  // earlier turns (only role and text), the most recent ones that fit. Never a
  // user: the backend takes the user from the access token.
  function buildRequest(session, message) {
    const turns = session.history.slice(-MAX_HISTORY_TURNS);
    return {
      message,
      history: turns.map((turn) => ({ role: turn.role, text: turn.text })),
    };
  }

  // The coach request's headers: the access token, when signed in. Without one
  // the request is sent unauthenticated, to see the API refuse it.
  function requestHeaders(session) {
    const headers = { "Content-Type": "application/json" };
    if (session.token) headers.Authorization = `Bearer ${session.token}`;
    return headers;
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
    401: "Not signed in, or the session expired. Log in again.",
    404: "Not found.",
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

  // A failed login: one message for every wrong email or password, as the API
  // gives one answer for all of them.
  function describeLoginError(status) {
    if (status === 401) return "Invalid email or password.";
    if (status === 422) return "Enter an email and a password.";
    if (status === 503) return "Authentication is not configured (AUTH_JWT_SECRET is not set).";
    if (status === 0) return MESSAGES[0];
    return `Login failed (HTTP ${status}).`;
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
    LOGIN_PATH,
    MAX_HISTORY_TURNS,
    createSession,
    signIn,
    signOut,
    clearConversation,
    buildLogin,
    buildRequest,
    requestHeaders,
    recordExchange,
    addTurn,
    describeError,
    describeLoginError,
    parseExecution,
  };

  if (typeof module !== "undefined" && module.exports) module.exports = Playground;
  else root.Playground = Playground;
})(typeof window !== "undefined" ? window : globalThis);
