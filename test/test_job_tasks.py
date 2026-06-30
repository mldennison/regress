from types import SimpleNamespace

from ak_regress import akJob, akRegress
from pal_regress import domainResource, licenseResource
from regress import job, job_result, job_status, task


def append_phase_resources(job_instance, domains: int, task_index: int) -> None:
    job_instance.tasks[task_index].resources.append(
        domainResource("domains", [domains], ["REQUIRED"])
    )
    job_instance.tasks[task_index].resources.append(
        licenseResource("Palladium_Z2_Domain", [domains], ["REQUIRED"])
    )


class RecordingAkJob(akJob):
    def __init__(self) -> None:
        super().__init__()
        self.executions = []

    @classmethod
    def create_three_phase(cls, _testJob):
        nph = cls()
        phase_attrs = {
            f"{phase}_{attr}"
            for phase in job._PHASE_PREFIXES
            for attr in ("valid", "resources", "program", "args", "dir", "time")
        }

        for field in _testJob.__dict__:
            if field in phase_attrs:
                continue
            if hasattr(_testJob, field):
                setattr(nph, field, getattr(_testJob, field))

        for phase, index in (("build", 0), ("setup", 1), ("run", 2)):
            job.apply_phase_fields(nph, _testJob, phase, index)

        domains = getattr(_testJob, "domains", None)
        if domains is not None:
            for index in range(3):
                append_phase_resources(nph, domains, index)

        nph.update_status()
        return nph

    def run(self, _resources: list, _task: task) -> None:
        self.executions.append(
            {
                "name": _task.name,
                "program": _task.program,
                "args": _task.args,
            }
        )
        if _task.name == "run":
            self.status = job_status.COMPLETED
            self.result = job_result.SUCCESS


class ThreePhaseAkRegress(akRegress):
    def load_test_list(self) -> list:
        jobs = []
        for tjob in self.load_jobs_fn(self.testlist):
            jobs.append(RecordingAkJob.create_three_phase(tjob))
        return jobs


def make_three_phase_testlist_job():
    return SimpleNamespace(
        name="three_phase_job",
        domains=1,
        build_program="build_prog.py",
        build_args=["--build-arg"],
        build_dir=".",
        setup_program="setup_prog.py",
        setup_args=["--setup-arg"],
        setup_dir=".",
        run_program="run_prog.py",
        run_args=["--run-arg"],
        run_dir=".",
    )


def make_test_server_provider(domain_count: int):
    def provider(factory, _test_mode, _test_server_file):
        domain_ids = []
        for idx in range(domain_count):
            board = idx // 8
            domain = idx % 8
            domain_ids.append(f"{board}.{domain}")
        return [factory.create_resource("domains", domain_ids, ["FREE"] * domain_count)]

    return provider


def make_lmstat_provider(available_domains: int):
    def provider(factory, _test_mode, _license_file):
        return [
            factory.create_resource(
                "Palladium_Z2_Domain",
                [available_domains, 0],
                ["AVAILABLE", "USED"],
                "license",
            )
        ]

    return provider


def test_ak_regress_main_runs_build_setup_run_in_order():
    testlist_job = make_three_phase_testlist_job()

    regress_runner = ThreePhaseAkRegress(
        _load_jobs_fn=lambda _path: [testlist_job],
        _test_server_provider=make_test_server_provider(domain_count=3),
        _lmstat_provider=make_lmstat_provider(available_domains=3),
    )
    regress_runner.interval = 0
    regress_runner.main()

    assert len(regress_runner.jobs) == 1
    test_job = regress_runner.jobs[0]
    assert isinstance(test_job, RecordingAkJob)
    assert test_job.status == job_status.COMPLETED
    assert test_job.result == job_result.SUCCESS
    assert [execution["name"] for execution in test_job.executions] == [
        "build",
        "setup",
        "run",
    ]
    assert test_job.executions == [
        {"name": "build", "program": "build_prog.py", "args": ["--build-arg"]},
        {"name": "setup", "program": "setup_prog.py", "args": ["--setup-arg"]},
        {"name": "run", "program": "run_prog.py", "args": ["--run-arg"]},
    ]
