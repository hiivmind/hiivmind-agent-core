async def main(job):
    result = await job.run_node("halt", {})
    return f"halt {result['outcome']}: {result.get('reason', 'the node exited by itself')}"
