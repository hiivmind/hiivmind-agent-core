# AGENTS.md — hiivmind-agent-core

The agent-core harness: it runs an instance's nodes as jobs and sequences. Its planning (requirements, designs, plans, reviews, backlog) and its principles live in `hiivmind-central`, checked out beside this repository.

## Principles

Read the principles before you design or change nodes, node contracts, sequences, tools or the harness itself:

- **Inventory of every principle, P1–P18:** `../hiivmind-central/01.principles/hiivmind-agent-core/README.md` ([on GitHub](https://github.com/hiivmind/hiivmind-central/blob/main/01.principles/hiivmind-agent-core/README.md)).
- **How they are governed:** `../hiivmind-central/01.principles/hiivmind-agent-core/PRINCIPLES.md`.

P1–P13 are in §3 of the requirements specification; P14–P18 have a file each in the folder above.

How to use them:

- Check a proposed node set or node contract against P13–P18 before it goes to the owner. The design names the principle that settles each boundary; only the cases no principle settles go to the owner.
- A principle that keeps producing questions, or that an owner decision reverses, is amended in the same change. There are no silent exceptions.
- Core-scoped principles apply to every instance. An instance may narrow a principle, not contradict it.

## Planning

`../hiivmind-central/04.planning/hiivmind-agent-core/`: requirements and designs in `superpowers/specs/`, plans in `superpowers/plans/`, reviews and build records in `superpowers/reviews/`, and the backlog in `a.backlog/BACKLOG_INDEX.md`. Read `../hiivmind-central/AGENTS.md` before you change anything there.
