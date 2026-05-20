#!/bin/env python3.12

# take a list of jobs and schedule based on scheduler rules and continulally updated status from emulator

import argparse
import re
import sys
import os
import logging
from datetime import datetime
import time

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

class job:
    ''' represents a job/test to be run.  there are up to three phases to a job: build, setup, and run.  
        Each phase has its own resources, program, and arguments.  If only one phase is needed, use the run arguments'''

    def __init__(self) -> None:
        self.name = None

        self.build_resources = []
        self.build_program = None
        self.build_args = []
        self.build_dir = None
        self.setup_resources = []
        self.setup_program = None
        self.setup_args = []
        self.setup_dir = None
        self.run_resources = []
        self.run_program = None
        self.run_args = []
        self.run_dir = None     
        self.status = job_status.NOT_STARTED
        self.result = job_result.INCOMPLETE
        self.build_time = None
        self.setup_time = None
        self.run_time = None

        self.consumed_resources = []

    def finished(self) -> bool:
        return True if (self.status == job_status.COMPLETED) else False

    def get_resources(self) -> list:
        ''' return resources that are required for the current phase of the job'''
        if self.status == job_status.NOT_STARTED:
            return self.build_resources
        elif self.status == job_status.BUILD:
            return self.setup_resources
        elif self.status == job_status.SETUP:
            return self.run_resources
        else:
            return None

    def get_consumed_resources(self) -> list:
        ''' return resources that have been consumed by the job '''
        return self.consumed_resources


    def run_next(self, _resources:list) -> job_status:
        self.consumed_resources.extend(_resources)
        if self.status == job_status.NOT_STARTED:
            return self.build(_resources)
        elif self.status == job_status.BUILD:
            return self.setup(_resources)
        elif self.status == job_status.SETUP:
            return self.run(_resources)
        else:
            return None

    def build(self, _resources:list) -> None:
        ''' Extend to build the job '''
        return NotImplementedError

    def setup(self, _resources:list) -> None:
        ''' Extend to setup the job '''
        return NotImplementedError

    def run(self, _resources:list) -> None:
        ''' Extend to run the job '''
        return NotImplementedError

    def __repr__(self) -> str:
        ret = f"Job: {self.name:30}, Status: {self.status}, Result: {self.result}"
        if self.status == job_status.NOT_STARTED:
            ret = ret + f" build: {self.build_resources} {self.build_args}"
        elif self.status == job_status.BUILD:
            ret = ret + f" setup: {self.setup_resources} {self.setup_args}"
        elif self.status == job_status.SETUP or self.status == job_status.RUNNING or self.status == job_status.COMPLETED:
            ret = ret + f" run: {self.run_resources} {self.run_args}"
        else:
            return None
        # FIXME - better, add in the full commands and results
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
        pass

    def schedule_jobs(self, jobs, status):
        ''' Given a list of jobs and the status of resources, schedule any jobs available right now, 
            return a list of jobs [scheduled, skipped] '''
        scheduled = []
        skipped = []
        complete = []

        logging.info(f"Scheduling {len(jobs)} jobs")

        # iterate over jobs
        for job_to_schedule in jobs:
            if job_to_schedule.finished(): 
                # dont free, assume we will get another updaate
                #status.free(job_to_schedule.get_consumed_resources())
                complete.append(job_to_schedule)
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

            # start the run and consume the resources in our status
            status.consume(resources)
            job_to_schedule.run_next(resources)
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
            logging.error(f"No resources requested for job")
            return None
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
                                         description='Regre')
        # FIXME
        #parser.add_argument("-n", "--norun", action='store_true', help='For debug, skip running commands and just print')
        #parser.add_argument("-m", "--models", help='List of models to run, these should all be in the RUNS/regress area')
        #parser.add_argument("-s", "--scripts_dir", default="/proj/akeanaz1/SCRIPTS", help='Change the scripts dir away from SCRIPTS')
       
        # let extended class add arguments
        self.extended_args_parse(parser)
        self.args = parser.parse_args()

    #-------------------------------------------------------
    def extended_args_parse(self, parser:argparse.ArgumentParser) -> None:
        ''' Implement to add new arguments '''
        pass

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
