async def main(job):
    result = await job.run_node("gated_broken", {})
    return f"gated_broken {result['outcome']}"
