async def main(job):
    result = await job.run_node("gated", {})
    return f"gated {result['outcome']}: {result.get('reason', 'the node exited by itself')}"
