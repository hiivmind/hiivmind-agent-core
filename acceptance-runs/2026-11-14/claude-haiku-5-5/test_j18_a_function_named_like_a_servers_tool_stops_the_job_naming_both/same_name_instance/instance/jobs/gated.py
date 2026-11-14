async def main(job):
    result = await job.run_node("gated", {})
    return {"returned": [result]}
