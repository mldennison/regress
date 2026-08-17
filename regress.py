#!/bin/env python3.12

# take a list of jobs and schedule based on scheduler rules and continulally updated status from emulator

import argparse
import re
import sys
import os
import logging
import multiprocessing
from datetime import datetime
import time

from regress_utils import split_to_list

test_mode = True

class job_status:
    NOT_STARTED = 0
    BUILD = 1
    SETUP = 2
    RUNNING = 3
    COMPLETED = 4
    
class job_result:
    INCOMPLETE = 0
    SUCCESS = 1
    TIMEOUT = 2
    FAILED = 3

#######################################################

class task:
    ''' represents a single phase of the job to be done (build, setup, run) '''
    def __init__(self, name: str) -> None:
        self.name = name
        self.valid = False
        self.resources = []
        self.program = None
        self.args = []
        self.dir = None
        self.time = None

    def __repr__(self) -> str:
        return f"task(name={self.name!r}, valid={self.valid!r}, resources={self.resources!r}, program={self.program!r}, args={self.args!r}, dir={self.dir!r}, time={self.time!r})"

class job:
    ''' represents a job/test to be run.  there are up to three phases to a job: build, setup, and run.  
        Each phase has its own resources, program, and arguments.  If only one phase is needed, use the run arguments'''

    _PHASE_PREFIXES = ("build", "setup", "run")

    def __init__(self) -> None:
        self.name = None
        self.tasks = [task("build"), task("setup"), task("run")]
        self.status = job_status.NOT_STARTED
        self.result = job_result.INCOMPLETE
        self.consumed_resources = []

    @staticmethod
    def apply_phase_fields(job_instance, source, phase: str, index: int) -> None:
        t = job_instance.tasks[index]
        for attr in ("valid", "resources", "program", "args", "dir", "time"):
            field = f"{phase}_{attr}"
            if hasattr(source, field):
                val = getattr(source, field)
                if val is not None:
                    setattr(t, attr, val)
        if not t.valid and (t.program or t.args or t.dir):
            t.valid = True

    def finished(self) -> bool:
        return True if (self.status == job_status.COMPLETED) else False

    def update_status(self, _advance:bool=False) -> None:
        ''' update the status of the job based on the current status and the results of the previous phase '''
        # increment status first
        if _advance and self.status < job_status.COMPLETED:
            self.status = self.status + 1
        # if the task we are current on is not valid, increment status until we find a valid task
        while(True):
            t = self._get_current_task()
            if t is None: break
            if t.valid: break
            self.status += 1

    def get_resources(self) -> list:
        ''' return resources that are required for the current phase of the job'''
        self.update_status()
        t = self._get_current_task()
        if t is None: 
            return None
        else:
            return t.resources

    def get_consumed_resources(self) -> list:
        ''' return resources that have been consumed by the job '''
        return self.consumed_resources

    def _get_current_task(self) -> task:
        ''' return the task to execute for the current job status '''
        if self.status == job_status.NOT_STARTED:
            return self.tasks[0]
        if self.status == job_status.BUILD:
            return self.tasks[1]
        if self.status == job_status.SETUP:
            return self.tasks[2]
        return None

    def run_next(self, _resources:list) -> job_status:
        self.consumed_resources.extend(_resources)
        self.update_status()
        current_task = self._get_current_task()
        stat = None
        if current_task is not None:
            logging.info(f"Running task: {current_task.__repr__()}")
            stat = self.run(_resources, current_task)
        # move to the next task
        self.update_status(True)
        if self._get_current_task() is None and self.status != job_status.COMPLETED:
            self.status = job_status.COMPLETED
        return stat

    def run(self, _resources:list, _task:task) -> None:
        ''' Extend to run the given task '''
        return NotImplementedError

    def __repr__(self) -> str:
        ret = f"Job: {self.name:30}, Status: {self.status}, Result: {self.result}"
        for t in self.tasks:
            ret = ret + f" {t.__repr__()}"
        return ret
            
#######################################################

class resource:
    def __init__(self, _name:str, _values:list, _status:list=None, _live=False) -> None:
        self.name = _name
        # valid values of the resource
        self.values = _values
        # status of each value in values
        self.status = _status
        # a live resource is something we are trying to allocate for a job, ignore status if set
        self.live = _live

    def __repr__(self) -> str:
        parts = [f"resource(name={self.name!r}"]
        if self.status is not None and not self.live:
            paired = list(zip(self.values, self.status))
            parts.append(f"values+status={paired!r}")
        else:
            parts.append(f"values={self.values!r}")
        return ", ".join(parts) + ")"

    def allocate(self, _resource) -> list:
        ''' Extend to provide rules on how to allocate the resource.  Return a list of values consumed by this job'''
        raise NotImplementedError

    def consume(self, _values:list) -> bool:
        ''' Consume the resource'''
        for value in _values:
            if value not in self.values:
                return False
            self.status[self.values.index(value)] = "USED"
        return True

    def free(self, _values:list) -> bool:
        ''' Free the resource'''
        for value in _values:
            if value not in self.values:
                return False
            self.status[self.values.index(value)] = "FREE"
        return True

