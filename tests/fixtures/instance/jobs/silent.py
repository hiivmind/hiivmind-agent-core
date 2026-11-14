async def main(job):
    result = await job.run_node("silent", {})
    return f"silent {result['outcome']}: {result.get('reason', 'the node exited by itself')}"
