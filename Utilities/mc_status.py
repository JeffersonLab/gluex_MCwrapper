"""Shared MCwrapper workflow, attempt, merger, and utility run codes.

The namespaces describe separate fields: Project.Tested, Attempts.Status,
Attempts.ExitCode, the merger's return value, and utility run tracking. Database
NULL values have field-specific meanings and are distinct from numeric codes.
"""


class ProjectStatus:
    """Workflow codes stored in Project.Tested, beyond the initial test result."""

    TEST_FAILED = -1
    """The dispatcher could not successfully test the project configuration."""
    UNTESTED = 0
    """The project is awaiting its initial configuration test."""
    READY = 1
    """The project passed testing; also restored after normal completion."""
    STOPPED = 2
    """Output checks skip the project and the dispatcher recalls its jobs."""
    CANCEL_REQUESTED = 3
    """The dispatcher recalls jobs and removes the canceled project and job rows."""
    DECLARED_COMPLETE = 4
    """Completion was requested manually; outstanding jobs are recalled."""
    BUNDLE_PENDING = 20
    """All active jobs are complete and the project is awaiting output bundling."""
    BUNDLING = 21
    """The wrapper has claimed a normally completed project for bundling."""
    DECLARED_BUNDLE_PENDING = 40
    """A manually completed project is awaiting output bundling."""
    DECLARED_BUNDLING = 41
    """The wrapper has claimed a manually completed project for bundling."""
    UNSUPPORTED_BUNDLE_STATE = 50
    """Wrapper fallback that stops processing an unexpected pending state."""
    BUNDLED = 100
    """Normal output bundling succeeded; the overlord can finalize the project."""
    DECLARED_BUNDLED = 400
    """Manual-completion bundling succeeded; the dispatcher can finalize it."""
    UNKNOWN_BUNDLE_COMPLETION = 500
    """Wrapper fallback for a successful merger with an unexpected running state."""


class AttemptStatus:
    """Numeric Attempts.Status codes for OSG; SWIF continues to use text states.

    Codes 1 through 7 follow HTCondor's JobStatus values:
    https://htcondor.readthedocs.io/en/25.0/codes-other-values/job-status-codes.html
    MCwrapper also uses 6 and 7 locally when handling missing random-trigger
    inputs. These overlapping meanings are preserved, not reinterpreted.
    """

    IDLE = 1
    """The scheduler is waiting to start the job."""
    RUNNING = 2
    """The scheduler is executing the job."""
    REMOVED = 3
    """The job was removed from the scheduler queue."""
    COMPLETED = 4
    """Scheduler execution ended; ExitCode and output checks determine success."""
    HELD = 5
    """The scheduler held the job pending intervention."""
    TRANSFERRING_OUTPUT = 6
    """Scheduler transfer state; also used locally for deactivated input failures."""
    INACTIVE = TRANSFERRING_OUTPUT
    """A job was deactivated because a required input is missing."""
    SUSPENDED = 7
    """Scheduler suspension; also used locally while checking random-trigger input."""
    OUTPUTS_FOUND = 44
    """The observer found every expected output and sets ExitCode to success."""


class ExitCode:
    """Process outcomes and MCwrapper-specific failures stored in Attempts.ExitCode."""

    SUCCESS = 0
    """Execution completed successfully."""
    RANDOM_TRIGGER_NOT_FOUND = 232
    """The random-trigger input was not found by the worker."""
    RANDOM_TRIGGER_DOES_NOT_EXIST = -232
    """Monitoring determined that the required random-trigger input does not exist."""
    OUTPUT_NOT_RETURNED = 404
    """Execution ended but expected output data was not returned."""


class MergerResult:
    """Return values printed by MCMerger and interpreted by the bundle wrapper."""

    SUCCESS = 0
    """All requested merging completed successfully."""
    ONGOING = -666
    """A merging marker already exists; the wrapper may try again later."""


class RunStatus:
    """Text states recorded by the drone, mover, and other utility run trackers."""

    RUNNING = "Running"
    """The utility recorded the start of its work."""
    SUCCESS = "Success"
    """The utility completed its run successfully."""
    FAIL = "Fail"
    """The utility caught an error and recorded a failed run."""


JOB_ACTIVE = 1
"""Jobs.IsActive value included in active-job queries."""
DATA_UNVERIFIED = 0
"""Jobs.DataVerified value indicating outputs still need verification."""
PROJECT_NOTIFIED = 1
"""Project.Notified value indicating completion notification was recorded."""