#######################################################

class resourceFactory:
    def create_resource(self, _name:str, _values:list, _status:list=None, _match_name=None) -> resource:
        return resource(_name, _values, _status)
        
#######################################################

class scheduler:
    def __init__(self) -> None:
        self._inflight = {}

    @classmethod
    def _parent_log_config(cls) -> tuple:
        ''' Return the parent's log file and level so workers can log to the same place. '''
        root = logging.getLogger()
        for handler in root.handlers:
            if isinstance(handler, logging.FileHandler):
                level = handler.level if handler.level != logging.NOTSET else root.level
                return handler.baseFilename, level or logging.DEBUG
        return os.path.abspath("test/regress.log"), logging.DEBUG

    @classmethod
    def _configure_child_logging(cls, log_file, log_level) -> None:
        ''' Give the child its own FileHandler for the parent's log file. '''
        if not log_file:
            return
        logging.basicConfig(filename=log_file, level=log_level, force=True)

    @classmethod
    def _run_job_worker(cls, job, resources, result_queue, log_file=None, log_level=logging.DEBUG):
        ''' Child process entry: run one job phase and send status back to the parent. '''
        cls._configure_child_logging(log_file, log_level)
        try:
            job.run_next(resources)
            result_queue.put((
                job.status,
                job.result,
                job.consumed_resources,
                getattr(job, "executions", None),
            ))
        except Exception:
            logging.exception("Job worker failed")
            result_queue.put((
                getattr(job, "status", job_status.RUNNING),
                job_result.FAILED,
                getattr(job, "consumed_resources", []),
                getattr(job, "executions", None),
            ))
        finally:
            for handler in logging.getLogger().handlers:
                handler.flush()
                handler.close()

    def _harvest(self) -> None:
        ''' Apply results from any worker processes that have exited. '''
        for key, (job, proc, q) in list(self._inflight.items()):
            if proc.is_alive():
                continue
            try:
                status, result, consumed, extra = q.get(timeout=5)
            except Exception:
                logging.error(f"Failed to read result for job {job.name}")
                status = job.status
                result = job_result.FAILED
                consumed = job.consumed_resources
                extra = None
            proc.join()
            job.status = status
            job.result = result
            job.consumed_resources = consumed
            if extra is not None:
                job.executions = extra
            del self._inflight[key]

    def schedule_jobs(self, jobs, status):
        ''' Given a list of jobs and the status of resources, schedule any jobs available right now, 
            return a list of jobs [scheduled, skipped] '''
        scheduled = []
        skipped = []
        complete = []

        logging.info(f"Scheduling {len(jobs)} jobs")
        self._harvest()
        log_file, log_level = self._parent_log_config()

        # iterate over jobs
        for job_to_schedule in jobs:
            if job_to_schedule.finished(): 
                # dont free, assume we will get another updaate
                #status.free(job_to_schedule.get_consumed_resources())
                complete.append(job_to_schedule)
                continue

            if id(job_to_schedule) in self._inflight:
                scheduled.append(job_to_schedule)
                continue

            # check resources, see if we can find some that match and return them if we can
            resources = status.find_resources(job_to_schedule.get_resources())
            if resources is None: 
                skipped.append(job_to_schedule)
                continue
            else:
                printstr = f"Found resources for job {job_to_schedule.name}:"
                for resource in resources: printstr += f"  {resource.__repr__()}"
                logging.info(printstr)

            # consume resources in the parent, then run the phase in a child process
            status.consume(resources)
            result_queue = multiprocessing.Queue()
            proc = multiprocessing.Process(
                target=type(self)._run_job_worker,
                args=(job_to_schedule, resources, result_queue, log_file, log_level),
            )
            proc.start()
            self._inflight[id(job_to_schedule)] = (job_to_schedule, proc, result_queue)
            scheduled.append(job_to_schedule)

        logging.info(f"Scheduled {len(scheduled)} jobs, skipped {len(skipped)} jobs, completed {len(complete)} jobs")

        return [scheduled, skipped, complete]

#######################################################

