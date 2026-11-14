async def main(job):
    result = await job.run_node("gated_missing", {})
    return f"gated_missing {result['outcome']}"
