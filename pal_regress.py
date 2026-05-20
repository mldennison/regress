#!/bin/env python3.12

from regress import *
import subprocess
import time
import random
from typing import Callable

#######################################################

def _regress_test_mode() -> bool:
    import regress as regress_module
    return bool(regress_module.test_mode)


def _default_load_jobs(testlist_path: str):
    from testlist_parser import load_jobs
    return load_jobs(testlist_path)


def _default_test_server_provider(factory: resourceFactory, _test_mode: bool, test_server_file: str) -> list[resource]:
    if _test_mode:
        from test_server import parse_emulator_status
        with open(test_server_file, "r") as f:
            return parse_emulator_status(factory, f.read())
    from test_server import run_test_server
    return run_test_server(factory)


def _default_lmstat_provider(factory: resourceFactory, _test_mode: bool, license_file: str) -> list[resource]:
    if _test_mode:
        from lmstat import parse_lmstat
        with open(license_file, "r") as f:
            return parse_lmstat(factory, f.read())
    from lmstat import run_lmstat
    return run_lmstat(factory)

class domainResource(resource):
    domains_per_board = 8

    def biggest_run(self, _free:list) -> list:
        # find the longest run of free domains
        longest_run = 0
        longest_run_list = []
        current_run = 0
        current_run_list = []
        for i in reversed(range(self.domains_per_board)):
            if i in _free:
                current_run += 1
                current_run_list.insert(0, i)
            else:
                if current_run >= longest_run:
                    longest_run = current_run
                    longest_run_list = current_run_list
                current_run = 0
                current_run_list = []
        if current_run >= longest_run:
            longest_run = current_run
            longest_run_list = current_run_list

        return longest_run_list

    def full_board(self, _free:list) -> bool:
        return len(_free) >= self.domains_per_board 

    def allocate(self, _resource) -> resource:
        # allocate from the top if possible
        requested = _resource.values[0]
        free_domains = {}
        bsplit = re.compile(r'(\d+).(\d+)')
        # find list of free domains, arranged by board
        for (idx, domain) in enumerate(self.values):
            if self.status[idx] == "FREE":
                match = bsplit.match(self.values[idx])
                if match:
                    board = int(match.group(1))
                    domain = int(match.group(2))
                    if board not in free_domains:
                        free_domains[board] = []
                    free_domains[board].append(domain)
                else:
                    logging.error(f"Invalid domain name: {self.values[idx]}")
                    return None

        # if more than one boards, move back from end of list
        if requested > self.domains_per_board:
            # see if we have a full board of domains
            pass # FIXME
            # then see if the partial domains are enough
        else:
            # less than a full board, start from the end and allocate
            for board in reversed(free_domains):
                run = self.biggest_run(free_domains[board])
                # make sure we are on an even boundary for the number requested
                if len(run) >= requested:
                    # add the board back in
                    ll = run[-requested:]
                    for (idx, domain) in enumerate(ll):
                        ll[idx] = f"{board}.{domain}"
                    return resource("domains", ll, ["USED"], True)
            return None

        # could not find any domains, return None
        return None
    
#######################################################

class tpodResource(resource):
    def allocate(self, _resource) -> resource:
        requested = _resource.values[0]
        for tpod in self.values:
            if tpod == requested:
                return resource("tpods", [requested], ["USED"], True)
        return None

#######################################################

class licenseResource(resource):
    availidx = None
    usedidx = None

    def find_indicies(self) -> None:
        if self.availidx is None:
            for idx, license in enumerate(self.status):
                if license == "AVAILABLE": self.availidx = idx
                if license == "USED": self.usedidx = idx
        return

    def allocate(self, _resource) -> resource:
        # check that we have enough
        self.find_indicies()
        requested = _resource.values[0]
        for license in self.values:
            if license >= requested:
                return resource("Palladium_Z2_Domain", [requested], ["USED"], True)
        return None

    def consume(self, _values:list) -> bool:
        requested = _values[0]    
        #self.find_indicies()
        if self.values[self.availidx] >= requested:
            self.values[self.availidx] -= requested
            self.values[self.usedidx] += requested
            return True
        else:
            logging.error(f"Requested {requested} licenses, but only {self.values[self.availidx]} available")
            return False

    def free(self, _values:list) -> bool:
        #self.find_indicies()
        requested = _values[0]
        self.values[self.availidx] += requested
        self.values[self.usedidx] -= requested
        return True

#######################################################

class palResourceFactory(resourceFactory):
    ''' Return one of the specialized resource classes above based on the name '''
    def create_resource(self, _name:str, _values:list, _status:list=None, _match_name=None) -> resource:
        if _name == "domains" or (_match_name is not None and _match_name == "domains"):
            return domainResource("domains", _values, _status)
        elif _name == "tpods" or (_match_name is not None and _match_name == "tpods"):
            return tpodResource("tpods", _values, _status)
        elif _name == "Palladium_Z1_Domain:" or _name == "Palladium_Z2_Domain:" or (_match_name is not None and _match_name == "license"):
            return licenseResource(_name, _values, _status)
        else:
            return super().create_resource(_name, _values, _status)
        return None

#######################################################
    
class palAvailableResources(available_resources):
    test_server_file = "test/test_server"
    license_file = "test/lmstat"

    def __init__(
        self,
        _test_server_provider: Callable[[resourceFactory, bool, str], list[resource]] = None,
        _lmstat_provider: Callable[[resourceFactory, bool, str], list[resource]] = None,
    ) -> None:
        super().__init__()
        self.test_server_provider = _test_server_provider or _default_test_server_provider
        self.lmstat_provider = _lmstat_provider or _default_lmstat_provider
    
    def __repr__(self) -> str:
        parts = []
        wanted = ("board", "domains", "tpods", "Palladium_Z2_Domain")
        for resource in getattr(self, "resources", []):
            if resource.name in wanted:
                parts.append(resource.__repr__())
        return "\n     ".join(parts)

    def update(self) -> None:
        '''  Query and return status of all known resources '''
        factory = palResourceFactory()

        # do not refresh if under interval
        if not self.needs_update(): return

        test_mode_value = _regress_test_mode()
        self.resources = self.test_server_provider(factory, test_mode_value, self.test_server_file)
        licenses = self.lmstat_provider(factory, test_mode_value, self.license_file)
        self.resources.extend(licenses)
        logging.info(f"Updated resources:\n {self.__repr__()}")
    
        return 0
        
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

        # expland the number of  domains out to a list of resources
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
