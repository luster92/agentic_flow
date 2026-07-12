# Graph-native CLI runtime

`main_graph.py` is the primary interactive CLI. New command behavior must be implemented through `GraphCLIController` or another transport-neutral service, not in the legacy procedural `main.py` pipeline.

## Execution ownership

- `GraphRuntime`: graph invocation, native HITL resume, graph state and persistence hooks
- `GraphCLIController`: command parsing, project lifecycle, planner sequencing and debate commands
- `main_graph.py`: terminal input/output and sandbox/tmux resource lifecycle

## Supported commands

- `/new <project>` and `/load <project>`
- `/list`, `/current`, `/status`, `/stats`, `/clear`
- `/persona [id]`
- `/checkpoint [label]`, `/rollback [step]`
- `/approve`, `/reject`, `/modify <replacement request>`
- `/debate`
- `/exit`
- `!<command>` for isolated sandbox execution
- `/test <command>` for tmux verification

## Planner behavior

Normal user requests first pass through `TaskPlanner`. Simple requests invoke the graph once. Complex plans execute dependency-ready tasks sequentially through the same `GraphRuntime`. A pending approval stops the plan immediately. A failed sub-task raises instead of leaving the plan in an infinite loop.

## Remaining differences from legacy main.py

The graph CLI does not yet include keyboard shortcuts for rewind/plan mode, automatic context handoff, MCP initialization from `config.yaml`, or dynamic cloud-model shortcut commands. These should be added as adapters around `GraphRuntime`; do not restore a separate procedural execution pipeline.

## Regression tests

`tests/test_graph_cli_controller.py` covers command dispatch, native HITL commands, planner dependency order, status and checkpoint behavior. The shared GitHub Actions workflow runs these tests on Python 3.11 and 3.12.
