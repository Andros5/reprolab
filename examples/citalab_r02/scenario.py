"""ReproLab target for the reconstructed CitaLab N-R02 episodes.

The scenario carries the business property. Its target appointment comes from the
corpus (``scenario.expect`` in each result line): ind-apt-f, the general-practice
appointment of 4 November, for both N-R02 and N-CF-R02.
"""

from __future__ import annotations

from examples.citalab_r02.invariants import reschedule_replaces
from reprolab import Scenario

TARGET_APPOINTMENT = "ind-apt-f"

r02 = Scenario(
    name="citalab_r02",
    invariants=(reschedule_replaces(TARGET_APPOINTMENT),),
    description="CitaLab N-R02 / N-CF-R02: move the 4 November general-practice appointment to the week of 9 November",
)
