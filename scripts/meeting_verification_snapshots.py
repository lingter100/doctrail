"""Stable report snapshots for follow-up verification; previous evidence stays unchanged."""
import copy

from scripts.verify_meeting_service import Verification


class SnapshotVerification(Verification):
    def meeting(self, *args, **kwargs):
        result = super().meeting(*args, **kwargs)
        # The test client may later edit the returned DTO to confirm a decision.
        # Keep the recorded initial response independent of those later actions.
        self.report['analyses'][-1] = copy.deepcopy(self.report['analyses'][-1])
        self.save()
        return result
