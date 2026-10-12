#!/bin/env python3.12

import os
import sys

from regress import *
from pal_regress import palAvailableResources
from pal_regress import palJob
from testlist_parser import load_jobs

#######################################################

class appJob(palJob):
    @classmethod
    def create_from_testlistjob(cls, _testJob):
        ''' create a job from a testlist job so the yaml parser can upconvert
            entries into application jobs '''
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

        nph.attach_testlist_resources(_testJob)
        nph.update_status()

        return nph

    def run(self, _resources:list, _task:task) -> None:
        ''' Implement to run the given task '''
        print(f"Running {self.name} {_task.name} with arguments: {_task.args}")

#######################################################

class appRegress(regress):
    def __init__(self, _sch: scheduler = None, _stat: available_resources = None) -> None:
        if _stat is None:
            _stat = palAvailableResources()
        super().__init__(_sch=_sch, _stat=_stat)

    #-------------------------------------------------------
    def setup(self) -> None:
        ''' Called after argument parsing, parse args and setup regression '''
        super().setup()
        # Add application setup here: root paths, license usage, and the test list to load.
        self.testlist = "test/regress.yaml"

    #-------------------------------------------------------
    def extended_args_parse(self, parser:argparse.ArgumentParser) -> None:
        ''' Implement to add new arguments '''
        # Add application arguments here, such as license usage, a model list, or an alternate test list.

    def load_test_list(self) -> list:
        ''' Implement to parse test list and return a list of jobs '''
        jobs = []
        tjobs = load_jobs(self.testlist)
        for tjob in tjobs:
            job = appJob.create_from_testlistjob(tjob)
            jobs.append(job)
            logging.info(f"Found job from testlist: {job.__repr__()}")
        logging.info(f"Loaded {len(jobs)} job(s) from '{self.testlist}':\n")
        return jobs

    def filter_test_list(self, test_list:list) -> list:
        ''' Implement to filter test list to only include jobs that we want to run '''
        return test_list

#######################################################

if __name__ == "__main__":
    try:
        regress_c = appRegress()
        regress_c.main()
    except KeyboardInterrupt:
        print('Interrupted')
        try:
            sys.exit(130)
        except SystemExit:
            os._exit(130)
