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
  // Formiq's proposal ids and bindings (app.api.routes.coach, app.schemas.coach)
  const PROPOSAL_ID = /^[0-9a-f]{32}$/;
  const BINDING = /^[0-9a-f]{64}$/;
  // the most earlier turns one request may carry (app.schemas.coach)
  const MAX_HISTORY_TURNS = 50;
  // A workout's sections, in the order they are done
  // (app.schemas.workout_plan.PlanSection), with the proposal's estimate of each.
  const SECTIONS = [
    { section: "WARM_UP", title: "Warm-up", minutes: "warm_up_minutes" },
    { section: "MAIN_WORKOUT", title: "Main workout", minutes: "main_minutes" },
    { section: "COOL_DOWN", title: "Cool-down", minutes: "cool_down_minutes" },
  ];

  // Signed out: no token, no conversation. email only labels the page. proposal
  // is the workout plan the coach's latest reply proposed, if any.
  function createSession() {
    return { email: null, token: null, history: [], proposal: null, epoch: 0 };
  }

  // Signing in, as anyone, starts a new conversation: nothing is carried over
  // from the previous user. The epoch tells a late reply it belongs to a
  // conversation that no longer exists.
  function signIn(session, email, token) {
    return { email, token, history: [], proposal: null, epoch: session.epoch + 1 };
  }

  // Signing out forgets the token and the conversation.
  function signOut(session) {
    return { email: null, token: null, history: [], proposal: null, epoch: session.epoch + 1 };
  }

  function clearConversation(session) {
    return { ...session, history: [], proposal: null, epoch: session.epoch + 1 };
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

  // After a reply: the message and the reply join the history, in order. The
  // reply's proposal, if it has one, replaces any earlier one on the page.
  function recordExchange(session, message, reply, proposal = null) {
    return {
      ...session,
      history: [
        ...session.history,
        { role: "user", text: message },
        { role: "coach", text: reply },
      ],
      proposal: readProposal(proposal),
    };
  }

  // A reply's proposal, or null when it has none or it is not one Formiq made.
  // It is kept as received: its binding is sent back unchanged to approve it.
  function readProposal(value) {
    if (!value || typeof value !== "object") return null;
    if (!PROPOSAL_ID.test(value.proposal_id) || !BINDING.test(value.binding)) return null;
    if (!Array.isArray(value.exercises)) return null;
    return { ...value, savedPlanId: null, savedCounts: null };
  }

  // A proposal's exercises by section, in order, each section with its
  // estimated minutes.
  function proposalSections(proposal) {
    return SECTIONS.map(({ section, title, minutes }) => ({
      section,
      title,
      minutes: proposal[minutes],
      exercises: proposal.exercises.filter((exercise) => exercise.section === section),
    }));
  }

  // An exercise's prescription as shown: "3 × 10, 60 s rest", or "2 × 30 s"
  // for a timed one.
  function prescription(exercise) {
    const target =
      exercise.duration_seconds == null ? `${exercise.reps}` : `${exercise.duration_seconds} s`;
    const rest = exercise.rest_seconds == null ? "" : `, ${exercise.rest_seconds} s rest`;
    return `${exercise.sets} × ${target}${rest}`;
  }

  // How many exercises a saved plan has in each section, as the API returned it.
  function sectionCounts(plan) {
    const counts = Object.fromEntries(SECTIONS.map(({ section }) => [section, 0]));
    for (const exercise of Array.isArray(plan.exercises) ? plan.exercises : []) {
      if (exercise && exercise.section in counts) counts[exercise.section] += 1;
    }
    return counts;
  }

  // The approval request, exactly as POST /coach/proposals/{id}/approve takes
  // it: the binding of the proposal as it was shown, and nothing else.
  function approvalPath(proposal) {
    return `/coach/proposals/${encodeURIComponent(proposal.proposal_id)}/approve`;
  }

  function buildApproval(proposal) {
    return { binding: proposal.binding };
  }

  // After the API saved the plan (201): the proposal shows the saved plan's id.
  // Only for the proposal still on the page, and only with a real plan id.
  function recordApproval(session, proposalId, plan) {
    const proposal = session.proposal;
    if (!proposal || proposal.proposal_id !== proposalId) return session;
    if (!plan || !Number.isInteger(plan.id)) return session;
    return {
      ...session,
      proposal: { ...proposal, savedPlanId: plan.id, savedCounts: sectionCounts(plan) },
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

  // A failed approval: a fixed message by status, never the raw body. Nothing
  // was saved.
  const APPROVAL_MESSAGES = {
    404: "Not approved: this proposal was not found. It may have been lost in a server restart. Ask the coach again.",
    409: "Not approved: this proposal expired, was already approved, or can no longer be saved. Ask the coach for a new one.",
    422: "Not approved: the approval request could not be processed.",
  };

  function describeApprovalError(status) {
    return {
      message: APPROVAL_MESSAGES[status] || MESSAGES[status] || `Not approved (HTTP ${status}).`,
      technical: { status },
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
    readProposal,
    proposalSections,
    prescription,
    sectionCounts,
    approvalPath,
    buildApproval,
    recordApproval,
    addTurn,
    describeError,
    describeApprovalError,
    describeLoginError,
    parseExecution,
  };

  if (typeof module !== "undefined" && module.exports) module.exports = Playground;
  else root.Playground = Playground;
})(typeof window !== "undefined" ? window : globalThis);