class available_resources:
    def __init__(self) -> None:
        self.resources = []
        self.last_update = None
        self.interval = 0

    def needs_update(self) -> bool:
        if (self.last_update is None) or (time.time() - self.last_update > self.interval):
            self.last_update = time.time()
            logging.info(f"Updating resources")
            return True
        logging.info(f"Resources updated within interval, skipping update")
        return False

    def find_resources(self, job_resources):
        ''' find resources (boards, equipment connections) that are required and return best matches '''
        retval = []
        matched = False

        if job_resources is None or len(job_resources) == 0:
            logging.info(f"No resources requested for job")
            return []
        for jresource in job_resources:
            matched = False
            for ourresource in self.resources:
                if jresource.name == ourresource.name:
                    matched = True
                    resource = ourresource.allocate(jresource)
                    if resource is None:
                        return None
                    retval.append(resource)
                    break
            if not matched:
                return None
        return retval

    def consume(self, _resources:list) -> bool:
        return self.operate(_resources, "consume")

    def free(self, _resources:list) -> bool:
        return self.operate(_resources, "free")

    def operate(self, _resources:list, _operation:str) -> bool:
        ''' internal method to implement free and consume '''
        matched = False
        for resource in _resources:
            matched = False
            for ourresource in self.resources:
                if resource.name == ourresource.name:
                    if _operation == "consume":
                        logging.info(f"Consuming resource: {resource.__repr__()}")
                        ourresource.consume(resource.values)
                    elif _operation == "free":
                        logging.info(f"Freeing resource: {resource.__repr__()}")
                        ourresource.free(resource.values)
                    else:
                        logging.error(f"Invalid operation: {_operation}")
                        return False
                    matched = True
                    break
            if not matched: return False

        return True
        
    def update(self) -> list:
        '''  Query and return status of all known resources '''
        return NotImplementedError

#######################################################

class regress:
    #-------------------------------------------------------
    def __init__(self, _sch:scheduler=None, _stat:available_resources=None) -> None:
        if _sch is None:
            self.sch = scheduler()
        else:
            self.sch = _sch
        if _stat is None:
            self.stat = available_resources()
        else:
            self.stat = _stat
        self.jobs = []
        self.interval = 10

    def load_test_list(self) -> list:
        '''  Implement to parse test list and return a list of jobs '''
        return NotImplementedError

    def filter_test_list(self, test_list:list) -> list:
        ''' Implement to filter test list to only include jobs that can be run now '''
        return NotImplementedError

    #-------------------------------------------------------
    def argument_parse(self) -> None:
        parser = argparse.ArgumentParser(prog='regress',
                                         description='Regression test scheduler')
        parser.add_argument("-r", "--root_dir", help='Root directory for regress')
        parser.add_argument("-n", "--norun", action='store_true', help='For debug, skip running commands and just print')
       
        # let extended class add arguments
        self.extended_args_parse(parser)
        self.args = parser.parse_args()

    #-------------------------------------------------------
    def extended_args_parse(self, parser:argparse.ArgumentParser) -> None:
        ''' Implement to add new arguments '''
        pass

    #-------------------------------------------------------
    def setup(self) -> None:
        ''' Called after argument parsing, parse args and setup regression '''
        self.root_dir = self.args.root_dir
        self.norun = self.args.norun

    #-------------------------------------------------------
    def report_status(self) -> None:
        for job in self.jobs:
            print(job)

    #-------------------------------------------------------
    def main(self) -> None:
        self.argument_parse()

        logging.basicConfig(filename="test/regress.log",level=logging.DEBUG)
        present_time = datetime.now()
        logging.info(f"\n\n\n")
        logging.info(f"------------------------------------------------------")
        logging.info(f"Regress.py running at {present_time:%Y%m%d%H%M%S}")
        logging.info(f"------------------------------------------------------\n")

        logging.info(f"Regress::main started")
        self.argument_parse()
        self.setup()

        # load test list of all possible jobs
        self.jobs = self.load_test_list()
        # filter test list to only include jobs that can be run now
        self.jobs = self.filter_test_list(self.jobs)

        logging.info(f"Will run {len(self.jobs)} jobs")

        # schedule jobs until all scheduled
        remaining = self.jobs
        scheduled = []
        while (len(remaining) > 0) or (len(scheduled) > 0):
            
            # get updated status 
            self.stat.update()

            [scheduled, remaining, complete] = self.sch.schedule_jobs(self.jobs, self.stat)
            logging.info(f"Scheduled jobs:")
            for sjob in scheduled: logging.info(f"  {sjob.__repr__()}")
            logging.info(f"Remaining jobs:")
            for rjob in remaining: logging.info(f"  {rjob.__repr__()}")
            logging.info(f"Completed jobs:")
            for cjob in complete: logging.info(f"  {cjob.__repr__()}")
            logging.info(f"Resources:\n {self.stat.__repr__()}")

            # sleep for interval
            time.sleep(self.interval)  

            logging.info(f"Job Status jobs: {len(self.jobs)}, scheduled: {len(scheduled)}, remaining: {len(remaining)}, complete: {len(complete)}")

        logging.info(f"Regress::main completed")

        # report status
        self.report_status()