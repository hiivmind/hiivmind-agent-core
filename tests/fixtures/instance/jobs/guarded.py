async def main(job):
    result = await job.run_node("guarded", {})
    return f"guarded {result['outcome']}"
