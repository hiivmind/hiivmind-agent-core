async def main(job):
    result = await job.run_node("gated_srv", {})
    return f"gated_srv {result['outcome']}"
