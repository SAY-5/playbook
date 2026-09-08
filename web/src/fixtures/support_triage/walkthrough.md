# Walkthrough: support triage

Recorded with the support lead while triaging three live requests.

[00:00] Interviewer: Walk me through what you do when a request lands.
[00:12] Expert: First thing, before I even open Jira, I search the knowledge base for the error text. Half of these are known issues.
[00:41] Expert: Then I open the SUP ticket. Priority follows severity: sev1 is Highest, sev2 is High, sev3 is Medium, sev4 is Low.
[01:05] Expert: One exception: Enterprise accounts get bumped one level for sev2 and sev3, so a sev2 from Enterprise is Highest and a sev3 is High.
[01:30] Interviewer: What goes in the title?
[01:38] Expert: The severity in brackets and then the short problem statement, so people can scan the board.
[02:02] Expert: I always paste the KB matches into a comment along with the account id and tier so engineering has context.
[02:30] Interviewer: When do you escalate?
[02:36] Expert: Anything sev1 goes to #support-escalations and I page on-call in #oncall-sev1. Enterprise accounts get escalated at any severity.
[03:01] Expert: Never put the customer's email or phone number in Slack. Refer to them by account id.
[03:20] Expert: The Slack post must name the ticket key, otherwise nobody can find it.
[03:45] Interviewer: And the final state?
[03:50] Expert: If a KB article resolves it, the ticket goes to Waiting for Customer. Otherwise it is Triaged. It is never Done at this stage.
