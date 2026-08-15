# Regress 

Configurable library for allocating regression tests across a set of scarce resources.  Provide a set of tests (with separate build, setup and run steps) to run via YAML with the resources they consume and the scheduler will query the status of the resources and allocate them as they are available.

Extending the equipment-level layer allows you map external resource query (boards, licenses) to resources to be consumed.  Currently there is an example for the Cadence Palladium platform.

Extending the user-level layer allows you to add the command to execute for each step.
