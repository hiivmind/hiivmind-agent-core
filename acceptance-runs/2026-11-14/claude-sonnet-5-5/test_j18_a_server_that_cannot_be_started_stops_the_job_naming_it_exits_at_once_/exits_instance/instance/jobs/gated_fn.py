async def main(job):
    result = await job.run_node("gated_fn", {})
    return {"returned": [result]}
