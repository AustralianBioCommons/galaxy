"""Unit tests for ChatManager page-scoped methods."""

import json
from unittest import mock

import pytest

from galaxy.managers.chat import ChatManager


def _make_trans(user_id=1):
    """Create a mock ProvidesUserContext."""
    trans = mock.Mock()
    trans.user = mock.Mock()
    trans.user.id = user_id
    trans.sa_session = mock.Mock()
    return trans


class _FakeChatExchange:
    """Lightweight stand-in that avoids SQLAlchemy instrumentation."""

    user_id = mock.Mock()
    job_id = mock.Mock()
    page_id = mock.Mock()
    id = mock.Mock()

    def __init__(self, user=None, job_id=None, page_id=None, message=None, **kw):
        self.user = user
        self.job_id = job_id
        self.page_id = page_id
        self.messages = []
        if message:
            self.add_message(message)

    def add_message(self, message):
        self.messages.append(_FakeChatExchangeMessage(message=message))


class _FakeChatExchangeMessage:
    def __init__(self, message, feedback=None):
        self.message = message
        self.feedback = feedback


def _chainable_select(*args, **kwargs):
    """Return a mock that supports chained .where().order_by().limit()."""
    m = mock.Mock()
    m.where.return_value = m
    m.order_by.return_value = m
    m.limit.return_value = m
    return m


@pytest.fixture(autouse=True)
def _patch_models(monkeypatch):
    """Replace real SQLAlchemy models with lightweight fakes."""
    monkeypatch.setattr("galaxy.managers.chat.ChatExchange", _FakeChatExchange)
    monkeypatch.setattr("galaxy.managers.chat.ChatExchangeMessage", _FakeChatExchangeMessage)
    monkeypatch.setattr("galaxy.managers.chat.select", _chainable_select)


class TestCreatePageChat:
    def test_creates_exchange_with_page_id(self):
        mgr = ChatManager()
        trans = _make_trans()

        exchange = mgr.create_page_chat(trans, page_id=42, query="Describe the datasets", response_data="OK")

        assert exchange.page_id == 42
        assert exchange.job_id is None
        assert len(exchange.messages) == 1

        msg_data = json.loads(exchange.messages[0].message)
        assert msg_data["query"] == "Describe the datasets"
        assert msg_data["response"] == "OK"
        assert msg_data["agent_type"] == "page_assistant"

        trans.sa_session.add.assert_called()
        trans.sa_session.commit.assert_called_once()

    def test_creates_with_dict_response(self):
        mgr = ChatManager()
        trans = _make_trans()

        response = {"response": "I see 3 datasets", "agent_response": {"edit_mode": "section_patch"}}
        exchange = mgr.create_page_chat(trans, page_id=7, query="What's here?", response_data=response)

        msg_data = json.loads(exchange.messages[0].message)
        assert msg_data["response"] == "I see 3 datasets"
        assert msg_data["agent_response"] == {"edit_mode": "section_patch"}

    def test_default_agent_type(self):
        mgr = ChatManager()
        trans = _make_trans()

        exchange = mgr.create_page_chat(trans, page_id=1, query="hi", response_data="hello")
        msg_data = json.loads(exchange.messages[0].message)
        assert msg_data["agent_type"] == "page_assistant"

    def test_custom_agent_type(self):
        mgr = ChatManager()
        trans = _make_trans()

        exchange = mgr.create_page_chat(trans, page_id=1, query="hi", response_data="hello", agent_type="custom")
        msg_data = json.loads(exchange.messages[0].message)
        assert msg_data["agent_type"] == "custom"


