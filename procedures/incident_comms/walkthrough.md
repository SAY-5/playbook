# Walkthrough: incident communications

Recorded with the on-call lead during a tabletop exercise.

[00:00] Interviewer: What happens in the first five minutes?
[00:09] Expert: I look up the owning channel for the service first, because that is who I need to reach.
[00:30] Expert: Then the INC ticket. Priority is from the impact matrix: full outage is Highest, partial outage is High, degraded is Medium, internal is Low.
[00:58] Expert: The title is the impact level in brackets and then the service, so the board reads at a glance.
[01:20] Expert: The first post goes to #incidents and it always names the ticket key. We say we are investigating and nothing more.
[01:45] Expert: Never say resolved in the first announcement, even if it looks fixed.
[02:05] Expert: If the incident is customer-facing, it must also go to #status-updates.
[02:30] Expert: If it is a full outage, page the incident commander in #ic-oncall.
[02:50] Interviewer: Anything else?
[02:55] Expert: Never post any of this to #general. And I log which channels were notified on the ticket.
