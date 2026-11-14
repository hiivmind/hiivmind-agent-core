async def main(job):
    result = await job.run_node("gated_fn", {})
    return f"gated_fn {result['outcome']}: {result.get('reason', 'the node exited by itself')}"
