"""Integration tests for CoachService.

They require the local PostgreSQL container to be running (test database). The
model is a mock: no test calls the Gemini API.
"""

from unittest.mock import Mock

import pytest

from app.agent import COACH_INSTRUCTIONS
from app.ai import AIProviderError, AIProviderNotConfiguredError, GeminiProvider
from app.schemas import UserCreate
from app.services import CoachService, UserService
from app.services.exceptions import UserNotFoundError


@pytest.fixture
def user(service_session):
    return UserService(service_session).create_user(UserCreate(email="coach@example.com"))


@pytest.fixture
def provider():
    provider = Mock(spec=GeminiProvider)
    provider.generate.return_value = "Start with three sets of eight."
    return provider


@pytest.fixture
def service(service_session, provider):
    return CoachService(service_session, provider)


def test_reply_comes_from_the_model_through_the_graph(service, user, provider):
    assert service.reply(user.id, "How should I start?") == "Start with three sets of eight."
    provider.generate.assert_called_once_with(
        "How should I start?", instructions=COACH_INSTRUCTIONS
    )


def test_unknown_user_is_not_found_and_the_model_is_not_called(service, provider):
    with pytest.raises(UserNotFoundError, match="user 2147483647 does not exist"):
        service.reply(2_147_483_647, "Hi")

    provider.generate.assert_not_called()


def test_no_transaction_is_open_while_the_model_answers(service, service_session, user, provider):
    in_transaction = []

    def answer(message, *, instructions):
        in_transaction.append(service_session.in_transaction())
        return "Rest today."

    provider.generate.side_effect = answer

    assert service.reply(user.id, "Hi") == "Rest today."
    assert in_transaction == [False]


@pytest.mark.parametrize(
    "failure",
    [AIProviderNotConfiguredError("GEMINI_API_KEY is not set"), AIProviderError("failed")],
)
def test_provider_errors_reach_the_caller(service, user, provider, failure):
    provider.generate.side_effect = failure

    with pytest.raises(AIProviderError) as raised:
        service.reply(user.id, "Hi")

    assert raised.value is failure