class TestGetPageChatHistory:
    def test_queries_by_page_id(self):
        mgr = ChatManager()
        trans = _make_trans()

        mock_exchange = mock.Mock()
        trans.sa_session.execute.return_value.scalars.return_value.all.return_value = [mock_exchange]

        result = mgr.get_page_chat_history(trans, page_id=42)

        assert result == [mock_exchange]
        trans.sa_session.execute.assert_called_once()

    def test_empty_result(self):
        mgr = ChatManager()
        trans = _make_trans()
        trans.sa_session.execute.return_value.scalars.return_value.all.return_value = []

        result = mgr.get_page_chat_history(trans, page_id=99)
        assert result == []


class TestGetUserChatHistoryExcludesPage:
    def test_excludes_page_chats_by_default(self):
        mgr = ChatManager()
        trans = _make_trans()
        trans.sa_session.execute.return_value.scalars.return_value.all.return_value = []

        mgr.get_user_chat_history(trans)

        trans.sa_session.execute.assert_called_once()

    def test_includes_page_chats_when_asked(self):
        mgr = ChatManager()
        trans = _make_trans()
        trans.sa_session.execute.return_value.scalars.return_value.all.return_value = []

        mgr.get_user_chat_history(trans, include_page_chats=True)

        trans.sa_session.execute.assert_called_once()


class TestWasLastMessageClarification:
    """The router emits agent_type='clarification' when it asks the user a question.
    The next turn's answer needs that one turn of routing context, so the API surfaces
    'was the last turn a clarification?' as a flag -- this is the detection helper."""

    @staticmethod
    def _exchange_with(*messages):
        exchange = _FakeChatExchange()
        for message in messages:
            exchange.add_message(message if isinstance(message, str) else json.dumps(message))
        return exchange

    def test_true_when_last_response_is_clarification(self):
        mgr = ChatManager()
        trans = _make_trans()
        exchange = self._exchange_with(
            {"query": "help me", "agent_type": "auto", "agent_response": {"agent_type": "clarification"}},
        )
        with mock.patch.object(mgr, "get_exchange_by_id", return_value=exchange):
            assert mgr.was_last_message_clarification(trans, 1) is True

    def test_false_for_normal_last_message(self):
        mgr = ChatManager()
        trans = _make_trans()
        exchange = self._exchange_with(
            {"query": "align reads", "agent_response": {"agent_type": "tool_recommendation"}},
        )
        with mock.patch.object(mgr, "get_exchange_by_id", return_value=exchange):
            assert mgr.was_last_message_clarification(trans, 1) is False

    def test_only_the_last_message_counts(self):
        mgr = ChatManager()
        trans = _make_trans()
        # Earlier clarification, last is normal -> False
        stale = self._exchange_with(
            {"agent_response": {"agent_type": "clarification"}},
            {"agent_response": {"agent_type": "router"}},
        )
        with mock.patch.object(mgr, "get_exchange_by_id", return_value=stale):
            assert mgr.was_last_message_clarification(trans, 1) is False
        # Earlier normal, last is clarification -> True
        fresh = self._exchange_with(
            {"agent_response": {"agent_type": "router"}},
            {"agent_response": {"agent_type": "clarification"}},
        )
        with mock.patch.object(mgr, "get_exchange_by_id", return_value=fresh):
            assert mgr.was_last_message_clarification(trans, 1) is True

    def test_false_when_no_exchange(self):
        mgr = ChatManager()
        trans = _make_trans()
        with mock.patch.object(mgr, "get_exchange_by_id", return_value=None):
            assert mgr.was_last_message_clarification(trans, 999) is False

    def test_false_for_empty_messages(self):
        mgr = ChatManager()
        trans = _make_trans()
        with mock.patch.object(mgr, "get_exchange_by_id", return_value=_FakeChatExchange()):
            assert mgr.was_last_message_clarification(trans, 1) is False

    def test_false_for_malformed_json(self):
        mgr = ChatManager()
        trans = _make_trans()
        exchange = self._exchange_with("not valid json{{{")
        with mock.patch.object(mgr, "get_exchange_by_id", return_value=exchange):
            assert mgr.was_last_message_clarification(trans, 1) is False
