## Steps of a procedure

The procedure of a node is a list of numbered steps. This section says how to read them. Read the steps in order and do what each one says, once. The capitalised words (`CALL`, `ASK`, `STATE.set`, `EXIT`, `DISPLAY`, `VALIDATE` and the rest) are written forms in the procedure, not tools. Only the tools you are offered can be called. `DISPLAY` and `VALIDATE` are things you do yourself, not calls.

- **Phases.** A long procedure may be divided into phases, each a heading `## Phase <n>: <name>` with a line `Outputs:` naming what the phase produces. Do the phases in order, and finish a phase before starting the next. The steps are numbered within a phase.

  ```
  ## Phase 2: Update
  Outputs: `sources_updated`
  1. CALL `tools__shell` with the command `echo updating`.
  ```

- **Steps.** Each numbered step is one action. Do the steps in order, one after another. A step that names a tool is a call to that tool with the arguments the step gives. A step that carries a condition ("If ...") is done only when the condition holds.

  ```
  1. CALL `tools__shell` with the command `echo checked`.
  2. If "Sources to update" reads "not given", ASK "Which sources?".
  3. EXIT `done`.
  ```

- **CALL.** `CALL <tool>` means call that tool, which the node declares. A step is done once: when the conversation already shows the call and its result, do not call it again.

  ```
  CALL `tools__shell` with the command `echo updating` followed by the sources.
  ```

- **ASK.** `ASK "<question>"` means call `ask` with those words. The reply is the answer. Ask only when the step says to, and put the question in the words given. When the step says to record the answer, do that with `state_set` as the step says.

  ```
  ASK "Which sources should I update?"
  When the person answers, STATE.set `sources` to the answer.
  ```

- **STATE.set and STATE.get.** `STATE.set <name>` means call `state_set` with that name; `STATE.get <name>` means call `state_get`.

  ```
  STATE.set `branch` to `refresh/alpha`.
  ```

- **EXIT.** `EXIT <outcome>` finishes the node with that outcome. The outputs the step names are the outputs of the exit; an output that was recorded earlier need not be repeated. An `EXIT` call goes alone: send nothing in the same response.

  ```
  EXIT `done` with outputs `sources_updated` and `branch`.
  EXIT `failed` with output `reason` saying what went wrong.
  ```

- **ASK, ENTER and EXIT stand alone.** Never put `ask`, `enter` or `exit` in one response with another call. Finish the other calls first, read their results, and then send it. `ENTER <node>` calls `enter` to start another node; a job's node is not offered it, so a procedure run as a job has no such step.

  ```
  Not allowed: a `state_set` call and an `exit` call in the same response.
  Do: `state_set` first, read its result, then `exit` alone.
  ```

- **Go to step.** `go to step <n>` means carry on from step `<n>` and not from the next one, then go on in order from there. Steps between are skipped. A step is carried out twice only when a `go to step` sends you back to it.

  ```
  4. If the check printed a failure, go to step 6.
  5. EXIT `done`.
  6. EXIT `failed` with output `reason`.
  ```

- **Values that are not given.** A value that reads `not given` was not given to the node; `not set` means no fact has been recorded under that name. Do not make a value up. Ask for an input that is not given only when a step tells you to.

  ```
  Sources to update: not given.
  Branch: not set.
  ```

- **A tool that reports an error.** A result that begins with `error:` tells you what went wrong. Do not repeat the same call hoping for another answer unless the step says to retry. When the procedure says what to do on an error, do that; otherwise `EXIT` with the outcome `failed` and give the error as the `reason`.

  ```
  error: no such file: sources.yaml
  EXIT `failed` with output `reason` set to "no such file: sources.yaml".
  ```

- **Display templates.** `DISPLAY` followed by a quoted block means: say that text to the person in a plain reply, as written. The values in it were filled in when the run started, so it can show an input or a setting, not a value produced during the run; read that from the result of the call that produced it. Do not add to it or leave parts out, and say it once.

  ```
  DISPLAY "Updating {{ input.sources }} for {{ settings.CORPUS_NAME }}."
  ```

- **Validation.** `VALIDATE` followed by a list of conditions means: check each condition against the values you have. When one fails, do what the step says for a failure, and do not go on as if it held. When the step says nothing, `EXIT` with the outcome `failed` and name the condition in `reason`.

  ```
  VALIDATE: "Sources to update" is not "not given"; "Branch" is not empty.
  If a condition fails, EXIT `failed` with output `reason` naming it.
  ```

- **Error tables.** A procedure may end with an error table of the columns Error and Behaviour. When a call returns an error result, or a condition of a row holds, do what that row's Behaviour says and nothing else. A situation that has no row is handled as a tool that reports an error, above.

  ```
  | Error | Behaviour |
  |-------|-----------|
  | `error: no such file` | EXIT `failed` with output `reason` set to the error. |
  ```
