#!/bin/env python3.12

import os
import random
import subprocess
import sys
import time
from datetime import datetime
from typing import Callable

from regress import *
from pal_regress import _regress_test_mode
from pal_regress import domainResource
from pal_regress import licenseResource
from pal_regress import palAvailableResources

#######################################################

class akJob(job):
    home = "."
    user_dir =  "."
    programs = "."
    default_run_dir = "."
    model_dir = "."
    script_dir = "."
    time_arg = None

    def __init__(self) -> None:
        super().__init__()

    @classmethod
    def create_from_testlistjob(cls, _testJob):
        ''' create a job from a testlist job, this allows the yaml parser to generate job classes and 
            we can use this to upconvert to akjobs and add in specifics '''
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

        # expand the number of domains out to a list of resources
        domains = getattr(_testJob, "domains", None)
        if domains is not None:
            dresource = domainResource("domains", [domains], ["REQUIRED"])
            nph.tasks[2].resources.append(dresource)
            license_resource = licenseResource("Palladium_Z2_Domain", [domains], ["REQUIRED"])
            nph.tasks[2].resources.append(license_resource)
        xcelium = getattr(_testJob, "Xcelium_Single_Core", None)
        if xcelium is not None:
            nph.tasks[2].resources.append(
                licenseResource("Xcelium_Single_Core", [xcelium], ["REQUIRED"])
            )
        nph.update_status()

        # for debug print(repr(nph))

        return nph

    # we dont store the entire program path in the yaml, add it here
    _PROGRAM_PATH_OPTS = ("-p", "-c", "--extdata", "--sram", "--iob", "--flash")

    def _resolve_program_paths(self, args: list) -> list:
        ''' Prepend akJob.programs to values of path options from the yaml. '''
        resolved = []
        expect_path = False
        for arg in args:
            if expect_path:
                resolved.append(os.path.join(self.programs, arg))
                expect_path = False
            else:
                resolved.append(arg)
                expect_path = arg in self._PROGRAM_PATH_OPTS
        return resolved

    def run(self, _resources:list, _task:task):
        ''' run the given task '''
        cmd = [self.script_dir + "/" + _task.program] + self._resolve_program_paths(list(_task.args))
        if self.time_arg is None:
            self.time_arg = ["-e", datetime.now().strftime("%Y%m%d%H%M%S")]
        model_arg = ["-m", self.name]
        cmd = cmd + self.time_arg + model_arg
        logging.info(f"Running {self.name} {_task.name} : {cmd} from dir {_task.dir}")
        if _regress_test_mode():
            time.sleep(2)
            self.result = job_result.SUCCESS
        else:
            result = subprocess.run(cmd, cwd=_task.dir)
            self.result = job_result(result.returncode)
        logging.info(f"{self.name} {_task.name} completed with result: {self.result}")
        return

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
 
    #-------------------------------------------------------
    def setup(self) -> None:
        ''' Called after argument parsing, parse args and setup regression '''

        if self.args.root_dir is not None: self.root_dir = self.args.root_dir
        else:                              self.root_dir = "/proj/akeanaz1"
        if self.args.usage is not None: licenseResource.max_pct = self.args.usage
        else:                           licenseResource.max_pct = 50
        if not _regress_test_mode():
            akJob.home = "/home/" + os.environ.get('USER')
            akJob.user_dir =  self.root_dir + "/USERS/"  + os.environ.get('USER')
            self.user_dir = akJob.user_dir
            akJob.programs = self.root_dir + "/PROGRAMS/"
            akJob.default_run_dir =  self.user_dir + "/RUNS/regress"
            akJob.model_dir = self.root_dir + "/MODELS/regress"
            akJob.script_dir = self.root_dir + "/SCRIPTS"
        else:
            # make the interval very short for testing
            self.interval = 1

        if self.args.test_list is not None: self.testlist = self.args.test_list
        else:                               self.testlist = "test/regress.yaml"
        self.models = self.args.models

        # one timestamp for the whole regression so every job shares the same -e date
        akJob.time_arg = ["-e", datetime.now().strftime("%Y%m%d%H%M%S")]

    #-------------------------------------------------------
    def extended_args_parse(self, parser:argparse.ArgumentParser) -> None:
        ''' Implement to add new arguments '''
        parser.add_argument("-u", "--usage", default=100, type=int, help='License/domain usage percentage (0-100), default is 100')
        parser.add_argument("-m", "--models", help='List of models to run, these should all be in the RUNS/regress area')
        parser.add_argument("-t", "--test_list", help='Point to a different test list')

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
        if _regress_test_mode():
            # run everything in the test list
            return test_list
        elif getattr(self, "models", None) is not None:
            # -m provides <jobname>_<timearg> entries for models already set up
            model_map = {}
            for spec in split_to_list(self.models):
                if "_" not in spec:
                    logging.error(f"Invalid model spec '{spec}', expected <jobname>_<timearg>")
                    continue
                jobname, timearg = spec.rsplit("_", 1)
                model_map[jobname] = timearg

            jobs = []
            for job in test_list:
                if job.name not in model_map:
                    logging.info(f"Job {job.name} not in -m models list, skipping")
                    continue
                # reuse the provided timestamp; skip build/setup and go straight to run
                job.time_arg = ["-e", model_map[job.name]]
                job.tasks[0].valid = False
                job.tasks[1].valid = False
                job.update_status()
                jobs.append(job)
            logging.info(f"Filtered to {len(jobs)} job(s) from -m models list")
            return jobs
        else:
            # find builds that are are available to run right now
            jobs = []
            for job in test_list:
                # check to see if there is a tarball for this build in the user's directory
                tarball = self.user_dir + "/" + job.name + ".tar.gz"
                if not os.path.exists(tarball):
                    logging.info(f"Tarball {tarball} not found, skipping job {job.name}")
                    continue
                jobs.append(job)
            return jobs

#######################################################

def _default_load_jobs(testlist_path: str):
    from testlist_parser import load_jobs
    return load_jobs(testlist_path)

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
