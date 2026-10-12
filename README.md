# Regress

Regress schedules jobs that need scarce resources. A job can have up to three phases — build, setup, and run — and each phase can ask for its own resources and command. The scheduler watches resource status and starts a phase when what it needs is free.

## Introduction

The application is three layers. Each layer extends the one below it.

### Base layer

[`regress.py`](regress.py) does not know about hardware, software, or a particular set of jobs. It defines generic jobs, phases, and resources, and it schedules those resources as they become available. What a resource is, how to query it, and how to allocate it are left to classes that extend this layer.

### Equipment layer

This layer adds the hardware or software being scheduled. [`pal_regress.py`](pal_regress.py) is an example for the Cadence Palladium hardware. It implements board domains and the associated licenses into resources the base scheduler can allocate, including the rules for which domains can be given to a job.

### Application layer

This layer adds your applications regression environment. [`app_regress.py`](app_regress.py) is an example. `appJob` extends `palJob`. `create_from_testlistjob` copies a test-list entry onto a job, fills in the build, setup, and run phases, and attaches the Palladium resources that entry asks for. `run` prints the job and task name; a real application replaces that with the command to run. `appRegress` loads [`test/regress.yaml`](test/regress.yaml) through `load_jobs` and turns each entry into an `appJob`. `setup`, `extended_args_parse`, and `filter_test_list` are the places to add paths, arguments, and which jobs should run.

[`ak_regress.py`](ak_regress.py) is one company's regression. It fills in program paths, the model name, a timestamp, and the boards that were allocated, and it can keep only the models that are ready to run.

## Resources

A resource is a named pool the scheduler can give to a job. It has a list of values and a status for each value, such as `FREE` or `USED`. A job phase lists what it needs: the resource name, the count or identifier in `values`, and status `REQUIRED`.

When a phase is ready, the scheduler matches each requested name to a live resource and calls `allocate`. If every request can be filled, those values are consumed until the phase finishes, then freed. If any request cannot be filled, the job waits.

The base `resource` class records values and status. Equipment classes decide how to allocate based on their setup, the Palladium example of the Equipment later implements board domans where each job requires a number of domains.  These can only be allocated based on rules setup at the equipment later.