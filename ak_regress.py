#!/bin/env python3.12

import os
import random
import subprocess
import sys
import time
from typing import Callable

from regress import *
from pal_regress import (
    _regress_test_mode,
    domainResource,
    licenseResource,
    palAvailableResources,
)


#######################################################

def _default_load_jobs(testlist_path: str):
    from testlist_parser import load_jobs
    return load_jobs(testlist_path)


#######################################################

class akJob(job):
    def __init__(self) -> None:
        super().__init__()

    @classmethod
    def create_from_testlistjob(cls, _testJob):
        nph = cls()

        for field in _testJob.__dict__:
            if hasattr(_testJob, field):
                setattr(nph, field, getattr(_testJob, field))

        # expand the number of domains out to a list of resources
        domains = getattr(_testJob, "domains", None)
        if domains is not None:
            dresource = domainResource("domains", [domains], ["REQUIRED"])
            nph.run_resources.append(dresource)
            license_resource = licenseResource("Palladium_Z2_Domain", [domains], ["REQUIRED"])
            nph.run_resources.append(license_resource)
        # skip build and setup steps
        nph.status = job_status.SETUP

        return nph

    def run(self, _resources:list):
        # call runEmu
        logging.info(f"Running job: {self.run_program} {self.run_args} from dir {self.run_dir}")
        if _regress_test_mode():
            time.sleep(2)
            self.status = job_status.COMPLETED
            self.result = random.choice([job_result.SUCCESS, job_result.FAILED])
            logging.info(f"{self.name} completed with result: {self.result}")
        else:
            logging.info(f"Running job: {self.run_program} {self.run_args} from dir {self.run_dir}")
            result = subprocess.run([self.run_program] + self.run_args, cwd=self.run_dir, capture_output=True, text=True)
            self.status = job_status.COMPLETED
            self.result = job_result(result.returncode)
            logging.info(f"{self.name} completed with result: {self.result}")


#######################################################

class akRegress(regress):
    def __init__(
        self,
        _sch: scheduler = None,
        _stat: available_resources = None,
        _load_jobs_fn: Callable[[str], list] = None,
        _test_server_provider: Callable[[resourceFactory, bool, str], list[resource]] = None,
        _lmstat_provider: Callable[[resourceFactory, bool, str], list[resource]] = None,
    ) -> None:
        injected_stat = _stat
        if injected_stat is None:
            injected_stat = palAvailableResources(
                _test_server_provider=_test_server_provider,
                _lmstat_provider=_lmstat_provider,
            )
        super().__init__(_sch=_sch, _stat=injected_stat)
        self.load_jobs_fn = _load_jobs_fn or _default_load_jobs

    testlist = "test/regress.yaml"

    def load_test_list(self) -> list:
        '''  Implement to parse test list and return a list of jobs '''
        jobs = []
        tjobs = self.load_jobs_fn(self.testlist)
        for tjob in tjobs:
            job = akJob.create_from_testlistjob(tjob)
            jobs.append(job)
            logging.info(f"Found job from testlist: {job.__repr__()}")
        logging.info(f"Loaded {len(jobs)} job(s) from '{self.testlist}':\n")
        return jobs

    def filter_test_list(self, test_list:list) -> list:
        ''' Implement to filter test list to only include jobs that can be run now '''
        return test_list


#######################################################

if __name__ == "__main__":
    try:
        regress_c = akRegress()
        regress_c.main()
    except KeyboardInterrupt:
        print('Interrupted')
        try:
            sys.exit(130)
        except SystemExit:
            os._exit(130)
