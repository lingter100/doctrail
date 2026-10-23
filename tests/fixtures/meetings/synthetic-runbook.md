# Synthetic search operations runbook
This document was authored by AI for functional testing. It is not a real organization's policy.

Search logs contain request IDs and safe error codes. Raw question text and document text must not be written to operational logs.
To verify log deletion, inspect the scheduled deletion job and the retained timestamp range.
The retention period is determined by the confirmed release meeting decision; this runbook does not define a number of days.
The release requires access-control regression tests and source-citation checks.
