from types import SimpleNamespace

from ak_regress import akRegress
from regress import job_status, scheduler


class RecordingScheduler(scheduler):
    def __init__(self) -> None:
        super().__init__()
        self.skipped_counts = []

    def schedule_jobs(self, jobs, status):
        scheduled, skipped, complete = super().schedule_jobs(jobs, status)
        self.skipped_counts.append(len(skipped))
        return [scheduled, skipped, complete]


def make_test_job(name: str, domains: int):
    return SimpleNamespace(
        name=name,
        domains=domains,
        run_program="python",
        run_args=["-c", "print('ok')"],
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


def run_scheduling_iterations(regress_runner, iterations: int = 5) -> None:
    regress_runner.jobs = regress_runner.filter_test_list(regress_runner.load_test_list())
    for _ in range(iterations):
        regress_runner.stat.update()
        regress_runner.sch.schedule_jobs(regress_runner.jobs, regress_runner.stat)


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


def test_main_schedules_all_jobs_when_resources_sufficient():
    jobs = [
        make_test_job("job_1", domains=1),
        make_test_job("job_2", domains=2),
        make_test_job("job_3", domains=1),
    ]
    loaded_paths = []

    def load_jobs_fn(path):
        loaded_paths.append(path)
        return jobs

    regress_runner = akRegress(
        _load_jobs_fn=load_jobs_fn,
        _test_server_provider=make_test_server_provider(domain_count=8),
        _lmstat_provider=make_lmstat_provider(available_domains=8),
    )
    regress_runner.interval = 0
    regress_runner.main()

    assert loaded_paths == [regress_runner.testlist]
    assert len(regress_runner.jobs) == 3
    assert all(job.status == job_status.COMPLETED for job in regress_runner.jobs)


def test_main_handles_constrained_resources_across_iterations():
    jobs = [
        make_test_job("job_1", domains=1),
        make_test_job("job_2", domains=1),
        make_test_job("job_3", domains=1),
    ]
    rec_scheduler = RecordingScheduler()

    regress_runner = akRegress(
        _sch=rec_scheduler,
        _load_jobs_fn=lambda _path: jobs,
        _test_server_provider=make_test_server_provider(domain_count=1),
        _lmstat_provider=make_lmstat_provider(available_domains=1),
    )
    regress_runner.interval = 0
    regress_runner.main()

    assert any(count > 0 for count in rec_scheduler.skipped_counts)
    assert all(job.status == job_status.COMPLETED for job in regress_runner.jobs)


def test_main_behavior_changes_with_different_injected_test_lists():
    def run_once(job_count, available_domains):
        jobs = [make_test_job(f"job_{idx}", domains=1) for idx in range(job_count)]
        regress_runner = akRegress(
            _load_jobs_fn=lambda _path: jobs,
            _test_server_provider=make_test_server_provider(domain_count=available_domains),
            _lmstat_provider=make_lmstat_provider(available_domains=available_domains),
        )
        regress_runner.interval = 0
        regress_runner.main()
        return len(regress_runner.jobs)

    small_run_count = run_once(job_count=1, available_domains=1)
    large_run_count = run_once(job_count=4, available_domains=4)

    assert small_run_count == 1
    assert large_run_count == 4


def test_main_mixed_domain_requests_above_and_below_board_size():
    jobs = [
        make_test_job("job_large", domains=12),
        make_test_job("job_small", domains=4),
    ]
    rec_scheduler = RecordingScheduler()

    regress_runner = akRegress(
        _sch=rec_scheduler,
        _load_jobs_fn=lambda _path: jobs,
        _test_server_provider=make_test_server_provider(domain_count=16),
        _lmstat_provider=make_lmstat_provider(available_domains=16),
    )
    run_scheduling_iterations(regress_runner, iterations=5)

    job_by_name = {job.name: job for job in regress_runner.jobs}
    assert job_by_name["job_small"].status == job_status.COMPLETED
    assert job_by_name["job_large"].status == job_status.SETUP
    assert any(count > 0 for count in rec_scheduler.skipped_counts)
