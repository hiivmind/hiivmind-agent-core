async def main(job):
    result = await job.run_node("gated_srv", {})
    return {"returned": [result]}
