import socket

import anthropic
import httpx

from fakes import model_server
from fakes.model_server import RuleEngine, parse_action, parse_cond, parse_intake, parse_prompt


def _non_loopback_ipv4() -> str | None:
    """An address of this host on a real interface, found without sending a packet."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.255.255.255", 1))
            address = probe.getsockname()[0]
    except OSError:
        return None
    return None if address.startswith("127.") else address


def test_fakes_bind_loopback_by_default_and_any_interface_on_request():
    default = model_server.serve(0)
    try:
        assert default.httpd.server_address[0] == "127.0.0.1"
        assert default.url == f"http://127.0.0.1:{default.port}"
    finally:
        default.stop()
    wide = model_server.serve(0, host="0.0.0.0")
    try:
        assert wide.httpd.server_address[0] == "0.0.0.0"
        assert wide.url == f"http://127.0.0.1:{wide.port}"
        address = _non_loopback_ipv4() or "127.0.0.1"
        assert httpx.get(f"http://{address}:{wide.port}/health", timeout=5).json()["ok"] is True
    finally:
        wide.stop()


def test_model_fake_speaks_the_messages_api(fakes):
    client = anthropic.Anthropic(api_key="offline", base_url=fakes["model"].url)
    system = (
        "## Steps\n### Step 1: Search [kb-search] (tool: kb.search)\nSearch first.\n"
        "### Step 2: Ticket [create-ticket] (tool: jira.create_issue)\nUse project SUP.\n"
    )
    msg = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=256,
        system=system,
        tools=[],
        messages=[{"role": "user", "content": "New support request\nTitle: Export stuck\nSeverity: sev2"}],
    )
    assert msg.stop_reason == "tool_use"
    tool_use = next(b for b in msg.content if b.type == "tool_use")
    assert tool_use.name == "kb_search"
    assert tool_use.input == {"query": "Export stuck"}
    assert msg.usage.input_tokens > 0

    follow = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=256,
        system=system,
        messages=[
            {"role": "user", "content": "New support request\nTitle: Export stuck\nSeverity: sev2"},
            {"role": "assistant", "content": [b.model_dump() for b in msg.content]},
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": tool_use.id, "content": '{"matches": []}'}],
            },
        ],
    )
    second = next(b for b in follow.content if b.type == "tool_use")
    assert second.name == "jira_create_issue"
    assert second.input["project"] == "SUP"
    assert second.input["priority"] == "Medium"


def test_condition_grammar():
    assert parse_cond("severity is sev1").severity == "sev1"
    c = parse_cond("severity is sev2 and tier is enterprise")
    assert (c.severity, c.tier, c.specificity) == ("sev2", "enterprise", 2)
    assert parse_cond("a KB article resolves the issue").kb_hit is True
    assert parse_cond("no KB match is found").kb_hit is False
    assert parse_cond("the incident is customer-facing").customer_facing is True
    assert parse_cond("impact is full outage").impact == "full outage"
    assert parse_cond("the moon is full") is None
    assert parse_cond("severity is sev1 and the moon is full") is None


def test_action_grammar_and_prompt_parsing():
    assert parse_action('Set summary to "[{severity}] {title}"', None, "s").value == "[{severity}] {title}"
    post = parse_action("post to #oncall-sev1 mentioning the issue key", None, "s")
    assert (post.channel, post.mention_key) == ("#oncall-sev1", True)
    assert parse_action("Reference the ticket in the post", None, "s") is None
    parsed = parse_prompt(
        "### Step 5: State [set-state] (tool: jira.transition)\n"
        'If a KB article resolves the issue, transition to "Waiting for Customer". Otherwise transition to "Triaged".\n'
    )
    (d,) = parsed.directives
    assert (d.kind, d.value, d.else_value) == ("transition", "Waiting for Customer", "Triaged")


def test_intake_parsing_and_plan_follow_the_prompt():
    facts = parse_intake("New support request\nAccount: ACC-1\nTier: Enterprise\nSeverity: unknown\nTitle: T")
    assert facts["severity"] is None and facts["severity_stated"] is False
    assert facts["tier"] == "enterprise"
    engine = RuleEngine()
    prompt = parse_prompt(
        "### Step 1: Ticket [create-ticket] (tool: jira.create_issue)\nUse project SUP.\n"
        "### Step 2: Escalate [escalate] (tool: slack.post)\n"
        "Corrections:\n- (v2) When tier is enterprise, post to #support-escalations mentioning the issue key.\n"
    )
    intake = "New support request\nAccount: ACC-1\nTier: enterprise\nSeverity: sev3\nTitle: T"
    plan = engine.plan(prompt, intake, {"issue_key": "SUP-7"})
    assert [c["name"] for c in plan] == ["jira_create_issue", "slack_post"]
    assert plan[1]["input"]["text"].startswith("SUP-7:")
    plan_pro = engine.plan(prompt, intake.replace("enterprise", "pro"), {"issue_key": "SUP-7"})
    assert [c["name"] for c in plan_pro] == ["jira_create_issue"]


def test_jira_and_slack_fakes_record_evidence(fakes):
    jira, slack = fakes["jira"].url, fakes["slack"].url
    httpx.delete(jira + "/_inbox")
    httpx.delete(slack + "/_inbox")
    r = httpx.post(
        jira + "/rest/api/3/issue",
        json={"fields": {"project": {"key": "SUP"}, "summary": "x", "priority": {"name": "High"}}},
    )
    key = r.json()["key"]
    assert r.status_code == 201 and key.startswith("SUP-")
    assert (
        httpx.post(jira + f"/rest/api/3/issue/{key}/transitions", json={"transition": {"name": "Triaged"}}).status_code
        == 204
    )
    assert httpx.post(jira + "/rest/api/3/issue/SUP-999/comment", json={"body": "hi"}).status_code == 404
    inbox = httpx.get(jira + "/_inbox").json()
    assert inbox["issues"][key]["fields"]["status"]["name"] == "Triaged"
    assert [e["type"] for e in inbox["events"]] == ["create", "transition"]

    ok = httpx.post(slack + "/api/chat.postMessage", json={"channel": "#incidents", "text": "hello"}).json()
    assert ok["ok"] is True
    bad = httpx.post(slack + "/api/chat.postMessage", json={"channel": "#nope", "text": "hello"}).json()
    assert bad == {"ok": False, "error": "channel_not_found"}
    assert httpx.get(slack + "/_inbox").json()["messages"] == [
        {"channel": "#incidents", "text": "hello", "ts": "1700000000.000100"}
    ]
