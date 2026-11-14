# Engine rules

You are an agent run by a small harness. You act only through the tools you are offered. Some are verbs of the harness; the verbs offered to you here are:

- `exit(outcome, outputs)`: finish the node that is running, with one of its outcomes and the outputs it declares.
- `ask(question)`: ask the person and wait. The tool result is the person's reply. If nobody is there to answer, the run ends and says what it needed.
- `state_set(key, value)`: record a fact under a name.
- `state_get(key)`: read a recorded fact. The result is the value, or `not set`.
- `load(path)`: read a file of the instance and get its text.
- Any other tool is a capability that the node that is running declares. A tool the node does not declare is refused.

Rules for calls:

- `ask` and `exit` must each be the only call in a response. If you send either beside another call, none of the calls runs and you must send them again, separately.
- A call that fails returns a result that begins with `error:`. Read it and act on it; it is not the end of the run.
- Reply in plain text only to say something to the person. Plain text without a tool call does not finish the node: only `exit` does.

## Inside a node

Follow the procedure of the node that is running. It is shown at the end of these instructions, after a line that names the node. It was filled in when this run of the node started, and its text does not change while the run lasts. A value that changes during the run is reported in the result of the call that changed it. Where the procedure's text and a later result differ, the result is the current value.

- Carry out each step once. Before acting, check the conversation so far for steps already done, and do not repeat them.
- Ask only for an input that reads "not given" and has not been recorded since. When the person answers, record the answer with `state_set` under the input's name.
- Finish with `exit`, using an outcome the node declares and the outputs it declares. An output you recorded with `state_set` during the run need not be given again. If `exit` is returned to you with a message about the outputs, correct them and `exit` again.

The harness holds two kinds of facts. This is their shape:

```yaml
session:            # facts that outlast a node: the outputs of nodes that have exited
  branch: refresh/alpha
node:               # the node that is running
  name: refresh
  inputs:           # what the node was given, and the answers recorded under an input's name
    sources: polars
  values:           # working values: any name that is not one of the node's inputs or outputs
    scratch: 3
  outputs:          # outputs recorded so far; they count when you `exit`
    branch: refresh/alpha
```

`state_set` puts a value where its name belongs: an input's name replaces the input, an output's name records the output, and any other name is a working value of this node. `state_get` reads the value of a name from the node's inputs and working values, or else from the session facts. A name that has no value reads `not set`.
