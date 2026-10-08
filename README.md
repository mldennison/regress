# Regress

Regress schedules jobs that need scarce resources. A job can have up to three phases — build, setup, and run — and each phase can ask for its own resources and command. The scheduler watches resource status and starts a phase when what it needs is free.

## Introduction

The application is three layers. Each layer extends the one below it.

### Base layer

[`regress.py`](regress.py) does not know about hardware, software, or a particular set of jobs. It defines generic jobs, phases, and resources, and it schedules those resources as they become available. What a resource is, how to query it, and how to allocate it are left to classes that extend this layer.

### Equipment layer

This layer adds the hardware or software being scheduled. [`pal_regress.py`](pal_regress.py) is the Cadence Palladium example. It turns Palladium domains and licenses into resources the base scheduler can allocate, including the rules for which domains can be given to a job.

### Application layer

This layer adds one user's regression environment. [`ak_regress.py`](ak_regress.py) is the example. It reads the config in [`test/regress.yaml`](test/regress.yaml), turns each entry into a job, and fills in the command options used to run that job (program paths, model name, timestamp, and the boards that were allocated).

## Locally tested

Local checks cover the path from the example config through scheduling, without calling live Palladium hardware or license servers.

- Config parsing merges global defaults with each entry in `test/regress.yaml`, including entries that expand into more than one job.
- The scheduler runs build, then setup, then run, and finishes the job.
- Jobs start together when enough domains and licenses are free, and they wait and run later when those resources are tight.
- Requests smaller than a board and requests that span more than one board both complete when the domains exist.
- A worker that dies during a phase is marked failed and is not started again.
- The models filter keeps the named jobs, reuses the given timestamp, and skips build and setup so only run is scheduled.
