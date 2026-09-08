# Support triage

Purpose: Triage an inbound support request into Jira, attach what we already know, and escalate the cases that need engineering attention.

## Preconditions
- The request includes the account id and the customer tier.
- The request states a severity (sev1 to sev4) or enough detail to infer one.

## Steps
1. Search the knowledge base {#kb-search} (tool: kb.search)
   Search for the error text or the main symptom from the report before touching Jira.
2. Create the ticket {#create-ticket} (tool: jira.create_issue)
   Use project SUP. Title the issue with the severity and a short description of the problem.
   - Set priority according to the severity matrix.
   - Include the account id in the description.
3. Record what we know {#record-findings} (tool: jira.comment)
   Comment on the ticket with the KB findings and the customer context.
4. Escalate when needed {#escalate} (tool: slack.post)
   If the issue is sev1, post to #support-escalations. Enterprise accounts also get escalated. Reference the ticket in the post.
5. Set the triage state {#set-state} (tool: jira.transition)
   If a KB article resolves the issue, transition to "Waiting for Customer". Otherwise transition to "Triaged".

## Escalation
- sev1: page on-call in #oncall-sev1 and reference the ticket.
- Enterprise accounts: escalate regardless of severity.

## Never
- Never transition a ticket to Done during triage.
- Never post customer PII in Slack.
- Never skip the knowledge base search.

## Checks
- A SUP ticket exists with the severity in the title and the matrix priority.
- Escalations name the ticket key.
- The ticket ends in Waiting for Customer or Triaged.
