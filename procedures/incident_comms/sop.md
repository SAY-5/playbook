# Incident communications

Purpose: Open the incident record and get the first round of communications out within minutes of a report.

## Preconditions
- The report names the affected service and describes the impact.
- The report says whether the incident is customer-facing.

## Steps
1. Find the service channel {#find-channel} (tool: slack.lookup_channel)
   Look up the Slack channel that owns the affected service.
2. Open the incident record {#open-incident} (tool: jira.create_issue)
   Use project INC. Title the incident with the impact level and the affected service.
   - Set priority from the impact matrix.
3. Announce in the incidents channel {#announce} (tool: slack.post)
   Post to #incidents mentioning the issue key. Say that we are investigating.
4. Tell the service owners {#notify-owners} (tool: slack.post)
   Post to the service channel mentioning the issue key.
5. Log the communications {#log-comms} (tool: jira.comment)
   Comment on the incident with the channels that were notified.
6. Public status {#public-status} (tool: slack.post)
   Customer-facing incidents must also be announced in #status-updates.

## Escalation
- Full outage: page the incident commander in #ic-oncall.

## Never
- Never call an incident resolved in the first announcement.
- Never post incident details to #general.

## Checks
- An INC ticket exists with the matrix priority.
- The #incidents post names the ticket key.
- Customer-facing incidents appear in #status-updates.
