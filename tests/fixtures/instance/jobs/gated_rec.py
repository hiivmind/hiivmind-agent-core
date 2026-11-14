async def main(job):
    first = await job.run_node("gated_rec", {})
    second = await job.run_node("gated_norec", {})
    await job.call("locate", {"source": "after-the-check"})  # outside a node: this function's `state` is empty
    return f"gated_rec {first['outcome']}, gated_norec {second['outcome']}"
